# 🤖 Multi-Agent & LLM Harness Integration Guide

This guide provides technical specifications, schemas, tool wrappers, and prompt templates for integrating **Liquidity-Pulse** into third-party AI agents and agentic frameworks, including **ChatGPT / OpenAI Custom GPTs**, **Claude Code**, **Cursor**, **OpenClaw**, **LangChain**, and **CrewAI**.

---

## 📖 Table of Contents
1. [Overview & Integration Paradigms](#1-overview--integration-paradigms)
2. [OpenAI Custom GPTs & ChatGPT Actions](#2-openai-custom-gpts--chatgpt-actions)
3. [Claude & Claude Code Integration](#3-claude--claude-code-integration)
4. [Cursor & Windsurf IDE Agents](#4-cursor--windsurf-ide-agents)
5. [LangChain & CrewAI Python Tool Wrappers](#5-langchain--crewai-python-tool-wrappers)
6. [OpenClaw & Autonomous CLI Agents](#6-openclaw--autonomous-cli-agents)
7. [Standard Telemetry JSON Schema](#7-standard-telemetry-json-schema)

---

## 1. Overview & Integration Paradigms

Liquidity-Pulse exposes two primary interfaces for AI agents:
1. **File-System Sandboxed Interface**: Agents with bash/code-execution tools read `workspace/telemetry_latest.json`, `workspace/depth_latest.json`, and `workspace/artifacts/SESSION_BRIEFING.md`.
2. **REST API Interface**: Agents with HTTP capability connect to `http://localhost:8080` to fetch telemetry, depth deltas, the liquidation window, signal history, or trigger on-demand recalculations.

The data flows one way: Liquidity-Pulse contains no LLM of its own, and nothing in it calls
an agent. Everything it publishes is computed by deterministic Python.

> [!WARNING]
> The read endpoints and `POST /api/refresh` are **unauthenticated**. That is fine on
> `localhost`. Exposing the server through a tunnel or public IP so a hosted agent can reach
> it exposes all of them — and `/api/refresh` runs the full pipeline, which sends a briefing
> to Telegram/Discord if they are configured. Anyone with the URL can trigger that.

---

## 2. OpenAI Custom GPTs & ChatGPT Actions

You can connect a custom ChatGPT instance to your local Liquidity-Pulse server by importing this **OpenAPI 3.1.0 Specification** into **GPT Actions**. GPT Actions run on OpenAI's servers and cannot reach `localhost`, so replace the `servers.url` below with a public HTTPS tunnel URL (for example from `ngrok http 8080`) — and read the warning in §1 first.

### OpenAPI Specification (Actions Schema)
```yaml
openapi: 3.1.0
info:
  title: Liquidity-Pulse Market Intelligence API
  description: Real-time $BTC market structure, Pine S/R clusters, volume profile, and depth deltas.
  version: 1.0.0
servers:
  - url: http://localhost:8080
    description: Local Dashboard Server
paths:
  /api/telemetry:
    get:
      summary: Fetch Latest Market Telemetry
      description: Returns current price, 24h range, VPOC, volume profile, and ranked S/R clusters.
      operationId: getMarketTelemetry
      responses:
        '200':
          description: Successful telemetry retrieval
          content:
            application/json:
              schema:
                type: object
  /api/depth:
    get:
      summary: Fetch Real-Time Order Book Depth Delta
      description: Returns live bid/ask imbalance deltas across 0.5%, 1%, and 2% depth bands.
      operationId: getDepthDelta
      responses:
        '200':
          description: Successful depth metrics retrieval
  /api/liquidations:
    get:
      summary: Fetch Rolling Liquidation Cascade Window
      description: >-
        Returns the trailing 3-minute liquidation total split by liquidated side,
        with status NORMAL or CASCADE against the $5M threshold. Check the timestamp
        for staleness before acting on it: a stopped feed leaves the last snapshot in
        place, and status is "waiting_for_feed" before the first write.
      operationId: getLiquidationWindow
      responses:
        '200':
          description: Successful liquidation window retrieval
  /api/briefing:
    get:
      summary: Fetch Latest Session Briefing
      description: Returns formatted Markdown institutional session intelligence report.
      operationId: getSessionBriefing
      responses:
        '200':
          description: Successful briefing retrieval
  /api/refresh:
    post:
      summary: Trigger Telemetry Refresh
      description: Triggers quantitative engine recalculation in background.
      operationId: refreshTelemetry
      responses:
        '202':
          description: Refresh task accepted
```

### Custom GPT Instructions Prompt
```text
You are the Liquidity-Pulse Institutional Market Assistant.
Your goal is to analyze $BTCUSDT market liquidity, support/resistance conviction levels, and volume profile fair value.
Always query `getMarketTelemetry` and `getDepthDelta` before answering questions about market direction.
- If price is above VPOC, highlight bullish accumulation bias.
- If price is below VPOC, highlight bearish distribution bias.
- Highlight levels with HIGH conviction (>= 3 touches and VPOC/HVN volume confluence).
- Present the VPOC bias and conviction tiers as descriptions of market structure, not
  predictions. Neither has shown an edge over random levels in this system's own benchmark.
```

---

## 3. Claude & Claude Code Integration

For **Claude Code** and Anthropic API harnesses:
- **Project Configuration**: The root directory contains **[`CLAUDE.md`](../CLAUDE.md)** with build instructions, command shortcuts, reasoning rules, and error handling conventions.
- **Anthropic Tool Definition Example**:
```python
liquidity_pulse_tool = {
    "name": "get_btc_telemetry",
    "description": "Fetch real-time BTC liquidity telemetry, Pine S/R clusters, and Volume Profile from Liquidity-Pulse.",
    "input_schema": {
        "type": "object",
        "properties": {
            "include_depth": {"type": "boolean", "description": "Include live order book depth delta"}
        }
    }
}
```

---

## 4. Cursor & Windsurf IDE Agents

For **Cursor IDE** and **Windsurf**:
- The project includes **[`.cursorrules`](../.cursorrules)** in the root directory, which Cursor loads automatically.
- It lists the modules, their inputs and outputs, and the rule that the Pine indicator and `quant_engine.py` share invariants that must change together.

---

## 5. LangChain & CrewAI Python Tool Wrappers

To use Liquidity-Pulse as a Tool in **LangChain** or **CrewAI**:

```python
import requests
from langchain.tools import tool

class LiquidityPulseTools:
    BASE_URL = "http://localhost:8080"

    @tool("Fetch BTC Liquidity Telemetry")
    def get_telemetry() -> str:
        """Fetches current BTC price, VPOC, and ranked Support/Resistance clusters."""
        try:
            res = requests.get(f"{LiquidityPulseTools.BASE_URL}/api/telemetry", timeout=5)
            return res.text
        except Exception as e:
            return f"Error fetching telemetry: {e}"

    @tool("Fetch Order Book Depth Delta")
    def get_depth_delta() -> str:
        """Fetches live bid/ask liquidity depth imbalance across 0.5%, 1%, and 2% bands."""
        try:
            res = requests.get(f"{LiquidityPulseTools.BASE_URL}/api/depth", timeout=5)
            return res.text
        except Exception as e:
            return f"Error fetching depth data: {e}"

# Example LangChain Agent Initialization:
# tools = [LiquidityPulseTools.get_telemetry, LiquidityPulseTools.get_depth_delta]
```

---

## 6. OpenClaw & Autonomous CLI Agents

For **OpenClaw** or headless autonomous CLI agents:
- Execute pipeline directly via shell:
  ```bash
  python src/sentinel.py
  ```
- Parse the generated output JSON at `workspace/telemetry_latest.json`.
- Ingest the Markdown briefing report at `workspace/artifacts/SESSION_BRIEFING.md`.

---

## 7. Standard Telemetry JSON Schema

All agents consuming `workspace/telemetry_latest.json` (or `GET /api/telemetry`) can rely on
this Pydantic-validated contract. A real payload, trimmed — list fields show their first
entries only, and the per-bin histograms (`volume_profile.bins`, `tape_profile.bins`) are
omitted:

```json
{
  "timestamp": "2026-09-27T23:26:09.704708+00:00",
  "symbol": "BTCUSDT",
  "market": "BINANCE:BTCUSDT.P",
  "current_price": 84337.1,
  "high_24h": 85146.4,
  "low_24h": 84074.3,
  "volume_24h": 66445.86,
  "sr_levels": [
    { "price": 84436.6,  "type": "RESISTANCE", "touch_count": 20, "conviction": "HIGH",
      "distance_pct": 0.12,  "volume_confluence": true },
    { "price": 84127.35, "type": "SUPPORT",    "touch_count": 19, "conviction": "HIGH",
      "distance_pct": -0.25, "volume_confluence": true }
  ],
  "volume_profile": {
    "vpoc": 84335.83,
    "hvn_zones": [83850.24, 83931.18, 84012.11],
    "lvn_zones": [83283.73, 83364.66, 85387.93]
  },
  "tape_profile": {
    "vpoc": 83991.02,
    "value_area_high": 84837.28,
    "value_area_low": 83586.28,
    "bin_width": 36.7942,
    "hvn_zones": [83807.05, 83843.84, 83880.63],
    "lvn_zones": [82850.4, 82887.19, 82923.99]
  },
  "order_flow": {
    "available": true,
    "cvd": -14181.681,
    "cvd_24h": -757.119,
    "last_bar_delta_ratio": 0.1085,
    "divergence": 0.9279
  },
  "positioning": {
    "available": true,
    "funding_rate": 2.565e-05,
    "funding_annualised_pct": 2.809,
    "seconds_to_funding": 2031,
    "open_interest": 94337.422,
    "open_interest_value_usd": 7941362818.55,
    "oi_change_24h_pct": -0.23,
    "top_long_short_ratio": 1.8981,
    "oi_price_quadrant": null,
    "oi_history_days": 30
  },
  "liquidity_pools": [
    { "price": 84855.8,  "kind": "EQUAL_HIGHS", "side": "ABOVE", "strength": 3, "distance_pct": 0.62 },
    { "price": 83797.85, "kind": "EQUAL_LOWS",  "side": "BELOW", "strength": 4, "distance_pct": -0.64 }
  ],
  "market_summary": {
    "total_candles_analyzed": 500,
    "pine_pivots_found": 31,
    "levels_tracked": 9,
    "support_levels_count": 4,
    "resistance_levels_count": 5,
    "high_conviction_count": 4
  }
}
```

Notes for consumers:

- `volume_24h` is in BTC, not USD.
- `touch_count` counts distinct entries into a level's zone, so realistic values are in the
  tens. Older payloads counted every overlapping candle and reported values in the hundreds.
- `volume_profile` is the coarse 50-bin profile the Pine indicator reproduces; `tape_profile`
  is the finer 120-bin one. They report different VPOCs by design.
- When `order_flow.available` or `positioning.available` is `false`, the figures in that
  block are placeholders and must not be read as a flat market — the source was unavailable
  (for example the Bybit kline fallback, which has no taker volume, zeroes `order_flow`).
- `oi_price_quadrant` is `null` when either 24h change is unavailable, or either sits inside the deadband —
  a flat tape is not forced into a quadrant.
