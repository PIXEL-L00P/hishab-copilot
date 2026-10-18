"""End-to-end tests against the real HTTP server on a random local port."""
import json
import threading
import unittest
import urllib.error
import urllib.request

from tests.helpers import PASSWORDS, fresh_db
from app import server


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path, conn = fresh_db()
        conn.close()
        import os
        os.environ["HISHAB_QUIET"] = "1"
        cls.srv = server.make_server(cls.path, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.tok = {u: cls.call("/api/login", "POST", {"username": u, "password": PASSWORDS[u]})[1]["token"]
                   for u in ("farhana", "rakib", "lender_demo", "owner2")}

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    @classmethod
    def call(cls, path, method="GET", body=None, user=None, raw=None, headers=None):
        h = {"Content-Type": "application/json"}
        if user:
            h["Authorization"] = "Bearer " + cls.tok[user]
        h.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(cls.base + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.loads(r.read()), dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read()), dict(e.headers)

    def test_requires_authentication(self):
        self.assertEqual(self.call("/api/businesses/1/summary")[0], 401)
        s, body, _ = self.call("/api/businesses/1/summary", headers={"Authorization": "Bearer forged"})
        self.assertEqual(s, 401)

    def test_owner_reads_own_business_only(self):
        self.assertEqual(self.call("/api/businesses/1/summary", user="farhana")[0], 200)
        self.assertEqual(self.call("/api/businesses/2/summary", user="farhana")[0], 403)
        self.assertEqual(self.call("/api/businesses/1/summary", user="owner2")[0], 403)
        self.assertEqual(self.call("/api/businesses/1/summary", user="lender_demo")[0], 403)

    def test_security_headers(self):
        s, _, h = self.call("/api/health")
        self.assertEqual(s, 200)
        self.assertIn("default-src 'self'", h["Content-Security-Policy"])
        self.assertEqual(h["X-Frame-Options"], "DENY")
        self.assertEqual(h["X-Content-Type-Options"], "nosniff")

    def test_bad_requests(self):
        self.assertEqual(self.call("/api/login", "POST", raw=b"{not json")[0], 400)
        self.assertEqual(self.call("/api/login", "POST", raw=b"x" * 70_000)[0], 413)
        self.assertEqual(self.call("/api/nope", user="farhana")[0], 404)
        self.assertEqual(self.call("/api/businesses/1/scenario", "POST", {"evil": 1}, user="farhana")[0], 400)

    def test_records_are_validated_and_append_only(self):
        rec = {"week_start": "2026-10-19", "sales": 180000, "cash_sales": 140000, "credit_sales": 40000,
               "stock_purchases": 110000, "cash_balance": 380000}
        self.assertEqual(self.call("/api/businesses/1/records", "POST", {**rec, "week_start": "2026-10-20"},
                                   user="rakib")[0], 400)               # not a Monday
        self.assertEqual(self.call("/api/businesses/1/records", "POST", {**rec, "cash_sales": 1},
                                   user="rakib")[0], 400)               # parts don't add up
        self.assertEqual(self.call("/api/businesses/1/records", "POST", {**rec, "sales": -5},
                                   user="rakib")[0], 400)
        self.assertEqual(self.call("/api/businesses/1/records", "POST", rec, user="lender_demo")[0], 403)
        self.assertEqual(self.call("/api/businesses/1/records", "POST", {**rec, "week_start": "2026-10-12"},
                                   user="rakib")[0], 409)               # cannot overwrite history
        self.assertEqual(self.call("/api/businesses/1/records", "POST", rec, user="rakib")[0], 200)

    def test_full_agent_flow_and_lender_visibility(self):
        s, r, _ = self.call("/api/lender/reports", user="lender_demo")
        self.assertEqual(r["reports"], [])
        s, r, _ = self.call("/api/businesses/1/agent/chat", "POST",
                            {"message": "share the report with the lender"}, user="farhana")
        self.assertEqual(s, 200)
        aid = r["tool_calls"][0]["action_id"]
        self.assertEqual(self.call(f"/api/actions/{aid}/approve", "POST", user="rakib")[0], 403)
        self.assertEqual(self.call(f"/api/actions/{aid}/approve", "POST", user="owner2")[0], 403)
        self.assertEqual(self.call(f"/api/actions/{aid}/approve", "POST", user="farhana")[0], 200)
        s, r, _ = self.call("/api/lender/reports", user="lender_demo")
        self.assertEqual(len(r["reports"]), 1)
        self.assertIn("key_figures", r["reports"][0]["report"])

    def test_benchmark_endpoint(self):
        s, r, _ = self.call("/api/businesses/1/benchmark", user="farhana")
        self.assertEqual(s, 200)
        self.assertTrue(r["available"])
        self.assertEqual(self.call("/api/businesses/1/benchmark", user="lender_demo")[0], 403)
        self.assertEqual(self.call("/api/businesses/1/benchmark", user="owner2")[0], 403)

    def test_audit_endpoint_owner_only(self):
        s, r, _ = self.call("/api/businesses/1/audit", user="farhana")
        self.assertEqual(s, 200)
        self.assertTrue(r["chain"]["valid"])
        self.assertEqual(self.call("/api/businesses/1/audit", user="rakib")[0], 403)

    def test_static_ui_served(self):
        req = urllib.request.Request(self.base + "/")
        with urllib.request.urlopen(req) as r:
            self.assertIn(b"HishabAI", r.read())
        self.assertEqual(self.call("/static/../app/db.py")[0], 404)


if __name__ == "__main__":
    unittest.main()
