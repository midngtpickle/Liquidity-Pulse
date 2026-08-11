"""
Liquidity-Pulse - Dashboard Web Server

Serves static web files from web/ and provides REST API endpoints for
telemetry data, session briefing markdown, and pipeline refresh triggers.
"""

import os
import sys
import json
import logging
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from quant_engine import QuantEngine
from sentinel import SentinelOrchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("DashboardServer")

PROJECT_ROOT = Path(__file__).parent.parent
WEB_DIR = PROJECT_ROOT / "web"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
TELEMETRY_PATH = WORKSPACE_DIR / "telemetry_latest.json"
BRIEFING_PATH = WORKSPACE_DIR / "artifacts" / "SESSION_BRIEFING.md"


class DashboardHTTPRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/telemetry":
            self.handle_telemetry_api()
        elif path == "/api/briefing":
            self.handle_briefing_api()
        elif path == "/api/health":
            self.send_json_response({"status": "healthy", "service": "LiquidityPulse"})
        else:
            # Fallback to standard static file handler
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/refresh":
            self.handle_refresh_api()
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
        try:
            logger.info("Manual telemetry refresh triggered via API...")
            sentinel = SentinelOrchestrator(project_root=str(PROJECT_ROOT))
            sentinel.run_pipeline()
            self.send_json_response({"status": "success", "message": "Telemetry & briefing refreshed successfully."})
        except Exception as err:
            logger.error(f"Error executing manual refresh: {err}")
            self.send_json_response({"error": str(err)}, status=500)

    def send_json_response(self, payload: dict, status: int = 200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)


def run_server(port: int = 8080):
    server_address = ("", port)
    httpd = HTTPServer(server_address, DashboardHTTPRequestHandler)
    logger.info(f"⚡ Liquidity-Pulse Dashboard Web Server running on http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Server stopped by user.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Liquidity Pulse Dashboard Server")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default 8080)")
    args = parser.parse_args()

    run_server(port=args.port)
