"""
Liquidity-Pulse - Positioning: Open Interest, Funding, Long/Short Ratios

Everything else in this project is derived from price and size. This module reads
what traders are actually *holding*: how much open interest exists, what it costs to
hold a long, and how the crowd is leaning.

The single most important thing to know before building on any of it:

> [!IMPORTANT]
> **Open interest and the long/short ratios are capped at 30 days.** Not "about a
> month" -- `/futures/data/*` refuses an `endTime` older than 30 days with
> `-1130 parameter 'endTime' is invalid`, and a request near the boundary returns a
> short page and stops. At 15m that is 2,880 points, which is roughly 46 walk-forward
> folds. The benchmark in docs/STRATEGY.md needs 390 to say anything.
>
> Funding rate is the exception: `/fapi/v1/fundingRate` pages back years, so funding
> features *can* be tested on the full 20,000-candle window.

That split runs through the whole module. Funding features go into
`conditional_study.py` and get a real verdict. OI and ratio features cannot, and the
only fix is the same one the depth signal needs: start recording now, so the history
exists later. `record_snapshot()` exists for exactly that.

Rate limits: the `/futures/data/` endpoints are weighted per IP. Thirty days at 15m
is six paginated requests, which is cheap, but a tight polling loop is not -- the
recorder defaults to one snapshot every 5 minutes.
"""

import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger("Positioning")

FAPI = "https://fapi.binance.com"
HEADERS = {"User-Agent": "LiquidityPulse/1.0"}

# The exchange's own ceiling on /futures/data/* history. Stated as a constant so the
# limit is visible at the call site rather than discovered through an error code.
FUTURES_DATA_MAX_AGE_DAYS = 30
PAGE_LIMIT = 500

Klines = List[Dict[str, Any]]


def _get(path: str, params: Dict[str, Any], timeout: float = 15.0) -> Any:
    resp = requests.get(FAPI + path, params=params, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "code" in data:
        raise RuntimeError(f"{path} returned {data}")
    return data


# ------------------------------------------------------------------ open interest

def fetch_open_interest(
    symbol: str = "BTCUSDT", period: str = "15m", days: int = 30
) -> List[Dict[str, float]]:
    """
    Open interest history, walking `endTime` backwards to cover more than one page.

    Silently returns less than asked for when the 30-day wall is hit, because that is
    the exchange's answer and not an error condition. The caller can tell from the
    span of what comes back; `coverage_days()` reports it.
    """
    days = min(days, FUTURES_DATA_MAX_AGE_DAYS)
    out: List[Dict[str, float]] = []
    end_time: Optional[int] = None
    oldest_allowed = int((time.time() - days * 86400) * 1000)

    while True:
        params: Dict[str, Any] = {"symbol": symbol, "period": period, "limit": PAGE_LIMIT}
        if end_time is not None:
            params["endTime"] = end_time
        try:
            page = _get("/futures/data/openInterestHist", params)
        except Exception as err:
            # -1130 on endTime is the 30-day wall, which is a stop condition, not a
            # failure. Anything else is worth surfacing.
            logger.warning(f"Open interest page stopped: {err}")
            break
        if not page:
            break

        rows = [{
            "timestamp": int(r["timestamp"]),
            "open_interest": float(r["sumOpenInterest"]),
            "open_interest_value": float(r["sumOpenInterestValue"])
        } for r in page]
        out = rows + out

        if rows[0]["timestamp"] <= oldest_allowed or len(page) < PAGE_LIMIT:
            break
        end_time = rows[0]["timestamp"] - 1

    # Pages are 500 points regardless of how little was asked for, so a small `days`
    # would otherwise return whatever the first page happened to span. Trim, so the
    # parameter is a window and not a floor.
    out = [r for r in sorted(out, key=lambda r: r["timestamp"])
           if r["timestamp"] >= oldest_allowed]
    logger.info(f"Open interest: {len(out)} points, {coverage_days(out):.1f} days.")
    return out


def coverage_days(rows: List[Dict[str, Any]], key: str = "timestamp") -> float:
    if len(rows) < 2:
        return 0.0
    return (rows[-1][key] - rows[0][key]) / 86400000.0


# ---------------------------------------------------------------------- funding

def fetch_funding(
    symbol: str = "BTCUSDT", start_ms: Optional[int] = None, end_ms: Optional[int] = None
) -> List[Dict[str, float]]:
    """
    Funding rate history. Pages forward from `start_ms`; unlike open interest this
    genuinely goes back years, so it is the one positioning feature the full
    benchmark can use.

    Funding settles every 8 hours, so a 20,000-candle 15m window (~7 months) contains
    roughly 625 settlements. That is a coarse partition but a real one.
    """
    out: List[Dict[str, float]] = []
    cursor = start_ms

    while True:
        params: Dict[str, Any] = {"symbol": symbol, "limit": 1000}
        if cursor is not None:
            params["startTime"] = cursor
        if end_ms is not None:
            params["endTime"] = end_ms
        page = _get("/fapi/v1/fundingRate", params)
        if not page:
            break

        rows = [{
            "timestamp": int(r["fundingTime"]),
            "funding_rate": float(r["fundingRate"]),
            "mark_price": float(r.get("markPrice") or 0.0)
        } for r in page]
        out.extend(rows)

        if len(page) < 1000:
            break
        nxt = rows[-1]["timestamp"] + 1
        if cursor is not None and nxt <= cursor:
            break
        cursor = nxt

    # Pages can overlap at the boundary; dedupe on settlement time.
    seen = set()
    deduped = []
    for r in sorted(out, key=lambda x: x["timestamp"]):
        if r["timestamp"] in seen:
            continue
        seen.add(r["timestamp"])
        deduped.append(r)

    logger.info(f"Funding: {len(deduped)} settlements, {coverage_days(deduped):.1f} days.")
    return deduped


def current_funding(symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """Mark price, the rate in force, and when it next settles."""
    d = _get("/fapi/v1/premiumIndex", {"symbol": symbol})
    rate = float(d["lastFundingRate"])
    return {
        "funding_rate": rate,
        # Three settlements a day. Annualising makes a number like 0.0001 legible as
        # the ~11%/yr carry it actually is.
        "annualised_pct": rate * 3 * 365 * 100.0,
        "mark_price": float(d["markPrice"]),
        "index_price": float(d["indexPrice"]),
        "next_funding_time": int(d["nextFundingTime"]),
        "seconds_to_funding": max(0, int(d["nextFundingTime"] / 1000 - time.time()))
    }


# ------------------------------------------------------------------ crowd ratios

RATIO_ENDPOINTS = {
    "top_positions": "/futures/data/topLongShortPositionRatio",
    "top_accounts": "/futures/data/topLongShortAccountRatio",
    "all_accounts": "/futures/data/globalLongShortAccountRatio",
}


def fetch_long_short(
    kind: str = "top_positions", symbol: str = "BTCUSDT", period: str = "15m"
) -> List[Dict[str, float]]:
    """
    One page of a long/short ratio series. Same 30-day wall as open interest.

    `top_positions` is the default because it weights by size held rather than by
    headcount: one account's opinion counts for what it is risking. `all_accounts`
    counts every retail wallet equally and is the usual "retail is long" chart.
    """
    if kind not in RATIO_ENDPOINTS:
        raise ValueError(f"unknown ratio {kind!r}; expected one of {sorted(RATIO_ENDPOINTS)}")
    page = _get(RATIO_ENDPOINTS[kind], {"symbol": symbol, "period": period, "limit": PAGE_LIMIT})
    return [{
        "timestamp": int(r["timestamp"]),
        "long_short_ratio": float(r["longShortRatio"]),
        "long_account": float(r["longAccount"]),
        "short_account": float(r["shortAccount"])
    } for r in page]


# ------------------------------------------------------------------- alignment

def align_to_klines(
    klines: Klines, series: List[Dict[str, float]], field: str
) -> List[Optional[float]]:
    """
    For each candle, the most recent value at or before that candle opened.

    Strictly at-or-before. Funding settles on a schedule and open interest is stamped
    at the close of its period, so taking the nearest value in either direction would
    hand a backtest information that did not exist yet -- the single easiest way to
    manufacture an edge in a study like this.

    Returns None for candles that predate the series, which is the normal case for OI
    given the 30-day wall, and must be filtered rather than filled.
    """
    if not series:
        return [None] * len(klines)

    ordered = sorted(series, key=lambda r: r["timestamp"])
    times = [r["timestamp"] for r in ordered]
    out: List[Optional[float]] = []
    i = 0
    for k in klines:
        t = int(k["open_time"])
        while i + 1 < len(times) and times[i + 1] <= t:
            i += 1
        out.append(ordered[i][field] if times[i] <= t else None)
    return out


# -------------------------------------------------------------------- features

def zscore(values: List[Optional[float]], index: int, lookback: int) -> Optional[float]:
    """Standard score of `values[index]` against the `lookback` readings behind it."""
    start = index - lookback
    if start < 0 or index >= len(values):
        return None
    window = [v for v in values[start:index] if v is not None]
    if len(window) < max(8, lookback // 4):
        return None
    mean = sum(window) / len(window)
    var = sum((v - mean) ** 2 for v in window) / len(window)
    sd = var ** 0.5
    current = values[index]
    if current is None or sd <= 0:
        return None
    return (current - mean) / sd


def oi_price_quadrant(
    oi_change: Optional[float], price_change: Optional[float], deadband: float = 0.0
) -> Optional[str]:
    """
    The standard four-way read of open interest against price.

    | price | OI | reading |
    | :-- | :-- | :-- |
    | up | up | NEW_LONGS -- fresh money joining the move |
    | up | down | SHORT_COVERING -- a rally on positions closing, not opening |
    | down | up | NEW_SHORTS -- fresh money selling |
    | down | down | LONG_UNWIND -- a fall on positions closing |

    The two "covering/unwind" cases are the interesting ones: the same price move with
    the opposite implication for whether it continues. Returns None inside the
    deadband, so a flat tape is not forced into a quadrant it does not belong in.
    """
    if oi_change is None or price_change is None:
        return None
    if abs(price_change) <= deadband or abs(oi_change) <= deadband:
        return None
    if price_change > 0:
        return "NEW_LONGS" if oi_change > 0 else "SHORT_COVERING"
    return "NEW_SHORTS" if oi_change > 0 else "LONG_UNWIND"


def pct_change(values: List[Optional[float]], index: int, bars: int) -> Optional[float]:
    start = index - bars
    if start < 0 or index >= len(values):
        return None
    now, then = values[index], values[start]
    if now is None or then is None or then == 0:
        return None
    return (now - then) / then


# -------------------------------------------------------------------- recording

def record_snapshot(directory: Path, symbol: str = "BTCUSDT") -> Optional[Dict[str, Any]]:
    """
    Append one positioning snapshot to `workspace/positioning_history/`, one gzipped
    JSONL file per UTC day.

    This exists because of the 30-day wall. Open interest and the crowd ratios cannot
    be fetched for last spring and never will be -- the only way to have a year of
    them is to have been writing them down for a year. Run this on a schedule (every
    5 minutes is ample for a 15m signal) and the benchmark becomes possible later.
    """
    import gzip

    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    now = time.time()
    day = datetime.fromtimestamp(now, tz=timezone.utc).strftime("%Y-%m-%d")
    path = directory / f"positioning_{day}.jsonl.gz"

    try:
        funding = current_funding(symbol)
        oi = _get("/fapi/v1/openInterest", {"symbol": symbol})
        record: Dict[str, Any] = {
            "t": round(now, 3),
            "open_interest": float(oi["openInterest"]),
            "funding_rate": funding["funding_rate"],
            "mark_price": funding["mark_price"],
            "index_price": funding["index_price"],
            "next_funding_time": funding["next_funding_time"]
        }
        for kind in RATIO_ENDPOINTS:
            try:
                page = fetch_long_short(kind, symbol, "5m")
                if page:
                    record[kind] = page[-1]["long_short_ratio"]
            except Exception as err:
                logger.debug(f"Ratio {kind} unavailable: {err}")
    except Exception as err:
        logger.error(f"Positioning snapshot failed: {err}")
        return None

    with gzip.open(path, "at", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return record


def snapshot(symbol: str = "BTCUSDT", period: str = "15m") -> Dict[str, Any]:
    """
    Everything the dashboard needs, in one call, degrading field by field.

    Each block is fetched independently so that one endpoint being unavailable costs
    that block and not the whole payload -- the ratios in particular are the most
    likely to be missing.
    """
    out: Dict[str, Any] = {"available": False}

    try:
        out.update(current_funding(symbol))
        out["available"] = True
    except Exception as err:
        logger.warning(f"Funding unavailable: {err}")

    try:
        # 2 days at 15m is 192 points, comfortably more than the 97 the 24h
        # comparison needs, without paging deeper than one request.
        oi = fetch_open_interest(symbol, period, days=2)
        if oi:
            latest = oi[-1]["open_interest"]
            out["open_interest"] = latest
            out["open_interest_value"] = oi[-1]["open_interest_value"]
            # 96 fifteen-minute points is 24h; fall back to the oldest available.
            ref = oi[-97]["open_interest"] if len(oi) > 96 else oi[0]["open_interest"]
            out["oi_change_24h_pct"] = ((latest - ref) / ref * 100.0) if ref else 0.0
            out["oi_points"] = len(oi)
            out["available"] = True
    except Exception as err:
        logger.warning(f"Open interest unavailable: {err}")

    try:
        page = fetch_long_short("top_positions", symbol, period)
        if page:
            out["top_long_short_ratio"] = page[-1]["long_short_ratio"]
            out["top_long_account"] = page[-1]["long_account"]
    except Exception as err:
        logger.warning(f"Long/short ratio unavailable: {err}")

    # The OI/price quadrant needs a price change to pair with the OI change, and the
    # caller has the klines. Left for quant_engine to fill in rather than refetching.
    out["history_limit_days"] = FUTURES_DATA_MAX_AGE_DAYS
    return out


def _say(message: str) -> None:
    """
    print() that survives having no console.

    Under pythonw.exe -- which is how the scheduled task runs this, so no window
    appears every few minutes -- sys.stdout is None and a bare print() raises
    AttributeError. Diagnostics must never be the thing that kills the recorder.
    """
    try:
        if sys.stdout is not None:
            print(message, flush=True)
    except Exception:
        pass


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Binance USD-M positioning data")
    parser.add_argument("--record", action="store_true",
                        help="Append one snapshot to workspace/positioning_history/")
    parser.add_argument("--loop", type=float, default=0.0, metavar="SECONDS",
                        help="With --record, keep recording every SECONDS (e.g. 300). "
                             "One long-lived process rather than one per snapshot, so "
                             "the scheduled task does not open a window on every run.")
    parser.add_argument("--log", type=str, default=None, metavar="PATH",
                        help="Append logs to this file. Required under pythonw.exe, "
                             "which has nowhere else to put them.")
    parser.add_argument("--symbol", type=str, default="BTCUSDT")
    args = parser.parse_args()

    handlers: List[Any] = []
    if args.log:
        Path(args.log).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    elif sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = Path(__file__).parent.parent
    if args.record:
        directory = root / "workspace" / "positioning_history"
        if args.loop > 0:
            # Same single-writer rule as the depth recorder. Each snapshot here is its
            # own complete gzip member, so this is less fragile than the depth file --
            # but two loops would still double every row and silently halve the value
            # of any interval-based analysis later.
            from runlock import RunLock, LockHeld
            try:
                lock = RunLock(directory / ".recorder.lock", "positioning recorder").acquire()
            except LockHeld as err:
                logger.error(str(err))
                raise SystemExit(1)
            logger.info(f"Recording positioning every {args.loop:.0f}s to {directory}.")
            consecutive_failures = 0
            while True:
                rec = record_snapshot(directory, args.symbol)
                if rec is None:
                    consecutive_failures += 1
                    # Back off on a sustained outage rather than hammering a dead
                    # endpoint every interval, but never give up: the whole point is
                    # to still be recording months from now.
                    backoff = min(args.loop * (2 ** min(consecutive_failures, 4)), 3600.0)
                    logger.warning(f"Snapshot failed ({consecutive_failures} in a row); "
                                   f"next attempt in {backoff:.0f}s.")
                    time.sleep(backoff)
                    continue
                if consecutive_failures:
                    logger.info(f"Recovered after {consecutive_failures} failed snapshots.")
                    consecutive_failures = 0
                time.sleep(args.loop)
        rec = record_snapshot(directory, args.symbol)
        _say(json.dumps(rec, indent=2) if rec else "snapshot failed")
    else:
        snap = snapshot(args.symbol)
        _say(json.dumps(snap, indent=2))
        oi = fetch_open_interest(args.symbol, "15m", days=30)
        fr = fetch_funding(args.symbol, start_ms=int((time.time() - 200 * 86400) * 1000))
        _say(f"\nopen interest : {len(oi):>6} pts, {coverage_days(oi):>6.1f} days "
             f"(exchange cap {FUTURES_DATA_MAX_AGE_DAYS})")
        _say(f"funding       : {len(fr):>6} pts, {coverage_days(fr):>6.1f} days (no cap)")
