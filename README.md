# 🌊 Liquidity Pulse 3.6 — Autonomous $BTC Market & Liquidity Intelligence Harness

**Liquidity Pulse 3.6** is an institutional-grade, multi-agent market structure and liquidity monitoring system powered by **Gemini 3.6** and built on the **Antigravity Harness Framework**.

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
liquidity-pulse/
├── AGENTS.md                          # Multi-agent roles & permissions manifest
├── requirements.txt                   # Production Python dependencies
├── README.md                          # Framework documentation
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
│   └── server.py                      # Dashboard HTTP API & static file web server
├── web/
│   ├── index.html                     # Visual web UI structure
│   ├── styles.css                     # Dark mode quantitative glassmorphic styles
│   └── app.js                         # Dynamic auto-polling frontend script
└── workspace/
    ├── telemetry_latest.json          # Machine-readable market telemetry artifact
    └── artifacts/
        ├── .gitkeep                   # Artifacts directory placeholder
        └── SESSION_BRIEFING.md        # Institutional-grade session intelligence output
```

---

## 🚀 Quick Start & Usage

### Windows Users (One-Click Launch)
Double-click **[`start_all.bat`](file:///c:/Users/HP%20FURY/GitHub/New%20folder/liquidity-pulse/start_all.bat)** in File Explorer or run `.\start_all.bat` in PowerShell. It automatically creates a virtual environment, installs requirements, compiles telemetry, starts the WebSocket daemon and Web UI server, and opens **`http://localhost:8080`** in your browser.

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
