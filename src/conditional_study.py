"""
Liquidity-Pulse - Conditional Level Study

Tests whether S/R levels carry an edge *in context* that they do not carry unconditionally.

The derivation study asked "does price reverse at these levels" and answered no, across
fourteen derivations. That is an unconditional question, and it is not how anyone trades a
level. This module asks the conditional version: does a level hold more often when it is
tested with trend, on a sweep, above fair value, on heavy volume, in a given session?

Two disciplines make the answer trustworthy:

**The control is filtered identically.** Every condition is applied to the randomly
displaced control levels as well. Comparing filtered-real against unfiltered-random would
show an edge for any condition that merely selects calmer market states, which is most of
them.

**Multiple comparisons are counted.** Testing fourteen conditions and reporting the best
one is how noise becomes a strategy. The summary states how many rows would be expected to
clear 2 sd by chance alone, so a single hit can be read against that.

Conditions are computed from klines only. Depth imbalance is the obvious missing one, and
cannot be included until enough history exists from `ws_feed.py --record`.
"""

import os
import sys
import json
import random
import logging
import statistics
from datetime import datetime, timezone
from typing import List, Dict, Any, Callable, Tuple, Optional

sys.path.insert(0, str(os.path.dirname(__file__)))

from quant_engine import QuantEngine, SRLevel
from backtester import SRBacktester

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ConditionalStudy")

TREND_BARS = 50
TREND_DEADBAND = 0.002      # below this the market is treated as directionless
VOLUME_BARS = 20
VOLATILITY_BARS = 20

# name -> predicate over the context dict
CONDITIONS: List[Tuple[str, Callable[[Dict[str, Any]], bool]]] = [
    ("all touches (baseline)", lambda c: True),
    ("with trend", lambda c: c["trend_agrees"] is True),
    ("against trend", lambda c: c["trend_agrees"] is False),
    ("no trend", lambda c: c["trend_agrees"] is None),
    ("above VPOC", lambda c: c["above_vpoc"]),
    ("below VPOC", lambda c: not c["above_vpoc"]),
    ("sweep (pierced + reclaimed)", lambda c: c["sweep"]),
    ("deep sweep (cleared zone)", lambda c: c["deep_sweep"]),
    ("shallow sweep", lambda c: c["sweep"] and not c["deep_sweep"]),
    ("no sweep", lambda c: not c["sweep"]),
    ("sweep, with trend", lambda c: c["sweep"] and c["trend_agrees"] is True),
    ("sweep, against trend", lambda c: c["sweep"] and c["trend_agrees"] is False),
    ("sweep on heavy volume", lambda c: c["sweep"] and c["volume_ratio"] >= 1.5),
    ("heavy volume touch (>1.5x)", lambda c: c["volume_ratio"] >= 1.5),
    ("light volume touch (<0.7x)", lambda c: c["volume_ratio"] <= 0.7),
    ("fast approach", lambda c: c["approach_ratio"] >= 1.5),
    ("slow approach", lambda c: c["approach_ratio"] <= 0.7),
    ("high volatility", lambda c: c["volatility_ratio"] >= 1.3),
    ("low volatility", lambda c: c["volatility_ratio"] <= 0.8),
    ("Asia session", lambda c: c["session"] == "ASIA"),
    ("London session", lambda c: c["session"] == "LONDON"),
    ("New York session", lambda c: c["session"] == "NY"),
]


def _session(hour: int) -> str:
    if 0 <= hour < 7:
        return "ASIA"
    if 7 <= hour < 13:
        return "LONDON"
    return "NY"


class ConditionalStudy:
    def __init__(self, symbol: str = "BTCUSDT", interval: str = "15m", total_candles: int = 20000):
        self.backtester = SRBacktester(symbol=symbol, interval=interval, total_candles=total_candles)
        self.engine = self.backtester.engine

    @staticmethod
    def context(
        klines: List[Dict[str, float]],
        index: int,
        level_price: float,
        direction: str,
        vpoc: float,
        zone_tolerance_pct: float
    ) -> Dict[str, Any]:
        """
        Market state at the moment of a touch. Everything is computed from candles at or
        before `index`, so nothing here can see the outcome it will later be used to
        partition.
        """
        candle = klines[index]
        close = candle["close"]

        # Trend: signed move over TREND_BARS, with a deadband so chop is not called a
        # trend in either direction.
        start = max(0, index - TREND_BARS)
        past_close = klines[start]["close"]
        drift = (close - past_close) / past_close if past_close else 0.0
        if abs(drift) < TREND_DEADBAND:
            trend_agrees: Optional[bool] = None
        else:
            trending_up = drift > 0
            # Testing support in an uptrend, or resistance in a downtrend, is "with trend".
            trend_agrees = (direction == "SUPPORT") == trending_up

        # Sweep: price traded through the level itself and closed back on the side it
        # approached from. A pierce of the far edge of the zone was the first definition
        # tried and fired on 2% of touches -- the zone is 0.35% wide, so clearing it
        # demands an implausible wick. Piercing the level is the conventional stop-run and
        # the event a scalper is actually watching for.
        tol = level_price * zone_tolerance_pct
        if direction == "SUPPORT":
            pierced = candle["low"] < level_price
            reclaimed = close > level_price
            depth_pct = (level_price - candle["low"]) / level_price * 100.0
        else:
            pierced = candle["high"] > level_price
            reclaimed = close < level_price
            depth_pct = (candle["high"] - level_price) / level_price * 100.0
        sweep = pierced and reclaimed

        # A deep sweep clears the whole zone before reclaiming; a shallow one only nicks
        # the level. Separating them tests whether the size of the run matters.
        deep_sweep = sweep and depth_pct >= zone_tolerance_pct * 100.0

        vol_start = max(0, index - VOLUME_BARS)
        recent_volume = [k["volume"] for k in klines[vol_start:index]]
        mean_volume = sum(recent_volume) / len(recent_volume) if recent_volume else 0.0
        volume_ratio = candle["volume"] / mean_volume if mean_volume else 1.0

        # Approach: how much ground price covered getting here, versus its usual bar range.
        atr_start = max(0, index - VOLATILITY_BARS)
        ranges = [k["high"] - k["low"] for k in klines[atr_start:index]]
        mean_range = sum(ranges) / len(ranges) if ranges else 0.0
        approach = abs(close - klines[max(0, index - 3)]["close"])
        approach_ratio = approach / mean_range if mean_range else 1.0

        # Volatility now versus the longer baseline behind it.
        base_start = max(0, index - VOLATILITY_BARS * 5)
        base_ranges = [k["high"] - k["low"] for k in klines[base_start:index]]
        base_range = sum(base_ranges) / len(base_ranges) if base_ranges else 0.0
        volatility_ratio = mean_range / base_range if base_range else 1.0

        stamp = datetime.fromtimestamp(candle["open_time"] / 1000.0, tz=timezone.utc)

        return {
            "trend_agrees": trend_agrees,
            "above_vpoc": close > vpoc,
            "sweep": sweep,
            "deep_sweep": deep_sweep,
            "sweep_depth_pct": depth_pct if sweep else 0.0,
            "volume_ratio": volume_ratio,
            "approach_ratio": approach_ratio,
            "volatility_ratio": volatility_ratio,
            "session": _session(stamp.hour)
        }

    def collect(
        self,
        levels_for_fold: Callable[[List[Dict[str, float]], float], List[SRLevel]],
        lookback: int,
        horizon: int,
        tol: float,
        target: float,
        break_margin: float,
        resolve_bars: int,
        anchor: str,
        seeds: int
    ) -> Tuple[List[Dict[str, Any]], List[List[Dict[str, Any]]]]:
        """
        One pass over every fold, producing outcome+context records for the real levels and
        for each control seed. Conditions are applied afterwards by filtering these lists,
        so adding a condition costs nothing.
        """
        klines = self.backtester.history()
        starts = list(range(lookback, len(klines) - horizon + 1, horizon))
        real: List[Dict[str, Any]] = []
        controls: List[List[Dict[str, Any]]] = [[] for _ in range(seeds)]
        rngs = [random.Random(s) for s in range(seeds)]

        for start in starts:
            train = klines[start - lookback:start]
            test = klines[start:start + horizon]
            ref_price = train[-1]["close"]
            vpoc = self.engine.calculate_volume_profile(train).vpoc
            levels = levels_for_fold(train, ref_price)
            if not levels:
                continue

            arms = [(real, levels)] + [
                (controls[s], self.backtester.control_levels(levels, rngs[s], tol))
                for s in range(seeds)
            ]

            for sink, arm_levels in arms:
                for i, level, direction in self.backtester.find_tests(arm_levels, test, tol):
                    anchor_price = level.price if anchor == "level" else test[i]["close"]
                    outcome = self.backtester.resolve_outcome(
                        anchor_price, direction, test, i, target, break_margin, resolve_bars
                    )
                    ctx = self.context(klines, start + i, level.price, direction, vpoc, tol)
                    ctx["outcome"] = outcome
                    sink.append(ctx)

        return real, controls

    @staticmethod
    def rate(records: List[Dict[str, Any]], predicate) -> Tuple[float, int, int]:
        hold = brk = 0
        for r in records:
            if not predicate(r):
                continue
            if r["outcome"] == "HOLD":
                hold += 1
            elif r["outcome"] == "BREAK":
                brk += 1
        resolved = hold + brk
        return (hold / resolved * 100.0 if resolved else 0.0), hold, resolved

    def run(
        self,
        lookback: int = 500,
        horizon: int = 50,
        tol: float = 0.0035,
        target: float = 0.005,
        break_margin: float = 0.0035,
        resolve_bars: int = 32,
        anchor: str = "entry",
        seeds: int = 30,
        min_resolved: int = 100
    ) -> Dict[str, Any]:
        def derive(train, ref_price):
            levels = self.engine.cluster_sr_levels(
                self.engine.calculate_pine_pivots(train), train, ref_price, threshold_pct=tol
            )
            self.engine.apply_volume_confluence(
                levels, self.engine.calculate_volume_profile(train), ref_price
            )
            return [l for l in levels if l.touch_count >= 2]

        logger.info(f"Collecting touches across folds with {seeds} control seeds...")
        real, controls = self.collect(
            derive, lookback, horizon, tol, target, break_margin, resolve_bars, anchor, seeds
        )
        logger.info(f"Collected {len(real)} real touches, {sum(len(c) for c in controls)} control touches.")

        rows = []
        for name, predicate in CONDITIONS:
            real_rate, _, resolved = self.rate(real, predicate)
            control_rates = [self.rate(c, predicate)[0] for c in controls]
            control_rates = [r for r in control_rates if r > 0]
            if not control_rates:
                continue
            mean_rate = statistics.mean(control_rates)
            sd_rate = statistics.pstdev(control_rates)
            edge = real_rate - mean_rate
            rows.append({
                "condition": name,
                "resolved": resolved,
                "hold_rate_pct": round(real_rate, 2),
                "control_mean_pct": round(mean_rate, 2),
                "control_sd": round(sd_rate, 2),
                "edge_points": round(edge, 2),
                "edge_sd": round(abs(edge) / sd_rate, 2) if sd_rate > 0 else None,
                "underpowered": resolved < min_resolved
            })

        return {
            "symbol": self.backtester.symbol,
            "interval": self.backtester.interval,
            "run_time_utc": datetime.now(timezone.utc).isoformat(),
            "params": {
                "lookback": lookback, "horizon": horizon, "zone_tolerance_pct": tol,
                "target_pct": target, "break_margin_pct": break_margin,
                "resolve_bars": resolve_bars, "anchor": anchor, "control_seeds": seeds,
                "min_resolved": min_resolved
            },
            "conditions_tested": len(rows),
            "results": rows
        }

    @staticmethod
    def print_summary(results: Dict[str, Any]):
        p = results["params"]
        print("\n" + "=" * 94)
        print("LIQUIDITY-PULSE - CONDITIONAL LEVEL STUDY")
        print("=" * 94)
        print(f"{results['symbol']} {results['interval']}  |  {p['anchor']}-anchored, "
              f"target {p['target_pct']*100:.2f}% / break {p['break_margin_pct']*100:.2f}% "
              f"within {p['resolve_bars']} bars  |  {p['control_seeds']} control seeds")
        print("-" * 94)
        print(f"{'condition':<32}{'resolved':>10}{'real%':>9}{'random%':>10}"
              f"{'sd':>7}{'edge':>8}{'sd':>7}")
        print("-" * 94)
        for row in results["results"]:
            flag = "  (low n)" if row["underpowered"] else ""
            sd = row["edge_sd"]
            print(f"{row['condition']:<32}{row['resolved']:>10}{row['hold_rate_pct']:>8.2f}%"
                  f"{row['control_mean_pct']:>9.2f}%{row['control_sd']:>7.2f}"
                  f"{row['edge_points']:>+8.2f}"
                  f"{(f'{sd:>7.1f}' if sd is not None else '      -')}{flag}")
        print("-" * 94)

        n = results["conditions_tested"]
        hits = [r for r in results["results"]
                if r["edge_sd"] is not None and r["edge_points"] > 0
                and r["edge_sd"] >= 2.0 and not r["underpowered"]]
        expected = n * 0.046  # two-tailed 2 sd, per comparison
        print(f"conditions tested: {n}   positive hits past 2 sd: {len(hits)}"
              f"   expected by chance: {expected:.1f}")
        if hits:
            print("  " + ", ".join(r["condition"] for r in hits))
            print("  Treat as a lead, not a result. Re-test on held-out data before believing it.")
        else:
            print("  No condition separates from its control.")
        print("=" * 94 + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test S/R levels under market-context conditions")
    parser.add_argument("--candles", type=int, default=20000)
    parser.add_argument("--interval", type=str, default="15m")
    parser.add_argument("--lookback", type=int, default=500)
    parser.add_argument("--horizon", type=int, default=50)
    parser.add_argument("--target", type=float, default=0.005)
    parser.add_argument("--break-margin", type=float, default=0.0035)
    parser.add_argument("--resolve-bars", type=int, default=32)
    parser.add_argument("--anchor", choices=["entry", "level"], default="entry")
    parser.add_argument("--seeds", type=int, default=30)
    args = parser.parse_args()

    study = ConditionalStudy(interval=args.interval, total_candles=args.candles)
    res = study.run(
        lookback=args.lookback, horizon=args.horizon, target=args.target,
        break_margin=args.break_margin, resolve_bars=args.resolve_bars,
        anchor=args.anchor, seeds=args.seeds
    )
    study.print_summary(res)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.abspath(os.path.join(script_dir, "..", "workspace"))
    report_file = os.path.join(workspace_dir, "conditional_study.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(f"Conditional study JSON saved to {report_file}")
