# 📐 Liquidity-Pulse — Strategy Reference

How the strategy is defined, how the Pine indicator and the Python hub divide the work,
which invariants must hold across both, and what the benchmark says about all of it.

For *running* the system see [USER_GUIDE.md](USER_GUIDE.md). For the underlying market
theory see [ORDER_FLOW_MASTERCLASS.md](ORDER_FLOW_MASTERCLASS.md). This document is about
the strategy itself.

---

## 📖 Table of Contents

1. [What the system computes](#1-what-the-system-computes)
2. [Two implementations, one strategy](#2-two-implementations-one-strategy)
3. [The shared invariants](#3-the-shared-invariants)
4. [The alert path, end to end](#4-the-alert-path-end-to-end)
5. [What the benchmark says](#5-what-the-benchmark-says)
6. [How to use this, given the above](#6-how-to-use-this-given-the-above)
7. [Changing the strategy safely](#7-changing-the-strategy-safely)

---

## 1. What the system computes

Three independent signals:

| Signal | Question it answers | Where it lives |
| :--- | :--- | :--- |
| **S/R clusters** | Which horizontal prices has the market repeatedly turned at? | Pine + `quant_engine.py` |
| **Volume profile** | Where has volume been accepted (VPOC/HVN) or rejected (LVN)? | Pine + `quant_engine.py` |
| **Depth imbalance** | Is resting liquidity stacked on the bid or the ask right now? | `ws_feed.py` only |

The first two are derived from OHLCV candles and are computed **twice** — once in Pine for
the chart, once in Python for the dashboard, briefings and alerts. The third needs a live
order book and exists only in Python.

### S/R derivation, step by step

1. **Pivots** — `ta.pivothigh` / `ta.pivotlow` with 10 bars either side. A candle is a
   pivot high if its high exceeds the 10 highs before it and meets or exceeds the 10 after.
2. **Clustering** — each new pivot is merged into an existing level if it falls within
   **0.35%** of that level's running mean; otherwise it starts a new level.
3. **Touch counting** — a touch is counted when price *enters* the level's zone from
   outside. Bars that merely sit inside the zone do not add touches.
4. **Conviction** — see the invariant table below.

### Volume profile

A 50-bin histogram over candle mid-prices `(high + low) / 2`, weighted by volume, across
500 candles. VPOC is the centre of the heaviest bin. HVN and LVN are the bins above the
80th and below the 20th percentile of bin volume.

### Depth imbalance

`(bid_depth − ask_depth) / (bid_depth + ask_depth) × 100`, measured across 0.5%, 1.0% and
2.0% bands from mid, against a full local order book seeded from a REST snapshot and
maintained by the `@depth@100ms` diff stream.

> [!IMPORTANT]
> On the USD-M perpetual the REST snapshot caps at **1,000 levels**, which reaches only
> about **0.16%** from mid. All three bands are wider than that, so all three are
> **under-reported** — the diff stream reports a level only when it changes, so resting
> liquidity beyond the seed reach is invisible. Every snapshot publishes a
> `bands_complete` map alongside `book.complete_bid_span_pct`. A band flagged `false` is a
> floor, not a measurement, and the dashboard marks it `PARTIAL`.

#### Book reach: spot vs perpetual

Recorded 2026-09-03, when the system moved from Binance spot to `BINANCE:BTCUSDT.P` so
that the chart and the backend would describe the same instrument. The move cost snapshot
reach, and the numbers are kept here because the loss is not obvious from the code.

| | Spot (before) | USD-M perpetual (now) |
| :--- | :--- | :--- |
| Endpoint | `api.binance.com/api/v3/depth` | `fapi.binance.com/fapi/v1/depth` |
| Snapshot cap | 5,000 levels | **1,000 levels** (exchange maximum) |
| Contiguous reach from mid | ~1.11% bid / ~1.15% ask | ~0.16% bid / ~0.17% ask |
| `bands_complete` | 0.5% ✅ 1.0% ✅ 2.0% ❌ | 0.5% ❌ 1.0% ❌ 2.0% ❌ |
| Depth inside the 0.5% band | ~$16M bid / ~$18M ask | ~$74-103M bid / ~$53-80M ask |

The last row is the part worth remembering: **the perpetual book is far deeper in dollar
terms, not shallower.** What was lost is reach, not liquidity. The perp book packs much
more size into a tighter price range, so a 1,000-level snapshot covers less ground than
5,000 levels did on the thinner spot book.

This is not fixable in code. 1,000 is Binance's hard cap for `fapi/v1/depth`, and while
the diff stream does extend real coverage as levels change, `complete_bid_span_pct` is
deliberately frozen at seed time: a resting level that has not moved since the snapshot
is still invisible, so a reach that grew with the stream would overstate what is known.

If this is ever worth reopening, the options are a paid market-data feed with full-book
snapshots, aggregating several venues, or publishing an observed-reach figure alongside
the seed-time guarantee and treating the two differently. Until then the 0.5% band is the
most trustworthy of the three, and all three are floors.

---

## 2. Two implementations, one strategy

```
        TradingView chart                        Your machine
   ┌───────────────────────────┐        ┌──────────────────────────────┐
   │ liquidity_pulse_sr.pine   │        │ quant_engine.py              │
   │  · ta.pivothigh/low 10/10 │        │  · calculate_pine_pivots()   │
   │  · merge within 0.35%     │  ═══   │  · cluster_sr_levels()       │
   │  · debounced touches      │ must   │  · debounced touch counting  │
   │  · 50-bin VPOC histogram  │ agree  │  · calculate_volume_profile()│
   │  · grade conviction       │        │  · grade_conviction()        │
   └─────────────┬─────────────┘        └───────────────┬──────────────┘
                 │ alert webhook                        │ telemetry_latest.json
                 ▼                                      ▼
        ┌────────────────────────────────────────────────────────┐
        │ server.py  ·  dashboard :8080  ·  sentinel briefings    │
        └────────────────────────────────────────────────────────┘
```

They are **not** client and server. Neither calls the other to compute levels. They are
two independent implementations of the same specification, and the only thing keeping
them in agreement is that someone wrote them to match.

**Why duplicate at all?** Pine cannot reach your local machine, and the Python hub cannot
draw on a TradingView chart. The chart needs levels rendered live as candles form; the
dashboard, briefings and Discord/Telegram alerts need them as JSON.

**What goes wrong.** These two have drifted before. The Pine VPOC was once a
single-peak-volume-bar proxy while Python ran the 50-bin histogram — the same label on
the chart and in the briefing, describing different prices. Since VPOC drives the
bullish/bearish bias rule, the chart and the briefing could disagree about market bias
while both looked authoritative. Touch counting and conviction had drifted the same way.

---

## 3. The shared invariants

Change any of these on one side and you must change the other, or the chart and the
briefings will quietly disagree.

| Invariant | Value | Pine | Python |
| :--- | :--- | :--- | :--- |
| Pivot left/right bars | `10` / `10` | `leftBars`, `rightBars` inputs | `calculate_pine_pivots(left_bars, right_bars)` |
| Cluster threshold | `0.35%` | `clusterPct` input | `cluster_sr_levels(threshold_pct)` |
| Touch counting | rising edge only | `pivotInZone` debounce | `entered_from_outside` mask |
| Cluster merge order | time order, first matching centre | `mergePivot()` | `cluster_sr_levels()` |
| S/R lookback | `500` candles | `srLookback` input | `QuantEngine(limit=500)` + pivot lead-in |
| Conviction: HIGH | ≥3 touches **AND** HVN/VPOC overlap | `minTouchesHigh` + confluence | `grade_conviction()` |
| Conviction: MEDIUM | ≥2 touches | same | same |
| Conviction: LOW | isolated pivot | same | same |
| VPOC bins | `50` over mid-prices | `vpocBins` input | `calculate_volume_profile(num_bins)` |
| VPOC lookback | `500` candles | `vpocBars` input | `QuantEngine(limit=500)` |
| Timeframe | `15m` | chart timeframe | `QuantEngine(interval="15m")` |

> [!WARNING]
> **The chart must be on 15m** for the Pine output to match the telemetry. The indicator
> reads whatever timeframe the chart is on; the backend is hardcoded to `15m`. On a 1h
> chart the indicator is internally consistent but will not agree with the dashboard.

Conviction cannot be finalised where levels are clustered, because the volume profile does
not exist yet. In Python, `cluster_sr_levels()` grades provisionally and
`apply_volume_confluence()` finalises. **Any caller that skips the second pass caps every
level at MEDIUM** — that is by construction, not a bug, but it will silently flatten your
tiers if you forget.

---

## 4. The alert path, end to end

```
Pine: price re-enters a HIGH-conviction zone
  │
  ├─ alertcondition()  → const message, {{close}} only
  └─ alert()           → dynamic message, carries level price and touch count
  │
  ▼
TradingView alert  →  POST /api/webhook/tradingview?secret=…
  │
  ▼
server.py  ·  validates secret  ·  appends workspace/tradingview_signals.json
  │
  ├─→ Discord embed   (DISCORD_WEBHOOK_URL)
  └─→ Telegram HTML   (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID)
```

**The secret must travel in the query string.** TradingView alerts cannot set custom
headers, and `alertcondition` messages are const strings so it cannot ride in the JSON
body either. Set `TRADINGVIEW_WEBHOOK_SECRET` in the environment *before* starting the
server — [server.py](../src/server.py) reads it once at import, so a running server will
never pick up a change.

The endpoint binds `127.0.0.1`. Until you put a tunnel in front of it the secret is
optional; the moment you do, an unauthenticated endpoint lets anyone who finds the URL
write to your signals file and fire your Discord and Telegram alerts.

---

## 5. What the benchmark says

[`src/derivation_study.py`](../src/derivation_study.py) tests fourteen ways of deriving
levels against an identical evaluation and an identical control. Read this before
building anything on top of the conviction tiers.

**Method.** Walk-forward: levels are re-derived from the trailing 500 candles, tested over
the next 50, then the window advances — mirroring how production recomputes on every run.
A test is recorded only when price enters a zone from outside, from a definite side, and
only the nearest level is tested per candle. Outcomes resolve by first touch: HOLD, BREAK,
or UNRESOLVED.

**The control.** Every derivation is scored against the same levels displaced by a random
0.6–2% offset. This asks the sharp question: *is this particular price special, or would
any price nearby do as well?*

**Result** — BTCUSDT 15m, 20,000 candles (~7 months), 390 folds:

| derivation | resolved tests | real | control | edge |
| :--- | ---: | ---: | ---: | ---: |
| pivot clusters (production) | 2296 | 38.81% | 38.73% | **+0.08** |
| pivot clusters, 5+ touches | 2048 | 39.06% | 39.06% | **−0.00** |
| VPOC + HVN nodes | 2311 | 39.16% | 39.55% | −0.39 |
| LVN nodes | 1332 | 40.54% | 39.91% | +0.63 |
| fib retracements | 1046 | 40.25% | 39.23% | +1.02 |
| recent pivots (150 bars) | 1563 | 40.37% | 40.20% | +0.17 |
| HTF pivots (30/30) | 1534 | 38.14% | 40.72% | −2.58 |
| session opens | 1214 | 38.30% | 40.76% | −2.45 |
| round numbers | 1014 | 37.67% | 39.10% | −1.43 |
| prior-day high/low | 694 | 40.35% | 41.60% | −1.25 |
| 50/200 EMA (static) | 969 | 39.42% | 39.68% | −0.25 |
| anchored VWAP | 293 | 36.18% | 37.26% | −1.08 |
| prior-week high/low | 270 | 37.78% | 41.53% | −3.75 |
| untested pivots (1 touch) | 65 | 35.38% | 43.99% | −8.61 |

**No derivation beats its control by 2 standard deviations.** Raw hit rate across
thresholds from 0.25% to 2.0% sits between 45% and 53% for every derivation and every
control — a coin flip.

### What this does and does not establish

**Does:** over this sample, price entering these zones does not reverse more often than it
reverses at an arbitrary price 0.6–2% away. The sample supports ruling out an edge larger
than roughly 2 points.

**Does not:** it tests whether price *reverses at a level over the following bars*. It
says nothing about levels as context for position sizing or stop placement, nothing about
other regimes (this window trended hard), nothing about other timeframes or symbols, and
nothing about the depth-imbalance signal, which is untested because historical order books
are not available from the exchange.

Two rows are underpowered by construction and should not be read as tested at all:
*untested pivots* yields 0.7 levels per fold, and the *EMA* row is frozen per fold while a
real EMA drifts.

---

## 6. How to use this, given the above

The conviction badge describes **how a level was constructed** — how many times price
returned to it, and whether volume was accepted there. It does not describe how likely the
level is to hold. 🔥 HIGH means "three or more touches with volume confluence", and that is
all it means.

That makes the levels a reasonable **market-structure visualisation**: a compact answer to
"where has this market been turning, and where has volume been accepted?" Nothing in the
benchmark undermines that use. What the benchmark does undermine is treating the tier as a
probability, or gating alerts as though HIGH were more likely to hold than MEDIUM.

The depth imbalance is the signal in this system that has *not* been shown to lack an
edge — it has simply never been tested, because testing it needs order-book history that
exchanges do not serve. That history can only come from data recorded beforehand:

```bash
python src/ws_feed.py --record
```

This appends to `workspace/depth_history/`, one gzipped JSONL file per UTC day, at roughly
12MB/day. It writes derived band metrics every second across five band widths, a 500-level
book snapshot every minute so features nobody has thought of yet can still be recomputed,
and an explicit `gap` record on every reconnect, resync, start and stop — so analysis can
treat a break in continuity as a boundary instead of interpolating across it.

Each derived record carries the book's `span`, the reach it is complete to. Bands wider
than that span are floors rather than measurements; filter on it before trusting a wide
band. At 15m resolution you get 96 samples a day, so a sample large enough for the same
walk-forward-plus-control treatment is one to two months away. Purchased L2 history from a
market data vendor is the alternative to waiting.

---

## 7. Changing the strategy safely

1. **Change one side, change the other.** Work through the invariant table in §3.
2. **Re-run the benchmark against the control.** `python src/derivation_study.py`. A new
   derivation is worth keeping if it beats its control; a hold rate on its own is not
   evidence of anything, which is why the control is not optional.
3. **Add new derivations to `DERIVATIONS`** in `derivation_study.py` — a function taking
   `(engine, klines, ref_price, tol)` and returning `List[SRLevel]`. The evaluation is
   held fixed, so any two rows are directly comparable.
4. **Watch for underpowered rows.** A derivation emitting one or two levels per fold
   produces few tests and a large control spread. Check the `resolved` column before
   reading the edge.
5. **Verify the Pine side compiles.** There is no Pine compiler in this repo; paste the
   file into the TradingView editor. The indicator once shipped in a non-compiling state
   for months without anyone noticing.
