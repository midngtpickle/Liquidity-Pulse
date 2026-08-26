"""
Liquidity-Pulse - Historical S/R Backtesting Engine

Walk-forward benchmark of Pine S/R clusters. Levels are re-derived from a trailing
window at each fold and tested over the candles that immediately follow, mirroring how
production recomputes levels on every run.

A test is recorded only when price enters a level's zone from outside, approaching from
a definite side. The outcome is resolved by walking candles in order and taking whichever
happens first -- the level holding and price reaching the target, or price breaching the
level by the break margin. Outcomes that reach neither inside the resolution window are
reported as UNRESOLVED rather than silently counted as failures.
"""

import os
import sys
import json
import random
import logging
import statistics
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
import numpy as np

# Add src to sys.path
sys.path.insert(0, str(os.path.dirname(__file__)))

from quant_engine import QuantEngine, SRLevel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("SRBacktester")

CONVICTION_TIERS = ("HIGH", "MEDIUM", "LOW")
OUTCOMES = ("HOLD", "BREAK", "UNRESOLVED")


class SRBacktester:
    def __init__(self, symbol: str = "BTCUSDT", interval: str = "15m", total_candles: int = 5000):
        self.symbol = symbol
        self.interval = interval
        self.total_candles = total_candles
        self.engine = QuantEngine(symbol=symbol, interval=interval, limit=total_candles)
        self._kline_cache: Optional[List[Dict[str, float]]] = None

    def history(self) -> List[Dict[str, float]]:
        """Fetches once and reuses, so a parameter sweep does not re-hit the exchange."""
        if self._kline_cache is None:
            logger.info(f"Fetching {self.total_candles} historical candles for backtesting...")
            self._kline_cache = self.engine.fetch_klines_paginated(self.total_candles)
        return self._kline_cache

    @staticmethod
    def resolve_outcome(
        level_price: float,
        direction: str,
        klines: List[Dict[str, float]],
        test_index: int,
        target_pct: float,
        break_margin_pct: float,
        resolve_bars: int
    ) -> str:
        """
        Walks forward candle by candle and returns whichever happens first.

        Order matters. Taking max/min across the whole window, as the original did,
        scores a level that broke and then recovered as a successful hold.

        When one candle straddles both the target and the barrier, the adverse move is
        assumed to have come first. Intrabar sequence is unknowable from OHLC, and
        assuming the favourable leg first would flatter the result.
        """
        if direction == "SUPPORT":
            target = level_price * (1.0 + target_pct)
            barrier = level_price * (1.0 - break_margin_pct)
        else:
            target = level_price * (1.0 - target_pct)
            barrier = level_price * (1.0 + break_margin_pct)

        end = min(test_index + 1 + resolve_bars, len(klines))
        for j in range(test_index + 1, end):
            candle = klines[j]
            if direction == "SUPPORT":
                hit_target = candle["high"] >= target
                hit_barrier = candle["low"] <= barrier
            else:
                hit_target = candle["low"] <= target
                hit_barrier = candle["high"] >= barrier

            if hit_target and hit_barrier:
                return "BREAK"
            if hit_target:
                return "HOLD"
            if hit_barrier:
                return "BREAK"

        return "UNRESOLVED"

    def evaluate_fold(
        self,
        levels: List[SRLevel],
        test_klines: List[Dict[str, float]],
        zone_tolerance_pct: float,
        target_pct: float,
        break_margin_pct: float,
        resolve_bars: int
    ) -> List[Dict[str, Any]]:
        """
        Produces one test record per candle that freshly enters a level's zone.

        Only the nearest qualifying level is tested on any given candle. Clustered
        levels would otherwise each emit their own record for the same price action,
        and those records are not independent observations.

        The support/resistance hypothesis comes from the side price approached from,
        not from where the level sat when it was derived. A level classified SUPPORT at
        fold start that price has since fallen below is overhead supply now, and testing
        it for an upward bounce measures the wrong thing.
        """
        records: List[Dict[str, Any]] = []
        if not levels or len(test_klines) < 2:
            return records

        for i in range(1, len(test_klines)):
            candle = test_klines[i]
            prev = test_klines[i - 1]

            best: Optional[Tuple[float, SRLevel, str]] = None
            for level in levels:
                price = level.price
                tol = price * zone_tolerance_pct

                if not (candle["low"] <= price + tol and candle["high"] >= price - tol):
                    continue

                # Require a fresh entry from a definite side. If the previous candle was
                # already inside the zone this is continuation, not a new test.
                if prev["low"] > price + tol:
                    direction = "SUPPORT"
                elif prev["high"] < price - tol:
                    direction = "RESISTANCE"
                else:
                    continue

                distance = abs(candle["close"] - price)
                if best is None or distance < best[0]:
                    best = (distance, level, direction)

            if best is None:
                continue

            _, level, direction = best
            outcome = self.resolve_outcome(
                level.price, direction, test_klines, i,
                target_pct, break_margin_pct, resolve_bars
            )
            records.append({
                "candle_index": i,
                "level_price": round(level.price, 2),
                "conviction": level.conviction,
                "touch_count": level.touch_count,
                "volume_confluence": level.volume_confluence,
                "direction": direction,
                "outcome": outcome
            })

        return records

    @staticmethod
    def control_levels(active_levels: List[SRLevel], rng: random.Random) -> List[SRLevel]:
        """
        Null-hypothesis levels: the same count, drawn uniformly across the price band the
        real levels occupy, carrying none of the pivot-cluster derivation.

        Drawing from the real band rather than anywhere on the chart keeps the comparison
        honest. The question is whether a derived level beats an arbitrary price in the
        same region, not whether it beats a line somewhere price never went.
        """
        if not active_levels:
            return []
        low = min(l.price for l in active_levels)
        high = max(l.price for l in active_levels)
        return [
            SRLevel(
                price=rng.uniform(low, high),
                type="SUPPORT",
                touch_count=3,
                conviction="HIGH",
                distance_pct=0.0,
                volume_confluence=True
            )
            for _ in active_levels
        ]

    def run_backtest(
        self,
        cluster_threshold_pct: float = 0.0035,
        target_pct: float = 0.005,
        break_margin_pct: float = 0.0035,
        resolve_bars: int = 8,
        lookback: int = 500,
        horizon: int = 50,
        min_touches: int = 2,
        control_seeds: int = 5
    ) -> Dict[str, Any]:
        """
        Walk-forward evaluation.

        At each fold, S/R levels are derived from the trailing `lookback` candles and
        tested over the next `horizon` candles, then the window advances by `horizon`.
        """
        klines = self.history()

        if len(klines) < lookback + horizon:
            raise ValueError(
                f"Insufficient klines for walk-forward: got {len(klines)}, "
                f"need at least {lookback + horizon} (lookback {lookback} + horizon {horizon})."
            )

        params = {
            "cluster_threshold_pct": cluster_threshold_pct,
            "target_pct": target_pct,
            "break_margin_pct": break_margin_pct,
            "resolve_bars": resolve_bars,
            "lookback": lookback,
            "horizon": horizon,
            "min_touches": min_touches,
            "control_seeds": control_seeds
        }

        results: Dict[str, Any] = {
            "symbol": self.symbol,
            "interval": self.interval,
            "backtest_time_utc": datetime.now(timezone.utc).isoformat(),
            "method": "walk_forward_first_touch",
            "total_candles": len(klines),
            "params": params,
            "folds": 0,
            "totals": {outcome: 0 for outcome in OUTCOMES},
            "conviction_stats": {
                tier: {outcome: 0 for outcome in OUTCOMES} for tier in CONVICTION_TIERS
            },
            "fold_details": [],
            "control": {
                "seeds": control_seeds,
                "totals": {outcome: 0 for outcome in OUTCOMES},
                "hold_rate_pct_per_seed": []
            }
        }

        levels_per_fold: List[int] = []
        control_totals: List[Dict[str, int]] = [
            {outcome: 0 for outcome in OUTCOMES} for _ in range(control_seeds)
        ]
        rngs = [random.Random(seed) for seed in range(control_seeds)]

        for fold_index, start in enumerate(range(lookback, len(klines) - horizon + 1, horizon)):
            train_klines = klines[start - lookback:start]
            test_klines = klines[start:start + horizon]
            ref_price = train_klines[-1]["close"]

            pivots = self.engine.calculate_pine_pivots(train_klines)
            sr_levels = self.engine.cluster_sr_levels(
                pivots, train_klines, ref_price, threshold_pct=cluster_threshold_pct
            )
            volume_prof = self.engine.calculate_volume_profile(train_klines)
            self.engine.apply_volume_confluence(sr_levels, volume_prof, ref_price)

            active_levels = [l for l in sr_levels if l.touch_count >= min_touches]
            levels_per_fold.append(len(active_levels))

            fold_records = self.evaluate_fold(
                active_levels, test_klines, cluster_threshold_pct,
                target_pct, break_margin_pct, resolve_bars
            )

            fold_counts = {outcome: 0 for outcome in OUTCOMES}
            for record in fold_records:
                outcome = record["outcome"]
                tier = record["conviction"] if record["conviction"] in CONVICTION_TIERS else "LOW"
                fold_counts[outcome] += 1
                results["totals"][outcome] += 1
                results["conviction_stats"][tier][outcome] += 1

            # Same evaluation, same fold, randomly placed levels. A hold rate quoted
            # without this alongside it is not interpretable.
            for seed_index in range(control_seeds):
                control = self.control_levels(active_levels, rngs[seed_index])
                for record in self.evaluate_fold(
                    control, test_klines, cluster_threshold_pct,
                    target_pct, break_margin_pct, resolve_bars
                ):
                    control_totals[seed_index][record["outcome"]] += 1

            results["folds"] += 1
            results["fold_details"].append({
                "fold_index": fold_index,
                "train_end_index": start,
                "train_end_time_utc": datetime.fromtimestamp(
                    train_klines[-1]["close_time"] / 1000.0, tz=timezone.utc
                ).isoformat(),
                "reference_price": round(ref_price, 2),
                "levels_evaluated": len(active_levels),
                **fold_counts
            })

        results["avg_levels_per_fold"] = (
            round(float(np.mean(levels_per_fold)), 2) if levels_per_fold else 0.0
        )
        results["hold_rate_pct"] = self.hold_rate(results["totals"])

        seed_rates = [self.hold_rate(t) for t in control_totals]
        for totals in control_totals:
            for outcome in OUTCOMES:
                results["control"]["totals"][outcome] += totals[outcome]
        results["control"]["hold_rate_pct_per_seed"] = seed_rates
        if seed_rates:
            mean_rate = statistics.mean(seed_rates)
            sd_rate = statistics.pstdev(seed_rates)
            results["control"]["hold_rate_pct_mean"] = round(mean_rate, 2)
            results["control"]["hold_rate_pct_sd"] = round(sd_rate, 2)
            results["edge_points"] = round(results["hold_rate_pct"] - mean_rate, 2)
            results["edge_sd"] = (
                round(abs(results["edge_points"]) / sd_rate, 2) if sd_rate > 0 else None
            )
        for tier in CONVICTION_TIERS:
            stats = results["conviction_stats"][tier]
            stats["hold_rate_pct"] = self.hold_rate(stats)

        logger.info(
            f"Walk-forward complete: {results['folds']} folds, "
            f"{sum(results['totals'].values())} tests, "
            f"hold rate {results['hold_rate_pct']}%."
        )
        return results

    @staticmethod
    def hold_rate(counts: Dict[str, int]) -> float:
        """
        Hold rate over resolved tests only. UNRESOLVED means the horizon expired without
        the level either holding or breaking, which is not evidence either way.
        """
        resolved = counts.get("HOLD", 0) + counts.get("BREAK", 0)
        return round(counts.get("HOLD", 0) / resolved * 100.0, 2) if resolved else 0.0

    def print_summary(self, results: Dict[str, Any]):
        totals = results["totals"]
        resolved = totals["HOLD"] + totals["BREAK"]
        n = sum(totals.values())
        p = results["params"]

        print("\n" + "=" * 74)
        print("LIQUIDITY-PULSE - S/R WALK-FORWARD BENCHMARK REPORT")
        print("=" * 74)
        print(f"Symbol:            {results['symbol']} ({results['interval']})")
        print(f"History:           {results['total_candles']} candles over {results['folds']} folds")
        print(f"Level derivation:  {p['lookback']} trailing candles, "
              f"zone +/-{p['cluster_threshold_pct'] * 100:.2f}%, min {p['min_touches']} touches")
        print(f"Outcome rule:      target {p['target_pct'] * 100:.2f}% / "
              f"break {p['break_margin_pct'] * 100:.2f}% within {p['resolve_bars']} candles")
        print(f"Avg levels/fold:   {results['avg_levels_per_fold']}")
        print("-" * 74)
        print(f"Tests recorded:    {n}")
        print(f"  HOLD             {totals['HOLD']}")
        print(f"  BREAK            {totals['BREAK']}")
        print(f"  UNRESOLVED       {totals['UNRESOLVED']}"
              f"   ({totals['UNRESOLVED'] / n * 100:.1f}% of tests)" if n else "")
        print(f"HOLD RATE:         {results['hold_rate_pct']}%   (of {resolved} resolved)")
        print("-" * 74)
        print(f"{'TIER':<10}{'HOLD':>8}{'BREAK':>8}{'UNRES':>8}{'HOLD RATE':>12}")
        for tier in CONVICTION_TIERS:
            s = results["conviction_stats"][tier]
            print(f"{tier:<10}{s['HOLD']:>8}{s['BREAK']:>8}{s['UNRESOLVED']:>8}"
                  f"{s['hold_rate_pct']:>11}%")

        control = results.get("control", {})
        if control.get("hold_rate_pct_per_seed"):
            print("-" * 74)
            print(f"CONTROL ({control['seeds']} seeds of randomly placed levels, same evaluation)")
            print(f"  random hold rate:  {control['hold_rate_pct_mean']}%  "
                  f"(sd {control['hold_rate_pct_sd']})")
            print(f"  real hold rate:    {results['hold_rate_pct']}%")
            edge = results.get("edge_points")
            edge_sd = results.get("edge_sd")
            verdict = (
                "no detectable edge over random levels"
                if edge_sd is None or edge_sd < 2.0
                else "edge exceeds the random spread"
            )
            print(f"  EDGE:              {edge:+.2f} points"
                  + (f"  ({edge_sd} sd)" if edge_sd is not None else ""))
            print(f"  => {verdict}")
        print("=" * 74 + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Liquidity Pulse S/R Walk-Forward Backtester")
    parser.add_argument("--candles", type=int, default=5000)
    parser.add_argument("--lookback", type=int, default=500)
    parser.add_argument("--horizon", type=int, default=50)
    parser.add_argument("--target", type=float, default=0.005)
    parser.add_argument("--break-margin", type=float, default=0.0035)
    parser.add_argument("--resolve-bars", type=int, default=8)
    parser.add_argument("--min-touches", type=int, default=2)
    parser.add_argument("--control-seeds", type=int, default=5,
                        help="Random-level control runs (0 disables)")
    args = parser.parse_args()

    backtester = SRBacktester(symbol="BTCUSDT", interval="15m", total_candles=args.candles)
    res = backtester.run_backtest(
        target_pct=args.target,
        break_margin_pct=args.break_margin,
        resolve_bars=args.resolve_bars,
        lookback=args.lookback,
        horizon=args.horizon,
        min_touches=args.min_touches,
        control_seeds=args.control_seeds
    )
    backtester.print_summary(res)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.abspath(os.path.join(script_dir, "..", "workspace"))
    report_file = os.path.join(workspace_dir, "backtest_results.json")

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(f"Backtest JSON results saved to {report_file}")
