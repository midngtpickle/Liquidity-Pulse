"""
Liquidity-Pulse - Historical S/R Backtesting Engine

Walk-forward benchmark of Pine S/R clusters: levels are re-derived from a trailing
window at each fold and tested over the candles that immediately follow, then the
window advances. Reports bounce accuracy %, win rate, and conviction tier precision.
"""

import os
import sys
import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any
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


class SRBacktester:
    def __init__(self, symbol: str = "BTCUSDT", interval: str = "15m", total_candles: int = 5000):
        self.symbol = symbol
        self.interval = interval
        self.total_candles = total_candles
        self.engine = QuantEngine(symbol=symbol, interval=interval, limit=total_candles)

    def evaluate_level(
        self,
        level: SRLevel,
        test_klines: List[Dict[str, float]],
        cluster_threshold_pct: float,
        bounce_target_pct: float
    ) -> Dict[str, int]:
        """
        Counts how often price entered one level's zone during the test window and
        whether it bounced or broke through. Unchanged in substance from the original
        single-split implementation; only the surrounding windowing differs.
        """
        lvl_price = level.price
        tolerance = lvl_price * cluster_threshold_pct
        lvl_type = level.type

        level_tests = 0
        bounces = 0
        breakthroughs = 0

        i = 0
        while i < len(test_klines):
            candle = test_klines[i]
            c_low = candle["low"]
            c_high = candle["high"]

            # Check if candle touches level zone
            if c_low <= (lvl_price + tolerance) and c_high >= (lvl_price - tolerance):
                # Look ahead 4 candles to evaluate bounce vs breakthrough. A touch on
                # the final candle has no future to judge it by, so it is not counted
                # at all — counting it would leave tests > bounces + breakthroughs.
                lookahead = test_klines[i + 1: i + 5]
                if not lookahead:
                    break

                level_tests += 1

                bounced = False
                if lvl_type == "SUPPORT":
                    max_future_high = max(k["high"] for k in lookahead)
                    min_future_low = min(k["low"] for k in lookahead)
                    if max_future_high >= (lvl_price * (1.0 + bounce_target_pct)):
                        bounced = True
                    elif min_future_low < (lvl_price * (1.0 - cluster_threshold_pct * 2)):
                        bounced = False
                else:  # RESISTANCE
                    min_future_low = min(k["low"] for k in lookahead)
                    max_future_high = max(k["high"] for k in lookahead)
                    if min_future_low <= (lvl_price * (1.0 - bounce_target_pct)):
                        bounced = True
                    elif max_future_high > (lvl_price * (1.0 + cluster_threshold_pct * 2)):
                        bounced = False

                if bounced:
                    bounces += 1
                else:
                    breakthroughs += 1

                # Skip lookahead candles to avoid double counting same test
                i += 4
            else:
                i += 1

        return {"tests": level_tests, "bounces": bounces, "breakthroughs": breakthroughs}

    def run_backtest(
        self,
        cluster_threshold_pct: float = 0.0035,
        bounce_target_pct: float = 0.005,
        lookback: int = 500,
        horizon: int = 50
    ) -> Dict[str, Any]:
        """
        Walk-forward evaluation.

        At each fold, S/R levels are derived from the trailing `lookback` candles and
        tested over the next `horizon` candles, then the window advances by `horizon`.
        This mirrors production, which recomputes levels from the trailing 500 candles
        on every run.

        The previous single 50/50 chronological split benchmarked something the system
        never does: it derived levels once from the oldest half and never refreshed
        them. In any trending market that produces zero tests, because every level sits
        outside the range price occupied during the second half.
        """
        logger.info(f"Fetching {self.total_candles} historical candles for backtesting...")
        klines = self.engine.fetch_klines_paginated(self.total_candles)

        if len(klines) < lookback + horizon:
            raise ValueError(
                f"Insufficient klines for walk-forward: got {len(klines)}, "
                f"need at least {lookback + horizon} (lookback {lookback} + horizon {horizon})."
            )

        results: Dict[str, Any] = {
            "symbol": self.symbol,
            "interval": self.interval,
            "backtest_time_utc": datetime.now(timezone.utc).isoformat(),
            "method": "walk_forward",
            "total_candles": len(klines),
            "lookback_candles": lookback,
            "horizon_candles": horizon,
            "folds": 0,
            "total_level_tests": 0,
            "successful_bounces": 0,
            "breakthroughs": 0,
            "overall_win_rate_pct": 0.0,
            "conviction_stats": {
                tier: {"tests": 0, "bounces": 0, "win_rate_pct": 0.0}
                for tier in CONVICTION_TIERS
            },
            "fold_details": []
        }

        levels_per_fold: List[int] = []

        for start in range(lookback, len(klines) - horizon + 1, horizon):
            train_klines = klines[start - lookback:start]
            test_klines = klines[start:start + horizon]
            ref_price = train_klines[-1]["close"]

            # Derive levels exactly as production does for this trailing window.
            pivots = self.engine.calculate_pine_pivots(train_klines)
            sr_levels = self.engine.cluster_sr_levels(
                pivots, train_klines, ref_price, threshold_pct=cluster_threshold_pct
            )
            volume_prof = self.engine.calculate_volume_profile(train_klines)
            self.engine.apply_volume_confluence(sr_levels, volume_prof, ref_price)

            active_levels = [l for l in sr_levels if l.touch_count >= 2]
            levels_per_fold.append(len(active_levels))

            fold_tests = 0
            fold_bounces = 0
            fold_breaks = 0

            for level in active_levels:
                stats = self.evaluate_level(
                    level, test_klines, cluster_threshold_pct, bounce_target_pct
                )
                fold_tests += stats["tests"]
                fold_bounces += stats["bounces"]
                fold_breaks += stats["breakthroughs"]

                tier = level.conviction if level.conviction in CONVICTION_TIERS else "LOW"
                results["conviction_stats"][tier]["tests"] += stats["tests"]
                results["conviction_stats"][tier]["bounces"] += stats["bounces"]

            results["folds"] += 1
            results["total_level_tests"] += fold_tests
            results["successful_bounces"] += fold_bounces
            results["breakthroughs"] += fold_breaks

            results["fold_details"].append({
                "train_end_index": start,
                "train_end_time_utc": datetime.fromtimestamp(
                    train_klines[-1]["close_time"] / 1000.0, tz=timezone.utc
                ).isoformat(),
                "reference_price": round(ref_price, 2),
                "levels_evaluated": len(active_levels),
                "tests": fold_tests,
                "bounces": fold_bounces,
                "breakthroughs": fold_breaks,
                "win_rate_pct": round((fold_bounces / fold_tests * 100.0) if fold_tests else 0.0, 2)
            })

        total_t = results["total_level_tests"]
        results["overall_win_rate_pct"] = round(
            (results["successful_bounces"] / total_t * 100.0) if total_t > 0 else 0.0, 2
        )
        for tier in CONVICTION_TIERS:
            tier_stats = results["conviction_stats"][tier]
            tier_stats["win_rate_pct"] = round(
                (tier_stats["bounces"] / tier_stats["tests"] * 100.0) if tier_stats["tests"] > 0 else 0.0, 2
            )

        results["avg_levels_per_fold"] = round(float(np.mean(levels_per_fold)), 2) if levels_per_fold else 0.0

        logger.info(
            f"Walk-forward complete: {results['folds']} folds, "
            f"{results['total_level_tests']} level tests."
        )
        return results

    def print_summary(self, results: Dict[str, Any]):
        """
        Prints formatted backtest summary report to console.
        """
        print("\n" + "=" * 70)
        print("LIQUIDITY-PULSE - S/R WALK-FORWARD BENCHMARK REPORT")
        print("=" * 70)
        print(f"Symbol:                {results['symbol']} ({results['interval']})")
        print(f"History:               {results['total_candles']} candles")
        print(f"Window:                {results['lookback_candles']} train / {results['horizon_candles']} test per fold")
        print(f"Folds:                 {results['folds']}")
        print(f"Avg Levels Per Fold:   {results['avg_levels_per_fold']}")
        print(f"Total S/R Level Tests: {results['total_level_tests']}")
        print(f"Successful Bounces:    {results['successful_bounces']}")
        print(f"Breakthroughs:         {results['breakthroughs']}")
        print(f"OVERALL WIN RATE:      {results['overall_win_rate_pct']}%")
        print("-" * 70)
        for tier in CONVICTION_TIERS:
            stats = results["conviction_stats"][tier]
            print(
                f"{tier + ' CONVICTION WIN RATE:':<30} {stats['win_rate_pct']:>6}%  "
                f"({stats['bounces']}/{stats['tests']} tests)"
            )
        print("=" * 70 + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Liquidity Pulse S/R Walk-Forward Backtester")
    parser.add_argument("--candles", type=int, default=5000, help="Total history to fetch (default 5000)")
    parser.add_argument("--lookback", type=int, default=500, help="Training window per fold (default 500)")
    parser.add_argument("--horizon", type=int, default=50, help="Test window per fold (default 50)")
    args = parser.parse_args()

    backtester = SRBacktester(symbol="BTCUSDT", interval="15m", total_candles=args.candles)
    res = backtester.run_backtest(lookback=args.lookback, horizon=args.horizon)
    backtester.print_summary(res)

    # Output backtest report JSON
    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.abspath(os.path.join(script_dir, "..", "workspace"))
    report_file = os.path.join(workspace_dir, "backtest_results.json")

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(f"Backtest JSON results saved to {report_file}")
