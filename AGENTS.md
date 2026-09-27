# AGENTS.md — Coding Agent Instructions for Liquidity-Pulse

This is the single source of instructions for coding agents working on the **Liquidity-Pulse** codebase: commands, architecture references, data contracts, reasoning rules and code conventions. It follows the [AGENTS.md](https://agents.md) convention, so Codex, Cursor, Copilot, Gemini-based tools and others read it directly; `CLAUDE.md` imports it for Claude Code.

> [!NOTE]
> Edit **this** file. `CLAUDE.md` and `.cursorrules` are pointers to it, kept that way so the
> instructions cannot drift between tools.

---

## 🏛️ Project Architecture Overview

Liquidity-Pulse is a $BTC market liquidity monitoring and session intelligence system organized under the **Sentinel & Subagent Pattern**. The names are module names: every component is deterministic Python, and nothing at runtime calls an LLM. See `docs/RUNTIME_ARCHITECTURE.md` for what runs and what starts it — notably, nothing schedules `sentinel.py`.

> [!IMPORTANT]
> The tracked instrument is the **Binance USD-M perpetual, `BINANCE:BTCUSDT.P`**, on every
> surface: the Pine indicator's chart, `quant_engine.py` klines, and the `ws_feed.py` order
> book. Spot and perp are different books with different levels — do not mix them.

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

# 2. Run Sentinel Orchestrator (updates telemetry, generates SESSION_BRIEFING.md,
#    dispatches Telegram/Discord only when their env vars are set; 15s hard deadline)
python src/sentinel.py

# 3. Start Concurrent Dashboard Server & Webhook Listener (serves UI on :8080)
python src/server.py --port 8080

# 4. Start Live WebSocket depth delta & liquidation monitor
python src/ws_feed.py

# 4b. Same, but also record order book history for later analysis
#     Exchanges do not serve historical order books, so the depth signal can only be
#     tested against data recorded beforehand. ~12MB/day gzipped.
python src/ws_feed.py --record

# 5. Run Walk-Forward S/R Benchmark (5,000 candles, with random-level control)
python src/backtester.py

# 5b. Benchmark level derivations against a displaced random control
#      (adds volume-at-price and liquidity-pool rows to the fourteen S/R ones)
python src/derivation_study.py --candles 20000

# 5c. Test whether levels hold better in context (trend, sweep, session, taker flow)
python src/conditional_study.py --candles 20000

# 5d. Score liquidity pools as magnets rather than barriers.
#      Hold rate is the wrong test for a pool: it marks a working magnet as a failure.
#      This measures reach (is it traded through?) and post-reach reversal instead.
python src/pool_study.py --candles 20000

# 5e. Positioning: open interest, funding and crowd ratios.
#      OI and the long/short ratios stop 30 days back (exchange cap), which is far
#      too little to benchmark -- so record snapshots on a schedule to build history.
python src/positioning.py            # print a live snapshot
python src/positioning.py --record   # append one snapshot; run every 5 minutes

# 5f. Install the two data recorders as Windows scheduled tasks (do this once).
#      Depth history and open-interest history cannot be fetched retroactively --
#      exchanges do not serve the first at all, and cap the second at 30 days. The
#      only way to have a year of either is to have been recording for a year.
powershell -ExecutionPolicy Bypass -File scripts\install_recorders.ps1
powershell -ExecutionPolicy Bypass -File scripts\uninstall_recorders.ps1

# 6. Test Discord Webhook embed dispatcher (dry-run mode)
python src/discord_webhook.py --dry-run

# 7. Test Telegram alert dispatcher (dry-run mode)
python src/telegram_bot.py --dry-run
```

---

## 📁 Key File Map & Data Contracts

| File Path | Description | Input / Output Contract |
| :--- | :--- | :--- |
| `src/quant_engine.py` | Fetches OHLCV, calculates Pine pivots & VPOC | Reads Binance USD-M futures REST (`fapi`), Bybit `linear` fallback $\rightarrow$ Writes `workspace/telemetry_latest.json` |
| `src/ws_feed.py` | Depth from Binance, liquidations from Bybit/OKX | Connects to `fstream` `@depth@100ms`, maintaining a full local order book seeded from a REST snapshot (futures caps that snapshot at 1000 levels) $\rightarrow$ Writes `workspace/depth_latest.json`; records to `workspace/depth_history/` under a single-writer lock |
| `src/liquidation_feed.py` | Normalised multi-venue liquidations | Bybit `allLiquidation` + OKX `liquidation-orders` $\rightarrow$ `Liquidation` events with `liquidated_side` LONG/SHORT. Binance `forceOrder` delivers nothing here and is off by default |
| `src/runlock.py` | Single-writer lock for the recorders | Refuses a second writer, takes over a lock whose PID is dead |
| `src/sentinel.py` | Session intelligence generator & dispatch runner | Ingests `telemetry_latest.json` $\rightarrow$ Writes `workspace/artifacts/SESSION_BRIEFING.md` |
| `src/server.py` | Concurrent HTTP server & TradingView webhook relay | Serves `web/`, handles `/api/telemetry`, `/api/depth`, `/api/webhook/tradingview` |
| `src/discord_webhook.py` | Visual rich embed cards for Discord | Dispatches formatted embeds using `DISCORD_WEBHOOK_URL` |
| `src/telegram_bot.py` | HTML alert dispatcher for Telegram | Dispatches messages using `TELEGRAM_BOT_TOKEN` & `TELEGRAM_CHAT_ID` |
| `src/depth_recorder.py` | Gzipped JSONL order book history, one file per UTC day | Invoked by `ws_feed.py --record` $\rightarrow$ Writes `workspace/depth_history/` |
| `src/tape_profile.py` | Volume-at-price across each candle range; taker delta and CVD | Reads klines (needs Binance `taker_buy_base`) $\rightarrow$ Surfaces in telemetry as `tape_profile` / `order_flow` |
| `src/positioning.py` | Open interest, funding, long/short ratios; 30-day history wall | Reads Binance `fapi`/`futures/data` $\rightarrow$ Surfaces in telemetry as `positioning`; `--record` writes `workspace/positioning_history/` |
| `src/liquidity_pools.py` | Untested swings, equal highs/lows, session extremes | Reads klines $\rightarrow$ Surfaces in telemetry as `liquidity_pools` |
| `src/pool_study.py` | Scores pools as magnets (reach + post-reach reversal), not as barriers | Reads Binance history $\rightarrow$ Writes `workspace/pool_study.json` |
| `src/conditional_study.py` | Tests whether levels hold better under market context | Reads Binance history $\rightarrow$ Writes `workspace/conditional_study.json` |
| `src/derivation_study.py` | Compares level derivations against a random control | Reads Binance history $\rightarrow$ Writes `workspace/derivation_study.json` |
| `src/backtester.py` | Walk-forward S/R hold-rate benchmark with a random-level control | Re-derives levels per fold from the trailing 500 candles, resolves HOLD/BREAK/UNRESOLVED by first touch $\rightarrow$ Writes `workspace/backtest_results.json`. Entry-anchored by default (~40%); `--anchor level` reports ~85% and is inflated by the zone geometry |
| `scripts/install_recorders.ps1` | Registers both recorders as scheduled tasks under \Liquidity-Pulse\ | Runs pythonw.exe daemons $\rightarrow$ Writes `workspace/depth_history/`, `workspace/positioning_history/`, `workspace/logs/` |
| `scripts/uninstall_recorders.ps1` | Removes those tasks; never deletes recorded data | Unregisters \Liquidity-Pulse\* |
| `liquidity_pulse_sr.pine` | Official TradingView Pine Script v6 indicator | Rebuilds S/R levels over a 500-bar window, overlays S/R lines and VPOC, and sends alert webhooks to `src/server.py` |
| `tools/liquidation_probe.py` | Checks whether a liquidation stream actually delivers events | Records its own uptime and event counts to `workspace/liquidation_probe.jsonl` |

---

## 📐 Strategy Definition

See [`docs/STRATEGY.md`](docs/STRATEGY.md) for the strategy specification: the shared
invariants the Pine indicator and the Python hub must both honour, the alert path, and the
benchmark results.

> [!IMPORTANT]
> The conviction tier describes how a level was **constructed**, not how likely it is to
> hold. Against a randomly displaced control, production levels have measured between
> +0.08 and +1.79 points depending on the window, HIGH and MEDIUM do not measurably
> separate, and no market-context condition (trend, VPOC side, sweeps, session, flow,
> funding) has separated over up to ~2.8 years of history. Do not treat `HIGH` as a
> probability or add logic that assumes it predicts reversals.

## 🧠 Reasoning Guidelines for AI Agents

When analyzing market structure and generating briefings from telemetry data. These are the
system's labelling conventions; present them as descriptions of structure, not predictions.

1. **Volume Point of Control (VPOC)**:
   - If `current_price > vpoc` $\rightarrow$ Market bias is **BULLISH ACCUMULATION** (Fair value is acting as support).
   - If `current_price < vpoc` $\rightarrow$ Market bias is **BEARISH DISTRIBUTION** (Fair value is acting as overhead supply).
   - Tested: over ~2.8 years, levels held no differently above VPOC than below it.
2. **Support & Resistance Conviction**:
   - `HIGH`: $\ge 3$ touch points **AND** overlapping with High Volume Node (HVN) or VPOC.
   - `MEDIUM`: $2$ touch points.
   - `LOW / MINOR`: Isolated swing pivot.
3. **Liquidity Depth Imbalance Delta**:
   - $\text{Imbalance Delta \%} = \frac{\text{Bid Depth} - \text{Ask Depth}}{\text{Bid Depth} + \text{Ask Depth}} \times 100$.
   - Delta $> +15\%$ indicates heavy passive buy support (absorption).
   - Delta $< -15\%$ indicates heavy passive sell resistance.
   - Untested, and on the perpetual all three bands exceed the snapshot's ~0.16% reach, so they arrive flagged incomplete in `bands_complete`. Read a flagged band's sign as unconfirmed.
4. **Liquidation Cascade Alerts**:
   - Accumulated volume exceeding **$5,000,000 USD** within a 3-minute sliding window triggers an alert.
   - Sourced from **Bybit and OKX**, not Binance: `forceOrder` accepts a subscription here and delivers nothing (8.7h logged at zero; 0 vs Bybit 26 / OKX 57 over the same 100s).
   - Sides are normalised to `LONG`/`SHORT` at the source. Binance reports the forced *order* side and Bybit the *position* side on an identically-named field, so reading them the same way inverts longs and shorts.
   - The threshold was written for Binance's whole USD-M market. It now sums a smaller population, so treat it as a number to re-tune against observed cascades.

---

## 🛠️ Code Conventions & Safety Rules

- **Python Version**: 3.10+.
- **Typing**: Use standard Python `typing` annotations (`List`, `Dict`, `Optional`, `Tuple`, `Any`) and Pydantic models for data interchange.
- **Server Architecture**: Use `ThreadingHTTPServer` from standard library to ensure non-blocking HTTP requests for UI polling and webhooks.
- **Error Handling**: REST endpoints in `quant_engine.py` must maintain fallback mirrors (Binance $\rightarrow$ Bybit).
- **Paths**: Always use `Path(__file__).parent` relative pathing to support execution across Windows, Linux, and macOS.
