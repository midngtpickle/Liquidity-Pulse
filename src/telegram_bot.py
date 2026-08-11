"""
Liquidity-Pulse - Telegram Bot Alert Dispatcher

Dispatches structured Telegram alerts for session briefings and real-time
liquidation cascades (> $5M) via Telegram Bot API.
"""

import os
import sys
import logging
import requests
from typing import Optional, Dict, Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("TelegramBot")


class TelegramAlertDispatcher:
    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID")
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage" if self.bot_token else ""

    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        Sends message to configured Telegram channel or logs dry-run output.
        """
        if not self.is_configured():
            logger.info("Telegram credentials not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID). Dry-run output below:\n" + text)
            return False

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }

        try:
            res = requests.post(self.api_url, json=payload, timeout=10)
            res.raise_for_status()
            logger.info("Telegram message dispatched successfully.")
            return True
        except Exception as err:
            logger.error(f"Failed to dispatch Telegram message: {err}")
            return False

    def send_session_briefing_alert(self, telemetry: Dict[str, Any], session_name: str) -> bool:
        """
        Formats and dispatches session briefing summary to Telegram.
        """
        price = telemetry.get("current_price", 0.0)
        vpoc = telemetry.get("volume_profile", {}).get("vpoc", 0.0)
        high_24h = telemetry.get("high_24h", 0.0)
        low_24h = telemetry.get("low_24h", 0.0)
        sr_levels = telemetry.get("sr_levels", [])

        supports = [l for l in sr_levels if l["type"] == "SUPPORT"][:3]
        resistances = [l for l in sr_levels if l["type"] == "RESISTANCE"][:3]

        sup_text = "\n".join([f"  • <b>${s['price']:,.2f}</b> ({s['conviction']} - {s['touch_count']} touches)" for s in supports])
        res_text = "\n".join([f"  • <b>${r['price']:,.2f}</b> ({r['conviction']} - {r['touch_count']} touches)" for r in resistances])

        msg = (
            f"🟢 <b>LIQUIDITY-PULSE — SESSION BRIEFING</b>\n\n"
            f"<b>Active Session:</b> {session_name}\n"
            f"<b>Symbol:</b> $BTCUSDT\n"
            f"<b>Current Price:</b> <code>${price:,.2f}</code>\n"
            f"<b>VPOC (Fair Value):</b> <code>${vpoc:,.2f}</code>\n"
            f"<b>24h Range:</b> ${low_24h:,.2f} - ${high_24h:,.2f}\n\n"
            f"<b>🛡️ Support Clusters:</b>\n{sup_text if sup_text else '  • None'}\n\n"
            f"<b>⚔️ Resistance Clusters:</b>\n{res_text if res_text else '  • None'}\n\n"
            f"📊 View Dashboard: http://localhost:8080"
        )
        return self.send_message(msg, parse_mode="HTML")

    def send_liquidation_cascade_alert(
        self, total_usd: float, long_usd: float, short_usd: float, current_price: float
    ) -> bool:
        """
        Formats and dispatches liquidation cascade alert to Telegram.
        """
        msg = (
            f"🚨 <b>LIQUIDATION CASCADE ALERT ($BTCUSDT)</b> 🚨\n\n"
            f"<b>3-Minute Window Total:</b> <code>${total_usd:,.2f} USD</code>\n"
            f"<b>Long Liquidations (Sells):</b> ${long_usd:,.2f}\n"
            f"<b>Short Liquidations (Buys):</b> ${short_usd:,.2f}\n"
            f"<b>Current Price:</b> <code>${current_price:,.2f}</code>\n\n"
            f"<i>Liquidity depletion detected. Expect wick volatility & bounce reaction!</i>"
        )
        return self.send_message(msg, parse_mode="HTML")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Liquidity Pulse Telegram Bot Alert Dispatcher")
    parser.add_argument("--dry-run", action="store_true", help="Run test message dispatch in dry-run mode")
    args = parser.parse_args()

    bot = TelegramAlertDispatcher()
    dummy_telemetry = {
        "current_price": 64304.05,
        "high_24h": 65237.8,
        "low_24h": 63806.27,
        "volume_profile": {"vpoc": 65005.9},
        "sr_levels": [
            {"price": 64215.7, "type": "SUPPORT", "conviction": "HIGH", "touch_count": 127},
            {"price": 64847.13, "type": "RESISTANCE", "conviction": "HIGH", "touch_count": 292}
        ]
    }
    bot.send_session_briefing_alert(dummy_telemetry, "LONDON_SESSION (07:00 UTC)")
