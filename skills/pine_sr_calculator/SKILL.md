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
2. **Clustering Algorithm**:
   - Collect all detected Pivot High and Pivot Low price levels.
   - Sort price levels in ascending order.
   - Group contiguous levels where $|P_{j} - P_{i}| / P_{i} \le 0.0035$.
   - Calculate cluster center as the volume-weighted average price (VWAP) or mean of pivot prices in the cluster:
     $$\text{Level\_Price} = \frac{1}{N} \sum_{m=1}^{N} P_m$$
3. **Touch Count Calculation**:
   - Iterate over all historical 15m candles in the dataset (e.g., 500 candles).
   - Count a "touch" whenever a candle's range $[Low, High]$ intersects the level tolerance zone:
     $$\text{Zone} = [\text{Level\_Price} \times (1 - 0.0035), \text{Level\_Price} \times (1 + 0.0035)]$$

---

## 3. Conviction Scoring & Tagging

Each calculated level is tagged based on touch frequency and current price position:

- **Classification**:
  - `SUPPORT`: $\text{Level\_Price} < \text{Current Mid Price}$
  - `RESISTANCE`: $\text{Level\_Price} > \text{Current Mid Price}$

- **Conviction Tiers**:
  - **High Conviction**: $\ge 3$ touch points **AND** overlapping with High Volume Node (HVN) or Key Pivot.
  - **Medium Conviction**: $2$ touch points.
  - **Low Conviction / Minor**: $1$ touch point (isolated pivot).

---

## 4. Volume Profile Confluence Integration

1. **Volume Profile Bins**: Divide price range into 50 equal bins over the 500-candle sample.
2. **Volume Point of Control (VPOC)**: Bin with the absolute highest traded volume.
3. **High Volume Nodes (HVN)**: Bins with volume in top 20th percentile of profile volume.
4. **Low Volume Nodes (LVN)**: Bins with volume in bottom 20th percentile (acts as rapid price traversal / slippage zones).

---

## 5. Output Data Contract

Quant Subagent scripts MUST produce JSON telemetry matching this schema structure:

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
