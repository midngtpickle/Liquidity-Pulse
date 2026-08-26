# CLAUDE.md — Agent & Harness Instructions for Liquidity-Pulse

This document provides system instructions, command shortcuts, architecture references, and data contracts for **Claude**, **Claude Code**, and **Anthropic-powered AI harnesses** interacting with the **Liquidity-Pulse** codebase.

---

## 🏛️ Project Architecture Overview

Liquidity-Pulse is an autonomous $BTC market liquidity monitoring and session intelligence system organized under the **Sentinel & Subagent Pattern**:

```
                         ┌─────────────────────────────┐
                         │ Sentinel Agent (src/sentinel.py)│
                         │ Session Orchestration & Briefings│
                         └──────────────┬──────────────┘
                                        │
           ┌────────────────────────────┴────────────────────────────┐
           ▼                                                         ▼
┌──────────────────────┐                                 ┌──────────────────────┐
│ Quant Subagent Engine│                                 │ Real-Time Stream Guard│
│ (src/quant_engine.py)│                                 │   (src/ws_feed.py)   │
└──────────┬───────────┘                                 └──────────┬───────────┘
           │                                                        │
           ▼                                                        ▼
[workspace/telemetry_latest.json]                       [workspace/depth_latest.json]
           │                                                        │
           └────────────────────────────┬───────────────────────────┘
                                        ▼
                         ┌─────────────────────────────┐
                         │   Web Server & API Relay    │
                         │      (src/server.py)        │
                         │    http://localhost:8080    │
                         └─────────────────────────────┘
```

---

## ⚡ Essential Commands

### Environment Setup & Installation
```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Linux/macOS:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Running Modules
```bash
# 1. Compile quantitative telemetry (500 candles, Pine S/R clusters, VPOC)
python src/quant_engine.py

# 2. Run Sentinel Orchestrator (updates telemetry, generates SESSION_BRIEFING.md, dispatches Discord/Telegram)
python src/sentinel.py

# 3. Start Concurrent Dashboard Server & Webhook Listener (serves UI on :8080)
python src/server.py --port 8080

# 4. Start Live WebSocket depth delta & liquidation monitor
python src/ws_feed.py

# 5. Run Historical S/R Backtester Benchmark (1,000 historical candles)
python src/backtester.py

# 6. Test Discord Webhook embed dispatcher (dry-run mode)
python src/discord_webhook.py --dry-run

# 7. Test Telegram alert dispatcher (dry-run mode)
python src/telegram_bot.py --dry-run
```

---

## 📁 Key File Map & Data Contracts

| File Path | Description | Input / Output Contract |
| :--- | :--- | :--- |
| `src/quant_engine.py` | Fetches OHLCV, calculates Pine pivots & VPOC | Reads Binance/Bybit REST $\rightarrow$ Writes `workspace/telemetry_latest.json` |
| `src/ws_feed.py` | Async WebSocket listener for depth & force orders | Connects to `@depth@100ms` & `@forceOrder`, maintaining a full local order book seeded from a REST snapshot $\rightarrow$ Writes `workspace/depth_latest.json` |
| `src/sentinel.py` | Session intelligence generator & dispatch runner | Ingests `telemetry_latest.json` $\rightarrow$ Writes `workspace/artifacts/SESSION_BRIEFING.md` |
| `src/server.py` | Concurrent HTTP server & TradingView webhook relay | Serves `web/`, handles `/api/telemetry`, `/api/depth`, `/api/webhook/tradingview` |
| `src/discord_webhook.py` | Visual rich embed cards for Discord | Dispatches formatted embeds using `DISCORD_WEBHOOK_URL` |
| `src/telegram_bot.py` | HTML alert dispatcher for Telegram | Dispatches messages using `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID` |
| `src/backtester.py` | Historical S/R bounce accuracy benchmark | Simulates train/test splits $\rightarrow$ Writes `workspace/backtest_results.json` |
| `liquidity_pulse_sr.pine` | Official TradingView Pine Script v5 indicator | Overlays S/R lines, VPOC, and sends alert webhooks to `src/server.py` |

---

## 🧠 Reasoning Guidelines for AI Agents

When analyzing market structure and generating briefings from telemetry data:

1. **Volume Point of Control (VPOC)**:
   - If `current_price > vpoc` $\rightarrow$ Market bias is **BULLISH ACCUMULATION** (Fair value is acting as support).
   - If `current_price < vpoc` $\rightarrow$ Market bias is **BEARISH DISTRIBUTION** (Fair value is acting as overhead supply).
2. **Support & Resistance Conviction**:
   - `HIGH`: $\ge 3$ touch points **AND** overlapping with High Volume Node (HVN) or VPOC.
   - `MEDIUM`: $2$ touch points.
   - `LOW / MINOR`: Isolated swing pivot.
3. **Liquidity Depth Imbalance Delta**:
   - $\text{Imbalance Delta \%} = \frac{\text{Bid Depth} - \text{Ask Depth}}{\text{Bid Depth} + \text{Ask Depth}} \times 100$.
   - Delta $> +15\%$ indicates heavy passive buy support (absorption).
   - Delta $< -15\%$ indicates heavy passive sell resistance.
4. **Liquidation Cascade Alerts**:
   - Single cascade or accumulated volume exceeding **$5,000,000 USD** within a 3-minute sliding window triggers institutional mean-reversion bounce alerts.

---

## 🛠️ Code Conventions & Safety Rules

- **Python Version**: 3.10+.
- **Typing**: Use standard Python `typing` annotations (`List`, `Dict`, `Optional`, `Tuple`, `Any`) and Pydantic models for data interchange.
- **Server Architecture**: Use `ThreadingHTTPServer` from standard library to ensure non-blocking HTTP requests for UI polling and webhooks.
- **Error Handling**: REST endpoints in `quant_engine.py` must maintain fallback mirrors (Binance $\rightarrow$ Bybit).
- **Paths**: Always use `Path(__file__).parent` relative pathing to support execution across Windows, Linux, and macOS.
