"""
Liquidity-Pulse - Level Derivation Study

Compares different ways of deriving S/R levels against the same evaluation and the same
random-level control, so the derivation is the only thing that varies.

The question each row answers: does price reverse at levels produced this way more often
than it reverses at arbitrary prices drawn from the same band? A derivation that cannot
beat its own control carries no information the evaluation can detect, however
sophisticated its construction.

Defaults to the entry-anchored rule. Level anchoring is biased toward HOLD and mostly
reports that bias; entry anchoring has a calculable random-walk baseline, so the numbers
mean something on their own as well as relative to the control.
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
logger = logging.getLogger("DerivationStudy")

Klines = List[Dict[str, float]]
Derivation = Callable[[QuantEngine, Klines, float, float], List[SRLevel]]


def _level(price: float, ref_price: float) -> SRLevel:
    """Wraps a bare price as an SRLevel. Type is nominal; evaluate_fold decides direction
    from the side price approaches from, not from this field."""
    return SRLevel(
        price=float(price),
        type="SUPPORT" if price < ref_price else "RESISTANCE",
        touch_count=3,
        conviction="HIGH",
        distance_pct=0.0,
        volume_confluence=True
    )


def _pivot_levels(
    engine: QuantEngine, klines: Klines, ref_price: float, tol: float,
    left: int = 10, right: int = 10, min_touches: int = 2
) -> List[SRLevel]:
    pivots = engine.calculate_pine_pivots(klines, left_bars=left, right_bars=right)
    levels = engine.cluster_sr_levels(pivots, klines, ref_price, threshold_pct=tol)
    engine.apply_volume_confluence(levels, engine.calculate_volume_profile(klines), ref_price)
    return [l for l in levels if l.touch_count >= min_touches]


def pivot_clusters(engine, klines, ref_price, tol):
    """The production derivation."""
    return _pivot_levels(engine, klines, ref_price, tol)


def pivot_clusters_strong(engine, klines, ref_price, tol):
    """Same, but only levels price has revisited many times."""
    return _pivot_levels(engine, klines, ref_price, tol, min_touches=5)


def htf_pivots(engine, klines, ref_price, tol):
    """Wider swing definition, so only larger structural turns qualify."""
    return _pivot_levels(engine, klines, ref_price, tol, left=30, right=30)


def recent_pivots(engine, klines, ref_price, tol):
    """Only the trailing 150 candles, on the theory that old levels go stale."""
    recent = klines[-150:]
    return _pivot_levels(engine, recent, ref_price, tol)


def volume_nodes(engine, klines, ref_price, tol):
    """VPOC and High Volume Nodes: prices the market spent the most volume accepting."""
    profile = engine.calculate_volume_profile(klines)
    return [_level(p, ref_price) for p in [profile.vpoc] + list(profile.hvn_zones)]


def lvn_nodes(engine, klines, ref_price, tol):
    """Low Volume Nodes: the thin pockets price is supposed to traverse quickly."""
    profile = engine.calculate_volume_profile(klines)
    return [_level(p, ref_price) for p in profile.lvn_zones]


def prior_day_extremes(engine, klines, ref_price, tol):
    """High and low of the trailing 96 candles (24h at 15m)."""
    day = klines[-96:]
    return [
        _level(max(k["high"] for k in day), ref_price),
        _level(min(k["low"] for k in day), ref_price)
    ]


def round_numbers(engine, klines, ref_price, tol, step: float = 1000.0):
    """Psychological round numbers inside the last day's range."""
    day = klines[-96:]
    low = min(k["low"] for k in day)
    high = max(k["high"] for k in day)
    first = int(low // step) * step
    prices = [first + i * step for i in range(int((high - first) // step) + 2)]
    return [_level(p, ref_price) for p in prices if low <= p <= high]


def untested_pivots(engine, klines, ref_price, tol):
    """
    Pivots price has NOT returned to. Inverts the production filter, testing the common
    claim that a fresh level is stronger than one already worked over.
    """
    return [l for l in _pivot_levels(engine, klines, ref_price, tol, min_touches=0)
            if l.touch_count <= 1]


def session_opens(engine, klines, ref_price, tol):
    """Asia (00:00), London (07:00) and New York (13:30) UTC opens, most recent three."""
    targets = {(0, 0), (7, 0), (13, 30)}
    found = []
    for k in reversed(klines):
        stamp = datetime.fromtimestamp(k["open_time"] / 1000.0, tz=timezone.utc)
        if (stamp.hour, stamp.minute) in targets:
            found.append(_level(k["open"], ref_price))
            if len(found) >= 3:
                break
    return found


def prior_week_extremes(engine, klines, ref_price, tol):
    """High and low of the trailing 672 candles (7 days at 15m)."""
    week = klines[-672:]
    return [
        _level(max(k["high"] for k in week), ref_price),
        _level(min(k["low"] for k in week), ref_price)
    ]


def fib_retracements(engine, klines, ref_price, tol):
    """38.2 / 50 / 61.8 retracements of the trailing 200-candle swing."""
    swing = klines[-200:]
    high = max(k["high"] for k in swing)
    low = min(k["low"] for k in swing)
    span = high - low
    return [_level(high - span * r, ref_price) for r in (0.382, 0.5, 0.618)]


def anchored_vwap(engine, klines, ref_price, tol):
    """Volume-weighted average price across the whole lookback window."""
    numerator = sum(((k["high"] + k["low"] + k["close"]) / 3.0) * k["volume"] for k in klines)
    denominator = sum(k["volume"] for k in klines)
    return [_level(numerator / denominator, ref_price)] if denominator else []


def moving_averages(engine, klines, ref_price, tol):
    """
    50 and 200 period EMAs.

    Approximate: an EMA is a dynamic level that moves each candle, but the harness holds
    levels fixed for the fold, so these are frozen at the value they had when the fold
    opened. Over a 50-candle test window a 50-EMA drifts, so treat this row as
    indicative rather than a faithful test of moving-average support.
    """
    closes = [k["close"] for k in klines]
    out = []
    for period in (50, 200):
        if len(closes) < period:
            continue
        multiplier = 2.0 / (period + 1)
        ema = sum(closes[:period]) / period
        for close in closes[period:]:
            ema = close * multiplier + ema * (1 - multiplier)
        out.append(_level(ema, ref_price))
    return out


DERIVATIONS: List[Tuple[str, Derivation]] = [
    ("pivot clusters (production)", pivot_clusters),
    ("pivot clusters, 5+ touches", pivot_clusters_strong),
    ("HTF pivots (30/30)", htf_pivots),
    ("recent pivots (150 bars)", recent_pivots),
    ("VPOC + HVN nodes", volume_nodes),
    ("LVN nodes", lvn_nodes),
    ("prior-day high/low", prior_day_extremes),
    ("round numbers", round_numbers),
    ("untested pivots (1 touch)", untested_pivots),
    ("session opens", session_opens),
    ("prior-week high/low", prior_week_extremes),
    ("fib retracements", fib_retracements),
    ("anchored VWAP", anchored_vwap),
    ("50/200 EMA (static)", moving_averages),
]


THRESHOLDS = [0.001, 0.0025, 0.005, 0.01, 0.02]


class DerivationStudy:
    def __init__(self, symbol: str = "BTCUSDT", interval: str = "15m", total_candles: int = 20000):
        self.backtester = SRBacktester(symbol=symbol, interval=interval, total_candles=total_candles)
        self.engine = self.backtester.engine

    def _tally(self, fold_levels, tol, target, break_margin, bars, anchor) -> Dict[str, int]:
        counts = {"HOLD": 0, "BREAK": 0, "UNRESOLVED": 0}
        for test_klines, levels in fold_levels:
            for record in self.backtester.evaluate_fold(
                levels, test_klines, tol, target, break_margin, bars, anchor
            ):
                counts[record["outcome"]] += 1
        return counts

    @staticmethod
    def _rate(counts: Dict[str, int]) -> float:
        resolved = counts["HOLD"] + counts["BREAK"]
        return counts["HOLD"] / resolved * 100.0 if resolved else 0.0

    def threshold_curve(
        self,
        fold_levels: List[Tuple[Klines, List[SRLevel]]],
        tol: float,
        thresholds: List[float],
        resolve_bars: int,
        anchor: str
    ) -> Dict[float, Dict[str, int]]:
        """
        Hit rates across a range of symmetric thresholds from a single scan.

        Symmetric barriers mean a random walk sits near 50% at every threshold, so each
        row is readable on its own as well as against the control.
        """
        counts = {x: {"HOLD": 0, "BREAK": 0, "UNRESOLVED": 0} for x in thresholds}
        for test_klines, levels in fold_levels:
            for i, level, direction in self.backtester.find_tests(levels, test_klines, tol):
                anchor_price = level.price if anchor == "level" else test_klines[i]["close"]
                outcomes = self.backtester.resolve_thresholds(
                    anchor_price, direction, test_klines, i, thresholds, resolve_bars
                )
                for x, outcome in outcomes.items():
                    counts[x][outcome] += 1
        return counts

    def run(
        self,
        lookback: int = 500,
        horizon: int = 50,
        tol: float = 0.0035,
        target: float = 0.005,
        break_margin: float = 0.0035,
        resolve_bars: int = 32,
        anchor: str = "entry",
        seeds: int = 5
    ) -> Dict[str, Any]:
        klines = self.backtester.history()
        starts = list(range(lookback, len(klines) - horizon + 1, horizon))
        logger.info(f"{len(klines)} candles, {len(starts)} folds, anchor={anchor}.")

        results: Dict[str, Any] = {
            "symbol": self.backtester.symbol,
            "interval": self.backtester.interval,
            "run_time_utc": datetime.now(timezone.utc).isoformat(),
            "params": {
                "total_candles": len(klines), "folds": len(starts), "lookback": lookback,
                "horizon": horizon, "zone_tolerance_pct": tol, "target_pct": target,
                "break_margin_pct": break_margin, "resolve_bars": resolve_bars,
                "anchor": anchor, "control_seeds": seeds
            },
            "derivations": []
        }

        for name, derive in DERIVATIONS:
            fold_levels = []
            level_counts = []
            for start in starts:
                train = klines[start - lookback:start]
                test = klines[start:start + horizon]
                levels = derive(self.engine, train, train[-1]["close"], tol)
                fold_levels.append((test, levels))
                level_counts.append(len(levels))

            real = self._tally(fold_levels, tol, target, break_margin, resolve_bars, anchor)
            real_rate = self._rate(real)

            control_rates = []
            for seed in range(seeds):
                rng = random.Random(seed)
                control = [
                    (test, self.backtester.control_levels(levels, rng, tol))
                    for test, levels in fold_levels
                ]
                control_rates.append(
                    self._rate(self._tally(control, tol, target, break_margin, resolve_bars, anchor))
                )

            real_curve = self.threshold_curve(fold_levels, tol, THRESHOLDS, resolve_bars, anchor)
            control_curves = []
            for seed in range(seeds):
                rng = random.Random(seed)
                control = [
                    (test, self.backtester.control_levels(levels, rng, tol))
                    for test, levels in fold_levels
                ]
                control_curves.append(
                    self.threshold_curve(control, tol, THRESHOLDS, resolve_bars, anchor)
                )

            curve_rows = []
            for x in THRESHOLDS:
                real_x = self._rate(real_curve[x])
                ctrl_x = [self._rate(c[x]) for c in control_curves]
                cm = statistics.mean(ctrl_x) if ctrl_x else 0.0
                csd = statistics.pstdev(ctrl_x) if ctrl_x else 0.0
                curve_rows.append({
                    "threshold_pct": round(x * 100, 3),
                    "resolved": real_curve[x]["HOLD"] + real_curve[x]["BREAK"],
                    "unresolved": real_curve[x]["UNRESOLVED"],
                    "hold_rate_pct": round(real_x, 2),
                    "control_mean_pct": round(cm, 2),
                    "control_sd": round(csd, 2),
                    "edge_points": round(real_x - cm, 2),
                    "edge_sd": round(abs(real_x - cm) / csd, 2) if csd > 0 else None
                })

            mean_rate = statistics.mean(control_rates) if control_rates else 0.0
            sd_rate = statistics.pstdev(control_rates) if control_rates else 0.0
            edge = real_rate - mean_rate

            results["derivations"].append({
                "name": name,
                "avg_levels_per_fold": round(statistics.mean(level_counts), 2),
                "tests": sum(real.values()),
                "resolved": real["HOLD"] + real["BREAK"],
                "outcomes": real,
                "hold_rate_pct": round(real_rate, 2),
                "control_hold_rate_pct_mean": round(mean_rate, 2),
                "control_hold_rate_pct_sd": round(sd_rate, 2),
                "edge_points": round(edge, 2),
                "edge_sd": round(abs(edge) / sd_rate, 2) if sd_rate > 0 else None,
                "threshold_curve": curve_rows
            })
            logger.info(f"  {name}: {real_rate:.2f}% vs control {mean_rate:.2f}%")

        return results

    @staticmethod
    def print_summary(results: Dict[str, Any]):
        p = results["params"]
        print("\n" + "=" * 96)
        print("LIQUIDITY-PULSE - LEVEL DERIVATION STUDY")
        print("=" * 96)
        print(f"{results['symbol']} {results['interval']}  |  {p['total_candles']} candles, "
              f"{p['folds']} folds  |  {p['anchor']}-anchored, "
              f"target {p['target_pct']*100:.2f}% / break {p['break_margin_pct']*100:.2f}% "
              f"within {p['resolve_bars']} bars")
        print("-" * 96)
        print(f"{'derivation':<30}{'lvls':>6}{'tests':>8}{'resolved':>10}"
              f"{'real%':>9}{'random%':>10}{'sd':>7}{'edge':>8}{'sd':>6}")
        print("-" * 96)
        for d in results["derivations"]:
            edge_sd = d["edge_sd"]
            print(f"{d['name']:<30}{d['avg_levels_per_fold']:>6.1f}{d['tests']:>8}"
                  f"{d['resolved']:>10}{d['hold_rate_pct']:>8.2f}%"
                  f"{d['control_hold_rate_pct_mean']:>9.2f}%{d['control_hold_rate_pct_sd']:>7.2f}"
                  f"{d['edge_points']:>+8.2f}"
                  f"{(f'{edge_sd:>6.1f}' if edge_sd is not None else '     -')}")
        print("-" * 96)
        print()
        print("RAW HIT RATE BY THRESHOLD (symmetric barriers, random walk ~50% at every row)")
        print("Read: after a fresh touch, how often price moved +X before -X.")
        header = "  " + f"{'threshold':<12}" + "".join(
            f"{d['name'][:16]:>18}" for d in results["derivations"][:4])
        print(header)
        for idx, row in enumerate(results["derivations"][0]["threshold_curve"]):
            line = "  " + f"{row['threshold_pct']:>6.2f}%      "
            for d in results["derivations"][:4]:
                r = d["threshold_curve"][idx]
                line += f"{r['hold_rate_pct']:>7.1f}/{r['control_mean_pct']:<6.1f}   "
            print(line)
        print("  (real / random control, %)")
        print()
        beat = [d for d in results["derivations"]
                if d["edge_sd"] is not None and d["edge_points"] > 0 and d["edge_sd"] >= 2.0]
        print(f"derivations beating their control by 2+ sd: {len(beat)}"
              + (f"  ({', '.join(d['name'] for d in beat)})" if beat else ""))
        print("=" * 96 + "\n")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Compare S/R level derivations against a random control")
    parser.add_argument("--candles", type=int, default=20000)
    parser.add_argument("--lookback", type=int, default=500)
    parser.add_argument("--horizon", type=int, default=50)
    parser.add_argument("--target", type=float, default=0.005)
    parser.add_argument("--break-margin", type=float, default=0.0035)
    parser.add_argument("--resolve-bars", type=int, default=32)
    parser.add_argument("--anchor", choices=["entry", "level"], default="entry")
    parser.add_argument("--seeds", type=int, default=5)
    args = parser.parse_args()

    study = DerivationStudy(total_candles=args.candles)
    res = study.run(
        lookback=args.lookback, horizon=args.horizon, target=args.target,
        break_margin=args.break_margin, resolve_bars=args.resolve_bars,
        anchor=args.anchor, seeds=args.seeds
    )
    study.print_summary(res)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.abspath(os.path.join(script_dir, "..", "workspace"))
    report_file = os.path.join(workspace_dir, "derivation_study.json")
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)
    print(f"Derivation study JSON saved to {report_file}")
