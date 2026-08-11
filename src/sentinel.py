"""
Liquidity-Pulse - Sentinel Orchestrator

Integrates the multi-agent pipeline:
1. Invokes QuantEngine to refresh workspace/telemetry_latest.json.
2. Reads market telemetry and identifies active trading session (Asia, London, NY).
3. Synthesizes institutional-grade session intelligence.
4. Generates workspace/artifacts/SESSION_BRIEFING.md artifact.
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

# Add src to python path if needed
sys.path.insert(0, str(Path(__file__).parent))

from quant_engine import QuantEngine
from telegram_bot import TelegramAlertDispatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("SentinelOrchestrator")


class SentinelOrchestrator:
    def __init__(self, project_root: Optional[str] = None):
        if project_root is None:
            project_root = str(Path(__file__).parent.parent)
        self.project_root = Path(project_root)
        self.workspace_dir = self.project_root / "workspace"
        self.artifacts_dir = self.workspace_dir / "artifacts"
        self.telemetry_path = self.workspace_dir / "telemetry_latest.json"
        self.briefing_path = self.artifacts_dir / "SESSION_BRIEFING.md"

        # Ensure directories exist
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def detect_active_session(self, now_utc: Optional[datetime] = None) -> str:
        """
        Determines current active trading session based on UTC hour:
        - Asia Session: 00:00 - 07:00 UTC
        - London Session: 07:00 - 13:30 UTC
        - New York Session: 13:30 - 21:00 UTC
        - Off-Hours / NY Close: 21:00 - 00:00 UTC
        """
        if now_utc is None:
            now_utc = datetime.now(timezone.utc)
        
        hour = now_utc.hour
        minute = now_utc.minute
        time_decimal = hour + (minute / 60.0)

        if 0.0 <= time_decimal < 7.0:
            return "ASIA_SESSION (00:00 UTC Open)"
        elif 7.0 <= time_decimal < 13.5:
            return "LONDON_SESSION (07:00 UTC Open)"
        elif 13.5 <= time_decimal < 21.0:
            return "NEW_YORK_SESSION (13:30 UTC Open)"
        else:
            return "NY_CLOSE_OFF_HOURS"

    def run_quant_pipeline(self) -> dict:
        """
        Runs QuantEngine to fetch latest data and write telemetry.
        """
        logger.info("Triggering QuantEngine telemetry compilation...")
        engine = QuantEngine(symbol="BTCUSDT", interval="15m", limit=500)
        telemetry_payload = engine.run(output_path=str(self.telemetry_path))
        return telemetry_payload.model_dump()

    def generate_session_briefing(self, telemetry: dict) -> str:
        """
        Crafts institutional-grade session briefing markdown report from telemetry.
        """
        now_utc_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        session_name = self.detect_active_session()

        current_price = telemetry.get("current_price", 0.0)
        high_24h = telemetry.get("high_24h", 0.0)
        low_24h = telemetry.get("low_24h", 0.0)
        volume_24h = telemetry.get("volume_24h", 0.0)
        sr_levels = telemetry.get("sr_levels", [])
        volume_profile = telemetry.get("volume_profile", {})

        vpoc = volume_profile.get("vpoc", 0.0)
        hvn_zones = volume_profile.get("hvn_zones", [])
        lvn_zones = volume_profile.get("lvn_zones", [])

        supports = [l for l in sr_levels if l["type"] == "SUPPORT"]
        resistances = [l for l in sr_levels if l["type"] == "RESISTANCE"]

        # Sort supports descending (closest first) and resistances ascending (closest first)
        supports.sort(key=lambda x: x["price"], reverse=True)
        resistances.sort(key=lambda x: x["price"])

        # Format S/R tables
        support_rows = ""
        for s in supports[:5]:
            conf_badge = "🔥 HIGH" if s["conviction"] == "HIGH" else ("⚡ MED" if s["conviction"] == "MEDIUM" else "MINOR")
            vol_icon = "✅ VPOC/HVN" if s["volume_confluence"] else "---"
            support_rows += f"| **${s['price']:,.2f}** | {conf_badge} | {s['touch_count']} | {s['distance_pct']:.2f}% | {vol_icon} |\n"

        resistance_rows = ""
        for r in resistances[:5]:
            conf_badge = "🔥 HIGH" if r["conviction"] == "HIGH" else ("⚡ MED" if r["conviction"] == "MEDIUM" else "MINOR")
            vol_icon = "✅ VPOC/HVN" if r["volume_confluence"] else "---"
            resistance_rows += f"| **${r['price']:,.2f}** | {conf_badge} | {r['touch_count']} | {r['distance_pct']:.2f}% | {vol_icon} |\n"

        briefing_md = f"""# 🟢 Liquidity-Pulse — Session Briefing Report

**Generated At**: `{now_utc_str}`  
**Active Session**: `{session_name}`  
**Symbol**: `$BTCUSDT`  

---

## 1. Executive Market Structure Summary

> [!IMPORTANT]
> **Mid-Price**: **${current_price:,.2f}** | **24h Range**: `${low_24h:,.2f}` — `${high_24h:,.2f}` | **VPOC**: `${vpoc:,.2f}`

- **Volume Point of Control (VPOC)**: High-density fair value anchor located at **${vpoc:,.2f}**.
- **24h Volume Aggregate**: `{volume_24h:,.2f} BTC`.
- **Market Bias**: Current price relative to VPOC is **{'BULLISH ACCUMULATION' if current_price > vpoc else 'BEARISH DISTRIBUTION'}**.

---

## 2. Horizontal Support & Resistance Clusters (Pine Pivot Analysis)

### 🛡️ Primary Support Clusters (Bulls Defense Line)
| Price Level | Conviction | Touch Count | Distance | Volume Confluence |
| :--- | :--- | :--- | :--- | :--- |
{support_rows if support_rows else "| *No clear supports detected* | | | | |\n"}

### ⚔️ Primary Resistance Clusters (Bears Overhead Supply)
| Price Level | Conviction | Touch Count | Distance | Volume Confluence |
| :--- | :--- | :--- | :--- | :--- |
{resistance_rows if resistance_rows else "| *No clear resistances detected* | | | | |\n"}

---

## 3. Volume Profile & Liquidity Node Confluences

- **High Volume Nodes (HVNs)**: Price acceptance zones expected to act as strong support/resistance reaction points:
  `{', '.join([f'${h:,.2f}' for h in hvn_zones[:5]])}`
- **Low Volume Nodes (LVNs)**: Air pockets and liquidity voids where price is prone to rapid acceleration / slippage:
  `{', '.join([f'${l:,.2f}' for l in lvn_zones[:5]])}`

---

## 4. Session Tactical Execution Plan

> [!TIP]
> **Key Tactical Rules**:
> 1. **Liquidity Sweep Play**: Watch for candle wicks probing into High Conviction levels with immediate volume delta reversal.
> 2. **LVN Traversal**: Avoid setting limit orders inside Low Volume Nodes (`{', '.join([f'${l:,.2f}' for l in lvn_zones[:3]])}`); expect rapid price movement through these pockets.
> 3. **VPOC Re-test**: Re-tests of VPOC (**${vpoc:,.2f}**) offer high R:R entry invalidation references.

---
*Report automatically generated by Sentinel Agent Orchestrator & Macro Subagent.*
"""
        with open(self.briefing_path, "w", encoding="utf-8") as f:
            f.write(briefing_md)

        logger.info(f"Session briefing successfully written to {self.briefing_path}")
        return briefing_md

    def run_pipeline(self):
        """
        Executes full orchestration pipeline.
        """
        logger.info(f"=== Starting Liquidity-Pulse Sentinel Pipeline ===")
        telemetry = self.run_quant_pipeline()
        briefing = self.generate_session_briefing(telemetry)
        
        # Dispatch Telegram session briefing alert
        telegram = TelegramAlertDispatcher()
        session_name = self.detect_active_session()
        telegram.send_session_briefing_alert(telemetry, session_name)
        
        logger.info(f"=== Sentinel Pipeline Completed Successfully ===")
        return briefing


if __name__ == "__main__":
    sentinel = SentinelOrchestrator()
    sentinel.run_pipeline()
