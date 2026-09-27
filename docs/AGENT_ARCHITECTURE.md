# Liquidity-Pulse — Runtime Architecture

What actually runs, what starts it, and what it writes.

> [!IMPORTANT]
> **There are no LLM agents in this system.** Earlier versions of this file described a
> "Macro Subagent" doing LLM reasoning, cron-scheduled session runs, subagent invocation
> and Slack dispatch. None of that existed. Every component below is deterministic Python:
> the session briefing is a Markdown template with values interpolated, and the market bias
> line in it is a single `if current_price > vpoc` comparison in `sentinel.py`.
>
> The names "Sentinel" and "Quant engine" are kept because they are the module names. An
> external LLM can *consume* this system's output — see
> [AGENT_INTEGRATION_GUIDE.md](AGENT_INTEGRATION_GUIDE.md) — but nothing inside it calls one.

---

## Processes

```
 on demand / start_all.bat           long-running                     scheduled (optional)
┌────────────────────────┐   ┌───────────────────────────┐   ┌──────────────────────────────┐
│ sentinel.py            │   │ ws_feed.py                │   │ install_recorders.ps1         │
│  └ quant_engine.py     │   │  · Binance USD-M depth    │   │  · ws_feed.py --record        │
│     (klines, levels,   │   │  · Bybit + OKX liqs       │   │  · positioning.py --record    │
│      profiles, flow,   │   │    (liquidation_feed.py)  │   │    --loop 300                 │
│      pools, position.) │   └─────────────┬─────────────┘   └──────────────┬───────────────┘
└───────────┬────────────┘                 │                                │
            ▼                              ▼                                ▼
 telemetry_latest.json        depth_latest.json               depth_history/*.jsonl.gz
 artifacts/SESSION_BRIEFING   liquidations_latest.json        positioning_history/*.jsonl.gz
            │                              │
            └──────────────┬───────────────┘
                           ▼
              server.py  ·  http://localhost:8080
              dashboard + REST API + TradingView webhook
```

| Process | Started by | Lifetime | Writes |
| :--- | :--- | :--- | :--- |
| `sentinel.py` | you, `start_all.bat`, or `POST /api/refresh` | runs once and exits | `telemetry_latest.json`, `SESSION_BRIEFING.md`; Telegram/Discord if configured |
| `quant_engine.py` | `sentinel.py` (or run directly) | runs once and exits | `telemetry_latest.json` |
| `ws_feed.py` | you or `start_all.bat` | long-running, reconnects | `depth_latest.json`, `liquidations_latest.json`; cascade alerts |
| `ws_feed.py --record` | the depth scheduled task | long-running daemon | `workspace/depth_history/` |
| `positioning.py --record --loop` | the positioning scheduled task | long-running daemon | `workspace/positioning_history/` |
| `server.py` | you or `start_all.bat` | long-running | `tradingview_signals.json` on webhook |

---

## What triggers what

**Nothing runs `sentinel.py` on a schedule.** Older docs listed session-open runs at 00:00,
07:00 and 13:30 UTC. Those are the boundaries `sentinel.py` uses to *label* the active
session in the briefing; no cron job or scheduled task invokes it at those times. If you
want briefings at session opens, add a Task Scheduler entry for `venv\Scripts\python.exe
src\sentinel.py` yourself.

The only scheduled tasks this repository installs are the two data recorders, via
`scripts\install_recorders.ps1`. They run under `pythonw.exe` while you are logged on, with
a five-minute watchdog trigger that restarts either if it dies. See
[STRATEGY.md §6](STRATEGY.md#how-the-recorders-are-scheduled).

**`POST /api/refresh`** — including the dashboard's *Refresh Telemetry* button — runs the
full `sentinel.py` pipeline. Once Telegram is configured, that means every refresh also
sends a briefing to your chat.

**Liquidation cascades** are evaluated inside `ws_feed.py` on every liquidation event:
more than $5M liquidated across Bybit and OKX inside a 3-minute window fires an alert, with a
3-minute cooldown. There is no depth-imbalance alert.

---

## Alert channels

Telegram and Discord are each dispatched **only when their environment variables are
set** — `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID`, and `DISCORD_WEBHOOK_URL`. An unconfigured
channel is skipped, not retried. `sentinel.py` sends on daemon threads with a hard
15-second deadline, so a hung request cannot stall the pipeline or block the process from
exiting.

There is no queue. An event that happens while the machine is off or the feed is stopped
produces no alert later.
