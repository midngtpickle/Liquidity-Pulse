# 🌊 Liquidity-Pulse — Autonomous $BTC Market & Liquidity Intelligence Harness

**Liquidity-Pulse** is an institutional-grade, multi-agent market structure and liquidity monitoring system built on the **Antigravity Harness Framework**.

---

## 🏛️ System Architecture

Liquidity Pulse uses a **Sentinel & Subagent Pattern**:

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
│  - Volume Profile    │                                 │  - Webhook Alerts    │
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
├── requirements.txt                   # Production Python dependencies
├── README.md                          # Framework documentation
├── READ.md                            # Quick summary documentation
├── start_all.bat                      # One-click Windows launcher script
├── liquidity_pulse_sr.pine            # Official TradingView Pine Script v5 indicator
├── docs/
│   ├── USER_GUIDE.md                  # Comprehensive user operational manual & API reference
│   └── ORDER_FLOW_MASTERCLASS.md      # Institutional Order Flow & Market Structure Masterclass
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
│   ├── backtester.py                  # Historical S/R backtester & accuracy benchmark
│   └── server.py                      # Dashboard HTTP API & static file web server
├── web/
│   ├── index.html                     # Visual web UI structure
│   ├── styles.css                     # Dark mode quantitative glassmorphic styles
│   └── app.js                         # Dynamic auto-polling frontend script
└── workspace/
    ├── telemetry_latest.json          # Machine-readable market telemetry artifact
    ├── backtest_results.json          # Historical backtest benchmark results
    └── artifacts/
        ├── .gitkeep                   # Artifacts directory placeholder
        └── SESSION_BRIEFING.md        # Institutional-grade session intelligence output
```

---

## 🚀 Quick Start & Usage

### Windows Users (One-Click Launch)
Double-click **[`start_all.bat`](file:///start_all.bat)** in File Explorer or run `.\start_all.bat` in PowerShell. It automatically creates a virtual environment, installs requirements, compiles telemetry, starts the WebSocket daemon and Web UI server, and opens **`http://localhost:8080`** in your browser.

---

### Manual Cross-Platform Setup

#### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

#### 2. Run the Quantitative Telemetry Engine
```bash
python src/quant_engine.py
```

#### 3. Run the Sentinel Orchestrator
```bash
python src/sentinel.py
```

#### 4. Run the Visual Dashboard Server
```bash
python src/server.py --port 8080
```
Open **`http://localhost:8080`** in your browser!
