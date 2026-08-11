"""
Liquidity-Pulse - Historical S/R Backtesting Engine

Simulates historical price tests against calculated Pine S/R clusters over 1,000+
klines to benchmark bounce accuracy %, win rate, and conviction tier precision.
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

from quant_engine import QuantEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("SRBacktester")


class SRBacktester:
    def __init__(self, symbol: str = "BTCUSDT", interval: str = "15m", total_candles: int = 1000):
        self.symbol = symbol
        self.interval = interval
        self.total_candles = total_candles
        self.engine = QuantEngine(symbol=symbol, interval=interval, limit=total_candles)

    def run_backtest(self, cluster_threshold_pct: float = 0.0035, bounce_target_pct: float = 0.005) -> Dict[str, Any]:
        """
        Executes backtest:
        1. Fetches klines.
        2. Splits into Train (500 candles) and Test (remaining candles).
        3. Computes S/R clusters on Train set.
        4. Simulates test set candles touching S/R levels.
        """
        logger.info(f"Fetching {self.total_candles} historical candles for backtesting...")
        klines = self.engine.fetch_klines()

        if len(klines) < 300:
            raise ValueError(f"Insufficient klines fetched: {len(klines)}")

        # Split 50% Train, 50% Test
        split_idx = len(klines) // 2
        train_klines = klines[:split_idx]
        test_klines = klines[split_idx:]

        logger.info(f"Train Dataset: {len(train_klines)} candles | Test Dataset: {len(test_klines)} candles")

        # Step 1: Detect S/R clusters on train set
        mid_train_price = train_klines[-1]["close"]
        pivots = self.engine.calculate_pine_pivots(train_klines)
        sr_levels = self.engine.cluster_sr_levels(pivots, train_klines, mid_train_price, threshold_pct=cluster_threshold_pct)

        # Filter levels with at least 2 touches
        active_levels = [l for l in sr_levels if l.touch_count >= 2]
        logger.info(f"Calculated {len(active_levels)} active S/R levels on train dataset.")

        # Step 2: Backtest active levels on test dataset
        results = {
            "symbol": self.symbol,
            "backtest_time_utc": datetime.now(timezone.utc).isoformat(),
            "train_candles": len(train_klines),
            "test_candles": len(test_klines),
            "levels_evaluated": len(active_levels),
            "total_level_tests": 0,
            "successful_bounces": 0,
            "breakthroughs": 0,
            "overall_win_rate_pct": 0.0,
            "high_conviction_stats": {"tests": 0, "bounces": 0, "win_rate_pct": 0.0},
            "medium_conviction_stats": {"tests": 0, "bounces": 0, "win_rate_pct": 0.0},
            "level_details": []
        }

        for lvl in active_levels:
            lvl_price = lvl.price
            tolerance = lvl_price * cluster_threshold_pct
            lvl_type = lvl.type
            conviction = lvl.conviction

            level_tests = 0
            bounces = 0
            breakthroughs = 0

            # Iterate test candles
            i = 0
            while i < len(test_klines):
                candle = test_klines[i]
                c_low = candle["low"]
                c_high = candle["high"]

                # Check if candle touches level zone
                if c_low <= (lvl_price + tolerance) and c_high >= (lvl_price - tolerance):
                    level_tests += 1
                    
                    # Look ahead 4 candles to evaluate bounce vs breakthrough
                    lookahead = test_klines[i+1 : i+5]
                    if not lookahead:
                        break

                    bounced = False
                    if lvl_type == "SUPPORT":
                        # Target bounce: max high in lookahead exceeds (lvl_price + bounce_target)
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

            win_rate = (bounces / level_tests * 100.0) if level_tests > 0 else 0.0

            results["total_level_tests"] += level_tests
            results["successful_bounces"] += bounces
            results["breakthroughs"] += breakthroughs

            if conviction == "HIGH":
                results["high_conviction_stats"]["tests"] += level_tests
                results["high_conviction_stats"]["bounces"] += bounces
            else:
                results["medium_conviction_stats"]["tests"] += level_tests
                results["medium_conviction_stats"]["bounces"] += bounces

            results["level_details"].append({
                "price": lvl_price,
                "type": lvl_type,
                "conviction": conviction,
                "tests": level_tests,
                "bounces": bounces,
                "breakthroughs": breakthroughs,
                "win_rate_pct": round(win_rate, 2)
            })

        # Calculate Win Rates
        total_t = results["total_level_tests"]
        results["overall_win_rate_pct"] = round((results["successful_bounces"] / total_t * 100.0) if total_t > 0 else 0.0, 2)

        hc = results["high_conviction_stats"]
        results["high_conviction_stats"]["win_rate_pct"] = round((hc["bounces"] / hc["tests"] * 100.0) if hc["tests"] > 0 else 0.0, 2)

        mc = results["medium_conviction_stats"]
        results["medium_conviction_stats"]["win_rate_pct"] = round((mc["bounces"] / mc["tests"] * 100.0) if mc["tests"] > 0 else 0.0, 2)

        return results

    def print_summary(self, results: Dict[str, Any]):
        """
        Prints formatted backtest summary report to console.
        """
        print("\n" + "=" * 70)
        print("LIQUIDITY-PULSE - S/R BACKTEST BENCHMARK REPORT")
        print("=" * 70)
        print(f"Symbol:                {results['symbol']}")
        print(f"Train Dataset:         {results['train_candles']} candles")
        print(f"Test Dataset:          {results['test_candles']} candles")
        print(f"Total S/R Level Tests: {results['total_level_tests']}")
        print(f"Successful Bounces:    {results['successful_bounces']}")
        print(f"Breakthroughs:         {results['breakthroughs']}")
        print(f"OVERALL WIN RATE:      {results['overall_win_rate_pct']}%")
        print("-" * 70)
        hc = results['high_conviction_stats']
        mc = results['medium_conviction_stats']
        print(f"HIGH CONVICTION WIN RATE:   {hc['win_rate_pct']}%  ({hc['bounces']}/{hc['tests']} tests)")
        print(f"MEDIUM CONVICTION WIN RATE: {mc['win_rate_pct']}%  ({mc['bounces']}/{mc['tests']} tests)")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    backtester = SRBacktester(symbol="BTCUSDT", interval="15m", total_candles=1000)
    res = backtester.run_backtest()
    backtester.print_summary(res)

    # Output backtest report JSON
    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.abspath(os.path.join(script_dir, "..", "workspace"))
    report_file = os.path.join(workspace_dir, "backtest_results.json")

    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(f"Backtest JSON results saved to {report_file}")
