"""
Liquidity-Pulse - Multi-Venue Liquidation Feed

Binance USD-M `forceOrder` does not deliver from this machine. That is not a guess:

  * `tools/liquidation_probe.py` ran 8.7 hours and logged **0** liquidations, on
    `btcusdt@forceOrder` *and* on `!forceOrder@arr`, which covers every USD-M symbol.
  * A 275-second re-run, and an independent minimal client sharing no code with it,
    both returned 0.
  * A final three-venue probe over the same 100 seconds: Binance **0**, Bybit **26**,
    OKX **57** -- all three with the same five symbols, from the same machine, at the
    same moment.

The subscription is accepted and nothing is ever sent. Binance does this for liquidation
streams in some regions, and there is nothing to fix on our side, so this module stops
depending on it: liquidations come from venues that answer.

## Side conventions differ, and getting it backwards inverts the signal

Each venue describes a liquidation from a different angle:

| venue | field | meaning | a liquidated LONG appears as |
| :--- | :--- | :--- | :--- |
| Binance | `o.S` | side of the forced **order** | `SELL` |
| Bybit | `S` | side of the liquidated **position** | `Buy` |
| OKX | `posSide` / `side` | both, explicitly | `long` / `sell` |

Binance and Bybit use opposite conventions on identically-named fields, so treating
`S` the same way across both silently flips longs and shorts.

This was settled against live data rather than from documentation. During a rally from
~82.0k to ~84.1k, Bybit reported `S: "Sell"` on BTCUSDT while OKX -- which states both
fields separately -- reported `posSide: "short"` with `side: "buy"` on the same move.
A rally liquidates shorts, and a short is closed by a forced buy. So Bybit's `"Sell"`
there is the *position* side, not the order side.

Everything downstream sees `liquidated_side` as `LONG` or `SHORT` and never a raw venue
field.

## What the totals mean now

The `$5,000,000 / 3-minute` cascade threshold was written when the intended source was
Binance's whole USD-M market. It now sums the venues actually connected. Bybit plus OKX
is not the same population, so the threshold is not measuring what it originally meant
to -- it is a smaller slice, and will trip less often. `CASCADE_THRESHOLD_USD` is a
number to re-tune against observed cascades, not a constant carried over on faith.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

try:
    import websockets
except ImportError:  # pragma: no cover - surfaced by the caller
    websockets = None

logger = logging.getLogger("LiquidationFeed")

LONG = "LONG"
SHORT = "SHORT"


@dataclass
class Liquidation:
    """One liquidation, normalised across venues."""
    venue: str
    symbol: str
    liquidated_side: str      # LONG or SHORT -- the position that was closed out
    price: float
    qty: float
    usd: float
    event_time: float         # venue timestamp, seconds; falls back to receipt time
    received_at: float = field(default_factory=time.time)

    @property
    def forced_order_side(self) -> str:
        """The side of the order the exchange had to send. A long is closed by a sell."""
        return "SELL" if self.liquidated_side == LONG else "BUY"


Handler = Callable[[Liquidation], Any]


class LiquidationSource:
    """One venue's websocket, normalising into Liquidation events."""

    name = "base"

    def __init__(self, symbols: Sequence[str]):
        self.symbols = list(symbols)
        self.events = 0
        self.connects = 0
        self.last_event_time: float = 0.0

    # -- to implement per venue ------------------------------------------------
    def url(self) -> str:
        raise NotImplementedError

    def subscribe_message(self) -> Optional[str]:
        return None

    def parse(self, message: Dict[str, Any]) -> List[Liquidation]:
        raise NotImplementedError

    # -- shared -----------------------------------------------------------------
    async def run(self, handler: Handler, stop: asyncio.Event) -> None:
        """
        Connect, subscribe, normalise, reconnect. Each source runs independently so
        one venue going quiet or dropping cannot take the others down with it --
        which is the entire point of having more than one.
        """
        backoff = 1.0
        while not stop.is_set():
            try:
                async with websockets.connect(self.url(), ping_interval=20, ping_timeout=20) as ws:
                    self.connects += 1
                    sub = self.subscribe_message()
                    if sub:
                        await ws.send(sub)
                    logger.info(f"{self.name}: connected ({len(self.symbols)} symbols).")
                    backoff = 1.0

                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30.0)
                        except asyncio.TimeoutError:
                            continue
                        try:
                            message = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        for event in self.parse(message):
                            self.events += 1
                            self.last_event_time = event.received_at
                            result = handler(event)
                            if asyncio.iscoroutine(result):
                                await result
            except asyncio.CancelledError:
                raise
            except Exception as err:
                if stop.is_set():
                    break
                logger.warning(f"{self.name}: connection lost ({err}); retrying in {backoff:.0f}s.")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=backoff)
                except asyncio.TimeoutError:
                    pass
                # Cap the backoff: a venue down for an hour should still be retried
                # every half minute, because a cascade is exactly when it matters.
                backoff = min(backoff * 2, 30.0)


class BybitLiquidations(LiquidationSource):
    """
    Bybit V5 linear `allLiquidation`, which batches into a single push every 500ms.

    `S` is the **position** side here, so `"Buy"` means a long was liquidated. See the
    module docstring for how that was established; it is the opposite of Binance's
    convention on an identically-named field.
    """

    name = "bybit"
    WS_URL = "wss://stream.bybit.com/v5/public/linear"

    def url(self) -> str:
        return self.WS_URL

    def subscribe_message(self) -> str:
        return json.dumps({
            "op": "subscribe",
            "args": [f"allLiquidation.{s}" for s in self.symbols]
        })

    def parse(self, message: Dict[str, Any]) -> List[Liquidation]:
        if message.get("op") == "subscribe":
            if not message.get("success", True):
                logger.error(f"bybit: subscription refused: {message}")
            return []
        if "allLiquidation" not in str(message.get("topic", "")):
            return []

        out: List[Liquidation] = []
        for row in message.get("data", []) or []:
            try:
                price = float(row["p"])
                qty = float(row["v"])
            except (KeyError, TypeError, ValueError):
                continue
            side = str(row.get("S", "")).upper()
            out.append(Liquidation(
                venue=self.name,
                symbol=str(row.get("s", "")),
                liquidated_side=LONG if side == "BUY" else SHORT,
                price=price,
                qty=qty,
                usd=price * qty,
                event_time=float(row.get("T", 0)) / 1000.0 or time.time()
            ))
        return out


class OKXLiquidations(LiquidationSource):
    """
    OKX `liquidation-orders` for SWAP. Unlike the other two this is not
    symbol-filtered server side -- it pushes every swap -- so the filtering happens
    here against the instrument ids we care about.

    OKX states `posSide` and `side` separately, which is why it could be used to
    settle Bybit's ambiguity.
    """

    name = "okx"
    WS_URL = "wss://ws.okx.com:8443/ws/v5/public"

    def __init__(self, symbols: Sequence[str]):
        super().__init__(symbols)
        # BTCUSDT -> BTC-USDT-SWAP
        self.instruments = set()
        for s in self.symbols:
            upper = s.upper()
            if upper.endswith("USDT"):
                self.instruments.add(f"{upper[:-4]}-USDT-SWAP")

    def url(self) -> str:
        return self.WS_URL

    def subscribe_message(self) -> str:
        return json.dumps({
            "op": "subscribe",
            "args": [{"channel": "liquidation-orders", "instType": "SWAP"}]
        })

    def parse(self, message: Dict[str, Any]) -> List[Liquidation]:
        if message.get("event"):
            if message.get("event") == "error":
                logger.error(f"okx: {message}")
            return []

        out: List[Liquidation] = []
        for row in message.get("data", []) or []:
            inst = str(row.get("instId", ""))
            if inst not in self.instruments:
                continue
            for detail in row.get("details", []) or []:
                try:
                    price = float(detail["bkPx"])
                    qty = float(detail["sz"])
                except (KeyError, TypeError, ValueError):
                    continue
                pos_side = str(detail.get("posSide", "")).lower()
                if pos_side not in ("long", "short"):
                    # Fall back to the order side: a forced buy closes a short.
                    pos_side = "short" if str(detail.get("side", "")).lower() == "buy" else "long"
                out.append(Liquidation(
                    venue=self.name,
                    symbol=inst,
                    liquidated_side=LONG if pos_side == "long" else SHORT,
                    price=price,
                    qty=qty,
                    usd=price * qty,
                    event_time=float(detail.get("ts", 0)) / 1000.0 or time.time()
                ))
        return out


class BinanceLiquidations(LiquidationSource):
    """
    Binance USD-M `forceOrder`. Retained because it costs nothing to keep and the
    block may be regional or temporary, but it is **not** in DEFAULT_VENUES: it has
    delivered zero events in every test, and a source that is silently dead is worse
    than one that is absent, because it looks like a quiet market.

    `o.S` is the **order** side here, so `SELL` means a long was liquidated.
    """

    name = "binance"

    def url(self) -> str:
        streams = "/".join(f"{s.lower()}@forceOrder" for s in self.symbols)
        return f"wss://fstream.binance.com/stream?streams={streams}"

    def parse(self, message: Dict[str, Any]) -> List[Liquidation]:
        order = (message.get("data") or {}).get("o") or {}
        if not order:
            return []
        try:
            price = float(order["p"])
            qty = float(order["q"])
        except (KeyError, TypeError, ValueError):
            return []
        order_side = str(order.get("S", "")).upper()
        return [Liquidation(
            venue=self.name,
            symbol=str(order.get("s", "")),
            liquidated_side=LONG if order_side == "SELL" else SHORT,
            price=price,
            qty=qty,
            usd=price * qty,
            event_time=float(order.get("T", 0)) / 1000.0 or time.time()
        )]


SOURCES = {
    "bybit": BybitLiquidations,
    "okx": OKXLiquidations,
    "binance": BinanceLiquidations,
}

# Binance is deliberately absent. See BinanceLiquidations.
DEFAULT_VENUES = ("bybit", "okx")


class LiquidationFeed:
    """Several venues at once, normalised into one stream of events."""

    def __init__(
        self,
        symbols: Sequence[str] = ("BTCUSDT",),
        venues: Sequence[str] = DEFAULT_VENUES
    ):
        unknown = [v for v in venues if v not in SOURCES]
        if unknown:
            raise ValueError(f"unknown venue(s) {unknown}; expected {sorted(SOURCES)}")
        self.sources = [SOURCES[v](symbols) for v in venues]
        self._stop = asyncio.Event()

    async def run(self, handler: Handler) -> None:
        if websockets is None:
            logger.error("websockets package is not installed; liquidation feed disabled.")
            return
        await asyncio.gather(*(s.run(handler, self._stop) for s in self.sources))

    def stop(self) -> None:
        self._stop.set()

    def stats(self) -> Dict[str, Dict[str, Any]]:
        return {
            s.name: {
                "events": s.events,
                "connects": s.connects,
                "seconds_since_event": (
                    round(time.time() - s.last_event_time, 1) if s.last_event_time else None
                )
            }
            for s in self.sources
        }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Watch normalised liquidations across venues")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT"])
    parser.add_argument("--venues", nargs="+", default=list(DEFAULT_VENUES),
                        help=f"any of {sorted(SOURCES)} (binance is known silent)")
    parser.add_argument("--duration", type=float, default=60.0)
    args = parser.parse_args()

    feed = LiquidationFeed(args.symbols, args.venues)
    totals: Dict[str, float] = {LONG: 0.0, SHORT: 0.0}

    def show(event: Liquidation) -> None:
        totals[event.liquidated_side] += event.usd
        print(f"{event.venue:>8} {event.symbol:<16} {event.liquidated_side:<5} "
              f"liquidated  ${event.usd:>12,.2f}  @ {event.price:,.2f} "
              f"(forced {event.forced_order_side})", flush=True)

    async def main() -> None:
        task = asyncio.create_task(feed.run(show))
        await asyncio.sleep(args.duration)
        feed.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(main())
    print(f"\nlongs liquidated  ${totals[LONG]:,.2f}")
    print(f"shorts liquidated ${totals[SHORT]:,.2f}")
    print(f"stats: {json.dumps(feed.stats())}")
