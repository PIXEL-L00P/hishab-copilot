import unittest
from datetime import date

from tests.helpers import fresh_db
from app import financing, forecast as fc, planner


class Planner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path, cls.conn = fresh_db()
        cls.f = fc.forecast_sales(cls.conn, 1)
        cls.plan = planner.draft_payment_plan(cls.conn, 1, cls.f)

    def test_plan_buys_time_and_never_worsens_cash(self):
        p = self.plan
        self.assertGreaterEqual(p["after"]["min_cash"], p["before"]["min_cash"])
        self.assertGreater(p["after"]["first_negative_week"] or 99, p["before"]["first_negative_week"])

    def test_extensions_respect_limits(self):
        cats = {r["id"]: (r["category"], r["flexible"]) for r in self.conn.execute("SELECT * FROM payables")}
        for s in self.plan["steps"]:
            if s["type"] != "request_supplier_extension":
                continue
            cat, flex = cats[s["payable_id"]]
            self.assertTrue(flex)
            self.assertNotIn(cat, planner.NON_DEFERRABLE)
            weeks = (date.fromisoformat(s["proposed_due"]) - date.fromisoformat(s["original_due"])).days / 7
            self.assertTrue(0 < weeks <= planner.MAX_EXTENSION_WEEKS)

    def test_financing_need_rounded_and_reminders_for_overdue(self):
        self.assertEqual(self.plan["financing_need"] % 10_000, 0)
        self.assertGreater(self.plan["financing_need"], 0)
        reminders = [s for s in self.plan["steps"] if s["type"] == "send_payment_reminder"]
        self.assertEqual({r["customer_name"] for r in reminders}, {"Karim Traders", "Mitu Boutique"})

    def test_healthy_business_gets_no_extensions(self):
        for bid in range(2, 41):
            f = fc.forecast_sales(self.conn, bid)
            p = planner.draft_payment_plan(self.conn, bid, f)
            if p["before"]["first_negative_week"] is None and p["before"]["min_cash"] >= p["safety_buffer"]:
                self.assertFalse([s for s in p["steps"] if s["type"] == "request_supplier_extension"])
                return
        self.skipTest("no healthy business found")


class Financing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path, cls.conn = fresh_db()

    def test_rules_are_applied(self):
        m = financing.match_financing(self.conn, 1, 210_000, "2026-12-07")
        by = {o["name"]: o for o in m["options"]}
        women = by["Women entrepreneur SME loan (participating bank)"]
        self.assertTrue(women["eligible"])                         # owner is a woman
        bank = by["Bank SME working-capital loan"]
        self.assertFalse(bank["eligible"])
        self.assertTrue(any("collateral" in r for r in bank["why_not"]))
        for o in m["options"]:
            if o["eligible"] and o["dscr_after"] is not None:
                self.assertGreaterEqual(o["dscr_after"], 1.25)

    def test_women_only_product_excluded_for_other_owners(self):
        self.conn.execute("UPDATE businesses SET owner_is_woman = 0 WHERE id = 1")
        m = financing.match_financing(self.conn, 1, 210_000)
        women = [o for o in m["options"] if o["name"].startswith("Women")][0]
        self.assertFalse(women["eligible"])
        self.conn.execute("UPDATE businesses SET owner_is_woman = 1 WHERE id = 1")

    def test_ranking_puts_eligible_first_and_validates_amount(self):
        m = financing.match_financing(self.conn, 1, 210_000, include_supplier_credit=False)
        flags = [o["eligible"] for o in m["options"]]
        self.assertEqual(flags, sorted(flags, reverse=True))
        self.assertFalse([o for o in m["options"] if o["provider_type"] == "supplier"])
        with self.assertRaises(ValueError):
            financing.match_financing(self.conn, 1, -5)


if __name__ == "__main__":
    unittest.main()
