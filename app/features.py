"""Feature engineering for the weekly sales forecaster.

Used by BOTH training (ml/train_forecast.py) and serving (app/forecast.py), so the model
always sees identically computed features.

Everything is expressed relative to the business's own recent scale (12-week mean sales),
so a single global model can serve shops of very different sizes.
"""
from datetime import date, timedelta

import numpy as np

from app.calendar_bd import calendar_features

HORIZONS = list(range(1, 9))       # forecast 1..8 weeks ahead
MIN_HISTORY = 12                   # weeks needed before the first forecast origin

CAL_KEYS = ["days_to_fitr", "days_since_fitr", "days_to_adha", "days_since_adha",
            "fitr_week", "adha_week", "boishakh_week", "month"]

FEATURES = (["h", "lag0", "lag1", "lag2", "lag3", "mean4", "mean26", "trend12", "yoy_ratio",
             "origin_days_to_fitr", "origin_days_since_fitr"]
            + [f"tgt_{k}" for k in CAL_KEYS])


def _safe_mean(a):
    return float(np.mean(a)) if len(a) else float("nan")


def origin_features(sales: np.ndarray, weeks: list, t: int, h: int) -> dict:
    """Features for forecasting week t+h, using only data up to and including week t."""
    scale = _safe_mean(sales[t - 11:t + 1])
    scale = scale if scale > 0 else 1.0
    f = {"h": h, "scale": scale}
    for k in range(4):
        f[f"lag{k}"] = sales[t - k] / scale
    f["mean4"] = _safe_mean(sales[t - 3:t + 1]) / scale
    f["mean26"] = _safe_mean(sales[t - 25:t + 1]) / scale if t >= 25 else np.nan
    f["trend12"] = (scale / _safe_mean(sales[t - 23:t - 11])) if t >= 23 and _safe_mean(sales[t - 23:t - 11]) > 0 else np.nan
    j = t + h - 52
    if j >= 0 and t - 63 >= 0:
        base_ly = _safe_mean(sales[t - 63:t - 51])
        f["yoy_ratio"] = sales[j] / base_ly if base_ly > 0 else np.nan
    else:
        f["yoy_ratio"] = np.nan
    oc = calendar_features(weeks[t])
    f["origin_days_to_fitr"] = oc["days_to_fitr"]
    f["origin_days_since_fitr"] = oc["days_since_fitr"]
    target_week = weeks[t] + timedelta(weeks=h)
    tc = calendar_features(target_week)
    for k in CAL_KEYS:
        f[f"tgt_{k}"] = tc[k]
    f["target_week"] = target_week
    return f


def build_training_rows(sales: np.ndarray, weeks: list):
    """All (origin, horizon) pairs with a known target. Returns list of dicts incl. 'y' and 'actual'."""
    out = []
    n = len(sales)
    for t in range(MIN_HISTORY - 1, n - 1):
        for h in HORIZONS:
            if t + h >= n:
                break
            f = origin_features(sales, weeks, t, h)
            f["actual"] = float(sales[t + h])
            f["y"] = float(np.log(max(sales[t + h], 1.0) / f["scale"]))
            f["origin_index"] = t
            # baselines, computed on the same information set
            f["bl_naive"] = float(sales[t])
            f["bl_mean4"] = f["mean4"] * f["scale"]
            f["bl_seasonal"] = (f["yoy_ratio"] * f["scale"]) if not np.isnan(f["yoy_ratio"]) else f["bl_mean4"]
            out.append(f)
    return out


def to_matrix(rows):
    return np.array([[r[k] for k in FEATURES] for r in rows], dtype=float)


def parse_weeks(week_strings):
    return [date.fromisoformat(w) if isinstance(w, str) else w for w in week_strings]
