"""
Liquidity-Pulse - Real-time WebSocket Feed Client

Connects to Binance WebSocket streams for $BTC depth (@depth@100ms diff stream) and
liquidations (@forceOrder). Maintains a full local order book seeded from a REST
snapshot so that bid/ask depth imbalance deltas across the 0.5%, 1.0%, and 2.0%
bands are measured against real liquidity: the @depth20 partial stream spans only
~0.004% of mid price, far inside the narrowest band, which made all three bands
report identical figures. Exports real-time depth metrics to
workspace/depth_latest.json, and triggers rate-limited alerts on liquidation
cascades > $5,000,000 in a 3-minute sliding window.
"""

import os
import sys
import json
import logging
import time
import threading
import asyncio
from pathlib import Path
from collections import deque
from typing import Dict, List, Tuple

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent))

try:
    import websockets
except ImportError:
    websockets = None

import requests

from depth_recorder import DepthRecorder
from telegram_bot import TelegramAlertDispatcher
from discord_webhook import DiscordWebhookDispatcher

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("WSFeed")

PROJECT_ROOT = Path(__file__).parent.parent
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
DEPTH_FILE_PATH = WORKSPACE_DIR / "depth_latest.json"
DEPTH_HISTORY_DIR = WORKSPACE_DIR / "depth_history"


class LocalOrderBook:
    """
    Full local order book maintained per Binance's documented procedure: seed from
    a REST snapshot, then apply diff events in strict sequence. Any gap in the
    update-id chain means the book can no longer be trusted, so it is torn down and
    reseeded rather than silently drifting.
    """

    SNAPSHOT_URL = "https://api.binance.com/api/v3/depth"

    def __init__(self, symbol: str = "BTCUSDT", limit: int = 5000):
        self.symbol = symbol
        self.limit = limit
        self.bids: Dict[float, float] = {}
        self.asks: Dict[float, float] = {}
        self.last_update_id: int = 0
        self.synced: bool = False
        # How far from mid the book is known to be *complete*. The REST snapshot is
        # capped at `limit` levels, and the diff stream only reports levels that
        # change, so resting liquidity beyond the snapshot's outermost level stays
        # invisible until it moves. Bands wider than this are under-reported.
        self.complete_bid_span_pct: float = 0.0
        self.complete_ask_span_pct: float = 0.0

    def reset(self) -> None:
        self.bids.clear()
        self.asks.clear()
        self.last_update_id = 0
        self.synced = False
        self.complete_bid_span_pct = 0.0
        self.complete_ask_span_pct = 0.0

    def fetch_snapshot(self) -> Dict:
        """Blocking REST call. Invoke via asyncio.to_thread from the event loop."""
        resp = requests.get(
            self.SNAPSHOT_URL,
            params={"symbol": self.symbol, "limit": self.limit},
            timeout=10
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _apply_levels(book: Dict[float, float], levels: List[List[str]]) -> None:
        for price_s, qty_s in levels:
            price = float(price_s)
            qty = float(qty_s)
            if qty == 0.0:
                book.pop(price, None)
            else:
                book[price] = qty

    def load_snapshot(self, snapshot: Dict) -> None:
        self.bids.clear()
        self.asks.clear()
        self._apply_levels(self.bids, snapshot.get("bids", []))
        self._apply_levels(self.asks, snapshot.get("asks", []))
        self.last_update_id = int(snapshot["lastUpdateId"])

        # Record the contiguous reach at seed time, before diff events scatter
        # isolated far-out levels into the book and make the raw min/max look
        # deeper than the data actually supports.
        if self.bids and self.asks:
            mid = (max(self.bids) + min(self.asks)) / 2.0
            if mid > 0:
                self.complete_bid_span_pct = (mid - min(self.bids)) / mid * 100.0
                self.complete_ask_span_pct = (max(self.asks) - mid) / mid * 100.0

        self.synced = True

    def apply_event(self, event: Dict) -> bool:
        """
        Apply one diff event. Returns False if the event reveals a sequence gap,
        meaning the caller must reseed from a fresh snapshot.
        """
        first_id = int(event["U"])
        final_id = int(event["u"])

        # Already covered by the snapshot or an earlier event.
        if final_id <= self.last_update_id:
            return True

        # Events must chain onto the current state with no missing updates.
        if first_id > self.last_update_id + 1:
            return False

        self._apply_levels(self.bids, event.get("b", []))
        self._apply_levels(self.asks, event.get("a", []))
        self.last_update_id = final_id
        return True

    def best_bid_ask(self) -> Tuple[float, float]:
        if not self.bids or not self.asks:
            return 0.0, 0.0
        return max(self.bids), min(self.asks)


class LiquidityPulseWS:
    STREAM_URL = "wss://stream.binance.com:9443/stream?streams=btcusdt@depth@100ms/btcusdt@forceOrder"
    CASCADE_THRESHOLD_USD = 5_000_000.0  # $5M
    CASCADE_WINDOW_SECONDS = 180  # 3 minutes
    CASCADE_COOLDOWN_SECONDS = 180  # Cooldown between Telegram cascade alerts
    SEED_RETRY_SECONDS = 2.0  # Floor between order book snapshot attempts

    def __init__(self, recorder: "DepthRecorder | None" = None):
        self.recorder = recorder
        # Sliding window for liquidations: tuple of (timestamp, usd_val, side, price)
        self.liquidation_window: deque[Tuple[float, float, str, float]] = deque()
        self.last_mid_price: float = 0.0
        self.last_cascade_alert_time: float = 0.0
        self.last_depth_write_time: float = 0.0
        self.running: bool = False
        self.order_book = LocalOrderBook()
        self.last_seed_attempt: float = 0.0

        # Ensure workspace exists
        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    async def seed_order_book(self) -> bool:
        """
        Fetches a REST depth snapshot off the event loop and loads it into the local
        book. Rate limited so a failing snapshot cannot be retried on every 100ms
        diff event.
        """
        now = time.time()
        if now - self.last_seed_attempt < self.SEED_RETRY_SECONDS:
            return False
        self.last_seed_attempt = now

        try:
            snapshot = await asyncio.to_thread(self.order_book.fetch_snapshot)
            self.order_book.load_snapshot(snapshot)
            logger.info(
                f"Order book seeded: {len(self.order_book.bids)} bid / "
                f"{len(self.order_book.asks)} ask levels "
                f"(lastUpdateId={self.order_book.last_update_id})."
            )
            return True
        except Exception as err:
            logger.error(f"Failed to seed order book snapshot: {err}")
            self.order_book.reset()
            return False

    def calculate_depth_delta(self) -> Dict[str, Dict[str, float]]:
        """
        Calculates bid/ask liquidity depth delta within 0.5%, 1.0%, and 2.0% depth bands
        from the full local order book and writes depth telemetry to
        workspace/depth_latest.json.
        """
        book = self.order_book
        if not book.synced or not book.bids or not book.asks:
            return {}

        best_bid, best_ask = book.best_bid_ask()
        mid_price = (best_bid + best_ask) / 2.0
        self.last_mid_price = mid_price

        bands = [0.005, 0.010, 0.020]

        # Single pass per side across the whole book rather than one pass per band.
        # The book carries thousands of levels and this runs on every persisted
        # snapshot, so the nested re-scan the partial feed could afford is no
        # longer free.
        floors = [mid_price * (1.0 - b) for b in bands]
        ceilings = [mid_price * (1.0 + b) for b in bands]
        bid_totals = [0.0] * len(bands)
        ask_totals = [0.0] * len(bands)

        for price, qty in book.bids.items():
            notional = price * qty
            for i, floor in enumerate(floors):
                if price >= floor:
                    bid_totals[i] += notional

        for price, qty in book.asks.items():
            notional = price * qty
            for i, ceiling in enumerate(ceilings):
                if price <= ceiling:
                    ask_totals[i] += notional

        results = {}
        for i, band in enumerate(bands):
            band_pct = f"{int(band * 1000) / 10}%"
            bid_vol_usd = bid_totals[i]
            ask_vol_usd = ask_totals[i]
            total_vol = bid_vol_usd + ask_vol_usd
            delta_pct = ((bid_vol_usd - ask_vol_usd) / total_vol * 100.0) if total_vol > 0 else 0.0

            results[band_pct] = {
                "bid_depth_usd": round(bid_vol_usd, 2),
                "ask_depth_usd": round(ask_vol_usd, 2),
                "imbalance_delta_pct": round(delta_pct, 2)
            }

        # Write to depth_latest.json throttled at 2.0s or on significant delta/price shifts
        now = time.time()
        d_05 = results.get("0.5%", {}).get("imbalance_delta_pct", 0.0)
        delta_shifted = abs(d_05 - getattr(self, "last_written_delta", 0.0)) >= 2.0
        price_shifted = abs(mid_price - getattr(self, "last_written_price", 0.0)) / (mid_price or 1.0) >= 0.0005

        if (now - self.last_depth_write_time >= 2.0) or (now - self.last_depth_write_time >= 0.5 and (delta_shifted or price_shifted)):
            self.last_depth_write_time = now
            self.last_written_delta = d_05
            self.last_written_price = mid_price
            depth_payload = {
                "timestamp": now,
                "mid_price": round(mid_price, 2),
                "bands": results,
                # complete_*_span_pct is how far the book is trustworthy. Any band
                # wider than it is under-reported, since resting liquidity past the
                # snapshot's cap is invisible until it changes. Compare against the
                # band width before reading a wide band as complete.
                "book": {
                    "bid_levels": len(book.bids),
                    "ask_levels": len(book.asks),
                    "last_update_id": book.last_update_id,
                    "complete_bid_span_pct": round(book.complete_bid_span_pct, 3),
                    "complete_ask_span_pct": round(book.complete_ask_span_pct, 3)
                },
                "bands_complete": {
                    f"{int(b * 1000) / 10}%": bool(
                        b * 100.0 <= book.complete_bid_span_pct
                        and b * 100.0 <= book.complete_ask_span_pct
                    )
                    for b in bands
                }
            }
            try:
                temp_path = DEPTH_FILE_PATH.with_suffix(".tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump(depth_payload, f, indent=2)
                temp_path.replace(DEPTH_FILE_PATH)
            except Exception as err:
                logger.debug(f"Error persisting depth snapshot: {err}")

        return results

    def process_liquidation(self, order_data: Dict) -> None:
        """
        Processes liquidation events and checks 3-minute sliding window threshold.
        """
        # Binance forceOrder structure: o: { s: symbol, S: side, p: price, q: quantity, ... }
        o = order_data.get("o", {})
        symbol = o.get("s", "")
        side = o.get("S", "")  # SELL (long liquidated) or BUY (short liquidated)
        price = float(o.get("p", 0.0))
        qty = float(o.get("q", 0.0))
        usd_val = price * qty
        now = time.time()

        # Append to sliding window
        self.liquidation_window.append((now, usd_val, side, price))

        # Evict expired liquidations (> 3 minutes old)
        cutoff = now - self.CASCADE_WINDOW_SECONDS
        while self.liquidation_window and self.liquidation_window[0][0] < cutoff:
            self.liquidation_window.popleft()

        # Sum total window liquidation volume
        total_cascade_usd = sum(item[1] for item in self.liquidation_window)
        long_liqs = sum(item[1] for item in self.liquidation_window if item[2] == "SELL")
        short_liqs = sum(item[1] for item in self.liquidation_window if item[2] == "BUY")

        logger.info(
            f"LIQUIDATION DETECTED [{symbol}] {side} @ ${price:,.2f} | "
            f"Val: ${usd_val:,.2f} | 3m Window Total: ${total_cascade_usd:,.2f}"
        )

        if total_cascade_usd >= self.CASCADE_THRESHOLD_USD:
            logger.warning(
                f"\n{'='*70}\n"
                f"🚨 LIQUIDATION CASCADE ALERT 🚨\n"
                f"3-Minute Window Liquidation Volume Exceeded $5M Target!\n"
                f"Total Liquidated: ${total_cascade_usd:,.2f} USD\n"
                f"  - Long Liquidations (Sells):  ${long_liqs:,.2f}\n"
                f"  - Short Liquidations (Buys):  ${short_liqs:,.2f}\n"
                f"Current Mid-Price: ${self.last_mid_price:,.2f}\n"
                f"{'='*70}\n"
            )
            # Dispatch Telegram and Discord Alerts non-blockingly with cooldown to avoid API bans / event loop freezes
            if now - self.last_cascade_alert_time >= self.CASCADE_COOLDOWN_SECONDS:
                self.last_cascade_alert_time = now
                telegram = TelegramAlertDispatcher()
                discord = DiscordWebhookDispatcher()
                
                try:
                    loop = asyncio.get_running_loop()
                    loop.run_in_executor(None, telegram.send_liquidation_cascade_alert, total_cascade_usd, long_liqs, short_liqs, self.last_mid_price)
                    loop.run_in_executor(None, discord.send_liquidation_alert_embed, total_cascade_usd, long_liqs, short_liqs, self.last_mid_price)
                except RuntimeError:
                    # Fallback if executing outside an active asyncio loop
                    threading.Thread(
                        target=telegram.send_liquidation_cascade_alert,
                        args=(total_cascade_usd, long_liqs, short_liqs, self.last_mid_price),
                        daemon=True
                    ).start()
                    threading.Thread(
                        target=discord.send_liquidation_alert_embed,
                        args=(total_cascade_usd, long_liqs, short_liqs, self.last_mid_price),
                        daemon=True
                    ).start()
            else:
                logger.info(f"Cascade alert suppressed due to active cooldown ({self.CASCADE_COOLDOWN_SECONDS}s).")

    async def listen(self, duration_sec: float = 0):
        """
        Main async loop connecting to Binance streams with automatic reconnection logic.
        """
        if websockets is None:
            logger.error("websockets package is not installed. Install requirements first.")
            return

        self.running = True
        start_time = time.time()

        while self.running:
            logger.info(f"Connecting to Binance combined stream: {self.STREAM_URL}")
            try:
                async with websockets.connect(self.STREAM_URL) as ws:
                    logger.info("Connected to Binance WebSocket successfully. Listening for Depth & Liquidations...")
                    # A dropped socket means missed diff events, so the book from
                    # the previous session can no longer be trusted.
                    self.order_book.reset()
                    if self.recorder:
                        self.recorder.mark_gap("reconnect")
                    while self.running:
                        if duration_sec > 0 and (time.time() - start_time) >= duration_sec:
                            logger.info(f"Reached execution duration limit ({duration_sec}s). Stopping.")
                            self.running = False
                            break

                        try:
                            message = await asyncio.wait_for(ws.recv(), timeout=10.0)
                            msg_json = json.loads(message)
                            stream_name = msg_json.get("stream", "")
                            data = msg_json.get("data", {})

                            if "depth" in stream_name:
                                # Seed the book on first event, and again after any
                                # sequence gap. Events arriving during the snapshot
                                # fetch stay queued in the websocket buffer and are
                                # reconciled by update id once it lands.
                                if not self.order_book.synced:
                                    await self.seed_order_book()

                                if self.order_book.synced and not self.order_book.apply_event(data):
                                    logger.warning(
                                        "Order book sequence gap detected "
                                        f"(event U={data.get('U')} vs last_update_id={self.order_book.last_update_id}). "
                                        "Reseeding from snapshot."
                                    )
                                    if self.recorder:
                                        self.recorder.mark_gap(
                                            "sequence_gap",
                                            f"U={data.get('U')} last={self.order_book.last_update_id}"
                                        )
                                    self.order_book.reset()
                                    await self.seed_order_book()
                                    continue

                                if self.recorder:
                                    self.recorder.record(self.order_book)

                                depth_metrics = self.calculate_depth_delta()
                                if "0.5%" in depth_metrics:
                                    d_05 = depth_metrics["0.5%"]
                                    logger.debug(
                                        f"Depth 0.5% Imbalance: {d_05['imbalance_delta_pct']}% "
                                        f"(Bids: ${d_05['bid_depth_usd']:,.0f} | Asks: ${d_05['ask_depth_usd']:,.0f})"
                                    )

                            elif "forceOrder" in stream_name:
                                self.process_liquidation(data)

                        except asyncio.TimeoutError:
                            continue
                        except Exception as err:
                            logger.error(f"Error processing message: {err}")
                            break
            except Exception as conn_err:
                logger.error(f"WebSocket connection failure: {conn_err}")
                if self.running and duration_sec == 0:
                    logger.info("Attempting auto-reconnect in 5 seconds...")
                    await asyncio.sleep(5)
                else:
                    break

    def stop(self):
        self.running = False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Liquidity Pulse WebSocket Feed Client")
    parser.add_argument("--duration", type=float, default=0, help="Duration to run in seconds (0 for indefinite)")
    parser.add_argument("--record", action="store_true",
                        help="Append order book history to workspace/depth_history/ for later analysis")
    parser.add_argument("--record-interval", type=float, default=1.0,
                        help="Seconds between derived depth records (default 1.0)")
    parser.add_argument("--snapshot-interval", type=float, default=60.0,
                        help="Seconds between full book snapshots (default 60)")
    args = parser.parse_args()

    recorder = None
    if args.record:
        recorder = DepthRecorder(
            DEPTH_HISTORY_DIR,
            derived_interval=args.record_interval,
            snapshot_interval=args.snapshot_interval
        )
        recorder.mark_gap("start")

    client = LiquidityPulseWS(recorder=recorder)
    try:
        asyncio.run(client.listen(duration_sec=args.duration))
    except KeyboardInterrupt:
        logger.info("WebSocket client stopped by user.")
    finally:
        if recorder:
            recorder.close()
