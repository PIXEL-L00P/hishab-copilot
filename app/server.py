"""HishabAI web server (Python standard library only).

Run:  python -m app.server            -> http://127.0.0.1:8000
Env:  HISHAB_DB (database path), HISHAB_HOST, HISHAB_PORT, ANTHROPIC_API_KEY (optional LLM mode)
"""
import json
import os
import re
import traceback
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from app import agent, audit, benchmark, db, finance_engine as fe, financing, forecast as fc, security

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
STATIC_FILES = {"/": ("index.html", "text/html; charset=utf-8"),
                "/static/app.js": ("app.js", "application/javascript; charset=utf-8"),
                "/static/style.css": ("style.css", "text/css; charset=utf-8")}
MAX_BODY = 64 * 1024
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
RECORD_FIELDS = ["sales", "cash_sales", "credit_sales", "receivables_collected", "stock_purchases", "rent",
                 "salaries", "festival_bonus", "utilities", "other_expenses", "loan_repayment",
                 "owner_drawings", "owner_injection", "cash_balance"]


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


# ------------------------------------------------------------------ auth
@route("POST", r"/api/login")
def h_login(req, conn, body):
    u, p = body.get("username"), body.get("password")
    if not isinstance(u, str) or not isinstance(p, str) or not u or not p or len(u) > 64 or len(p) > 128:
        raise HttpError(400, "username and password are required")
    token = security.login(conn, u, p)
    user = security.user_from_token(conn, token)
    return {"token": token, "user": user, "memberships": security.memberships(conn, user["id"])}


@route("POST", r"/api/logout")
def h_logout(req, conn, body):
    req.user()
    security.logout(conn, req.token())
    return {"ok": True}


@route("GET", r"/api/me")
def h_me(req, conn, body):
    user = req.user()
    return {"user": user, "memberships": security.memberships(conn, user["id"])}


@route("GET", r"/api/health")
def h_health(req, conn, body):
    fc.load_model()
    return {"status": "ok", "model": "loaded"}


# ------------------------------------------------------------------ finance (owner, accountant)
def biz(req, conn, bid, perm="view_finance"):
    user = req.user()
    role = security.require(conn, user, int(bid), perm)
    return user, int(bid), role


@route("GET", r"/api/businesses/(\d+)/summary")
def h_summary(req, conn, body, bid):
    user, bid, role = biz(req, conn, bid)
    return {"role": role, "summary": fe.financial_summary(conn, bid)}


@route("GET", r"/api/businesses/(\d+)/history")
def h_history(req, conn, body, bid):
    biz(req, conn, bid)
    rows = fe.weekly(conn, bid, 52)
    return {"weeks": [{k: r[k] for k in ("week_start", "sales", "cash_balance")} for r in rows]}


@route("GET", r"/api/businesses/(\d+)/forecast")
def h_forecast(req, conn, body, bid):
    biz(req, conn, bid)
    return fc.forecast_sales(conn, bid)


@route("GET", r"/api/businesses/(\d+)/cash")
def h_cash(req, conn, body, bid):
    biz(req, conn, bid)
    return fe.cash_outlook(conn, bid, fc.forecast_sales(conn, bid))


@route("GET", r"/api/businesses/(\d+)/benchmark")
def h_benchmark(req, conn, body, bid):
    biz(req, conn, bid)
    return benchmark.compare_with_peers(conn, int(bid))


@route("POST", r"/api/businesses/(\d+)/scenario")
def h_scenario(req, conn, body, bid):
    user, bid, _ = biz(req, conn, bid, "run_agent")
    allowed = {"sales_change_pct", "purchase_cost_change_pct", "extra_monthly_fixed", "one_time_cost",
               "loan_amount", "loan_annual_rate", "loan_months"}
    if set(body) - allowed:
        raise HttpError(400, f"Unknown fields: {sorted(set(body) - allowed)}")
    r = agent.call_tool(agent.Ctx(conn, user, bid, "ui"), "run_scenario", body)
    if r["status"] != "executed":
        raise HttpError(400, r.get("error") or r.get("message"))
    return r["result"]


@route("GET", r"/api/businesses/(\d+)/financing")
def h_financing(req, conn, body, bid):
    biz(req, conn, bid)
    q = req.query()
    try:
        amount = float(q.get("amount", ["200000"])[0])
    except ValueError:
        raise HttpError(400, "amount must be a number")
    by = q.get("by", [None])[0]
    if by:
        date.fromisoformat(by)
    return financing.match_financing(conn, bid, amount, by)


@route("GET", r"/api/businesses/(\d+)/receivables")
def h_receivables(req, conn, body, bid):
    biz(req, conn, bid)
    return {"receivables": db.rows(conn.execute(
        "SELECT id, customer_name, amount, due_date, status, note FROM receivables WHERE business_id = ? "
        "ORDER BY due_date", (bid,)))}


@route("GET", r"/api/businesses/(\d+)/payables")
def h_payables(req, conn, body, bid):
    biz(req, conn, bid)
    return {"payables": db.rows(conn.execute(
        "SELECT id, counterparty, description, amount, due_date, category, flexible, status FROM payables "
        "WHERE business_id = ? ORDER BY due_date", (bid,)))}


@route("POST", r"/api/businesses/(\d+)/records")
def h_add_record(req, conn, body, bid):
    user, bid, _ = biz(req, conn, bid, "edit_records")
    ws = body.get("week_start")
    try:
        d = date.fromisoformat(ws)
    except (TypeError, ValueError):
        raise HttpError(400, "week_start must be a date like 2026-10-19")
    if d.weekday() != 0:
        raise HttpError(400, "week_start must be a Monday")
    last = conn.execute("SELECT MAX(week_start) AS w FROM weekly_records WHERE business_id = ?", (bid,)).fetchone()["w"]
    if last and ws <= last:
        raise HttpError(409, "Past weeks cannot be overwritten. Records are append-only for audit integrity.")
    vals = []
    for f in RECORD_FIELDS:
        v = body.get(f, 0)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise HttpError(400, f"{f} must be a number")
        if f != "cash_balance" and not 0 <= v <= 1e9:
            raise HttpError(400, f"{f} must be between 0 and 100 crore")
        vals.append(float(v))
    rec = dict(zip(RECORD_FIELDS, vals))
    if abs(rec["cash_sales"] + rec["credit_sales"] - rec["sales"]) > 1:
        raise HttpError(400, "cash_sales + credit_sales must equal sales")
    conn.execute(f"INSERT INTO weekly_records (business_id, week_start, {','.join(RECORD_FIELDS)}) "
                 f"VALUES (?,?,{','.join('?' * len(RECORD_FIELDS))})", [bid, ws] + vals)
    conn.commit()
    audit.log(conn, user["id"], bid, "record_added", {"week_start": ws})
    return {"ok": True, "week_start": ws}


# ------------------------------------------------------------------ agent
@route("POST", r"/api/businesses/(\d+)/agent/check")
def h_agent_check(req, conn, body, bid):
    user, bid, _ = biz(req, conn, bid, "run_agent")
    lang = body.get("language", "en")
    if lang not in ("en", "bn"):
        raise HttpError(400, "language must be en or bn")
    return agent.run_cash_check(agent.Ctx(conn, user, bid), lang)


@route("POST", r"/api/businesses/(\d+)/agent/chat")
def h_agent_chat(req, conn, body, bid):
    user, bid, _ = biz(req, conn, bid, "run_agent")
    return agent.chat(agent.Ctx(conn, user, bid), body.get("message"))


@route("POST", r"/api/businesses/(\d+)/agent/tool")
def h_agent_tool(req, conn, body, bid):
    """Direct tool call (used by the UI buttons and by the tests). Same gateway as the agent."""
    user = req.user()
    name, params = body.get("tool"), body.get("params", {})
    if not isinstance(name, str):
        raise HttpError(400, "tool is required")
    return agent.call_tool(agent.Ctx(conn, user, int(bid), "ui"), name, params)


@route("GET", r"/api/businesses/(\d+)/actions")
def h_actions(req, conn, body, bid):
    biz(req, conn, bid, "run_agent")
    status = req.query().get("status", [None])[0]
    return {"actions": agent.list_actions(conn, int(bid), status)}


@route("POST", r"/api/actions/(\d+)/(approve|reject)")
def h_decide(req, conn, body, aid, verb):
    return agent.decide(conn, req.user(), int(aid), verb == "approve")


@route("GET", r"/api/businesses/(\d+)/outbox")
def h_outbox(req, conn, body, bid):
    biz(req, conn, bid, "view_outbox")
    return {"outbox": db.rows(conn.execute("SELECT * FROM outbox WHERE business_id = ? ORDER BY id DESC", (int(bid),)))}


@route("GET", r"/api/businesses/(\d+)/audit")
def h_audit(req, conn, body, bid):
    biz(req, conn, bid, "view_audit")
    return {"chain": audit.verify_chain(conn), "entries": audit.recent(conn, int(bid), 100)}


# ------------------------------------------------------------------ lender
@route("GET", r"/api/lender/reports")
def h_lender_reports(req, conn, body):
    user = req.user()
    rows = db.rows(conn.execute(
        "SELECT s.id, s.business_id, b.name AS business_name, s.report_json, s.created_at FROM shared_reports s "
        "JOIN businesses b ON b.id = s.business_id WHERE s.lender_user_id = ? ORDER BY s.id DESC", (user["id"],)))
    for r in rows:
        r["report"] = json.loads(r.pop("report_json"))
    audit.log(conn, user["id"], None, "lender_reports_viewed", {"count": len(rows)})
    return {"reports": rows}


# ------------------------------------------------------------------ HTTP plumbing
class Handler(BaseHTTPRequestHandler):
    server_version = "HishabAI/1.0"
    sys_version = ""

    def log_message(self, fmt, *args):
        if os.environ.get("HISHAB_QUIET") != "1":
            super().log_message(fmt, *args)

    def token(self):
        h = self.headers.get("Authorization", "")
        return h[7:] if h.startswith("Bearer ") else ""

    def user(self):
        return security.user_from_token(self.conn, self.token())

    def query(self):
        return parse_qs(urlparse(self.path).query)

    def send(self, status, payload, content_type="application/json; charset=utf-8"):
        data = payload if isinstance(payload, bytes) else json.dumps(payload, default=str, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def handle_any(self, method):
        path = urlparse(self.path).path
        if method == "GET" and path in STATIC_FILES:
            name, ctype = STATIC_FILES[path]
            with open(os.path.join(STATIC_DIR, name), "rb") as f:
                return self.send(200, f.read(), ctype)
        self.conn = db.connect(self.server.db_path)
        try:
            body = {}
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                if n > MAX_BODY:
                    raise HttpError(413, "Request body too large")
                if n:
                    if "application/json" not in (self.headers.get("Content-Type") or ""):
                        raise HttpError(415, "Content-Type must be application/json")
                    try:
                        body = json.loads(self.rfile.read(n))
                    except json.JSONDecodeError:
                        raise HttpError(400, "Invalid JSON")
                    if not isinstance(body, dict):
                        raise HttpError(400, "JSON body must be an object")
            for m, rx, fn in ROUTES:
                if m == method:
                    mt = rx.match(path)
                    if mt:
                        return self.send(200, fn(self, self.conn, body, *mt.groups()))
            raise HttpError(404, "Not found")
        except HttpError as e:
            self.send(e.status, {"error": str(e)})
        except security.AuthError as e:
            self.send(401, {"error": str(e)})
        except security.PermissionDenied as e:
            self.send(403, {"error": str(e)})
        except (KeyError, LookupError) as e:
            self.send(404, {"error": str(e).strip("'\"")})
        except (ValueError, agent.ToolError) as e:
            self.send(400, {"error": str(e)})
        except Exception:  # never leak internals to the client
            traceback.print_exc()
            self.send(500, {"error": "Internal error. It has been logged."})
        finally:
            self.conn.close()

    def do_GET(self):
        self.handle_any("GET")

    def do_POST(self):
        self.handle_any("POST")


def make_server(db_path=None, host="127.0.0.1", port=8000):
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.db_path = db_path or db.DEFAULT_DB
    return srv


def main():
    host = os.environ.get("HISHAB_HOST", "127.0.0.1")
    port = int(os.environ.get("HISHAB_PORT", "8000"))
    if not os.path.exists(db.DEFAULT_DB):
        print("No database found, creating one from the synthetic data...")
        conn = db.connect()
        db.seed(conn)
        conn.close()
    fc.load_model()
    srv = make_server(host=host, port=port)
    mode = "LLM (Anthropic API)" if os.environ.get("ANTHROPIC_API_KEY") else "offline rule-based agent"
    print(f"HishabAI running at http://{host}:{port}  (agent mode: {mode})  Ctrl+C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
