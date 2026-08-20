"""
Liquidity-Pulse - Real-time WebSocket Feed Client

Connects to Binance WebSocket streams for $BTC depth (@depth20@100ms) and
liquidations (@forceOrder). Calculates bid/ask depth imbalance deltas across
0.5%, 1.0%, and 2.0% bands, exports real-time depth metrics to workspace/depth_latest.json,
and triggers rate-limited alerts on liquidation cascades > $5,000,000 in a 3-minute sliding window.
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


class LiquidityPulseWS:
    STREAM_URL = "wss://stream.binance.com:9443/stream?streams=btcusdt@depth20@100ms/btcusdt@forceOrder"
    CASCADE_THRESHOLD_USD = 5_000_000.0  # $5M
    CASCADE_WINDOW_SECONDS = 180  # 3 minutes
    CASCADE_COOLDOWN_SECONDS = 180  # Cooldown between Telegram cascade alerts

    def __init__(self):
        # Sliding window for liquidations: tuple of (timestamp, usd_val, side, price)
        self.liquidation_window: deque[Tuple[float, float, str, float]] = deque()
        self.last_mid_price: float = 0.0
        self.last_cascade_alert_time: float = 0.0
        self.last_depth_write_time: float = 0.0
        self.running: bool = False

        # Ensure workspace exists
        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    def calculate_depth_delta(self, bids: List[List[str]], asks: List[List[str]]) -> Dict[str, Dict[str, float]]:
        """
        Calculates bid/ask liquidity depth delta within 0.5%, 1.0%, and 2.0% depth bands
        and writes depth telemetry to workspace/depth_latest.json.
        """
        if not bids or not asks:
            return {}

        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        mid_price = (best_bid + best_ask) / 2.0
        self.last_mid_price = mid_price

        bands = [0.005, 0.010, 0.020]
        results = {}

        for band in bands:
            band_pct = f"{int(band * 1000) / 10}%"
            bid_vol_usd = sum(
                float(price) * float(qty)
                for price, qty in bids
                if float(price) >= mid_price * (1.0 - band)
            )
            ask_vol_usd = sum(
                float(price) * float(qty)
                for price, qty in asks
                if float(price) <= mid_price * (1.0 + band)
            )
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
                "bands": results
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

                            if "depth20" in stream_name:
                                bids = data.get("bids", [])
                                asks = data.get("asks", [])
                                depth_metrics = self.calculate_depth_delta(bids, asks)
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
    args = parser.parse_args()

    client = LiquidityPulseWS()
    try:
        asyncio.run(client.listen(duration_sec=args.duration))
    except KeyboardInterrupt:
        logger.info("WebSocket client stopped by user.")
