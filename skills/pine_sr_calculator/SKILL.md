---
name: pine_sr_calculator
description: Instruction manual and algorithmic reference for calculating Pine Script style horizontal Support/Resistance clusters, swing high/low pivots, volume profile confluences, and conviction scoring for $BTC market structure analysis.
---

# Pine Script S/R & Market Structure Calculation Skill

This skill defines standard rules for evaluating horizontal Support & Resistance (S/R) density, swing high/low clustering, volume node confluences, and conviction scoring on $BTC market data.

---

## 1. Pivot High & Pivot Low Detection (Pine Script Style)

Follow TradingView's `ta.pivothigh` and `ta.pivotlow` algorithm:

- **Parameters**:
  - `left_bars` = 10
  - `right_bars` = 10
- **Pivot High Condition**:
  A high at index $i$ is a Pivot High if:
  $$High[i] > High[i-k] \quad \text{for all } k \in [1, \text{left\_bars}]$$
  $$\text{and } High[i] \ge High[i+k] \quad \text{for all } k \in [1, \text{right\_bars}]$$
- **Pivot Low Condition**:
  A low at index $i$ is a Pivot Low if:
  $$Low[i] < Low[i-k] \quad \text{for all } k \in [1, \text{left\_bars}]$$
  $$\text{and } Low[i] \le Low[i+k] \quad \text{for all } k \in [1, \text{right\_bars}]$$

---

## 2. Density-Based Clustering Rules

Individual pivot points must be merged into horizontal S/R zones using density clustering:

1. **Threshold ($\epsilon$)**: $0.35\%$ ($0.0035 \times \text{Price}$).
2. **Clustering Algorithm** (matches `mergePivot()` in the Pine script and `cluster_sr_levels()` in `quant_engine.py`):
   - Collect all detected Pivot High and Pivot Low prices **in the order they occurred** over the trailing 500-candle window.
   - For each pivot, walk the existing clusters in creation order and merge into the **first** whose running centre is within $|P - C| / C \le 0.0035$. If none matches, start a new cluster.
   - The centre is the arithmetic mean of the cluster's members, updated on every merge:
     $$\text{Level\_Price} = \frac{1}{N} \sum_{m=1}^{N} P_m$$
   - Do **not** sort by price and chain contiguous levels. That is a different algorithm: every merge drags the centre toward the incoming pivot, so a run of gradually rising pivots collapses into one level far wider than the threshold.
3. **Touch Count Calculation**:
   - Iterate over the same 500-candle window, against the finished cluster centres.
   - The zone is $[\text{Level\_Price} \times (1 - 0.0035), \text{Level\_Price} \times (1 + 0.0035)]$.
   - Count a touch only when a candle **enters** the zone from outside — its range intersects the zone and the previous candle's did not. The first candle of the window counts if it is already inside.
   - Do **not** count every candle whose range intersects the zone. That measures how long price loitered near a level, not how often it tested it, and inflated real levels to 200+ touches.

---

## 3. Conviction Scoring & Tagging

Each calculated level is tagged based on touch frequency and current price position:

- **Classification**:
  - `SUPPORT`: $\text{Level\_Price} < \text{Current Mid Price}$
  - `RESISTANCE`: $\text{Level\_Price} > \text{Current Mid Price}$

- **Volume Confluence**: the level sits within $0.5\%$ of the VPOC or of any HVN bin centre, measured against the reference price ($|L - X| / \text{Price} \le 0.005$).

- **Conviction Tiers** (`grade_conviction()`):
  - **High Conviction**: $\ge 3$ touches **AND** volume confluence. Touch count alone never reaches HIGH.
  - **Medium Conviction**: $\ge 2$ touches — including $\ge 3$ touches without confluence.
  - **Low Conviction / Minor**: $1$ touch (isolated pivot).

> The tier describes how a level was **constructed**, not how likely it is to hold. See
> `docs/STRATEGY.md` §5 for the benchmark.

---

## 4. Volume Profile Confluence Integration

1. **Volume Profile Bins**: 50 equal bins spanning `min(mid)` to `max(mid)`, where `mid = (high + low) / 2`, each candle's whole volume placed in the bin holding its mid. This coarse profile is the one the Pine indicator reproduces bar for bar.
2. **Volume Point of Control (VPOC)**: centre of the bin with the highest volume.
3. **High Volume Nodes (HVN)**: bins at or above the 80th percentile of bin volume (numpy's linear interpolation).
4. **Low Volume Nodes (LVN)**: bins at or below the 20th percentile.

A finer 120-bin profile that spreads each candle's volume across its high-low range ships separately as `tape_profile`; see `src/tape_profile.py`.

---

## 5. Output Data Contract

`quant_engine.py` produces JSON telemetry containing at least this structure (the full payload also carries `tape_profile`, `order_flow`, `positioning`, `liquidity_pools` and `market_summary`):

```json
{
  "timestamp": "ISO-8601 UTC string",
  "symbol": "BTCUSDT",
  "current_price": 64500.50,
  "sr_levels": [
    {
      "price": 63800.00,
      "type": "SUPPORT",
      "touch_count": 4,
      "conviction": "HIGH",
      "distance_pct": -1.08,
      "volume_confluence": true
    }
  ],
  "volume_profile": {
    "vpoc": 64200.00,
    "hvn_zones": [64200.00, 65100.00],
    "lvn_zones": [63400.00, 64800.00]
  }
}
```
