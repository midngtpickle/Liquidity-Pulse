"""
Liquidity-Pulse - Liquidity Pool Mapping

Every level this project derives today answers the same question: *where has price
turned before?* Pivot clusters, VPOC, HVN, fibs, session opens -- all of them are
history of reaction. That is support and resistance, and derivation_study.py has
tested fourteen versions of it against a displaced control without finding an edge
in any.

This module asks a different question: *where are the orders that have not been
filled yet?* A pool is a price a lot of resting stop and liquidation orders sit at,
which is not the same thing as a price that has held. The two often disagree in a
way that matters: a swing high price has rejected three times is strong resistance
by the S/R definition and, by this one, a magnet -- because every one of those
rejections left short stops parked above it.

Three derivations, in rough order of how much order flow they imply:

**Untested extremes.** A swing high or low price has never returned to. Every stop
placed beyond it when it formed is still sitting there. Once price trades through,
the pool is consumed and the level is dropped -- which is the whole point, and the
opposite of an S/R level, which is held to be *stronger* for having been tested.

**Equal highs / lows.** Two or more swings at nearly the same price. Stops stack at
a shared price far more densely than at any single swing, and the pattern is
visible enough that it is widely traded as a target in its own right.

**Session extremes.** The high and low of the previous Asia, London and New York
sessions, while still untested. Session boundaries concentrate resting orders for
reasons that have nothing to do with market structure -- desks flatten, stops move
to session levels -- so these are pools even where no pivot formed.

> [!IMPORTANT]
> None of this is claimed to work. It is a *different hypothesis*, wired into the
> same benchmark as everything else, so it gets the same displaced-control test the
> S/R derivations got. Read the numbers in workspace/derivation_study.json before
> trading any of it, and read section 5 of docs/STRATEGY.md on why a hold rate
> without a control is not evidence.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("LiquidityPools")

Klines = List[Dict[str, Any]]


class Pool:
    """A price with resting orders behind it, and how the pool was identified."""

    __slots__ = ("price", "kind", "side", "formed_index", "strength", "tested")

    def __init__(
        self,
        price: float,
        kind: str,
        side: str,
        formed_index: int,
        strength: int = 1,
        tested: bool = False
    ):
        self.price = float(price)
        self.kind = kind              # UNTESTED_SWING, EQUAL_HIGHS, EQUAL_LOWS, SESSION
        self.side = side              # ABOVE (sell-side stops) or BELOW (buy-side stops)
        self.formed_index = formed_index
        self.strength = strength      # how many swings stack at this price
        self.tested = tested

    def __repr__(self) -> str:
        return (f"Pool({self.price:,.2f} {self.kind} {self.side} "
                f"x{self.strength}{' TESTED' if self.tested else ''})")


def swing_points(
    klines: Klines, left: int = 10, right: int = 10
) -> Tuple[List[Tuple[int, float]], List[Tuple[int, float]]]:
    """
    Swing highs and lows with their bar index, using the same comparison
    calculate_pine_pivots() uses so pools and S/R levels are derived from the same
    notion of a swing.
    """
    highs = [k["high"] for k in klines]
    lows = [k["low"] for k in klines]
    n = len(klines)
    sh: List[Tuple[int, float]] = []
    sl: List[Tuple[int, float]] = []

    for i in range(left, n - right):
        h = highs[i]
        if all(h > highs[i - k] for k in range(1, left + 1)) and \
           all(h >= highs[i + k] for k in range(1, right + 1)):
            sh.append((i, h))
        lo = lows[i]
        if all(lo < lows[i - k] for k in range(1, left + 1)) and \
           all(lo <= lows[i + k] for k in range(1, right + 1)):
            sl.append((i, lo))

    return sh, sl


def _was_tested(klines: Klines, index: int, price: float, above: bool) -> bool:
    """
    Has price traded beyond this level since the bar it formed on?

    Strictly beyond, not merely to it. A wick that reaches the exact price does not
    clear the stops resting past it, and treating a touch as consumption would
    discard the pools most likely to still be live.
    """
    for k in klines[index + 1:]:
        if above and k["high"] > price:
            return True
        if not above and k["low"] < price:
            return True
    return False


def untested_extremes(
    klines: Klines, left: int = 10, right: int = 10, max_age_bars: Optional[int] = None
) -> List[Pool]:
    """
    Swing highs never exceeded and swing lows never undercut since forming.

    `max_age_bars` drops pools older than a given age. Left as None by default
    because an old untested pool is not a weaker pool -- if anything the orders
    behind it have had longer to accumulate -- but a very old one may sit so far
    from price that it is untradeable, and a caller working a single session may
    want the cut.
    """
    sh, sl = swing_points(klines, left, right)
    n = len(klines)
    pools: List[Pool] = []

    for idx, price in sh:
        if max_age_bars is not None and (n - idx) > max_age_bars:
            continue
        if not _was_tested(klines, idx, price, above=True):
            pools.append(Pool(price, "UNTESTED_SWING", "ABOVE", idx))

    for idx, price in sl:
        if max_age_bars is not None and (n - idx) > max_age_bars:
            continue
        if not _was_tested(klines, idx, price, above=False):
            pools.append(Pool(price, "UNTESTED_SWING", "BELOW", idx))

    return pools


def equal_levels(
    klines: Klines,
    left: int = 10,
    right: int = 10,
    tolerance_pct: float = 0.0008,
    min_count: int = 2,
    untested_only: bool = True
) -> List[Pool]:
    """
    Swings clustered at nearly the same price -- the classic stop shelf.

    The tolerance is deliberately an order of magnitude tighter than the 0.35% S/R
    cluster threshold. "Equal" has to mean equal: at 0.35% on BTC any two swings
    within $280 would qualify, which describes most of a range rather than a shelf.
    At 0.08% it is roughly $65, which is the scale traders actually mean when they
    call two highs equal.

    Merging is by running mean in time order, matching cluster_sr_levels(), so a
    shelf's price is derived the same way an S/R cluster's is.
    """
    sh, sl = swing_points(klines, left, right)
    pools: List[Pool] = []

    for points, side, kind in ((sh, "ABOVE", "EQUAL_HIGHS"), (sl, "BELOW", "EQUAL_LOWS")):
        centres: List[float] = []
        members: List[int] = []
        last_index: List[int] = []

        for idx, price in points:
            hit = -1
            for i, c in enumerate(centres):
                if abs(price - c) / c <= tolerance_pct:
                    hit = i
                    break
            if hit >= 0:
                m = members[hit]
                centres[hit] = (centres[hit] * m + price) / (m + 1)
                members[hit] = m + 1
                last_index[hit] = idx
            else:
                centres.append(price)
                members.append(1)
                last_index.append(idx)

        for c, m, idx in zip(centres, members, last_index):
            if m < min_count:
                continue
            tested = _was_tested(klines, idx, c, above=(side == "ABOVE"))
            if untested_only and tested:
                continue
            pools.append(Pool(c, kind, side, idx, strength=m, tested=tested))

    return pools


SESSION_BOUNDS = (
    ("ASIA", 0, 7),
    ("LONDON", 7, 13),
    ("NY", 13, 21),
)


def _session_of(open_time_ms: float) -> Optional[str]:
    hour = datetime.fromtimestamp(open_time_ms / 1000.0, tz=timezone.utc).hour
    for name, start, end in SESSION_BOUNDS:
        if start <= hour < end:
            return name
    return None


def session_extremes(klines: Klines, sessions_back: int = 3) -> List[Pool]:
    """
    High and low of each of the last `sessions_back` completed sessions, kept only
    while still untested.

    Distinct from the existing "session opens" derivation, which marks where a
    session *started*. An open is a reference price; a session high or low is where
    that session's losers have their stops.
    """
    if not klines:
        return []

    # Group consecutive candles into session runs, so a run is one session on one day
    # rather than every Asia bar in the window collapsed together.
    runs: List[Tuple[str, int, int]] = []
    current: Optional[str] = None
    start = 0
    for i, k in enumerate(klines):
        name = _session_of(k["open_time"])
        if name != current:
            if current is not None:
                runs.append((current, start, i - 1))
            current = name
            start = i
    if current is not None:
        runs.append((current, start, len(klines) - 1))

    # The final run may still be in progress; its extremes are not settled yet.
    completed = [r for r in runs if r[0] is not None][:-1] if runs else []
    pools: List[Pool] = []

    for name, lo_i, hi_i in completed[-sessions_back:]:
        chunk = klines[lo_i:hi_i + 1]
        if not chunk:
            continue
        high = max(k["high"] for k in chunk)
        low = min(k["low"] for k in chunk)
        if not _was_tested(klines, hi_i, high, above=True):
            pools.append(Pool(high, "SESSION", "ABOVE", hi_i))
        if not _was_tested(klines, hi_i, low, above=False):
            pools.append(Pool(low, "SESSION", "BELOW", hi_i))

    return pools


def all_pools(
    klines: Klines,
    left: int = 10,
    right: int = 10,
    include_sessions: bool = True
) -> List[Pool]:
    """Every pool type, deduplicated by price, strongest first.

    Where two derivations land on the same price the stronger claim wins, because a
    shelf of three equal highs that is also an untested extreme is one pool, not
    two, and reporting it twice would double its weight in any downstream ranking.
    """
    pools = untested_extremes(klines, left, right) + equal_levels(klines, left, right)
    if include_sessions:
        pools += session_extremes(klines)

    pools.sort(key=lambda p: (-p.strength, p.price))
    kept: List[Pool] = []
    for p in pools:
        if any(abs(p.price - q.price) / q.price <= 0.0008 for q in kept):
            continue
        kept.append(p)
    return kept
