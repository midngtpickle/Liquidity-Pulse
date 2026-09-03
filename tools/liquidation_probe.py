"""
Liquidation feed probe.

Standalone diagnostic for one question: does btcusdt@forceOrder actually deliver?
The stream was subscribed on the spot host for a long time, where Binance accepts
the subscription and then never sends anything, so silence alone proves nothing.

Every run appends to workspace/liquidation_probe.jsonl, and the file records the
probe's own uptime as well as the events. That distinction is the whole point: an
empty log means "nothing happened" only if the probe can show it was listening.

    python tools/liquidation_probe.py            # run until Ctrl-C
    python tools/liquidation_probe.py --hours 6  # stop on its own

Safe to stop and restart across days; records accumulate.
"""

import argparse
import asyncio
import json
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import websockets

WORKSPACE = Path(__file__).parent.parent / "workspace"
LOG_PATH = WORKSPACE / "liquidation_probe.jsonl"

# btcusdt@forceOrder is the stream ws_feed consumes. !forceOrder@arr covers every
# USD-M symbol and acts as the control: if BTC is silent while the market is not,
# that is a real signal. If both are silent, the market is simply quiet.
STREAM_URL = "wss://fstream.binance.com/stream?streams=!forceOrder@arr/btcusdt@forceOrder"

HEARTBEAT_SECONDS = 300
_stop = asyncio.Event()


def write(record: dict) -> None:
    record["ts"] = datetime.now(timezone.utc).isoformat()
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    print(json.dumps(record), flush=True)


async def run(deadline: float | None) -> None:
    started = time.time()
    btc = 0
    all_market = 0
    reconnects = 0

    write({"type": "session_start", "stream_url": STREAM_URL})

    while not _stop.is_set() and (deadline is None or time.time() < deadline):
        try:
            async with websockets.connect(STREAM_URL, ping_interval=20, ping_timeout=20) as ws:
                write({"type": "connected", "reconnects": reconnects})
                last_beat = time.time()

                while not _stop.is_set() and (deadline is None or time.time() < deadline):
                    timeout = min(
                        HEARTBEAT_SECONDS - (time.time() - last_beat),
                        30.0 if deadline is None else max(1.0, deadline - time.time()),
                    )
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=max(1.0, timeout))
                    except asyncio.TimeoutError:
                        raw = None

                    if raw:
                        msg = json.loads(raw)
                        order = msg.get("data", {}).get("o", {})
                        if order:
                            usd = float(order["p"]) * float(order["q"])
                            if msg.get("stream", "").startswith("!"):
                                all_market += 1
                                # Counted only; storing every symbol would bury the BTC ones.
                            else:
                                btc += 1
                                write({
                                    "type": "btc_liquidation",
                                    "symbol": order.get("s"),
                                    "side": order.get("S"),
                                    "price": float(order["p"]),
                                    "qty": float(order["q"]),
                                    "usd": round(usd, 2),
                                })

                    if time.time() - last_beat >= HEARTBEAT_SECONDS:
                        last_beat = time.time()
                        write({
                            "type": "heartbeat",
                            "uptime_s": round(time.time() - started),
                            "btc_liquidations": btc,
                            "all_market_liquidations": all_market,
                        })

        except asyncio.CancelledError:
            break
        except Exception as err:
            # A closing laptop drops the socket; that is expected, not a failure.
            reconnects += 1
            write({"type": "disconnected", "error": f"{type(err).__name__}: {err}"})
            try:
                await asyncio.wait_for(_stop.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    write({
        "type": "session_end",
        "uptime_s": round(time.time() - started),
        "btc_liquidations": btc,
        "all_market_liquidations": all_market,
        "reconnects": reconnects,
    })


def main() -> None:
    ap = argparse.ArgumentParser(description="Probe the Binance USD-M liquidation stream.")
    ap.add_argument("--hours", type=float, default=None, help="Stop after this many hours (default: run until Ctrl-C)")
    args = ap.parse_args()

    deadline = time.time() + args.hours * 3600 if args.hours else None

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(_stop.set))
    except (ValueError, AttributeError):
        pass
    try:
        loop.run_until_complete(run(deadline))
    except KeyboardInterrupt:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
