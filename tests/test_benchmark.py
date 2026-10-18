import json
import unittest

from tests.helpers import ctx, fresh_db
from app import agent, benchmark, financing


class PeerBenchmark(unittest.TestCase):
    def setUp(self):
        self.path, self.conn = fresh_db()

    def test_compares_with_all_peers_except_itself(self):
        b = benchmark.compare_with_peers(self.conn, 1)
        self.assertTrue(b["available"])
        self.assertEqual(b["peer_group"]["peer_count"], 39)
        for row in b["metrics"]:
            if row["available"]:
                self.assertTrue(0 <= row["percentile_rank"] <= 100)
                self.assertLessEqual(row["peer_p25"], row["peer_median"])
                self.assertLessEqual(row["peer_median"], row["peer_p75"])

    def test_demo_shop_profile(self):
        b = benchmark.compare_with_peers(self.conn, 1)
        by = {r["metric"]: r for r in b["metrics"]}
        self.assertEqual(by["gross_margin"]["status"], "strong")
        self.assertEqual(by["overdue_ratio"]["status"], "attention")
        self.assertIn("free about", by["overdue_ratio"]["tip"])

    def test_tip_amount_is_correct(self):
        import re
        b = benchmark.compare_with_peers(self.conn, 1)
        row = [r for r in b["metrics"] if r["metric"] == "overdue_ratio"][0]
        m = benchmark.business_metrics(self.conn, 1)
        expected = (row["you"] - row["peer_median"]) * m["_monthly_sales"]
        shown = float(re.search(r"৳([\d,]+)", row["tip"]).group(1).replace(",", ""))
        self.assertAlmostEqual(shown, expected, delta=max(5.0, 0.001 * expected))   # rounding of displayed ratios

    def test_k_anonymity_minimum_peer_count(self):
        # leave only 4 other shops in the peer group -> nothing may be released
        self.conn.execute("UPDATE businesses SET district = 'Chattogram' WHERE id > 5")
        b = benchmark.compare_with_peers(self.conn, 1)
        self.assertFalse(b["available"])
        self.assertNotIn("metrics", b)

    def test_no_individual_peer_data_leaks(self):
        b = benchmark.compare_with_peers(self.conn, 1)
        text = json.dumps(b, ensure_ascii=False)
        names = [r["name"] for r in self.conn.execute("SELECT name FROM businesses WHERE id != 1")]
        for n in names:
            self.assertNotIn(n, text)
        allowed = {"metric", "label", "available", "unit", "higher_is_better", "you", "peer_median", "peer_p25",
                   "peer_p75", "you_display", "median_display", "percentile_rank", "status", "peers_compared",
                   "tip", "reason"}
        for row in b["metrics"]:
            self.assertTrue(set(row) <= allowed, set(row) - allowed)

    def test_lender_report_only_contains_ranks(self):
        rep = financing.loan_readiness_report(self.conn, 1)
        pc = rep["peer_comparison"]
        self.assertTrue(pc["available"])
        self.assertEqual(set(pc), {"available", "peer_count", "overall_percentile", "metric_percentiles"})

    def test_agent_tool_and_chat(self):
        c = ctx(self.conn, "farhana")
        self.assertEqual(agent.call_tool(c, "compare_with_peers")["status"], "executed")
        self.assertEqual(agent.call_tool(ctx(self.conn, "lender_demo"), "compare_with_peers")["status"], "denied")
        self.assertEqual(agent.detect_intent("Am I more profitable than similar shops?"), "benchmark")
        self.assertEqual(agent.detect_intent("অন্য দোকানের সাথে তুলনা করো"), "benchmark")
        r = agent.chat(c, "Am I more profitable than similar shops?")
        self.assertIn("similar shops", r["reply"])
        r = agent.chat(c, "অন্য দোকানের সাথে তুলনা করো")
        self.assertTrue(agent.is_bangla(r["reply"]))


if __name__ == "__main__":
    unittest.main()
