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
2. **REST API Interface**: Agents with HTTP capability connect to `http://localhost:8080` to fetch telemetry, depth deltas, signal history, or trigger on-demand recalculations.

---

## 2. OpenAI Custom GPTs & ChatGPT Actions

You can connect a custom ChatGPT instance to your local Liquidity-Pulse server (using ngrok or public IP) by importing this **OpenAPI 3.1.0 Specification** into **GPT Actions**:

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
- The project includes **[`.cursorrules`](../.cursorrules)** in the root directory.
- Cursor AI automatically detects the multi-agent architecture and respects file contracts for `quant_engine.py`, `sentinel.py`, and `server.py`.

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

All agents consuming `workspace/telemetry_latest.json` can rely on this validated Pydantic schema contract:

```json
{
  "timestamp": "2026-08-14T10:40:20.094318+00:00",
  "symbol": "BTCUSDT",
  "market": "BINANCE:BTCUSDT.P",
  "current_price": 62894.00,
  "high_24h": 63999.00,
  "low_24h": 62700.00,
  "volume_24h": 12053.30,
  "sr_levels": [
    {
      "price": 62802.27,
      "type": "SUPPORT",
      "touch_count": 17,
      "conviction": "HIGH",
      "distance_pct": -0.15,
      "volume_confluence": true
    },
    {
      "price": 63456.68,
      "type": "RESISTANCE",
      "touch_count": 176,
      "conviction": "HIGH",
      "distance_pct": 0.89,
      "volume_confluence": true
    }
  ],
  "volume_profile": {
    "vpoc": 63421.99,
    "hvn_zones": [62900.00, 63400.00, 63800.00],
    "lvn_zones": [62750.00, 63100.00, 63600.00]
  },
  "market_summary": {
    "total_candles_analyzed": 500,
    "pine_pivots_found": 35,
    "support_levels_count": 1,
    "resistance_levels_count": 3,
    "high_conviction_count": 4
  }
}
```
