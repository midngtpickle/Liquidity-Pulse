# 📘 Liquidity-Pulse — User Operational Guide

Welcome to the **Liquidity-Pulse User Operational Guide**. This guide explains how to operate, configure, and monitor your autonomous $BTC market liquidity intelligence harness.

---

## 📐 1. Component & Architecture Overview

Liquidity-Pulse operates using a **Sentinel & Subagent Architecture**:

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
│  (src/quant_engine.py)│                                 │   (src/sentinel.py)  │
└──────────┬───────────┘                                 └──────────┬───────────┘
           │                                                        │
           ▼                                                        ▼
┌──────────────────────┐                                 ┌──────────────────────┐
│telemetry_latest.json │                                 │  SESSION_BRIEFING.md │
└──────────┬───────────┘                                 └──────────┬───────────┘
           │                                                        │
           └────────────────────────────┬───────────────────────────┘
                                        ▼
                         ┌─────────────────────────────┐
                         │   Visual Dashboard Server   │
                         │    http://localhost:8080    │
                         └─────────────────────────────┘
```

## 💻 Standalone Windows Operating & Startup Guide (No Antigravity Required)

If you are running Liquidity-Pulse natively on a Windows computer outside of the Antigravity IDE, follow these instructions.

### Option A: One-Click Automatic Startup (`start_all.bat`)
The project includes a pre-configured Windows launcher batch script that automates virtual environment creation, dependency installation, pipeline execution, web server startup, and browser launch.

1. Double-click **[`start_all.bat`](file:///c:/Users/HP%20FURY/GitHub/New%20folder/liquidity-pulse/start_all.bat)** in File Explorer (or run `.\start_all.bat` from Command Prompt/PowerShell).
2. The script will:
   - Check your Python installation (`Python 3.10+`).
   - Create a virtual environment `venv/` if not present.
   - Install required dependencies from `requirements.txt`.
   - Run `sentinel.py` to compile initial telemetry.
   - Spawn background windows for `ws_feed.py` and `server.py`.
   - Automatically open **`http://localhost:8080`** in your default web browser!

---

### Option B: Manual Windows PowerShell / CMD Startup

If you prefer to start each component manually in PowerShell or Command Prompt (`cmd.exe`):

#### 1. Open PowerShell & Navigate to Project Directory
```powershell
cd "C:\path\to\liquidity-pulse"
```

#### 2. Create & Activate Virtual Environment
```powershell
# Create virtual environment
python -m venv venv

# Activate virtual environment in PowerShell
.\venv\Scripts\Activate.ps1

# (Or if using Command Prompt CMD)
# .\venv\Scripts\activate.bat
```

#### 3. Install Production Dependencies
```powershell
pip install -r requirements.txt
```

#### 4. Run Telemetry & Sentinel Engine
```powershell
python src\sentinel.py
```

#### 5. Launch the Dashboard Web Server
```powershell
python src\server.py --port 8080
```
Open **`http://localhost:8080`** in Chrome, Edge, or Firefox.

#### 6. Launch Live WebSocket Feed (In a second PowerShell window)
```powershell
.\venv\Scripts\Activate.ps1
python src\ws_feed.py
```

---

## 🚀 2. Command-Line Execution Guide (Cross-Platform)

All execution commands are run inside the `liquidity-pulse/` directory.

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Run the Quantitative Engine (`src/quant_engine.py`)
Fetches 500 candles of 15m $BTC data from Binance/Bybit REST endpoints, clusters horizontal S/R zones using Pine Script pivot math, calculates Volume Profile (VPOC, HVNs, LVNs), and writes output to `workspace/telemetry_latest.json`.
```bash
python src/quant_engine.py
```
> **Output**: `workspace/telemetry_latest.json`

### Step 3: Run the Sentinel Orchestrator (`src/sentinel.py`)
Executes `quant_engine.py`, detects the active session open (Asia, London, or New York), and generates an institutional session intelligence briefing.
```bash
python src/sentinel.py
```
> **Output**: `workspace/artifacts/SESSION_BRIEFING.md`

### Step 4: Run the Real-Time WebSocket Feed (`src/ws_feed.py`)
Connects to Binance live WebSockets (`@depth20@100ms` and `@forceOrder`), calculates 0.5%, 1%, and 2% depth imbalance deltas, and triggers alerts on liquidation cascades exceeding $5,000,000 over a 3-minute window.
```bash
# Run for 30 seconds test
python src/ws_feed.py --duration 30

# Run continuously as daemon
python src/ws_feed.py
```

### Step 5: Launch the Visual Web UI Dashboard (`src/server.py`)
Launches the HTTP web server on port `8080` to serve the interactive terminal interface:
```bash
python src/server.py --port 8080
```
> **Access URL**: `http://localhost:8080`

---

## 🖥️ 3. Navigating the Visual Web UI (`http://localhost:8080`)

Open your browser to `http://localhost:8080` to access the terminal:

1. **Header Bar**:
   - Displays live $BTC mid-price, 24h High/Low range, 24h Volume, and Active Trading Session.
   - **`Refresh Telemetry`** button triggers on-demand quantitative engine recalculation.
2. **Pine S/R Clusters Heatmap Table**:
   - Filter by `All`, `Supports`, `Resistances`, or `High Conviction`.
   - Displays price levels, touch count frequency, distance %, and volume confluence tags (`VPOC/HVN`).
3. **Volume Profile Chart**:
   - Interactive horizontal bar chart.
   - Gold bar = **VPOC** (Volume Point of Control / Fair Value Anchor).
   - Cyan bars = **HVN** (High Volume Nodes / Price Acceptance).
   - Magenta bars = **LVN** (Low Volume Nodes / Air Pockets).
4. **Order Book Depth Imbalance Gauges**:
   - Shows live bid vs. ask depth percentages across 0.5%, 1%, and 2% depth bands.
5. **Institutional Session Briefing Reader**:
   - Formatted Markdown renderer showing the latest report from `SESSION_BRIEFING.md`.

---

## 📡 4. REST API Endpoint Reference

The dashboard web server exposes REST API endpoints for integration:

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `GET /api/telemetry` | `GET` | Returns machine-readable market telemetry JSON (`telemetry_latest.json`) |
| `GET /api/depth` | `GET` | Returns real-time depth delta and band metrics (`depth_latest.json`) |
| `GET /api/briefing` | `GET` | Returns latest session briefing markdown content (`SESSION_BRIEFING.md`) |
| `POST /api/refresh` | `POST` | Triggers `QuantEngine` and updates telemetry & briefing on demand |
| `POST /api/webhook/tradingview` | `POST` | Ingests TradingView alert webhook signals and broadcasts to Discord/Telegram |
| `GET /api/tradingview/signals` | `GET` | Returns historical list of received TradingView alert signals |
| `GET /api/health` | `GET` | Health check endpoint returning `{"status": "healthy"}` |

---

## 📲 6. Discord & Telegram Alert Setup

### Discord Webhook Configuration
1. Open your Discord server -> Channel Settings -> Integrations -> **Webhooks**.
2. Click **New Webhook**, copy the Webhook URL.
3. Set environment variable:
   ```bash
   # Windows PowerShell
   $env:DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/your/webhook/url"
   
   # Windows CMD
   set DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your/webhook/url
   ```
4. **Dispatches**:
   - 🟢 Color-coded Session Briefing Cards (Bulls in Green, Bears in Red) with VPOC, S/R tables, and clickable dashboard links.
   - 🚨 High-urgency **$5M+ Liquidation Cascade Alert Embeds**.

### Telegram Bot Configuration
1. Create a bot with `@BotFather` on Telegram to get your `TELEGRAM_BOT_TOKEN`.
2. Get your channel or user `TELEGRAM_CHAT_ID`.
3. Set environment variables:
   ```bash
   $env:TELEGRAM_BOT_TOKEN="your_token_here"
   $env:TELEGRAM_CHAT_ID="your_chat_id_here"
   ```

---

## 📈 7. TradingView Webhook Integration

Connect your TradingView charts directly into the Liquidity-Pulse server:

1. In TradingView, add the **[`liquidity_pulse_sr.pine`](file:///c:/Users/HP%20FURY/GitHub/New%20folder/Liquidity-Pulse/liquidity_pulse_sr.pine)** indicator script.
2. Click **Create Alert** on the indicator.
3. In the alert settings:
   - **Condition**: Select `Liquidity-Pulse: Support Touch` or `Liquidity-Pulse: Resistance Touch`.
   - **Webhook URL**: Check the Webhook URL box and enter `http://your-server-ip:8080/api/webhook/tradingview` (or your ngrok / public URL).
   - **Message**: Enter JSON payload:
     ```json
     {
       "symbol": "{{ticker}}",
       "event": "SUPPORT_TOUCH",
       "level_type": "SUPPORT",
       "price": {{close}},
       "conviction": "HIGH",
       "message": "High conviction support test on TradingView"
     }
     ```
4. When triggered, the server receives the alert, saves it to `workspace/tradingview_signals.json`, and automatically relays rich embeds to your Discord channel and Telegram chat!

---

## ⏰ 8. Automated Session Schedule & Daemons

To run the framework continuously in the background:
- **WebSocket Daemon**: Runs `ws_feed.py` with automatic reconnection logic to capture liquidation cascades.
- **Session Open Cron**: Triggers `sentinel.py` at `00:00 UTC` (Asia Open), `07:00 UTC` (London Open), and `13:30 UTC` (NY Open).
