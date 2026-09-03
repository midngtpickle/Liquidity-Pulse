# 🌊 Liquidity-Pulse — Autonomous $BTC Market & Liquidity Intelligence Harness

[![License: MIT](https://img.shields.io/badge/License-MIT-emerald.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![AI Harness Ready](https://img.shields.io/badge/AI%20Harness-Claude%20%7C%20Cursor%20%7C%20ChatGPT%20%7C%20OpenClaw-purple.svg)](#-multi-agent-harness--llm-integration)
[![TradingView](https://img.shields.io/badge/TradingView-Pine%20Script%20v5-orange.svg)](liquidity_pulse_sr.pine)

**Liquidity-Pulse** is an institutional-grade, multi-agent market structure and liquidity monitoring system built for algorithmic traders and autonomous AI agent harnesses.

---

## 🏛️ System Architecture

Liquidity-Pulse uses a **Sentinel & Subagent Pattern**:

```
                         ┌─────────────────────────────┐
                         │ Sentinel Agent Orchestrator │
                         │ Schedule: 00:00, 07:00, 13:30│
                         └──────────────┬──────────────┘
                                        │
           ┌────────────────────────────┴────────────────────────────┐
           ▼                                                         ▼
┌──────────────────────┐                                 ┌──────────────────────┐
│    Quant Subagent    │                                 │    Macro Subagent    │
│  - REST Kline Fetch  │                                 │  - Telemetry Synthesis│
│  - Pine S/R Density  │                                 │  - Session Briefings │
│  - Volume Profile    │                                 │  - Discord/Telegram  │
└──────────┬───────────┘                                 └──────────┬───────────┘
           │                                                        │
           ▼                                                        ▼
┌──────────────────────┐                                 ┌──────────────────────┐
│telemetry_latest.json │                                 │  SESSION_BRIEFING.md │
└──────────────────────┘                                 └──────────────────────┘
```

---

## 📁 Directory & File Tree

```
Liquidity-Pulse/
├── AGENTS.md                          # Multi-agent roles & permissions manifest
├── CLAUDE.md                          # Claude Code & Anthropic harness instructions
├── .cursorrules                       # Cursor IDE & Windsurf AI rules
├── LICENSE                            # Open-source MIT License
├── requirements.txt                   # Production Python dependencies
├── README.md                          # Framework documentation
├── READ.md                            # Quick summary guide
├── start_all.bat                      # One-click Windows launcher script
├── liquidity_pulse_sr.pine            # Official TradingView Pine Script v6 indicator
├── docs/
│   ├── USER_GUIDE.md                  # Comprehensive user operational manual & API reference
│   ├── ORDER_FLOW_MASTERCLASS.md      # Institutional Order Flow & Market Structure Masterclass
│   ├── AGENT_INTEGRATION_GUIDE.md     # Multi-Agent & LLM Harness Integration Guide
│   └── images/                        # Infographic diagrams
├── skills/
│   └── pine_sr_calculator/
│       └── SKILL.md                   # Pine Script S/R & volume profile math skill
├── src/
│   ├── __init__.py                    # Source package initializer
│   ├── init.py                        # Alternative initializer alias
│   ├── quant_engine.py                # REST data fetcher, S/R clustering & volume profile engine
│   ├── ws_feed.py                     # Real-time WebSocket depth delta & liquidation cascade monitor
│   ├── sentinel.py                    # Session intelligence orchestrator & briefing generator
│   ├── telegram_bot.py                # Telegram Bot API alert dispatcher
│   ├── discord_webhook.py             # Discord Webhook rich visual embed dispatcher
│   ├── backtester.py                  # Historical S/R backtester & accuracy benchmark
│   └── server.py                      # Dashboard HTTP API & TradingView Webhook listener
├── web/
│   ├── index.html                     # Visual web UI structure
│   ├── styles.css                     # Dark mode quantitative glassmorphic styles
│   └── app.js                         # Dynamic auto-polling frontend script
└── workspace/
    ├── telemetry_latest.json          # Machine-readable market telemetry artifact
    ├── depth_latest.json              # Live order book depth delta snapshot
    ├── tradingview_signals.json       # Ingested TradingView alert history
    ├── backtest_results.json          # Historical backtest benchmark results
    └── artifacts/
        ├── .gitkeep                   # Artifacts directory placeholder
        └── SESSION_BRIEFING.md        # Institutional-grade session intelligence output
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
Fetches 500 candles of 15m $BTC data, detects Pine Script swing high/low pivots, clusters horizontal S/R zones, and outputs `workspace/telemetry_latest.json`:
```bash
python src/quant_engine.py
```

### 3. Run the Sentinel Orchestrator
Triggers the full quantitative pipeline and generates the session briefing artifact `workspace/artifacts/SESSION_BRIEFING.md`:
```bash
python src/sentinel.py
```

### 4. Run the Real-time WebSocket Feed
Monitors order book depth imbalance (0.5%, 1%, 2% bands) and liquidation cascades (> $5,000,000 in 3-minute sliding window):
```bash
python src/ws_feed.py --duration 30
```

---

## 🧮 Quantitative Features

1. **Pine Script Pivot Detection**: Standard `ta.pivothigh` and `ta.pivotlow` swing detection ($left\_bars=10, right\_bars=10$).
2. **Density-Based Clustering**: Groups contiguous price pivots within a $0.35\%$ threshold window.
3. **Conviction Tiering**:
   - 🔥 **HIGH**: $\ge 3$ touch points + High Volume Node confluence.
   - ⚡ **MEDIUM**: $2$ touch points.
   - ▫️ **LOW / MINOR**: Isolated pivot points.
4. **Volume Profile Analysis**: Calculates VPOC (Volume Point of Control), HVNs (High Volume Nodes), and LVNs (Low Volume Nodes).
5. **Liquidity Cascade Alerting**: Tracks force orders over a 3-minute sliding window and alerts on $> \$5,000,000$ cascades.

---

## 🤖 Multi-Agent Harness & LLM Integration

Liquidity-Pulse is built from the ground up for seamless operation with modern AI coding agents and autonomous frameworks:

| Agent / Harness | Configuration File | How to Use |
| :--- | :--- | :--- |
| **Claude / Claude Code** | [`CLAUDE.md`](CLAUDE.md) | Claude automatically reads `CLAUDE.md` to execute scripts, format briefings, and reason over telemetry. |
| **Cursor / Windsurf** | [`.cursorrules`](.cursorrules) | Cursor IDE loads `.cursorrules` to guide code modifications and terminal executions. |
| **ChatGPT / OpenAI GPTs** | [`docs/AGENT_INTEGRATION_GUIDE.md`](docs/AGENT_INTEGRATION_GUIDE.md) | Import the provided OpenAPI 3.1.0 schema into Custom GPT Actions to query `/api/telemetry` & `/api/depth`. |
| **OpenClaw / LangChain / CrewAI** | [`docs/AGENT_INTEGRATION_GUIDE.md`](docs/AGENT_INTEGRATION_GUIDE.md) | Use the Python `@tool` wrapper classes to query live market intelligence from your multi-agent pipelines. |
| **Google Antigravity** | [`AGENTS.md`](AGENTS.md) & [`skills/`](skills/pine_sr_calculator/SKILL.md) | Native multi-agent Sentinel orchestrator with subagent delegation. |

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

