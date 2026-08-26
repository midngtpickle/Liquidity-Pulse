"""
Liquidity-Pulse - Dashboard Web Server

Serves static web files from web/ and provides REST API endpoints for
telemetry data, depth metrics, session briefing markdown, and pipeline refresh triggers.
Uses ThreadingHTTPServer for concurrent, non-blocking HTTP handling.
"""

import os
import sys
import json
import logging
import threading
import hashlib
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from quant_engine import QuantEngine
from sentinel import SentinelOrchestrator
from discord_webhook import DiscordWebhookDispatcher
from telegram_bot import TelegramAlertDispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("DashboardServer")

PROJECT_ROOT = Path(__file__).parent.parent
WEB_DIR = PROJECT_ROOT / "web"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
TELEMETRY_PATH = WORKSPACE_DIR / "telemetry_latest.json"
DEPTH_PATH = WORKSPACE_DIR / "depth_latest.json"
BRIEFING_PATH = WORKSPACE_DIR / "artifacts" / "SESSION_BRIEFING.md"
SIGNALS_PATH = WORKSPACE_DIR / "tradingview_signals.json"

# Mutex to ensure only one pipeline execution runs at a time
_pipeline_lock = threading.Lock()
_signals_lock = threading.Lock()
ALLOWED_HOSTS = {"localhost", "127.0.0.1"}

# Security configurations
TRADINGVIEW_WEBHOOK_SECRET = os.environ.get("TRADINGVIEW_WEBHOOK_SECRET", "")
MAX_PAYLOAD_BYTES = 64 * 1024  # 64 KB maximum payload limit


class DashboardHTTPRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/telemetry":
            self.handle_telemetry_api()
        elif path == "/api/depth":
            self.handle_depth_api()
        elif path == "/api/briefing":
            self.handle_briefing_api()
        elif path == "/api/tradingview/signals":
            self.handle_tradingview_signals_api()
        elif path == "/api/health":
            self.send_json_response({"status": "healthy", "service": "LiquidityPulse"})
        else:
            # Fallback to static file handler
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/refresh":
            self.handle_refresh_api()
        elif path == "/api/webhook/tradingview":
            self.handle_tradingview_webhook()
        else:
            self.send_error(404, "Endpoint not found")

    def handle_telemetry_api(self):
        if not TELEMETRY_PATH.exists():
            self.send_json_response({"error": "Telemetry file not found"}, status=404)
            return
        try:
            with open(TELEMETRY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.send_json_response(data)
        except Exception as err:
            logger.error(f"Error reading telemetry: {err}")
            self.send_json_response({"error": str(err)}, status=500)

    def handle_depth_api(self):
        if not DEPTH_PATH.exists():
            # If ws_feed hasn't written snapshot yet, synthesize fallback structure
            self.send_json_response({
                "status": "waiting_for_feed",
                "bands": {
                    "0.5%": {"bid_depth_usd": 0.0, "ask_depth_usd": 0.0, "imbalance_delta_pct": 0.0},
                    "1.0%": {"bid_depth_usd": 0.0, "ask_depth_usd": 0.0, "imbalance_delta_pct": 0.0},
                    "2.0%": {"bid_depth_usd": 0.0, "ask_depth_usd": 0.0, "imbalance_delta_pct": 0.0}
                }
            })
            return
        try:
            with open(DEPTH_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.send_json_response(data)
        except Exception as err:
            logger.error(f"Error reading depth data: {err}")
            self.send_json_response({"error": str(err)}, status=500)

    def handle_briefing_api(self):
        if not BRIEFING_PATH.exists():
            self.send_json_response({"content": "# No briefing generated yet."}, status=200)
            return
        try:
            with open(BRIEFING_PATH, "r", encoding="utf-8") as f:
                content = f.read()
            self.send_json_response({"content": content})
        except Exception as err:
            logger.error(f"Error reading briefing: {err}")
            self.send_json_response({"error": str(err)}, status=500)

    def handle_refresh_api(self):
        """
        Asynchronously triggers pipeline refresh without blocking server threads.
        """
        if not _pipeline_lock.acquire(blocking=False):
            self.send_json_response(
                {"status": "busy", "message": "Pipeline refresh is already running in background."},
                status=429
            )
            return

        def _worker():
            try:
                logger.info("Executing background telemetry & briefing refresh...")
                sentinel = SentinelOrchestrator(project_root=str(PROJECT_ROOT))
                sentinel.run_pipeline()
                logger.info("Background refresh finished successfully.")
            except Exception as err:
                logger.error(f"Background refresh encountered error: {err}")
            finally:
                _pipeline_lock.release()

        worker_thread = threading.Thread(target=_worker, daemon=True)
        worker_thread.start()

        self.send_json_response(
            {"status": "accepted", "message": "Telemetry & briefing refresh initiated."},
            status=202
        )

    def handle_tradingview_webhook(self):
        """
        Receives webhook alerts from TradingView Pine Script, validates authentication,
        persists signal, and asynchronously broadcasts alerts to Discord & Telegram.
        """
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self.send_json_response({"error": "Empty payload received"}, status=400)
                return

            if content_length > MAX_PAYLOAD_BYTES:
                logger.warning(f"Rejected oversized TradingView webhook payload ({content_length} bytes)")
                self.send_json_response(
                    {"error": f"Payload too large. Maximum allowed size is {MAX_PAYLOAD_BYTES} bytes."},
                    status=413
                )
                return

            body_bytes = self.rfile.read(content_length)
            payload_str = body_bytes.decode("utf-8")
            
            try:
                signal_data = json.loads(payload_str)
            except json.JSONDecodeError:
                # Handle plain text messages by wrapping into structured payload
                signal_data = {
                    "event": "CUSTOM_ALERT",
                    "symbol": "BTCUSDT",
                    "message": payload_str,
                    "level_type": "NEUTRAL",
                    "price": 0.0,
                    "conviction": "MEDIUM"
                }

            # Authenticate Webhook Secret if configured
            if TRADINGVIEW_WEBHOOK_SECRET:
                parsed_url = urlparse(self.path)
                query_params = parse_qs(parsed_url.query)
                query_secret = query_params.get("secret", [""])[0]
                header_secret = self.headers.get("X-Webhook-Secret", "")
                auth_header = self.headers.get("Authorization", "")
                bearer_secret = auth_header[7:].strip() if auth_header.startswith("Bearer ") else ""
                body_secret = signal_data.get("secret", "") if isinstance(signal_data, dict) else ""

                provided_secret = header_secret or query_secret or bearer_secret or body_secret
                if provided_secret != TRADINGVIEW_WEBHOOK_SECRET:
                    logger.warning("Unauthorized TradingView webhook access attempt (mismatched secret).")
                    self.send_json_response({"error": "Unauthorized: Invalid or missing webhook secret."}, status=401)
                    return
            else:
                logger.debug("TRADINGVIEW_WEBHOOK_SECRET not set; processing unauthenticated webhook request.")

            # Stamp receive timestamp
            signal_data["received_at"] = datetime.now(timezone.utc).isoformat()

            logger.info(f"TradingView Webhook Alert received: {signal_data.get('event')} | {signal_data.get('message')}")

            # Append to persistent signals file
            with _signals_lock:
                signals = []
                if SIGNALS_PATH.exists():
                    try:
                        with open(SIGNALS_PATH, "r", encoding="utf-8") as f:
                            signals = json.load(f)
                    except Exception:
                        signals = []
                signals.append(signal_data)
                # Keep last 100 signals
                signals = signals[-100:]
                with open(SIGNALS_PATH, "w", encoding="utf-8") as f:
                    json.dump(signals, f, indent=2)

            # Asynchronously broadcast to Discord & Telegram without blocking HTTP response
            def _async_dispatch(sig: dict):
                if os.environ.get("DISCORD_WEBHOOK_URL"):
                    try:
                        discord = DiscordWebhookDispatcher()
                        discord.send_tradingview_signal_embed(sig)
                    except Exception as d_err:
                        logger.error(f"Error dispatching TradingView signal to Discord: {d_err}")

                if not (os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")):
                    return
                try:
                    telegram = TelegramAlertDispatcher()
                    msg = (
                        f"🔔 <b>TradingView Alert ({sig.get('symbol', 'BTCUSDT')})</b>\n\n"
                        f"<b>Event:</b> <code>{sig.get('event')}</code>\n"
                        f"<b>Message:</b> {sig.get('message')}\n"
                        f"<b>Price:</b> <code>${float(sig.get('price', 0.0)):,.2f}</code>\n"
                        f"<b>Conviction:</b> <code>{sig.get('conviction', 'HIGH')}</code>\n"
                        f"<b>Time:</b> {sig.get('received_at')}"
                    )
                    telegram.send_message(msg, parse_mode="HTML")
                except Exception as t_err:
                    logger.error(f"Error dispatching TradingView signal to Telegram: {t_err}")

            threading.Thread(target=_async_dispatch, args=(signal_data,), daemon=True).start()

            self.send_json_response({
                "status": "success",
                "message": "TradingView signal accepted and queued for dispatch.",
                "signal": signal_data
            }, status=200)

        except Exception as err:
            logger.error(f"Error handling TradingView webhook: {err}")
            self.send_json_response({"error": str(err)}, status=500)

    def handle_tradingview_signals_api(self):
        """
        Returns recent TradingView signal history.
        """
        if not SIGNALS_PATH.exists():
            self.send_json_response({"signals": []}, status=200)
            return
        try:
            with _signals_lock:
                with open(SIGNALS_PATH, "r", encoding="utf-8") as f:
                    signals = json.load(f)
            self.send_json_response({"signals": signals}, status=200)
        except Exception as err:
            logger.error(f"Error reading signal history: {err}")
            self.send_json_response({"error": str(err)}, status=500)

    def send_json_response(self, payload: dict, status: int = 200, max_age: int = 1):
        body = json.dumps(payload).encode("utf-8")
        etag = f'"{hashlib.md5(body).hexdigest()}"'
        
        # Check conditional GET
        if status == 200 and self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", f"public, max-age={max_age}, must-revalidate")
            self.end_headers()
            return

        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", f"public, max-age={max_age}, must-revalidate")
        
        # Origin validation for CORS
        origin = self.headers.get("Origin", "")
        if origin:
            parsed_origin = urlparse(origin)
            if parsed_origin.hostname in ALLOWED_HOSTS:
                self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(body)


def run_server(host: str = "127.0.0.1", port: int = 8080):
    server_address = (host, port)
    httpd = ThreadingHTTPServer(server_address, DashboardHTTPRequestHandler)
    logger.info(f"⚡ Liquidity-Pulse Concurrent Dashboard Server running on http://{host}:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Liquidity Pulse Dashboard Server")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host address to bind to (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default 8080)")
    args = parser.parse_args()

    run_server(host=args.host, port=args.port)
