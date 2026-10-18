"""Bangladesh retail calendar features.

Eid dates are approximate (they depend on moon sighting and can shift by a day).
That is accurate enough for weekly features, because a one-day shift rarely moves
an event into a different week.
"""
from datetime import date, timedelta

EID_UL_FITR = [
    date(2022, 5, 3), date(2023, 4, 22), date(2024, 4, 11), date(2025, 3, 31),
    date(2026, 3, 21), date(2027, 3, 10), date(2028, 2, 27),
]
EID_UL_ADHA = [
    date(2022, 7, 10), date(2023, 6, 29), date(2024, 6, 17), date(2025, 6, 7),
    date(2026, 5, 27), date(2027, 5, 17), date(2028, 5, 5),
]

CAP_DAYS = 70  # features are capped at 10 weeks


def week_start(d: date) -> date:
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def _days_to_next(d: date, events) -> int:
    future = [(e - d).days for e in events if (e - d).days >= 0]
    return min(min(future), CAP_DAYS) if future else CAP_DAYS


def _days_since_last(d: date, events) -> int:
    past = [(d - e).days for e in events if (d - e).days > 0]
    return min(min(past), CAP_DAYS) if past else CAP_DAYS


def _contains(ws: date, events) -> bool:
    return any(ws <= e < ws + timedelta(days=7) for e in events)


def boishakh_dates(years):
    return [date(y, 4, 14) for y in years]


def calendar_features(ws: date) -> dict:
    """Calendar features for the week starting on Monday `ws`."""
    years = range(ws.year - 1, ws.year + 2)
    mid = ws + timedelta(days=3)
    return {
        "days_to_fitr": _days_to_next(mid, EID_UL_FITR),
        "days_since_fitr": _days_since_last(mid, EID_UL_FITR),
        "days_to_adha": _days_to_next(mid, EID_UL_ADHA),
        "days_since_adha": _days_since_last(mid, EID_UL_ADHA),
        "fitr_week": int(_contains(ws, EID_UL_FITR)),
        "adha_week": int(_contains(ws, EID_UL_ADHA)),
        "boishakh_week": int(_contains(ws, boishakh_dates(years))
                             or _contains(ws + timedelta(days=7), boishakh_dates(years))),
        "month": ws.month,
        "week_of_year": ws.isocalendar()[1],
    }


def festival_in_week(ws: date):
    """Festival-bonus week: the week whose window [Thu, next Wed] contains an Eid.

    Each Eid maps to exactly one bonus week, paid shortly before the holiday.
    """
    lo, hi = ws + timedelta(days=3), ws + timedelta(days=10)
    if any(lo <= e < hi for e in EID_UL_FITR):
        return "fitr"
    if any(lo <= e < hi for e in EID_UL_ADHA):
        return "adha"
    return None
