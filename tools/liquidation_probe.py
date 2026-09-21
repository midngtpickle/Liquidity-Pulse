"""
Liquidation feed probe.

Originally built to answer one question -- does `btcusdt@forceOrder` actually deliver?
-- because Binance accepts the subscription and then sends nothing, so silence alone
proved nothing without a record of having been listening.

It answered it. `workspace/liquidation_probe.jsonl` holds 8.7 hours of uptime with zero
events, on the BTC stream and on `!forceOrder@arr` (every USD-M symbol) simultaneously.
That, plus a three-venue side-by-side where Binance logged 0 while Bybit logged 26 and
OKX 57 over the same 100 seconds, is why src/liquidation_feed.py defaults to Bybit and
OKX instead.

The probe is kept and repointed, because the question it answers is permanent: **is my
liquidation feed alive, or merely connected?** A feed that silently stops delivering
looks exactly like a calm market, and the only way to tell them apart is a log that
records the probe's own uptime alongside the events.

    python tools/liquidation_probe.py                      # bybit + okx, until Ctrl-C
    python tools/liquidation_probe.py --venues binance     # re-check the Binance block
    python tools/liquidation_probe.py --hours 6

Every run appends to workspace/liquidation_probe.jsonl. Safe to stop and restart across
days; records accumulate.
"""

import argparse
import asyncio
import json
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from liquidation_feed import LiquidationFeed, Liquidation, DEFAULT_VENUES, SOURCES

WORKSPACE = Path(__file__).parent.parent / "workspace"
LOG_PATH = WORKSPACE / "liquidation_probe.jsonl"

HEARTBEAT_SECONDS = 300
_stop = asyncio.Event()


def write(record: dict) -> None:
    record["ts"] = datetime.now(timezone.utc).isoformat()
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    print(json.dumps(record), flush=True)


async def run(venues, symbols, deadline) -> None:
    started = time.time()
    feed = LiquidationFeed(symbols=symbols, venues=venues)
    counts = {v: 0 for v in venues}

    write({"type": "session_start", "venues": list(venues), "symbols": list(symbols)})

    def on_event(event: Liquidation) -> None:
        counts[event.venue] = counts.get(event.venue, 0) + 1
        write({
            "type": "liquidation",
            "venue": event.venue,
            "symbol": event.symbol,
            "liquidated_side": event.liquidated_side,
            "forced_order_side": event.forced_order_side,
            "price": event.price,
            "qty": event.qty,
            "usd": round(event.usd, 2),
        })

    feed_task = asyncio.create_task(feed.run(on_event))
    last_beat = time.time()

    try:
        while not _stop.is_set() and (deadline is None or time.time() < deadline):
            await asyncio.sleep(1.0)
            if time.time() - last_beat >= HEARTBEAT_SECONDS:
                last_beat = time.time()
                # Uptime alongside the counts is the whole point: zero events over a
                # known listening period is evidence, zero events over an unknown one
                # is nothing at all.
                write({
                    "type": "heartbeat",
                    "uptime_s": round(time.time() - started),
                    "counts": dict(counts),
                    "stats": feed.stats(),
                })
    finally:
        feed.stop()
        feed_task.cancel()
        try:
            await feed_task
        except asyncio.CancelledError:
            pass

    write({
        "type": "session_end",
        "uptime_s": round(time.time() - started),
        "counts": dict(counts),
        "stats": feed.stats(),
    })


def main() -> None:
    ap = argparse.ArgumentParser(description="Probe the liquidation feed for real delivery.")
    ap.add_argument("--venues", nargs="+", default=list(DEFAULT_VENUES),
                    choices=sorted(SOURCES),
                    help="Default: bybit okx. 'binance' is kept selectable so the block "
                         "can be re-checked; it has never delivered an event here.")
    ap.add_argument("--symbols", nargs="+", default=["BTCUSDT"])
    ap.add_argument("--hours", type=float, default=None,
                    help="Stop after this many hours (default: run until Ctrl-C)")
    args = ap.parse_args()

    deadline = time.time() + args.hours * 3600 if args.hours else None

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(_stop.set))
    except (ValueError, AttributeError):
        pass
    try:
        loop.run_until_complete(run(args.venues, args.symbols, deadline))
    except KeyboardInterrupt:
        pass
    finally:
        # websockets leaves a keepalive task per connection. Closing the loop without
        # draining them prints "Task was destroyed but it is pending!" on every exit,
        # which is noise in a log whose whole value is that unusual lines mean
        # something. asyncio.run() does this for us but cannot be used here, because
        # the SIGINT handler needs the loop before the coroutine starts.
        pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()


if __name__ == "__main__":
    main()
