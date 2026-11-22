"""
Session clock shared by the live pipeline (liquidity pools, sentinel briefing).

Session opens follow local exchange time, not fixed UTC hours, so they move when the
UK and US change their clocks:

| Session | Starts | Ends |
| :-- | :-- | :-- |
| ASIA | Tokyo open, 00:00 UTC (Japan has no DST) | London open |
| LONDON | London open, 08:00 London time | NY open |
| NY | NYSE open, 09:30 New York time | NYSE close |
| PRE_ASIA | NYSE close, 16:00 New York time | Tokyo open |

The old fixed table (Asia 0-7, London 7-13:30, NY 13:30-21 UTC) is only right
while both the UK and US are on summer time. On winter time it opens London an hour
early and New York an hour early, and it labelled the NY-close-to-Tokyo gap as
"NY CLOSE", which read as New York being in session.

DST is computed from the published rules rather than zoneinfo, because zoneinfo
needs the tzdata package on Windows and this project does not ship it:
- UK: last Sunday of March 01:00 UTC to last Sunday of October 01:00 UTC.
- US: second Sunday of March 02:00 local to first Sunday of November 02:00 local.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

TOKYO_OPEN_UTC_MIN = 0


def _nth_sunday(year: int, month: int, n: int) -> datetime:
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    offset = (6 - first.weekday()) % 7  # weekday(): Monday 0 .. Sunday 6
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_sunday(year: int, month: int) -> datetime:
    nxt = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
    last = nxt - timedelta(days=1)
    return last - timedelta(days=(last.weekday() + 1) % 7)


def uk_summer_time(now_utc: datetime) -> bool:
    y = now_utc.year
    start = _last_sunday(y, 3).replace(hour=1)
    end = _last_sunday(y, 10).replace(hour=1)
    return start <= now_utc < end


def us_summer_time(now_utc: datetime) -> bool:
    y = now_utc.year
    start = _nth_sunday(y, 3, 2).replace(hour=7)   # 02:00 EST
    end = _nth_sunday(y, 11, 1).replace(hour=6)    # 02:00 EDT
    return start <= now_utc < end


def session_bounds_utc(now_utc: datetime) -> Tuple[int, int, int]:
    """London open, NY open and NY close for this UTC day, in minutes after 00:00 UTC."""
    london_open = 8 * 60 - (60 if uk_summer_time(now_utc) else 0)
    ny_shift = 0 if us_summer_time(now_utc) else 60
    ny_open = 13 * 60 + 30 + ny_shift
    ny_close = 20 * 60 + ny_shift
    return london_open, ny_open, ny_close


def session_at(now_utc: datetime) -> str:
    """ASIA, LONDON, NY or PRE_ASIA for a UTC timestamp."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    london_open, ny_open, ny_close = session_bounds_utc(now_utc)
    m = now_utc.hour * 60 + now_utc.minute
    if m < london_open:
        return "ASIA"
    if m < ny_open:
        return "LONDON"
    if m < ny_close:
        return "NY"
    return "PRE_ASIA"


def session_of_ms(open_time_ms: float) -> Optional[str]:
    """Session for a candle open time; None for the pre-Asia gap, which is not a session."""
    name = session_at(datetime.fromtimestamp(open_time_ms / 1000.0, tz=timezone.utc))
    return None if name == "PRE_ASIA" else name
