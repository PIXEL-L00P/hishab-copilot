"""Serve sales forecasts from the trained model for a business stored in the database."""
import functools
import os
from datetime import timedelta

import joblib
import numpy as np

from app.features import HORIZONS, MIN_HISTORY, origin_features, parse_weeks, to_matrix

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.environ.get("HISHAB_MODEL", os.path.join(ROOT, "models", "forecast_model.joblib"))


@functools.lru_cache(maxsize=1)
def load_model():
    if not os.path.exists(MODEL_PATH):
        raise FileNotFoundError(f"Model not found at {MODEL_PATH}. Run: python ml/train_forecast.py")
    return joblib.load(MODEL_PATH)


def history(conn, business_id: int):
    rows = conn.execute("SELECT week_start, sales FROM weekly_records WHERE business_id = ? ORDER BY week_start",
                        (business_id,)).fetchall()
    return parse_weeks([r["week_start"] for r in rows]), np.array([r["sales"] for r in rows], dtype=float)


def forecast_sales(conn, business_id: int, horizons=HORIZONS):
    """Weekly sales forecast with an 80% calibrated uncertainty band.

    Returns {"method", "weeks": [{"week_start", "p50", "low", "high"}], "last_actual_week"}.
    """
    weeks, sales = history(conn, business_id)
    if len(sales) == 0:
        return {"method": "none", "weeks": [], "note": "No records yet."}
    last = weeks[-1]
    if len(sales) < MIN_HISTORY:
        avg = float(np.mean(sales))
        return {"method": "simple_average (insufficient history)", "last_actual_week": last.isoformat(),
                "weeks": [{"week_start": (last + timedelta(weeks=h)).isoformat(), "p50": round(avg),
                           "low": round(avg * 0.7), "high": round(avg * 1.3)} for h in horizons],
                "note": f"Only {len(sales)} weeks of history; at least {MIN_HISTORY} are needed for the AI model."}
    bundle = load_model()
    t = len(sales) - 1
    rows = [origin_features(sales, weeks, t, h) for h in horizons]
    X = to_matrix(rows)
    scale = np.array([r["scale"] for r in rows])
    m = bundle["models"]
    widen = bundle.get("conformal_margin", 0.0)
    p50 = m["p50"].predict(X)
    lo = np.minimum(m["p10"].predict(X), p50) - widen
    hi = np.maximum(m["p90"].predict(X), p50) + widen
    out = []
    for i, r in enumerate(rows):
        out.append({"week_start": r["target_week"].isoformat(),
                    "p50": round(float(scale[i] * np.exp(p50[i]))),
                    "low": round(float(scale[i] * np.exp(lo[i]))),
                    "high": round(float(scale[i] * np.exp(hi[i])))})
    return {"method": "gradient_boosted_trees_v" + bundle.get("version", "1"),
            "last_actual_week": last.isoformat(), "weeks": out,
            "band": "80% calibrated prediction interval"}
