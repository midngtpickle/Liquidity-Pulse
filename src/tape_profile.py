"""
Liquidity-Pulse - Volume-at-Price and Order Flow

Two things quant_engine.py cannot currently say, both derived from candles it
already fetches.

**Volume at price.** calculate_volume_profile() puts each candle's entire volume in
one bin at its mid price. On a 15m BTC candle whose range is routinely $200-400
that is a coarse approximation: the resulting VPOC is the modal candle *midpoint*
weighted by volume, not the price the most volume actually traded at, and the
histogram's range excludes the wicks entirely -- the bins span min(mid) to
max(mid), so the extremes of the real traded range fall outside the profile. This
module spreads each candle's volume across its own high-low range instead, which
is the standard approximation when trade-level data is not on hand, and bins over
the true range.

It does not claim to be a tick-accurate profile. Reconstructing one means paging
`/fapi/v1/aggTrades` a thousand rows at a time -- roughly twelve million trades
for the 500-candle window -- which is not viable on every refresh. Feeding this
1m candles instead of 15m gets most of the way there for eight paginated
requests, which is what `load_klines(interval="1m")` is for.

**Order flow.** Binance ships taker-buy base volume in field 9 of every kline, so
the signed taker delta of each bar is free and fully historical:

    delta = taker_buy_base - (volume - taker_buy_base)

Cumulative delta (CVD) is its running sum. This is *taker* flow -- who crossed the
spread -- which is the half of order flow that candles hide and the half that
matters at a level: price holding a support while CVD falls means passive bids are
absorbing sellers, and that is a different event from price holding because nobody
sold. Nothing here says it predicts anything; see docs/STRATEGY.md on why that
question is settled by derivation_study.py and conditional_study.py, not by
whether a feature sounds plausible.
"""

import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field

logger = logging.getLogger("TapeProfile")

Klines = List[Dict[str, Any]]


class PriceLevelBin(BaseModel):
    price: float = Field(..., description="Bin centre price")
    volume: float = Field(..., description="Volume attributed to this price bin")
    tag: str = Field(..., description="VPOC, VALUE_AREA, HVN, LVN, or NORMAL")


class TapeProfile(BaseModel):
    vpoc: float = Field(..., description="Price bin holding the most volume")
    value_area_high: float = Field(..., description="Upper bound of the 70% value area")
    value_area_low: float = Field(..., description="Lower bound of the 70% value area")
    hvn_zones: List[float] = Field(default_factory=list)
    lvn_zones: List[float] = Field(default_factory=list)
    bins: List[PriceLevelBin] = Field(default_factory=list)
    bin_width: float = Field(0.0, description="Price span of one bin")
    source_bars: int = Field(0, description="Candles the profile was built from")


def build_profile(
    klines: Klines,
    num_bins: int = 120,
    value_area_pct: float = 0.70,
    hvn_percentile: float = 80.0,
    lvn_percentile: float = 20.0
) -> TapeProfile:
    """
    Volume-at-price over the true traded range, spreading each candle's volume
    uniformly across the bins its high-low range covers.

    Uniform-within-range is an assumption, and a candle spends more time near its
    close than its extremes in reality. It is still much closer than assigning
    everything to the midpoint, and it has the property that matters here: the
    profile covers the whole range price actually traded, so a level sitting in a
    wick is inside the profile rather than off the end of it.

    More bins than the 50 quant_engine uses, because the point is resolution: at
    120 bins over a typical 500-candle 15m window a bin is roughly $50 wide rather
    than $130, which is narrower than the zone tolerance levels are matched with.
    """
    if not klines:
        raise ValueError("build_profile requires at least one candle")

    lows = np.array([k["low"] for k in klines], dtype=np.float64)
    highs = np.array([k["high"] for k in klines], dtype=np.float64)
    vols = np.array([k["volume"] for k in klines], dtype=np.float64)

    lo = float(lows.min())
    hi = float(highs.max())
    if hi <= lo:
        raise ValueError("build_profile requires a non-zero price range")

    width = (hi - lo) / num_bins
    hist = np.zeros(num_bins, dtype=np.float64)

    # Spread each candle across the bins it spans. A candle narrower than one bin
    # lands entirely in that bin, which is the mid-price behaviour as a special
    # case rather than as the rule.
    for low, high, vol in zip(lows, highs, vols):
        if vol <= 0.0:
            continue
        first = int((low - lo) / width)
        last = int((high - lo) / width)
        first = max(0, min(num_bins - 1, first))
        last = max(0, min(num_bins - 1, last))
        if last == first:
            hist[first] += vol
            continue
        # Weight by how much of the candle's range falls in each bin, so a candle
        # that barely clips a bin does not donate a full share to it.
        span = high - low
        for idx in range(first, last + 1):
            bin_lo = lo + idx * width
            bin_hi = bin_lo + width
            overlap = min(high, bin_hi) - max(low, bin_lo)
            if overlap > 0.0:
                hist[idx] += vol * (overlap / span)

    centres = np.array([lo + (i + 0.5) * width for i in range(num_bins)])
    poc_idx = int(np.argmax(hist))
    vpoc = float(centres[poc_idx])

    va_low_idx, va_high_idx = _value_area(hist, poc_idx, value_area_pct)

    nonzero = hist[hist > 0]
    p_hi = float(np.percentile(nonzero, hvn_percentile)) if nonzero.size else 0.0
    p_lo = float(np.percentile(nonzero, lvn_percentile)) if nonzero.size else 0.0

    bins: List[PriceLevelBin] = []
    hvn: List[float] = []
    lvn: List[float] = []
    for i in range(num_bins):
        price = round(float(centres[i]), 2)
        vol = float(hist[i])
        if i == poc_idx:
            tag = "VPOC"
        elif vol >= p_hi and vol > 0:
            tag = "HVN"
            hvn.append(price)
        elif 0.0 < vol <= p_lo:
            tag = "LVN"
            lvn.append(price)
        elif va_low_idx <= i <= va_high_idx:
            tag = "VALUE_AREA"
        else:
            tag = "NORMAL"
        bins.append(PriceLevelBin(price=price, volume=round(vol, 4), tag=tag))

    return TapeProfile(
        vpoc=round(vpoc, 2),
        value_area_high=round(float(centres[va_high_idx]), 2),
        value_area_low=round(float(centres[va_low_idx]), 2),
        hvn_zones=hvn,
        lvn_zones=lvn,
        bins=bins,
        bin_width=round(width, 4),
        source_bars=len(klines)
    )


def _value_area(hist: np.ndarray, poc_idx: int, target_pct: float) -> Tuple[int, int]:
    """
    Standard value-area walk: start at the point of control and repeatedly take
    whichever neighbouring bin holds more volume, until the accumulated share
    reaches the target.
    """
    total = float(hist.sum())
    if total <= 0.0:
        return poc_idx, poc_idx

    lo_idx = hi_idx = poc_idx
    acc = float(hist[poc_idx])
    target = total * target_pct
    n = len(hist)

    while acc < target and (lo_idx > 0 or hi_idx < n - 1):
        below = float(hist[lo_idx - 1]) if lo_idx > 0 else -1.0
        above = float(hist[hi_idx + 1]) if hi_idx < n - 1 else -1.0
        if above >= below:
            hi_idx += 1
            acc += above
        else:
            lo_idx -= 1
            acc += below

    return lo_idx, hi_idx


# --------------------------------------------------------------------- order flow

def bar_delta(kline: Dict[str, Any]) -> Optional[float]:
    """
    Signed taker volume for one bar, or None when the venue did not supply it.

    Returns base-asset units, matching `volume`, so a delta can be read against the
    bar's own size without a unit conversion.
    """
    taker_buy = kline.get("taker_buy_base")
    if taker_buy is None:
        return None
    return float(taker_buy) - (float(kline["volume"]) - float(taker_buy))


def deltas(klines: Klines) -> Optional[List[float]]:
    """Per-bar taker delta, or None if any bar is missing the field. All-or-nothing
    because a series with holes silently flattens CVD wherever the data ran out."""
    out: List[float] = []
    for k in klines:
        d = bar_delta(k)
        if d is None:
            return None
        out.append(d)
    return out


def cvd(klines: Klines) -> Optional[List[float]]:
    """Cumulative volume delta, one running total per bar."""
    series = deltas(klines)
    if series is None:
        return None
    total = 0.0
    out: List[float] = []
    for d in series:
        total += d
        out.append(total)
    return out


def delta_ratio(kline: Dict[str, Any]) -> Optional[float]:
    """
    Bar delta as a share of bar volume, in [-1, 1]. Normalising by volume is what
    makes a quiet bar's lopsidedness comparable to a busy bar's.
    """
    d = bar_delta(kline)
    if d is None:
        return None
    vol = float(kline["volume"])
    return d / vol if vol > 0 else 0.0


def cvd_divergence(
    klines: Klines, index: int, lookback: int = 12
) -> Optional[float]:
    """
    Signed disagreement between price and cumulative delta over `lookback` bars.

    Positive means CVD rose more than price did (buying that is not being rewarded
    with higher prices -- absorption by passive sellers); negative means the
    reverse. Both legs are scaled by their own recent magnitude so the two are
    comparable, and the result is a z-like ratio rather than a currency amount.

    Returns None if the venue supplied no taker data, or if there is not enough
    history behind `index` to measure over.
    """
    start = index - lookback
    if start < 0 or index >= len(klines):
        return None

    window = klines[start:index + 1]
    series = cvd(window)
    if series is None:
        return None

    price_move = window[-1]["close"] - window[0]["close"]
    cvd_move = series[-1] - series[0]

    ranges = [k["high"] - k["low"] for k in window]
    price_scale = sum(ranges) / len(ranges) if ranges else 0.0
    vols = [k["volume"] for k in window]
    cvd_scale = sum(vols) / len(vols) if vols else 0.0

    if price_scale <= 0 or cvd_scale <= 0:
        return None

    return (cvd_move / cvd_scale) - (price_move / price_scale)
