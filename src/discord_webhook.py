"""
Liquidity-Pulse - Discord Webhook Alert Dispatcher

Dispatches institutional rich embed notifications to Discord channels via Webhooks:
- Color-coded Session Briefings (Emerald Green #00e676 for Bullish / Crimson Red #ff1744 for Bearish)
- Real-time Liquidation Cascade Alerts (> $5M) with custom emojis
- TradingView Pine Script signal broadcasts
"""

import os
import sys
import json
import logging
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("DiscordWebhook")


class DiscordWebhookDispatcher:
    COLOR_BULLISH = 0x00E676   # Emerald Green
    COLOR_BEARISH = 0xFF1744   # Crimson Red
    COLOR_GOLD    = 0xFFD700   # VPOC Gold
    COLOR_FIRE    = 0xFF9100   # Liquidation Orange
    COLOR_CYAN    = 0x00F2FE   # Cyan Blue

    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.environ.get("DISCORD_WEBHOOK_URL")

    def is_configured(self) -> bool:
        return bool(self.webhook_url and self.webhook_url.startswith("https://discord.com/api/webhooks/"))

    def send_raw_payload(self, payload: Dict[str, Any]) -> bool:
        """
        Sends JSON payload to Discord webhook endpoint or logs dry-run output.
        """
        if not self.is_configured():
            logger.info("Discord Webhook not configured (DISCORD_WEBHOOK_URL). Dry-run embed payload below:\n" + json.dumps(payload, indent=2))
            return False

        try:
            res = requests.post(self.webhook_url, json=payload, timeout=10)
            res.raise_for_status()
            logger.info("Discord embed dispatched successfully.")
            return True
        except Exception as err:
            logger.error(f"Failed to dispatch Discord embed: {err}")
            return False

    def send_session_briefing_embed(
        self, telemetry: Dict[str, Any], session_name: str, dashboard_url: str = "http://localhost:8080"
    ) -> bool:
        """
        Formats and dispatches rich visual embed for session open briefing.
        """
        price = telemetry.get("current_price", 0.0)
        vpoc = telemetry.get("volume_profile", {}).get("vpoc", 0.0)
        high_24h = telemetry.get("high_24h", 0.0)
        low_24h = telemetry.get("low_24h", 0.0)
        volume_24h = telemetry.get("volume_24h", 0.0)
        sr_levels = telemetry.get("sr_levels", [])
        
        is_bullish = price >= vpoc
        embed_color = self.COLOR_BULLISH if is_bullish else self.COLOR_BEARISH
        bias_text = "🟢 BULLISH (Above VPOC)" if is_bullish else "🔴 BEARISH (Below VPOC)"

        supports = [l for l in sr_levels if l["type"] == "SUPPORT"][:3]
        resistances = [l for l in sr_levels if l["type"] == "RESISTANCE"][:3]

        sup_field_val = "\n".join([
            f"• **${s['price']:,.2f}** `({s['conviction']})` | {s['touch_count']} touches | `{s['distance_pct']:+.2f}%`"
            for s in supports
        ]) or "*No clear supports detected*"

        res_field_val = "\n".join([
            f"• **${r['price']:,.2f}** `({r['conviction']})` | {r['touch_count']} touches | `{r['distance_pct']:+.2f}%`"
            for r in resistances
        ]) or "*No clear resistances detected*"

        embed = {
            "title": f"⚡ Liquidity-Pulse — Session Briefing Report",
            "description": f"**Active Session:** `{session_name}`\n**Market Structure Bias:** {bias_text}",
            "color": embed_color,
            "fields": [
                {
                    "name": "💵 Current Price",
                    "value": f"**`${price:,.2f}`**",
                    "inline": True
                },
                {
                    "name": "🎯 VPOC (Fair Value)",
                    "value": f"**`${vpoc:,.2f}`**",
                    "inline": True
                },
                {
                    "name": "📊 24h Range & Volume",
                    "value": f"`${low_24h:,.2f}` — `${high_24h:,.2f}`\n**Vol:** `{volume_24h:,.1f} BTC`",
                    "inline": True
                },
                {
                    "name": "🛡️ Primary Support Clusters",
                    "value": sup_field_val,
                    "inline": False
                },
                {
                    "name": "⚔️ Primary Resistance Clusters",
                    "value": res_field_val,
                    "inline": False
                }
            ],
            "footer": {
                "text": f"Liquidity-Pulse Institutional Intelligence • {dashboard_url}"
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        payload = {
            "username": "Liquidity-Pulse Sentinel",
            "avatar_url": "https://raw.githubusercontent.com/midngtpickle/Liquidity-Pulse/main/docs/images/order_book_depth_1786443680582.jpg",
            "embeds": [embed]
        }

        return self.send_raw_payload(payload)

    def send_liquidation_alert_embed(
        self, total_usd: float, long_usd: float, short_usd: float, current_price: float
    ) -> bool:
        """
        Formats and dispatches high-urgency liquidation cascade warning card.
        """
        embed = {
            "title": "🚨 LIQUIDATION CASCADE ALERT ($BTCUSDT)",
            "description": "3-Minute Window Liquidation Volume Exceeded **$5,000,000 USD** Target!\nLiquidity depletion detected — prepare for wick volatility & mean-reversion bounces.",
            "color": self.COLOR_FIRE,
            "fields": [
                {
                    "name": "💥 Total 3m Liquidated",
                    "value": f"**`${total_usd:,.2f} USD`**",
                    "inline": True
                },
                {
                    "name": "📉 Long Liquidations (Forced Sells)",
                    "value": f"`${long_usd:,.2f}`",
                    "inline": True
                },
                {
                    "name": "📈 Short Liquidations (Forced Buys)",
                    "value": f"`${short_usd:,.2f}`",
                    "inline": True
                },
                {
                    "name": "📍 Current Mid-Price",
                    "value": f"**`${current_price:,.2f}`**",
                    "inline": True
                }
            ],
            "footer": {
                "text": "Liquidity-Pulse Real-Time Force Order Stream"
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        payload = {
            "username": "Liquidity-Pulse Volatility Guard",
            "embeds": [embed]
        }

        return self.send_raw_payload(payload)

    def send_tradingview_signal_embed(self, signal_data: Dict[str, Any]) -> bool:
        """
        Dispatches TradingView Pine Script Webhook alert card.
        """
        symbol = signal_data.get("symbol", "BTCUSDT")
        event = signal_data.get("event", "SR_TOUCH")
        level_type = signal_data.get("level_type", "SUPPORT")
        price = float(signal_data.get("price", 0.0))
        conviction = signal_data.get("conviction", "HIGH")
        message = signal_data.get("message", "Pine Script Alert Triggered")

        embed_color = self.COLOR_BULLISH if level_type == "SUPPORT" else self.COLOR_BEARISH

        embed = {
            "title": f"🔔 TradingView Alert: {event} ({symbol})",
            "description": f"**Message:** {message}",
            "color": embed_color,
            "fields": [
                {"name": "Level Type", "value": f"`{level_type}`", "inline": True},
                {"name": "Price Level", "value": f"**`${price:,.2f}`**", "inline": True},
                {"name": "Conviction", "value": f"**`{conviction}`**", "inline": True}
            ],
            "footer": {
                "text": "TradingView Webhook Listener • Liquidity-Pulse"
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        payload = {
            "username": "TradingView Pine Relay",
            "embeds": [embed]
        }

        return self.send_raw_payload(payload)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Liquidity Pulse Discord Webhook Dispatcher")
    parser.add_argument("--dry-run", action="store_true", help="Test embed formatting in dry-run mode")
    args = parser.parse_args()

    dispatcher = DiscordWebhookDispatcher()
    sample_telemetry = {
        "current_price": 64244.92,
        "high_24h": 65237.8,
        "low_24h": 63806.27,
        "volume_24h": 13624.7,
        "volume_profile": {"vpoc": 65005.9},
        "sr_levels": [
            {"price": 64215.7, "type": "SUPPORT", "conviction": "HIGH", "touch_count": 130, "distance_pct": -0.05},
            {"price": 64847.13, "type": "RESISTANCE", "conviction": "HIGH", "touch_count": 289, "distance_pct": 0.94}
        ]
    }
    dispatcher.send_session_briefing_embed(sample_telemetry, "LONDON_SESSION (07:00 UTC)")
    dispatcher.send_liquidation_alert_embed(5240000.0, 4800000.0, 440000.0, 64244.92)
