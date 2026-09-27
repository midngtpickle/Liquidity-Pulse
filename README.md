# 🌊 Liquidity-Pulse — Autonomous $BTC Market & Liquidity Intelligence Harness

[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![AI Harness Ready](https://img.shields.io/badge/AI%20Harness-Claude%20%7C%20Cursor%20%7C%20ChatGPT%20%7C%20OpenClaw-purple.svg)](#-multi-agent-harness--llm-integration)
[![TradingView](https://img.shields.io/badge/TradingView-Pine%20Script%20v6-orange.svg)](liquidity_pulse_sr.pine)

**Liquidity-Pulse** is a market structure and liquidity monitoring system for the Binance USD-M perpetual `BINANCE:BTCUSDT.P`: S/R clusters and VPOC drawn on a TradingView chart, and the same levels plus order flow, positioning, liquidity pools, live order-book depth and multi-venue liquidations served from a local dashboard and API.

Everything at runtime is deterministic Python — there are no LLM agents inside it. It is built to be *consumed* by AI agents and harnesses, which can read its telemetry over the API or the filesystem.

---

## 🏛️ System Architecture

Two implementations of one strategy — a Pine indicator on the chart and a Python hub on your
machine — kept in agreement by a shared set of invariants ([docs/STRATEGY.md](docs/STRATEGY.md) §3):

```
 TradingView chart                  Your machine
┌─────────────────────────┐   ┌─────────────────────────────────────────────────┐
│ liquidity_pulse_sr.pine │   │ sentinel.py ─► quant_engine.py                  │
│  S/R clusters, VPOC,    │   │   levels · profiles · order flow · pools ·      │
│  conviction, alerts     │   │   positioning ─► telemetry_latest.json          │
└────────────┬────────────┘   │                  SESSION_BRIEFING.md            │
             │                │ ws_feed.py                                      │
             │ alert webhook  │   Binance depth · Bybit/OKX liquidations        │
             │                │   ─► depth_latest.json · liquidations_latest    │
             ▼                └────────────────────────┬────────────────────────┘
   ┌─────────────────────────────────────────────────────────────┐
   │ server.py · dashboard + REST API · http://localhost:8080    │
   └─────────────────────────────────────────────────────────────┘
```

Nothing is scheduled by default. `sentinel.py` runs when you (or `start_all.bat`, or the
dashboard's Refresh button) start it; the only scheduled tasks are the optional data
recorders. See [docs/AGENT_ARCHITECTURE.md](docs/AGENT_ARCHITECTURE.md) for what runs when.

---

## 📁 Directory & File Tree

```
Liquidity-Pulse/
├── AGENTS.md                          # Pointer to CLAUDE.md for agent working instructions
├── CLAUDE.md                          # Claude Code instructions, file map & data contracts
├── .cursorrules                       # Cursor IDE & Windsurf AI rules
├── LICENSE                            # MIT License
├── requirements.txt                   # Python dependencies
├── README.md                          # This file
├── start_all.bat                      # One-click Windows launcher
├── liquidity_pulse_sr.pine            # TradingView Pine Script v6 indicator
├── docs/
│   ├── STRATEGY.md                    # Strategy spec, Pine/hub invariants, benchmark results
│   ├── USER_GUIDE.md                  # Operating manual & API reference
│   ├── AGENT_ARCHITECTURE.md          # What runs at runtime, and what starts it
│   ├── AGENT_INTEGRATION_GUIDE.md     # Wiring external LLMs/agents to the API
│   ├── ORDER_FLOW_MASTERCLASS.md      # Order flow & market structure primer
│   └── images/
├── skills/
│   └── pine_sr_calculator/SKILL.md    # S/R clustering & volume profile algorithm reference
├── scripts/
│   ├── install_recorders.ps1          # Register the depth & positioning recorders as tasks
│   └── uninstall_recorders.ps1        # Remove them (never deletes recorded data)
├── tools/
│   └── liquidation_probe.py           # Measures whether a liquidation stream actually delivers
├── src/
│   ├── quant_engine.py                # Klines, pivots, S/R clusters, conviction, volume profile
│   ├── tape_profile.py                # Volume-at-price across candle ranges; taker delta & CVD
│   ├── liquidity_pools.py             # Untested swings, equal highs/lows, session extremes
│   ├── positioning.py                 # Open interest, funding, long/short ratios (+ recorder)
│   ├── sentinel.py                    # Runs the engine, writes the briefing, dispatches alerts
│   ├── ws_feed.py                     # Local order book (Binance) + liquidation cascades
│   ├── liquidation_feed.py            # Bybit & OKX liquidations, normalised to LONG/SHORT
│   ├── depth_recorder.py              # Gzipped JSONL order-book history, one file per UTC day
│   ├── runlock.py                     # Single-writer lock for the recorders
│   ├── server.py                      # Dashboard, REST API & TradingView webhook
│   ├── telegram_bot.py                # Telegram alert dispatcher
│   ├── discord_webhook.py             # Discord embed dispatcher
│   ├── backtester.py                  # Walk-forward S/R hold-rate benchmark with control
│   ├── derivation_study.py            # Compares level derivations against a random control
│   ├── conditional_study.py           # Tests levels under market context (trend, sweeps, ...)
│   └── pool_study.py                  # Scores liquidity pools as magnets, not barriers
├── web/                               # index.html, styles.css, app.js (dashboard)
└── workspace/
    ├── telemetry_latest.json          # Market telemetry (regenerated each run)
    ├── depth_latest.json              # Live depth snapshot (untracked)
    ├── liquidations_latest.json       # Live cascade window (untracked)
    ├── tradingview_signals.json       # Received TradingView alerts (untracked)
    ├── *_study.json, backtest_results.json   # Benchmark outputs
    ├── depth_history/, positioning_history/  # Recorder output (untracked)
    └── artifacts/SESSION_BRIEFING.md  # Latest session briefing
```

---

## 🚀 Quick Start & Usage

### Windows Users (One-Click Launch)
Double-click **[`start_all.bat`](start_all.bat)** in File Explorer or run `.\start_all.bat` in PowerShell. It automatically creates a virtual environment, installs requirements, compiles telemetry, starts the WebSocket daemon and Web UI server, and opens **`http://localhost:8080`** in your browser.

---

### Manual Cross-Platform Setup

#### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Run the Quantitative Telemetry Engine
Fetches 500 candles of 15m `BINANCE:BTCUSDT.P` from Binance USD-M futures (Bybit fallback), detects swing pivots, clusters horizontal S/R zones, builds the volume profiles, order flow, liquidity pools and positioning, and outputs `workspace/telemetry_latest.json`:
```bash
python src/quant_engine.py
```

### 3. Run the Sentinel Orchestrator
Runs the quant engine, generates `workspace/artifacts/SESSION_BRIEFING.md`, and sends it to Telegram/Discord if their credentials are set:
```bash
python src/sentinel.py
```

### 4. Run the Real-time WebSocket Feed
Monitors order book depth imbalance (0.5%, 1%, 2% bands) from Binance, and liquidation cascades (> $5,000,000 in a 3-minute sliding window) from **Bybit and OKX** — Binance accepts a `forceOrder` subscription and never sends anything, verified over 8.7 hours of uptime with zero events:
```bash
python src/ws_feed.py --duration 30
```

---

## 🧮 Quantitative Features

1. **Pivot Detection**: swing highs/lows with 10 bars either side, rebuilt over a trailing 500-candle window on every run (and on every bar on the chart).
2. **Density-Based Clustering**: pivots merged in time order into the first cluster within $0.35\%$ of its running centre.
3. **Debounced Touch Counting**: a touch is price *entering* a level's zone from outside, not every candle that overlaps it.
4. **Conviction Tiering**:
   - 🔥 **HIGH**: $\ge 3$ touches **and** VPOC/HVN volume confluence.
   - ⚡ **MEDIUM**: $\ge 2$ touches.
   - ▫️ **LOW / MINOR**: isolated pivot.

   The tier describes how a level was **constructed**, not how likely it is to hold — see [the benchmark](docs/STRATEGY.md#5-what-the-benchmark-says).
5. **Volume Profiles**: a 50-bin mid-price profile shared with the chart (VPOC, HVN, LVN), and a finer 120-bin volume-at-price profile with value area.
6. **Order Flow**: taker delta and CVD from Binance kline taker-buy volume.
7. **Liquidity Pools**: untested swings, equal highs/lows and session extremes — scored as targets, not entries.
8. **Positioning**: open interest, funding and long/short ratios. Open interest and the ratios are untested, because the exchange serves only 30 days of history.
9. **Order-Book Depth**: a full local book maintained from the diff stream, with 0.5/1/2% imbalance bands and a flag on bands the snapshot cannot fully see.
10. **Liquidation Cascades**: Bybit and OKX liquidations over a 3-minute window, alerting above $\$5,000,000$. The threshold predates the venue change and now sums a smaller population, so it is a number to re-tune, not one to trust.
11. **Research Harnesses**: walk-forward benchmarks that score every level derivation and condition against a randomly displaced control, with multiple-comparison counts.

---

## 🤖 Multi-Agent Harness & LLM Integration

Liquidity-Pulse is a data source for AI agents and coding assistants; it does not run any itself:

| Agent / Harness | Configuration File | How to Use |
| :--- | :--- | :--- |
| **Claude / Claude Code** | [`CLAUDE.md`](CLAUDE.md) | Claude Code reads `CLAUDE.md` for commands, the file map, data contracts and reasoning rules. |
| **Cursor / Windsurf** | [`.cursorrules`](.cursorrules) | Loaded by the IDE to guide code changes. |
| **ChatGPT / OpenAI GPTs** | [`docs/AGENT_INTEGRATION_GUIDE.md`](docs/AGENT_INTEGRATION_GUIDE.md) | Import the OpenAPI 3.1.0 schema into Custom GPT Actions to query `/api/telemetry`, `/api/depth` and `/api/liquidations`. |
| **LangChain / CrewAI / CLI agents** | [`docs/AGENT_INTEGRATION_GUIDE.md`](docs/AGENT_INTEGRATION_GUIDE.md) | Python `@tool` wrappers over the REST API, or read `workspace/` directly. |
| **Any agent** | [`skills/pine_sr_calculator/SKILL.md`](skills/pine_sr_calculator/SKILL.md) | Reference for the S/R clustering and volume profile algorithm. |

---

## 🤝 Contributing & Open-Source Guidelines

We welcome community contributions! To contribute:
1. **Fork the Repository**: [https://github.com/midngtpickle/Liquidity-Pulse](https://github.com/midngtpickle/Liquidity-Pulse)
2. **Create a Feature Branch**: `git checkout -b feat/your-feature-name`
3. **Commit Changes**: Follow semantic commit formatting (`feat:`, `fix:`, `docs:`, `refactor:`)
4. **Submit a Pull Request**: Provide a clear description and test verification steps.

---

## 📄 License

This project is licensed under the **[MIT License](LICENSE)**. Free for personal, educational, and commercial algorithmic trading applications.

