# 📘 Liquidity-Pulse — User Operational Guide

Welcome to the **Liquidity-Pulse User Operational Guide**. This guide explains how to operate, configure, and monitor your autonomous $BTC market liquidity intelligence harness.

---

## 📐 1. Component & Architecture Overview

Liquidity-Pulse is a set of deterministic Python processes plus a TradingView indicator.
There are no LLM agents at runtime; "Sentinel" and "Quant engine" are module names.

```
 sentinel.py ─► quant_engine.py ─► telemetry_latest.json ─┐
            └─────────────────────► SESSION_BRIEFING.md ───┤
 ws_feed.py ──► depth_latest.json, liquidations_latest.json┼─► server.py ─► http://localhost:8080
 liquidity_pulse_sr.pine (TradingView) ─── alert webhook ──┘
```

`sentinel.py` runs when you start it, when `start_all.bat` starts it, or when the dashboard's
Refresh button is pressed. Nothing runs it on a timer. `ws_feed.py` and `server.py` are
long-running. See [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md) for the full picture.

## 💻 Standalone Windows Operating & Startup Guide (No Antigravity Required)

If you are running Liquidity-Pulse natively on a Windows computer outside of the Antigravity IDE, follow these instructions.

### Option A: One-Click Automatic Startup (`start_all.bat`)
The project includes a pre-configured Windows launcher batch script that automates virtual environment creation, dependency installation, pipeline execution, web server startup, and browser launch.

1. Double-click **[`start_all.bat`](../start_all.bat)** in File Explorer (or run `.\start_all.bat` from Command Prompt/PowerShell).
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
Fetches 500 candles of 15m `BINANCE:BTCUSDT.P` data from Binance USD-M futures REST (Bybit `linear` fallback), clusters horizontal S/R zones using Pine Script pivot math, calculates Volume Profile (VPOC, HVNs, LVNs), and writes output to `workspace/telemetry_latest.json`.
```bash
python src/quant_engine.py
```
> **Output**: `workspace/telemetry_latest.json`

### Step 3: Run the Sentinel Orchestrator (`src/sentinel.py`)
Executes `quant_engine.py`, labels the active session (Asia, London, or New York), generates the session briefing, and sends it to Telegram/Discord if their credentials are set.
```bash
python src/sentinel.py
```
> **Output**: `workspace/artifacts/SESSION_BRIEFING.md`

### Step 4: Run the Real-Time WebSocket Feed (`src/ws_feed.py`)
Connects to Binance for depth (`@depth@100ms`) and to **Bybit and OKX** for liquidations, maintains a full local order book seeded from a REST snapshot, calculates 0.5%, 1%, and 2% depth imbalance deltas, and triggers alerts on liquidation cascades exceeding $5,000,000 over a 3-minute window summed across those venues.

> [!NOTE]
> Liquidations do not come from Binance. `btcusdt@forceOrder` and the market-wide `!forceOrder@arr` both accept a subscription here and then deliver nothing — 8.7 hours of logged uptime at zero events, and 0 against Bybit's 26 and OKX's 57 over an identical 100 seconds. See [`src/liquidation_feed.py`](../src/liquidation_feed.py).

> [!WARNING]
> Only one recorder may write at a time. `workspace/depth_history/` is append-only gzip, and two writers produce an unreadable file rather than a merged one. A second `--record` process refuses to start and names the PID holding the lock.

The REST snapshot is capped at 1,000 levels per side on the USD-M perpetual, which reaches roughly 0.16% from mid, so all three bands sit outside it. Bands wider than that reach are under-reported until resting liquidity beyond it moves, so every snapshot publishes a `bands_complete` map alongside `book.complete_bid_span_pct` / `complete_ask_span_pct`. Treat a band flagged `false` as a floor, not a measurement.
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
   - Instrument (`BINANCE:BTCUSDT.P`), live mid-price, and the active trading session.
   - **`Refresh Telemetry`** runs the full `sentinel.py` pipeline on demand. Once Telegram or Discord is configured, **every refresh also sends a briefing** to those channels.
2. **Stat Cards**: 24h range and volume, VPOC, count of HIGH-conviction levels, VPOC bias, and cumulative taker delta (CVD) over the 500-candle window.
3. **Pine S/R Clusters Table**:
   - Filter by `All`, `Supports`, `Resistances`, or `High Conviction`.
   - Price levels, touch count, distance %, and volume confluence tags (`VPOC/HVN`). The same levels the Pine indicator draws on a 15m chart.
4. **Positioning**: funding (and annualised rate) with a countdown to the next settlement, open interest and its 24h change, the top-trader long/short ratio, and the OI/price quadrant. Open interest and the ratios are marked **untested** — the exchange only serves 30 days of their history.
5. **Liquidity Pools**: untested swing extremes, equal highs/lows and session extremes, with side and distance. These are targets price tends to reach, not levels to fade — see [STRATEGY.md §5](STRATEGY.md#pools-are-scored-by-the-wrong-harness-here).
6. **Order Book Depth Imbalance**:
   - Bid vs. ask depth across the 0.5%, 1% and 2% bands, from `ws_feed.py`.
   - Bands wider than the order-book snapshot can see are marked **partial**. On the perpetual that is all three; treat them as floors, not measurements.
7. **Volume Profile Chart**: gold bar = **VPOC**, cyan = **HVN**, magenta = **LVN**, over 500 candles.
8. **Session Briefing Reader**: the latest `SESSION_BRIEFING.md`, rendered.

Liquidations are not shown on the dashboard; read them from `GET /api/liquidations`.

---

## 📡 4. REST API Endpoint Reference

The dashboard web server exposes REST API endpoints for integration:

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `GET /api/telemetry` | `GET` | Returns machine-readable market telemetry JSON (`telemetry_latest.json`) |
| `GET /api/depth` | `GET` | Returns real-time depth delta and band metrics (`depth_latest.json`) |
| `GET /api/liquidations` | `GET` | Returns the rolling 3-minute liquidation cascade window (`liquidations_latest.json`): `status` (`NORMAL`/`CASCADE`), `total_liquidations_usd`, `long_liquidations_usd`, `short_liquidations_usd`, `event_count`, `venues`. Written by `ws_feed` on every liquidation and on a 2s heartbeat, so a moving `timestamp` distinguishes a quiet market from a stopped feed. Serves `status: "waiting_for_feed"` before the first snapshot. |
| `GET /api/briefing` | `GET` | Returns latest session briefing markdown content (`SESSION_BRIEFING.md`) |
| `POST /api/refresh` | `POST` | Runs the full `sentinel.py` pipeline in the background (`202`, or `429` if one is already running): telemetry, briefing, and a briefing alert to any configured channel. Unauthenticated. |
| `POST /api/webhook/tradingview` | `POST` | Ingests TradingView alert webhook signals and relays them to configured channels. Checks `TRADINGVIEW_WEBHOOK_SECRET` if set; `401` on a wrong secret, `413` over 64KB, `503` if bound off-box with no secret. |
| `GET /api/tradingview/signals` | `GET` | Returns historical list of received TradingView alert signals |
| `GET /api/health` | `GET` | Health check endpoint returning `{"status": "healthy"}` |

---

## 📲 5. Telegram & Discord Alert Setup

Each channel is used **only when its environment variables are set**. An unconfigured
channel is skipped silently (the dispatchers log a dry run instead). Sending costs nothing on
either platform.

### Telegram Bot Configuration
1. Message [@BotFather](https://t.me/BotFather), send `/newbot`, and follow the prompts. It gives you a token.
2. Send any message to your new bot, then open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` and read `"chat":{"id": ...}`. That number is your chat ID.
3. Set both as persistent user environment variables:
   ```powershell
   setx TELEGRAM_BOT_TOKEN "your_token_here"
   setx TELEGRAM_CHAT_ID "your_chat_id_here"
   ```
4. **Open a new terminal.** `setx` only affects processes started afterwards, and every module reads the environment once at import, so a running server or feed never sees the change. (`$env:NAME="..."` works too, but only for the current PowerShell window.)
5. Test without sending anything: `python src/telegram_bot.py --dry-run`.

Tokens are scrubbed from error logs before they are written.

### Discord Webhook Configuration
1. Open your Discord server -> Channel Settings -> Integrations -> **Webhooks**.
2. Click **New Webhook**, copy the Webhook URL.
3. `setx DISCORD_WEBHOOK_URL "https://discord.com/api/webhooks/..."`, then open a new terminal.

### What gets sent

| Alert | When | Needs |
| :--- | :--- | :--- |
| Session briefing | whenever `sentinel.py` runs — including every dashboard Refresh | nothing else |
| Liquidation cascade | more than $5M liquidated across Bybit and OKX within 3 minutes; 3-minute cooldown | `ws_feed.py` running |
| TradingView S/R touch | price re-enters a HIGH-conviction zone on your chart | the setup in §6 |

There is no queue: an alert that would have fired while the machine was off or the feed was
stopped is simply never sent. Briefing dispatch has a hard 15-second deadline, so a hung
request cannot stall the pipeline.

---

## 📈 6. TradingView Webhook Integration

Connect your TradingView charts directly into the Liquidity-Pulse server:

1. In TradingView, add the **[`liquidity_pulse_sr.pine`](../liquidity_pulse_sr.pine)** indicator to a **15m** `BINANCE:BTCUSDT.P` chart. On other timeframes it will not agree with the dashboard.
2. Make the server reachable from the internet. It binds `127.0.0.1` by default, which TradingView cannot reach; use a tunnel such as `ngrok http 8080`, which gives you an HTTPS URL and keeps the server bound to localhost.
3. Set a secret **before** starting the server, then start it in a new terminal:
   ```powershell
   setx TRADINGVIEW_WEBHOOK_SECRET "a-long-random-string"
   ```
   If you instead bind the server off-box (`--host 0.0.0.0`) without a secret, the webhook refuses every request with `503`. Behind a tunnel the server is still bound to localhost, so that guard does **not** apply — without a secret, anyone who finds the tunnel URL can post alerts.
4. Click **Create Alert** on the indicator and choose one of:
   - **Condition** `Liquidity-Pulse: Support Touch` or `Resistance Touch` — sends a fixed JSON message with `{{close}}`.
   - **Condition** `Any alert() function call` — sends a richer message that also carries the tested `level` and its `touch_count`.
5. **Webhook URL**: `https://<your-tunnel>/api/webhook/tradingview?secret=<your-secret>`. The secret has to go in the query string: TradingView cannot set custom headers, and the alert messages are fixed in the indicator, so it cannot go in the body.
6. When triggered, the server checks the secret, strips it from the payload, appends the signal to `workspace/tradingview_signals.json`, and relays it to whichever of Telegram and Discord are configured.

> [!NOTE]
> Every read endpoint and `POST /api/refresh` are unauthenticated. A public tunnel exposes
> them too — including the ability to trigger a refresh, and therefore a Telegram briefing.

---

## ⏰ 7. Background Processes & Recorders

- **WebSocket feed**: `ws_feed.py` reconnects on its own. Each liquidation venue reconnects independently with capped backoff, so one venue going down costs that venue only.
- **Session briefings are not scheduled.** `sentinel.py` uses 00:00, 07:00 and 13:30 UTC to label which session is active, but nothing runs it at those times. If you want briefings at session opens, add a Windows Task Scheduler entry for `venv\Scripts\python.exe src\sentinel.py`.
- **Data recorders** (optional): order-book depth and open interest cannot be fetched retroactively, so the only way to have their history is to record it. Install both as scheduled tasks once:
  ```powershell
  powershell -ExecutionPolicy Bypass -File scripts\install_recorders.ps1
  ```
  They run while you are logged on (locking the screen is fine; signing out stops them) and restart themselves if they die. Remove with `scripts\uninstall_recorders.ps1`, which never deletes recorded data. Details in [STRATEGY.md §6](STRATEGY.md#how-the-recorders-are-scheduled).

---

## 🔬 8. Research Harnesses

Each benchmark re-derives levels walk-forward and scores them against randomly displaced
control levels, because a hold rate on its own says nothing. Results and their limits are
written up in [STRATEGY.md §5](STRATEGY.md#5-what-the-benchmark-says).

```bash
python src/backtester.py                        # production levels, hold rate vs control
python src/derivation_study.py --candles 20000  # many ways of deriving levels
python src/conditional_study.py --candles 20000 # levels under trend, sweeps, session, flow
python src/pool_study.py --candles 20000        # liquidity pools as magnets
```
