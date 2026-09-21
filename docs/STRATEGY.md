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
| **Volume at price** | Same question, at the resolution a wick can be seen in | `tape_profile.py` |
| **Taker order flow** | Who is crossing the spread, and is flow leading or lagging price? | `tape_profile.py` |
| **Liquidity pools** | Where are the *unfilled* stop orders? | `liquidity_pools.py` |
| **Positioning** | What is the market holding, and what does it cost to hold it? | `positioning.py` |
| **Depth imbalance** | Is resting liquidity stacked on the bid or the ask right now? | `ws_feed.py` only |
| **Liquidations** | Who is being forced out, on which side, and how fast? | `liquidation_feed.py` |

The first two are derived from OHLCV candles and are computed **twice** — once in Pine for
the chart, once in Python for the dashboard, briefings and alerts. The next three are
Python-only and derived from candles. Depth imbalance needs a live order book.

The first five all answer questions about *price levels*. Liquidity pools is the only one
that asks a different kind of question, and it is scored by a different harness
(`pool_study.py`) for that reason — see §5.

### Volume at price, and why there are two profiles

`calculate_volume_profile()` puts each candle's whole volume in one bin at its mid price,
over 50 bins spanning `min(mid)` to `max(mid)`. That is a coarse instrument: the VPOC it
reports is the modal candle *midpoint* weighted by volume, and the profile's range excludes
the wicks entirely, so a level sitting in one falls off the end of the histogram.

`tape_profile.build_profile()` spreads each candle's volume across its own high-low range,
weighted by overlap, over 120 bins spanning the true traded range. On a recent window that
is a $59 bin against a $141 one.

**Both ship.** The 50-bin mid-price profile is the number the Pine indicator reproduces bar
for bar, and replacing it would desync the chart from the dashboard — the exact failure §2
is about. `telemetry_latest.json` carries the coarse one as `volume_profile` and the fine
one as `tape_profile`. The coarse one is the *shared* measurement; the fine one is the
*better* measurement.

### Taker order flow

Binance ships taker-buy base volume in field 9 of every kline, so signed taker delta is free
and fully historical — no aggregate-trade paging required. `delta = taker_buy − (volume −
taker_buy)`, and CVD is its running sum. Bybit's kline has no equivalent field, so on the
fallback `order_flow.available` is false and every figure is zero; that must not be read as
a balanced market.

### Liquidations, and why not from Binance

The cascade alert was written against Binance USD-M `forceOrder` and had, as far as
anyone can tell, never fired. The stream accepts a subscription and sends nothing:

| evidence | result |
| :--- | :--- |
| `tools/liquidation_probe.py`, 8.7 hours, BTC **and** `!forceOrder@arr` | **0 events** |
| Re-run, 275 seconds | 0 events |
| Independent minimal client sharing no code, 100 seconds | 0 events |
| Three venues, five symbols, same 100 seconds | Binance **0**, Bybit **26**, OKX **57** |

Nothing to fix on our side, so the feed was repointed. `liquidation_feed.py` normalises
Bybit `allLiquidation` and OKX `liquidation-orders` into one event type; Binance remains
implemented and selectable so the block can be re-checked, but is not a default. A
source that is silently dead is worse than one that is absent, because it looks like a
calm market.

> [!WARNING]
> **The side conventions differ, and getting them backwards inverts the signal.**
> Binance's `S` is the forced **order** side, so a liquidated long is `SELL`. Bybit's
> `S` is the **position** side, so a liquidated long is `Buy`. Same field name,
> opposite meaning.
>
> This was settled against live data, not documentation: during a rally from ~82.0k to
> ~84.1k, Bybit reported `S: "Sell"` on BTCUSDT while OKX — which states `posSide` and
> `side` separately — reported `posSide: "short"`, `side: "buy"` on the same move. A
> rally liquidates shorts, and a short closes on a forced buy. Everything downstream
> sees `liquidated_side` as `LONG` or `SHORT` and never a raw venue field.

Liquidations are now written into `workspace/depth_history/` alongside the depth
records, unthrottled — a cascade is precisely the burst that sampling would discard,
and one file sorted by `t` puts the cascade and the book around it on one timeline
without aligning two clocks.

The `$5M / 3-minute` threshold was written for Binance's entire USD-M market. Bybit plus
OKX is a different, smaller population, so it will trip less often and no longer measures
what it originally meant to. Re-tune it against cascades you actually observe.

### Positioning, and the 30-day wall

Open interest, funding and the long/short ratios describe what traders are *holding*
rather than what price has done. They come from three families of Binance endpoint, and
the histories they offer are wildly different:

| series | endpoint | history | benchmarkable? |
| :--- | :--- | :--- | :--- |
| Funding rate | `/fapi/v1/fundingRate` | years, paginates freely | **yes** |
| Open interest | `/futures/data/openInterestHist` | **30 days, hard** | no |
| Long/short ratios | `/futures/data/*LongShortRatio` | **30 days, hard** | no |

The 30-day limit is not a parameter. An `endTime` older than 30 days is rejected with
`-1130 parameter 'endTime' is invalid`, and a request near the boundary returns a short
page and stops. At 15m that is 2,880 points, which is about **46 walk-forward folds**
against the 390 the benchmark uses. The control spread at that sample size is larger than
any edge worth having, so open interest and the crowd ratios ship **untested** — the only
signals in the project that do, and the dashboard card says so in those words.

Funding is the exception, and it *was* tested; see §5.

This is the same shape of problem as the depth signal: the history cannot be fetched
because it was never served, and the only fix is to start writing it down.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_recorders.ps1
```

That registers both recorders — depth and positioning — as scheduled tasks under
`\Liquidity-Pulse\` and starts them. Positioning appends to
`workspace/positioning_history/`, gzipped JSONL, one file per UTC day. A year of open
interest exists only if you spent a year collecting it.

See [§6](#6-how-to-use-this-given-the-above) for what the tasks actually do.

#### The OI/price quadrant

The one genuinely useful thing open interest says on its own, and the reason it is worth
showing untested: pairing its direction with price's disambiguates two very different
moves that look identical on a chart.

| price | OI | reading |
| :--- | :--- | :--- |
| up | up | **new longs** — fresh money joining the move |
| up | down | **short covering** — a rally on positions closing, not opening |
| down | up | **new shorts** — fresh money selling |
| down | down | **long unwind** — a fall on positions closing |

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

And again, more subtly. Until the rebuild, Pine *accumulated* levels: a cluster was created
with `touches = 1` on the bar its first pivot confirmed, counted re-entries only from that
bar onward, and against a centre that kept moving as later pivots merged in. Nothing aged a
cluster out, so the drawn set widened the longer a chart stayed open. Python re-derived from
a fixed window every run. The two were never the same algorithm, and the divergence grew
with chart uptime rather than showing up immediately.

Measured against a live chart on 2026-09-21: **all twelve drawn levels disagreed with the
dashboard's touch count** — 8 against 13, 3 against 7, 14 against 17, one level LOW on the
chart and MEDIUM in the briefing — and two backend levels (75,308.40 and 75,542.83) had
merged into one drawn line at 75,468.48. Pine now rebuilds on the last bar. Replaying its
bar-offset arithmetic against the engine gives 13 levels, 13 identical touch counts, zero
mismatches.

The lesson that keeps repeating: **an invariant nobody checks is not an invariant.** Both
drifts were found by comparing the two implementations on live data, not by reading either
one.

---

## 3. The shared invariants

Change any of these on one side and you must change the other, or the chart and the
briefings will quietly disagree.

| Invariant | Value | Pine | Python |
| :--- | :--- | :--- | :--- |
| Pivot left/right bars | `10` / `10` | `leftBars`, `rightBars` inputs | `calculate_pine_pivots(left_bars, right_bars)` |
| Cluster threshold | `0.35%` | `clusterPct` input | `cluster_sr_levels(threshold_pct)` |
| Touch counting | rising edge only, over the whole window | `rebuildLevels()` | `entered_from_outside` mask |
| Level derivation | rebuilt from the window, not accumulated | `rebuildLevels()` on `barstate.islast` | re-derived every run |
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

[`src/derivation_study.py`](../src/derivation_study.py) tests twenty-one ways of deriving
levels against an identical evaluation and an identical control. Read this before
building anything on top of the conviction tiers.

> [!NOTE]
> The numbers below are a **re-run on a later 20,000-candle window** (to 2026-09-21) than
> the original fourteen-row table, and the baseline moved: production pivot clusters went
> from +0.08 (0.2 sd) to +1.79 (2.2 sd). That is the sample changing, not the method
> improving. It is also the clearest possible warning against reading any single row here
> as settled — a result that swings from nothing to 2 sd when the window moves is a result
> that will swing back.

**Method.** Walk-forward: levels are re-derived from the trailing 500 candles, tested over
the next 50, then the window advances — mirroring how production recomputes on every run.
A test is recorded only when price enters a zone from outside, from a definite side, and
only the nearest level is tested per candle. Outcomes resolve by first touch: HOLD, BREAK,
or UNRESOLVED.

**The control.** Every derivation is scored against the same levels displaced by a random
0.6–2% offset. This asks the sharp question: *is this particular price special, or would
any price nearby do as well?*

**Result** — BTCUSDT 15m, 20,000 candles (~7 months), 390 folds:

| derivation | resolved | real | control | edge | sd |
| :--- | ---: | ---: | ---: | ---: | ---: |
| 50/200 EMA (static) | 954 | 43.71% | 39.31% | **+4.40** | 3.4 |
| VPOC + HVN (range-dist.) | 3106 | 40.60% | 39.11% | **+1.48** | 3.2 |
| pivot clusters (production) | 2517 | 41.36% | 39.57% | **+1.79** | 2.2 |
| pivot clusters, 5+ touches | 2226 | 41.28% | 39.33% | **+1.96** | 2.0 |
| fib retracements | 1097 | 42.21% | 39.81% | +2.39 | 1.6 |
| anchored VWAP | 272 | 41.18% | 39.06% | +2.12 | 1.3 |
| prior-week high/low | 246 | 40.65% | 39.11% | +1.54 | 0.9 |
| value area edges (70%) | 531 | 42.18% | 41.04% | +1.15 | 0.4 |
| session opens | 1164 | 40.98% | 40.36% | +0.62 | 0.4 |
| LVN nodes | 1341 | 40.12% | 40.08% | +0.04 | 0.0 |
| recent pivots (150 bars) | 1632 | 39.83% | 40.15% | −0.33 | 0.2 |
| HTF pivots (30/30) | 1506 | 39.31% | 39.92% | −0.61 | 0.4 |
| pools: all combined | 1332 | 37.99% | 39.31% | −1.32 | 0.8 |
| VPOC + HVN nodes | 2284 | 38.53% | 38.91% | −0.38 | 1.0 |
| pools: equal highs/lows | 384 | 34.38% | 41.54% | −7.17 | 1.4 |
| pools: session extremes | 646 | 37.15% | 40.16% | −3.01 | 1.4 |
| round numbers | 915 | 38.47% | 39.91% | −1.44 | 1.4 |
| LVN nodes (range-dist.) | 1667 | 38.45% | 39.74% | −1.28 | 1.6 |
| pools: untested extremes | 1293 | 38.44% | 40.93% | −2.49 | 1.8 |
| untested pivots (1 touch) | 65 | 36.92% | 39.83% | −2.91 | 2.7 |
| prior-day high/low | 684 | 36.26% | 41.98% | −5.73 | 4.2 |

**Four rows clear 2 sd on this window, and none of them should be believed yet.** Twenty-one
derivations tested means roughly one row past 2 sd by chance alone; four is more than that,
but not by much, and three of the four have an obvious problem:

- **50/200 EMA (static)**, the strongest row at 3.4 sd, is frozen per fold while a real EMA
  drifts. It was flagged as underpowered-by-construction in the previous run and it still is.
  A moving average that does not move is not the thing it is named after.
- **pivot clusters (production)** and **5+ touches** measured +0.08 and −0.00 on the previous
  window. They moved two full standard deviations without the code changing. That is sampling
  noise with a long memory, not a discovery.
- **VPOC + HVN (range-dist.)** at 3.2 sd is the only row that is both new and clean, and it is
  the most interesting result here: the same derivation on the mid-price profile scores −0.38.
  Attributing volume across the candle's range rather than to its midpoint moved a
  volume-node derivation from nothing to +1.48. That is a measurement improvement showing up
  as a result, which is the right order for those two things to happen in. It is still one
  window.

Raw hit rate across thresholds from 0.25% to 2.0% still sits between 47% and 55% for every
derivation and every control — a coin flip.

**All four pool rows are negative**, and that is the wrong test for them; see below.

### Pools are scored by the wrong harness here

A liquidity pool is not a level price should respect. It is a level price should be drawn to
and then straight through, because that is where the unfilled orders are. Hold rate scores
"price broke it" as a failure, so a perfectly working magnet scores negative. The four pool
rows above are being marked down for doing what they claim.

[`src/pool_study.py`](../src/pool_study.py) asks the two questions a pool actually makes.
Same walk-forward folds, same discipline, different control: displaced **0.3–1.0% on the same
side**, because reach probability is dominated by distance from spot and the derivation
study's 0.6–2% displacement would change the question.

**Result** — BTCUSDT 15m, 20,000 candles, 389 folds, 30 control seeds:

| family | levels | mean dist | reached | control | edge | sd | median bars | reversed | control | edge | sd |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pools: untested extremes | 3199 | 2.98% | 20.16% | 18.29% | **+1.87** | 5.0 | 20 | 46.41% | 51.26% | −4.85 | 2.3 |
| pools: equal highs/lows | 620 | 2.37% | 25.97% | 22.35% | **+3.61** | 2.9 | 17 | 40.14% | 49.58% | −9.44 | 2.1 |
| pools: session extremes | 1045 | 1.89% | 27.85% | 24.92% | **+2.93** | 3.4 | 20 | 41.70% | 50.60% | −8.90 | 3.1 |
| pools: all combined | 3149 | 3.00% | 19.75% | 17.91% | **+1.85** | 4.4 | 20 | 46.97% | 52.57% | −5.59 | 2.7 |
| all swings (tested or not) | 8019 | 2.47% | 27.66% | 25.47% | **+2.19** | 7.2 | 14 | 49.12% | 50.71% | −1.59 | 1.6 |

Two findings, and they point the same way.

**Reach is real.** Every family is reached more often than a price displaced a little either
side of it, all five past 2 sd, up to 7.2. The control displacement is symmetric and reach
probability is convex in distance, so by Jensen the control should be *advantaged* — the
effect survives a control that is biased against it.

**Reversal is worse than random.** Once reached, pools turn *less* often than the displaced
control, three families past 2 sd, and the coin-flip baseline for this test is 50%. Fading a
pool touch is a worse trade than fading an arbitrary nearby price.

**But the untested filter earns nothing.** Plain swing points — tested or not — show the
largest and most significant reach edge of the five. Whatever is happening is a property of
swing prices generally, not of the unfilled-orders story that motivated the module. The
mechanism may simply be that a swing high is a price the market has demonstrably traded at,
while a price 0.5% beyond it may be outside the recent range entirely.

So: **pools are targets, not entries.** That is what the dashboard card says, and it is the
only claim these numbers support.

### Order flow as a condition

[`src/conditional_study.py`](../src/conditional_study.py) asks whether a level holds more
often *in context*, with the control filtered identically and the multiple-comparison count
stated. Taker delta and CVD divergence were added as eight new conditions.

Funding was added as six more, and is the only positioning series with the history to be
there at all.

**Result** — 36 conditions, 2518 resolved baseline tests:

> **0 positive hits past 2 sd. 1.7 expected by chance.**

Not one condition separates from its control. That includes every order-flow condition and
every funding condition. The closest is "funding crowds the level" at +4.19 points (1.9 sd),
and it points the *opposite* way to the crowding hypothesis that motivated it — levels held
slightly better when funding was against the side defending them, not worse. At 1-in-36
that is noise with a direction, not a finding.

Worth noting against the previous run: taker flow's "delta against direction" was the single
2 sd hit at 30 conditions and fell back to 1.8 sd here, on a window differing by a handful of
candles. Rows at that level of significance are not stable enough to trade.

The order-flow and funding figures ship because they describe the market — who is crossing
the spread, and what it costs to stay positioned, are worth seeing — not because they
predict the next move.

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

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_recorders.ps1
```

This appends to `workspace/depth_history/`, one gzipped JSONL file per UTC day, at roughly
12MB/day — measured, not estimated: 9.5KB in 45 seconds on installation. It writes derived
band metrics every second across five band widths, a 500-level book snapshot every minute
so features nobody has thought of yet can still be recomputed, and an explicit `gap` record
on every reconnect, resync, start and stop — so analysis can treat a break in continuity as
a boundary instead of interpolating across it.

### How the recorders are scheduled

Both run as long-lived daemons under `pythonw.exe`, not as short tasks firing on a timer.
A per-snapshot task would open and close a console window every five minutes on a machine
you are trying to work on; `pythonw` has no console at all, so each recorder takes a
`--log` path and writes to `workspace/logs/` instead. That is also why
`positioning.py --record` takes `--loop SECONDS`: one process that sleeps, rather than 288
process launches a day.

Each task carries two triggers — at logon, and a five-minute repeat — with
`MultipleInstances` set to `IgnoreNew`. While the daemon is alive the repeat is ignored;
if it ever dies, the next repeat restarts it. A watchdog in two settings and no extra code.

They run **only when you are logged on**, because running otherwise would mean storing a
password in the task. That is not a trade worth making for a market data recorder, but it
does mean recording stops when you sign out — lock the machine rather than signing out if
you want it to keep going overnight.

`AllowStartIfOnBatteries` and `DontStopIfGoingOnBatteries` are set deliberately. The
defaults stop a running task the moment a laptop unplugs, which would punch silent holes
in the recording — exactly what the gap markers exist to make visible, except these holes
would be self-inflicted.

Remove with `scripts\uninstall_recorders.ps1`, which stops and unregisters both tasks and
**leaves the recorded data alone**. That data is the only copy that will ever exist.

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
3. **Check which anchor produced the number.** All three harnesses default to entry
   anchoring and report roughly 40%. `backtester.py --anchor level` measures from the
   level instead and reports ~85% on the same levels, because a test entering at the far
   edge of the zone has its target 0.15% away and its barrier 0.70%. That figure is the
   zone's geometry, not the market's behaviour. It was the backtester's default until it
   was changed, and it sat in the same repository as a 41% figure describing the same
   levels. Read it only against its own control, never against 50%.
4. **Add new derivations to `DERIVATIONS`** in `derivation_study.py` — a function taking
   `(engine, klines, ref_price, tol)` and returning `List[SRLevel]`. The evaluation is
   held fixed, so any two rows are directly comparable.
5. **Watch for underpowered rows.** A derivation emitting one or two levels per fold
   produces few tests and a large control spread. Check the `resolved` column before
   reading the edge.
6. **Verify the Pine side compiles.** The TradingView MCP can compile it in the Pine
   editor; `pine_smart_compile` reports errors without saving. The indicator once shipped
   in a non-compiling state for months without anyone noticing.
