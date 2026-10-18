"""Train and evaluate the HishabAI weekly sales forecaster.

Model: gradient-boosted trees (scikit-learn HistGradientBoostingRegressor) on log sales ratio,
plus two quantile models (P10, P90) for an uncertainty band.

Evaluation is deliberately strict:
  * held-out BUSINESSES the model never saw (every 4th shop, incl. the demo shop), and
  * held-out TIME: the last 53 weeks (includes Eid-ul-Fitr and Eid-ul-Adha 2026).
Compared against three baselines: last week (naive), 4-week mean, and seasonal naive.

Run:  python ml/train_forecast.py
Outputs: models/forecast_model.joblib, models/metrics.json, docs/figures/*.png
"""
import json
import os
import sys
import time
from datetime import date

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app.features import FEATURES, HORIZONS, build_training_rows, parse_weeks, to_matrix  # noqa: E402

DATA = os.path.join(ROOT, "data", "synthetic", "weekly_records.csv")
MODEL_PATH = os.path.join(ROOT, "models", "forecast_model.joblib")
METRICS_PATH = os.path.join(ROOT, "models", "metrics.json")
FIG_DIR = os.path.join(ROOT, "docs", "figures")
TEST_START = date(2025, 10, 13)          # targets on/after this week are the test period
CALIB_START = date(2025, 4, 14)          # last 26 training weeks calibrate the uncertainty band
TARGET_COVERAGE = 0.80
SEED = 7

PARAMS = dict(max_iter=400, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=40,
              l2_regularization=1.0, random_state=SEED)


def is_test_business(bid: int) -> bool:
    return bid % 4 == 1          # 1, 5, 9, ..., 37 -> 10 unseen shops (incl. Style Corner)


def load_rows():
    df = pd.read_csv(DATA)
    rows = []
    for bid, g in df.groupby("business_id"):
        g = g.sort_values("week_start")
        weeks = parse_weeks(g["week_start"].tolist())
        for r in build_training_rows(g["sales"].to_numpy(float), weeks):
            r["business_id"] = int(bid)
            rows.append(r)
    return rows


def fit_models(rows):
    X, y = to_matrix(rows), np.array([r["y"] for r in rows])
    models = {}
    for name, extra in [("p50", dict(loss="squared_error")),
                        ("p10", dict(loss="quantile", quantile=0.10)),
                        ("p90", dict(loss="quantile", quantile=0.90))]:
        m = HistGradientBoostingRegressor(**PARAMS, **extra)
        m.fit(X, y)
        models[name] = m
    return models


def predict(models, rows, widen=0.0):
    """Return (p50, lower, upper) in BDT. `widen` is the conformal margin in log space."""
    X = to_matrix(rows)
    scale = np.array([r["scale"] for r in rows])
    logs = {k: m.predict(X) for k, m in models.items()}
    lo = np.minimum(logs["p10"], logs["p50"]) - widen
    hi = np.maximum(logs["p90"], logs["p50"]) + widen
    return scale * np.exp(logs["p50"]), scale * np.exp(lo), scale * np.exp(hi)


def conformal_margin(models, calib_rows, coverage=TARGET_COVERAGE):
    """Conformalised quantile regression: how much to widen the band to hit `coverage`."""
    X = to_matrix(calib_rows)
    y = np.array([r["y"] for r in calib_rows])
    lo = np.minimum(models["p10"].predict(X), models["p50"].predict(X))
    hi = np.maximum(models["p90"].predict(X), models["p50"].predict(X))
    scores = np.maximum(lo - y, y - hi)
    n = len(scores)
    q = np.quantile(scores, min(1.0, np.ceil((n + 1) * coverage) / n))
    return float(max(q, 0.0))


def wape(actual, pred):
    return float(np.sum(np.abs(actual - pred)) / np.sum(np.abs(actual)))


def evaluate(models, rows, label, widen):
    actual = np.array([r["actual"] for r in rows])
    p50, lo, hi = predict(models, rows, widen)
    res = {"set": label, "n_forecasts": int(len(rows)), "metrics": {}}
    cands = {"HishabAI model (GBT)": p50,
             "Baseline: last week": np.array([r["bl_naive"] for r in rows]),
             "Baseline: 4-week mean": np.array([r["bl_mean4"] for r in rows]),
             "Baseline: seasonal naive": np.array([r["bl_seasonal"] for r in rows])}
    peak = np.array([r["tgt_days_to_fitr"] <= 35 for r in rows])
    for name, pred in cands.items():
        res["metrics"][name] = {
            "WAPE": round(wape(actual, pred), 4),
            "MAE_BDT": round(float(np.mean(np.abs(actual - pred))), 0),
            "WAPE_pre_Eid_weeks": round(wape(actual[peak], pred[peak]), 4) if peak.any() else None,
        }
    res["interval_coverage_target"] = TARGET_COVERAGE
    res["interval_coverage"] = round(float(np.mean((actual >= lo) & (actual <= hi))), 3)
    _, raw_lo, raw_hi = predict(models, rows, 0.0)
    res["interval_coverage_before_calibration"] = round(float(np.mean((actual >= raw_lo) & (actual <= raw_hi))), 3)
    res["wape_by_horizon"] = {}
    for h in HORIZONS:
        m = np.array([r["h"] == h for r in rows])
        res["wape_by_horizon"][str(h)] = {
            "model": round(wape(actual[m], p50[m]), 4),
            "best_baseline": round(min(wape(actual[m], c[m]) for k, c in cands.items() if k.startswith("Baseline")), 4)}
    return res


def make_figures(models, rows, widen):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(FIG_DIR, exist_ok=True)
    # 1) Style Corner, 1-week-ahead forecasts across the test year
    sel = [r for r in rows if r["business_id"] == 1 and r["h"] == 1 and r["target_week"] >= TEST_START]
    sel.sort(key=lambda r: r["target_week"])
    p50, lo, hi = predict(models, sel, widen)
    x = [r["target_week"] for r in sel]
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.fill_between(x, lo / 1e3, hi / 1e3, color="#9ec5e8", alpha=0.5, label="80% calibrated band")
    ax.plot(x, [r["actual"] / 1e3 for r in sel], color="#222", lw=1.6, label="Actual sales")
    ax.plot(x, p50 / 1e3, color="#1f6fb5", lw=1.6, ls="--", label="Model forecast (1 week ahead)")
    ax.plot(x, [r["bl_mean4"] / 1e3 for r in sel], color="#c0504d", lw=1, ls=":", label="Baseline: 4-week mean")
    ax.set_ylabel("Weekly sales (thousand BDT)")
    ax.set_title("Style Corner (unseen shop) — test year Oct 2025 to Oct 2026")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "forecast_style_corner.png"), dpi=150)
    plt.close(fig)


def main():
    t0 = time.time()
    rows = load_rows()
    train = [r for r in rows if not is_test_business(r["business_id"]) and r["target_week"] < TEST_START]
    test_unseen = [r for r in rows if is_test_business(r["business_id"]) and r["target_week"] >= TEST_START]
    test_temporal = [r for r in rows if not is_test_business(r["business_id"]) and r["target_week"] >= TEST_START]
    print(f"rows: train={len(train)} test_unseen_shops={len(test_unseen)} test_known_shops={len(test_temporal)}")

    fit_rows = [r for r in train if r["target_week"] < CALIB_START]
    calib_rows = [r for r in train if r["target_week"] >= CALIB_START]
    models = fit_models(fit_rows)
    widen = conformal_margin(models, calib_rows)
    print(f"conformal margin (log space): {widen:.4f} from {len(calib_rows)} calibration forecasts")
    models = fit_models(train)
    report = {
        "trained_at": time.strftime("%Y-%m-%d %H:%M"),
        "data": "synthetic (data/generate_synthetic.py)",
        "train_rows": len(train),
        "test_period_start": TEST_START.isoformat(),
        "conformal_margin_log": widen,
        "evaluation": [evaluate(models, test_unseen, "Unseen shops, test year", widen),
                       evaluate(models, test_temporal, "Training shops, test year", widen)],
        "features": FEATURES,
        "params": PARAMS,
    }
    make_figures(models, rows, widen)

    # final model: retrain on every shop and every week for serving
    final = fit_models(rows)
    joblib.dump({"models": final, "features": FEATURES, "horizons": HORIZONS, "conformal_margin": widen,
                 "trained_on_rows": len(rows), "version": "1.0"}, MODEL_PATH, compress=3)
    report["final_model_rows"] = len(rows)
    report["train_seconds"] = round(time.time() - t0, 1)
    with open(METRICS_PATH, "w") as f:
        json.dump(report, f, indent=2)

    for ev in report["evaluation"]:
        print(f"\n== {ev['set']} ({ev['n_forecasts']} forecasts) | 80% band coverage {ev['interval_coverage']} "
              f"(before calibration {ev['interval_coverage_before_calibration']})")
        for k, v in ev["metrics"].items():
            print(f"  {k:28s} WAPE {v['WAPE']:.3f}  MAE {v['MAE_BDT']:>9,.0f}  pre-Eid WAPE {v['WAPE_pre_Eid_weeks']}")
    print(f"\nSaved {MODEL_PATH} and {METRICS_PATH} in {report['train_seconds']}s")


if __name__ == "__main__":
    main()
