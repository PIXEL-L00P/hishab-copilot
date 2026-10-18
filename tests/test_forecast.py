import json
import os
import unittest

import numpy as np

from tests.helpers import ROOT, fresh_db
from app import forecast as fc
from app.features import origin_features, parse_weeks


class ForecastModel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path, cls.conn = fresh_db()

    def test_forecast_shape_and_band_order(self):
        f = fc.forecast_sales(self.conn, 1)
        self.assertEqual(len(f["weeks"]), 8)
        for w in f["weeks"]:
            self.assertLessEqual(w["low"], w["p50"])
            self.assertLessEqual(w["p50"], w["high"])
            self.assertGreater(w["p50"], 0)

    def test_short_history_falls_back_safely(self):
        self.conn.execute("DELETE FROM weekly_records WHERE business_id = 3 AND week_start < '2026-09-01'")
        f = fc.forecast_sales(self.conn, 3)
        self.assertIn("insufficient history", f["method"])

    def test_features_do_not_peek_into_the_future(self):
        weeks, sales = fc.history(self.conn, 1)
        t = 100
        a = origin_features(sales, weeks, t, 4)
        tampered = sales.copy()
        tampered[t + 1:] *= 10          # change everything after the forecast origin
        b = origin_features(tampered, weeks, t, 4)
        for k in a:
            if k in ("yoy_ratio",):     # uses last year's same week, i.e. still in the past
                continue
            if isinstance(a[k], float) and np.isnan(a[k]):
                continue
            self.assertEqual(a[k], b[k], k)

    def test_model_beats_all_baselines_on_unseen_shops(self):
        with open(os.path.join(ROOT, "models", "metrics.json")) as f:
            m = json.load(f)
        unseen = m["evaluation"][0]
        self.assertTrue(unseen["set"].startswith("Unseen shops"))
        model = unseen["metrics"]["HishabAI model (GBT)"]["WAPE"]
        for name, v in unseen["metrics"].items():
            if name.startswith("Baseline"):
                self.assertLess(model, v["WAPE"], name)
        self.assertGreaterEqual(unseen["interval_coverage"], 0.75)


if __name__ == "__main__":
    unittest.main()
