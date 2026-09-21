"""
Liquidity-Pulse - Liquidity Pool Study

derivation_study.py scores every level by hold rate: price enters the zone, does it
reverse or break? That is the right question for support and resistance, and it is
the *wrong* question for a liquidity pool.

A pool is not a level price is expected to respect. It is a level price is expected
to be drawn to and then through, because that is where the unfilled stop and
liquidation orders sit. Scored on hold rate the pool derivations came out at −2.5 to
−7.2 points against their control, and that number reads as a failure only if you
forget what was being claimed: breaking more often than a random nearby price is
what a magnet is supposed to do. The hold-rate harness cannot tell a good pool from
a bad level, because it treats the same event as a loss for one and a win for the
other.

So this module asks the two questions a pool actually makes:

**Reach.** Within the next H bars, does price trade beyond the pool? Compared
against a control displaced a short distance on the same side, which is the sharp
version of the question: *is this particular price a magnet, or would any price at
roughly this distance be reached about as often?*

**Reversal after the sweep.** Given price did reach it, does it then turn? This is
the tradeable claim -- pool as entry trigger rather than as a barrier -- and it is
scored with symmetric barriers from the reach bar, so a coin flip is 50%.

The control displacement is deliberately smaller than derivation_study's 0.6-2%.
Reach probability is dominated by distance from price: a level 0.3% away is reached
far more often than one 3% away, whatever it is. Displacing far enough to change the
distance materially would compare against a different question, and the result would
be a measure of how far away the pools happened to be. `CONTROL_BAND` keeps the
control close enough that distance is roughly held constant.
"""

import os
import sys
import json
import random
import logging
import statistics
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

sys.path.insert(0, str(os.path.dirname(__file__)))

from backtester import SRBacktester
import liquidity_pools

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("PoolStudy")

Klines = List[Dict[str, Any]]

# Same-side displacement for the control. Wide enough that it is a different price,
# narrow enough that it is at a comparable distance from spot.
CONTROL_BAND = (0.003, 0.010)


def _pool_prices(klines: Klines, kind: str) -> List[Tuple[float, str]]:
    """(price, side) for one pool family. Side is ABOVE or BELOW."""
    if kind == "untested":
        pools = liquidity_pools.untested_extremes(klines)
    elif kind == "equal":
        pools = liquidity_pools.equal_levels(klines)
    elif kind == "session":
        pools = liquidity_pools.session_extremes(klines)
    elif kind == "all":
        pools = liquidity_pools.all_pools(klines)
    else:
        raise ValueError(f"unknown pool kind {kind!r}")
    return [(p.price, p.side) for p in pools]


def _swing_control(klines: Klines, rng: random.Random) -> List[Tuple[float, str]]:
    """
    Control family: every swing point, untested or not, displaced like the others.

    Included as a second reference because "untested" is the interesting half of the
    pool claim. If untested extremes are reached no more often than swings in
    general, the untested part is carrying nothing.
    """
    sh, sl = liquidity_pools.swing_points(klines)
    return [(p, "ABOVE") for _, p in sh] + [(p, "BELOW") for _, p in sl]


FAMILIES: List[Tuple[str, Callable[[Klines, random.Random], List[Tuple[float, str]]]]] = [
    ("pools: untested extremes", lambda k, r: _pool_prices(k, "untested")),
    ("pools: equal highs/lows", lambda k, r: _pool_prices(k, "equal")),
    ("pools: session extremes", lambda k, r: _pool_prices(k, "session")),
    ("pools: all combined", lambda k, r: _pool_prices(k, "all")),
    ("all swings (tested or not)", _swing_control),
]


def evaluate(
    levels: List[Tuple[float, str]],
    ref_price: float,
    forward: Klines,
    reversal_pct: float,
    reversal_bars: int
) -> List[Dict[str, Any]]:
    """
    For each level: was it reached, how fast, and did price turn once it was.

    A level on the wrong side of spot is skipped rather than flipped. A pool above
    price and a pool below it are different trades, and silently reassigning the
    side would mix them.
    """
    out: List[Dict[str, Any]] = []

    for price, side in levels:
        if side == "ABOVE" and price <= ref_price:
            continue
        if side == "BELOW" and price >= ref_price:
            continue

        distance_pct = abs(price - ref_price) / ref_price * 100.0

        reach_index: Optional[int] = None
        for j, candle in enumerate(forward):
            if side == "ABOVE" and candle["high"] > price:
                reach_index = j
                break
            if side == "BELOW" and candle["low"] < price:
                reach_index = j
                break

        row: Dict[str, Any] = {
            "distance_pct": distance_pct,
            "reached": reach_index is not None,
            "bars_to_reach": reach_index,
            "reversed": None
        }

        if reach_index is not None:
            # Symmetric barriers from the pool price. Reversal means price retraced
            # `reversal_pct` back toward where it came from before extending the same
            # distance beyond. Ties resolve against the reversal, as elsewhere in this
            # repo, because intrabar order is unknowable and the optimistic reading
            # would flatter the result.
            if side == "ABOVE":
                target = price * (1.0 - reversal_pct)
                against = price * (1.0 + reversal_pct)
            else:
                target = price * (1.0 + reversal_pct)
                against = price * (1.0 - reversal_pct)

            verdict: Optional[bool] = None
            end = min(reach_index + 1 + reversal_bars, len(forward))
            for candle in forward[reach_index + 1:end]:
                if side == "ABOVE":
                    hit_t = candle["low"] <= target
                    hit_a = candle["high"] >= against
                else:
                    hit_t = candle["high"] >= target
                    hit_a = candle["low"] <= against
                if hit_t and hit_a:
                    verdict = False
                    break
                if hit_t:
                    verdict = True
                    break
                if hit_a:
                    verdict = False
                    break
            row["reversed"] = verdict

        out.append(row)

    return out


class PoolStudy:
    def __init__(self, symbol: str = "BTCUSDT", interval: str = "15m", total_candles: int = 20000):
        self.backtester = SRBacktester(symbol=symbol, interval=interval, total_candles=total_candles)

    def run(
        self,
        lookback: int = 500,
        horizon: int = 50,
        reversal_pct: float = 0.005,
        reversal_bars: int = 32,
        control_seeds: int = 30,
        output_path: Optional[str] = None
    ) -> Dict[str, Any]:
        klines = self.backtester.history()
        starts = list(range(lookback, len(klines) - horizon, horizon))
        logger.info(f"{len(klines)} candles, {len(starts)} folds.")

        results = []
        for name, builder in FAMILIES:
            rng = random.Random(0)
            real_rows: List[Dict[str, Any]] = []
            per_seed_reach: List[float] = []
            per_seed_rev: List[float] = []

            for start in starts:
                window = klines[start - lookback:start]
                forward = klines[start:start + horizon]
                ref = window[-1]["close"]
                real_rows.extend(
                    evaluate(builder(window, rng), ref, forward, reversal_pct, reversal_bars)
                )

            for seed in range(control_seeds):
                crng = random.Random(1000 + seed)
                rows: List[Dict[str, Any]] = []
                for start in starts:
                    window = klines[start - lookback:start]
                    forward = klines[start:start + horizon]
                    ref = window[-1]["close"]
                    shifted = []
                    for price, side in builder(window, crng):
                        off = crng.uniform(*CONTROL_BAND) * (1 if crng.random() < 0.5 else -1)
                        shifted.append((price * (1.0 + off), side))
                    rows.extend(evaluate(shifted, ref, forward, reversal_pct, reversal_bars))
                per_seed_reach.append(_rate(rows, "reached"))
                per_seed_rev.append(_reversal_rate(rows))

            reach = _rate(real_rows, "reached")
            rev = _reversal_rate(real_rows)
            resolved_rev = sum(1 for r in real_rows if r["reversed"] is not None)
            reached_rows = [r for r in real_rows if r["reached"]]
            median_bars = (statistics.median([r["bars_to_reach"] for r in reached_rows])
                           if reached_rows else None)

            c_reach = statistics.mean(per_seed_reach) if per_seed_reach else 0.0
            c_reach_sd = statistics.pstdev(per_seed_reach) if len(per_seed_reach) > 1 else 0.0
            c_rev = statistics.mean(per_seed_rev) if per_seed_rev else 0.0
            c_rev_sd = statistics.pstdev(per_seed_rev) if len(per_seed_rev) > 1 else 0.0

            results.append({
                "family": name,
                "levels": len(real_rows),
                "mean_distance_pct": round(
                    statistics.mean([r["distance_pct"] for r in real_rows]), 3) if real_rows else 0.0,
                "reach_pct": round(reach, 2),
                "control_reach_pct": round(c_reach, 2),
                "reach_edge": round(reach - c_reach, 2),
                "reach_edge_sd": round(abs(reach - c_reach) / c_reach_sd, 1) if c_reach_sd else 0.0,
                "median_bars_to_reach": median_bars,
                "resolved_reversals": resolved_rev,
                "reversal_pct": round(rev, 2),
                "control_reversal_pct": round(c_rev, 2),
                "reversal_edge": round(rev - c_rev, 2),
                "reversal_edge_sd": round(abs(rev - c_rev) / c_rev_sd, 1) if c_rev_sd else 0.0
            })
            logger.info(f"  {name}: reach {reach:.2f}% vs {c_reach:.2f}%, "
                        f"reversal {rev:.2f}% vs {c_rev:.2f}%")

        payload = {
            "symbol": self.backtester.symbol,
            "interval": self.backtester.interval,
            "run_time_utc": datetime.now(timezone.utc).isoformat(),
            "params": {
                "lookback": lookback, "horizon": horizon,
                "reversal_pct": reversal_pct, "reversal_bars": reversal_bars,
                "control_seeds": control_seeds, "control_band": list(CONTROL_BAND),
                "total_candles": len(klines), "folds": len(starts)
            },
            "results": results
        }

        if output_path:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            logger.info(f"Pool study JSON saved to {output_path}")

        return payload


def _rate(rows: List[Dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return sum(1 for r in rows if r[key]) * 100.0 / len(rows)


def _reversal_rate(rows: List[Dict[str, Any]]) -> float:
    resolved = [r for r in rows if r["reversed"] is not None]
    if not resolved:
        return 0.0
    return sum(1 for r in resolved if r["reversed"]) * 100.0 / len(resolved)


def print_report(payload: Dict[str, Any]) -> None:
    p = payload["params"]
    print("\n" + "=" * 100)
    print("LIQUIDITY-PULSE - LIQUIDITY POOL STUDY")
    print("=" * 100)
    print(f"{payload['symbol']} {payload['interval']}  |  {p['total_candles']} candles, "
          f"{p['folds']} folds  |  horizon {p['horizon']} bars")
    print(f"Control: same side, displaced {p['control_band'][0]*100:.1f}-{p['control_band'][1]*100:.1f}%, "
          f"{p['control_seeds']} seeds")
    print(f"Reversal: {p['reversal_pct']*100:.2f}% symmetric barriers within {p['reversal_bars']} bars "
          f"(coin flip = 50%)")
    print("-" * 100)
    print(f"{'family':<28}{'lvls':>6}{'dist%':>7}{'reach%':>8}{'ctrl%':>7}{'edge':>7}{'sd':>5}"
          f"{'bars':>6}{'rev%':>7}{'ctrl%':>7}{'edge':>7}{'sd':>5}")
    print("-" * 100)
    for r in payload["results"]:
        bars = r["median_bars_to_reach"]
        print(f"{r['family']:<28}{r['levels']:>6}{r['mean_distance_pct']:>7.2f}"
              f"{r['reach_pct']:>8.2f}{r['control_reach_pct']:>7.2f}"
              f"{r['reach_edge']:>+7.2f}{r['reach_edge_sd']:>5.1f}"
              f"{bars if bars is not None else '--':>6}"
              f"{r['reversal_pct']:>7.2f}{r['control_reversal_pct']:>7.2f}"
              f"{r['reversal_edge']:>+7.2f}{r['reversal_edge_sd']:>5.1f}")
    print("-" * 100)
    hits = [r["family"] for r in payload["results"]
            if r["reach_edge"] > 0 and r["reach_edge_sd"] >= 2.0]
    rev_hits = [r["family"] for r in payload["results"]
                if r["reversal_edge"] > 0 and r["reversal_edge_sd"] >= 2.0]
    n = len(payload["results"])
    print(f"families tested: {n}   reach edges past 2 sd: {len(hits)}   "
          f"reversal edges past 2 sd: {len(rev_hits)}   expected by chance: {n * 0.05:.1f} each")
    for h in hits:
        print(f"  reach:    {h}")
    for h in rev_hits:
        print(f"  reversal: {h}")
    print("=" * 100 + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test liquidity pools as magnets, not as barriers")
    parser.add_argument("--candles", type=int, default=20000)
    parser.add_argument("--horizon", type=int, default=50)
    parser.add_argument("--reversal", type=float, default=0.005)
    parser.add_argument("--reversal-bars", type=int, default=32)
    parser.add_argument("--seeds", type=int, default=30)
    args = parser.parse_args()

    out = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "workspace", "pool_study.json"))

    study = PoolStudy(total_candles=args.candles)
    payload = study.run(
        horizon=args.horizon,
        reversal_pct=args.reversal,
        reversal_bars=args.reversal_bars,
        control_seeds=args.seeds,
        output_path=out
    )
    print_report(payload)
