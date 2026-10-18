import unittest
from datetime import date

from tests.helpers import fresh_db
from app import finance_engine as fe, forecast as fc


class FormattingAndFormulas(unittest.TestCase):
    def test_bdt_uses_lakh_grouping(self):
        self.assertEqual(fe.fmt_bdt(1234567), "৳12,34,567")
        self.assertEqual(fe.fmt_bdt(-175475), "-৳1,75,475")
        self.assertEqual(fe.fmt_bdt(999), "৳999")

    def test_amortized_payment_matches_textbook_value(self):
        # 1,00,000 at 12% for 12 months -> 8,884.88 per month
        self.assertAlmostEqual(fe.amortized_payment(100_000, 0.12, 12), 8884.88, places=2)
        self.assertAlmostEqual(fe.amortized_payment(120_000, 0.0, 12), 10_000.0)
        with self.assertRaises(ValueError):
            fe.amortized_payment(1000, 0.1, 0)

    def test_week_helpers(self):
        self.assertTrue(fe.is_first_week_of_month(date(2026, 11, 2)))
        self.assertFalse(fe.is_first_week_of_month(date(2026, 11, 9)))
        self.assertTrue(fe.week_contains_day(date(2026, 11, 9), 10))
        self.assertEqual(fe.week_index_of(date(2026, 11, 4), date(2026, 10, 19)), 3)


class EngineOnData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path, cls.conn = fresh_db()
        cls.f = fc.forecast_sales(cls.conn, 1)

    def test_summary_break_even_is_consistent(self):
        s = fe.financial_summary(self.conn, 1)
        self.assertAlmostEqual(s["break_even_monthly_sales"] * s["gross_margin_estimate"],
                               s["fixed_costs_monthly"], delta=s["fixed_costs_monthly"] * 0.01)
        self.assertEqual(s["overdue_customers"], 2)
        self.assertEqual(s["receivables_overdue"], 70_500)

    def test_projection_arithmetic_closes(self):
        p = fe.project_cash(self.conn, 1, self.f)
        opening = p["starting_cash"]
        for w in p["weeks"]:
            self.assertAlmostEqual(w["opening_cash"], opening, delta=1)
            self.assertAlmostEqual(w["closing_cash"], w["opening_cash"] + w["total_in"] - w["total_out"], delta=2)
            opening = w["closing_cash"]

    def test_rent_salaries_only_in_first_week_of_month(self):
        p = fe.project_cash(self.conn, 1, self.f)
        for w in p["weeks"]:
            ws = date.fromisoformat(w["week_start"])
            self.assertEqual(w["outflow"]["rent_salaries"] > 0, ws.day <= 7)

    def test_payable_override_moves_the_bill(self):
        base = fe.project_cash(self.conn, 1, self.f)
        pid = self.conn.execute("SELECT id FROM payables WHERE counterparty = 'Nur Fabrics Ltd'").fetchone()["id"]
        moved = fe.project_cash(self.conn, 1, self.f, payable_overrides={pid: "2026-12-02"})
        self.assertEqual(base["weeks"][2]["outflow"]["payables"] - moved["weeks"][2]["outflow"]["payables"], 380_000)
        self.assertEqual(moved["weeks"][6]["outflow"]["payables"] - base["weeks"][6]["outflow"]["payables"], 380_000)

    def test_demo_business_is_critical(self):
        o = fe.cash_outlook(self.conn, 1, self.f)
        self.assertEqual(o["alert_level"], "critical")
        self.assertEqual(o["expected"]["first_negative_week"], 3)
        self.assertLessEqual(o["pessimistic"]["min_cash"], o["expected"]["min_cash"])

    def test_scenario_validation(self):
        with self.assertRaises(ValueError):
            fe.run_scenario(self.conn, 1, self.f, sales_change_pct=-95)
        with self.assertRaises(ValueError):
            fe.run_scenario(self.conn, 1, self.f, one_time_cost=-1)
        with self.assertRaises(ValueError):
            fe.run_scenario(self.conn, 1, self.f, loan_amount=100_000, loan_months=0)

    def test_scenario_direction(self):
        up = fe.run_scenario(self.conn, 1, self.f, sales_change_pct=20)
        down = fe.run_scenario(self.conn, 1, self.f, sales_change_pct=-20)
        self.assertGreater(up["scenario_min_cash"], up["baseline_min_cash"])
        self.assertLess(down["scenario_min_cash"], down["baseline_min_cash"])
        loan = fe.run_scenario(self.conn, 1, self.f, loan_amount=300_000, loan_annual_rate=0.06, loan_months=24)
        self.assertGreater(loan["scenario_min_cash"], loan["baseline_min_cash"])
        self.assertGreater(loan["new_loan_monthly_instalment"], 0)


if __name__ == "__main__":
    unittest.main()
