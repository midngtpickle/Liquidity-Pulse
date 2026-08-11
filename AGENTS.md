# Liquidity Pulse 3.6 — Multi-Agent Harness Manifest

System Architecture for **Liquidity Pulse 3.6**: Autonomous $BTC market liquidity monitoring and session intelligence agent cluster powered by Gemini 3.6.

---

## Agent Cluster Hierarchy

```
                   +----------------------------+
                   |  Sentinel Agent (Orch.)   |
                   | Cron: 00:00, 07:00, 13:30 |
                   +-------------+--------------+
                                 |
         +-----------------------+-----------------------+
         |                                               |
         v                                               v
+------------------+                           +--------------------+
|  Quant Subagent  |                           |   Macro Subagent   |
| (Code Execution) |                           |  (LLM Reasoning)   |
+--------+---------+                           +---------+----------+
         |                                               |
         v                                               v
[telemetry_latest.json]                       [SESSION_BRIEFING.md]
```

---

## 1. Sentinel Agent (Orchestrator)

- **Role**: Lead Systems Orchestrator & Session Dispatcher.
- **Capabilities**:
  - Monitors session schedules across global trading hubs:
    - **Asia Session Open**: `00:00 UTC` (`0 0 * * *`)
    - **London Session Open**: `07:00 UTC` (`0 7 * * *`)
    - **New York Session Open**: `13:30 UTC` (`30 13 * * *`)
  - Evaluates real-time event hooks (liquidation spikes > $5M, order book depth delta imbalance > 35%).
  - Triggers the pipeline execution sequence (`quant_engine.py` -> telemetry verification -> `sentinel.py` synthesis).
- **Tool Access**: Read/Write filesystem, subagent invocation (`invoke_subagent`), schedule management (`schedule`).
- **Permissions**: Full orchestration control.

---

## 2. Quant Subagent (Execution)

- **Role**: Data Extraction, Math Engine & Telemetry Compiler.
- **Capabilities**:
  - Restricts operations to deterministic code execution and localized sandboxed data transformations.
  - Fetches 500 candles of 15-minute $BTCUSDT OHLCV data from Binance/Bybit REST endpoints with automatic retry logic.
  - Executes Pine Script-style horizontal S/R pivot detection (`ta.pivothigh` / `ta.pivotlow`, left/right=10).
  - Performs density-based spatial clustering (0.35% band tolerance) and ranks levels by touch frequency.
  - Computes Volume Profile (VPOC, High/Low Volume Nodes) and liquidity depth imbalances.
  - Outputs strictly structured, validated JSON to `workspace/telemetry_latest.json`.
- **Tool Access**: `run_command`, filesystem read/write scoped to `src/` and `workspace/`.
- **Permissions**: Code execution only; strictly prohibited from direct external narrative publishing.

---

## 3. Macro Subagent (Reasoning)

- **Role**: Institutional Market Intelligence Synthesizer.
- **Capabilities**:
  - Ingests `workspace/telemetry_latest.json` alongside live market structure inputs.
  - Applies institutional trading frameworks (Auction Market Theory, ICT Liquidity Sweeps, Wyckoff Accumulation/Distribution).
  - Evaluates key S/R conviction levels (High Conviction: >= 3 touches + volume node confluence).
  - Generates institutional-grade session briefs output to `workspace/artifacts/SESSION_BRIEFING.md`.
  - Dispatches alerting payloads to designated Discord/Slack webhooks on high-conviction events.
- **Tool Access**: Read `workspace/telemetry_latest.json`, write `workspace/artifacts/SESSION_BRIEFING.md`, network webhook dispatch.
- **Permissions**: LLM synthesis and reporting; read-only access to quantitative telemetry.

---

## Agent Communication Protocol

1. **Trigger Phase**: Sentinel receives schedule event or volatility alert.
2. **Quant Phase**: Sentinel invokes Quant Subagent to run `quant_engine.py`. Quant Subagent writes `workspace/telemetry_latest.json`.
3. **Macro Phase**: Sentinel triggers Macro Subagent with prompt referencing `telemetry_latest.json`.
4. **Publish Phase**: Macro Subagent writes `workspace/artifacts/SESSION_BRIEFING.md` and reports completion back to Sentinel.
