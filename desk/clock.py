"""IST market clock, expiry handling and time-to-expiry maths.

Indian options decay on a calendar clock but trade on a session clock. We keep
both: `t_calendar` for pricing consistency with quoted IVs, and `t_business`
which strips out the ~17.5 non-trading hours of each day plus weekends and
holidays. Theta measured on the business clock is what actually hurts an
intraday buyer, so the features module reports both.
"""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

SESSION_OPEN = dt.time(9, 15)
SESSION_CLOSE = dt.time(15, 30)
SESSION_MINUTES = 375

# NSE trading holidays. Update once a year from
# nseindia.com/resources/exchange-communication-holidays
HOLIDAYS_2026 = {
    "2026-01-26", "2026-02-15", "2026-03-03", "2026-03-19", "2026-03-21",
    "2026-04-01", "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-27",
    "2026-08-15", "2026-08-26", "2026-10-02", "2026-10-21", "2026-11-09",
    "2026-11-24", "2026-12-25",
}


def now() -> dt.datetime:
    return dt.datetime.now(IST)


def to_ist(ts: dt.datetime) -> dt.datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=IST)
    return ts.astimezone(IST)


def is_holiday(d: dt.date) -> bool:
    return d.weekday() >= 5 or d.isoformat() in HOLIDAYS_2026


def is_trading_day(d: dt.date) -> bool:
    return not is_holiday(d)


def is_market_open(ts: dt.datetime | None = None) -> bool:
    ts = to_ist(ts or now())
    if not is_trading_day(ts.date()):
        return False
    return SESSION_OPEN <= ts.time() <= SESSION_CLOSE


def minutes_into_session(ts: dt.datetime | None = None) -> float:
    ts = to_ist(ts or now())
    open_dt = ts.replace(hour=9, minute=15, second=0, microsecond=0)
    return max(0.0, (ts - open_dt).total_seconds() / 60.0)


def minutes_to_close(ts: dt.datetime | None = None) -> float:
    ts = to_ist(ts or now())
    close_dt = ts.replace(hour=15, minute=30, second=0, microsecond=0)
    return max(0.0, (close_dt - ts).total_seconds() / 60.0)


def parse_hhmm(s: str) -> dt.time:
    h, m = s.split(":")
    return dt.time(int(h), int(m))


def expiry_datetime(expiry: dt.date) -> dt.datetime:
    """NSE options stop trading at 15:30 IST on expiry day."""
    return dt.datetime.combine(expiry, SESSION_CLOSE, tzinfo=IST)


def t_calendar(expiry: dt.date, ts: dt.datetime | None = None,
               days_per_year: int = 365) -> float:
    """Year fraction on a wall-clock basis. Floored so pricing never blows up."""
    ts = to_ist(ts or now())
    secs = (expiry_datetime(expiry) - ts).total_seconds()
    return max(secs / (days_per_year * 86400.0), 1e-6)


def t_business(expiry: dt.date, ts: dt.datetime | None = None,
               days_per_year: int = 252) -> float:
    """Year fraction counting only open-market minutes."""
    ts = to_ist(ts or now())
    if ts >= expiry_datetime(expiry):
        return 1e-6

    minutes = 0.0
    # remainder of today
    if is_trading_day(ts.date()) and ts.time() < SESSION_CLOSE:
        start = max(ts.time(), SESSION_OPEN)
        today_close = dt.datetime.combine(ts.date(), SESSION_CLOSE, tzinfo=IST)
        today_start = dt.datetime.combine(ts.date(), start, tzinfo=IST)
        minutes += max(0.0, (today_close - today_start).total_seconds() / 60.0)

    d = ts.date() + dt.timedelta(days=1)
    while d < expiry:
        if is_trading_day(d):
            minutes += SESSION_MINUTES
        d += dt.timedelta(days=1)

    if expiry > ts.date() and is_trading_day(expiry):
        minutes += SESSION_MINUTES

    return max(minutes / (days_per_year * SESSION_MINUTES), 1e-6)


def sessions_remaining(expiry: dt.date, ts: dt.datetime | None = None) -> float:
    ts = to_ist(ts or now())
    return t_business(expiry, ts) * 252.0
