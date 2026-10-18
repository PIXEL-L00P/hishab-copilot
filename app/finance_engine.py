"""Deterministic financial engine.

All numbers the copilot reports come from here (or from the forecast model), never from
the language model. Every formula is explicit so results can be audited and unit-tested.
"""
from datetime import date, timedelta

import numpy as np

from app.calendar_bd import festival_in_week

COLLECTION_PROB_CURRENT = 0.85   # chance an open, not-yet-overdue customer due is paid on time
COLLECTION_PROB_OVERDUE = 0.50   # chance an overdue customer due is paid next week
CREDIT_LAG_WEEKS = 3             # credit (baki) sales are collected about three weeks later
DSCR_MIN = 1.25                  # debt-service coverage lenders typically look for


def fmt_bdt(x) -> str:
    """Format taka with South-Asian digit grouping: 1234567 -> ৳12,34,567."""
    neg = x < 0
    s = str(int(round(abs(x))))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return ("-" if neg else "") + "৳" + s


def amortized_payment(principal: float, annual_rate: float, months: int) -> float:
    """Equal monthly instalment for a reducing-balance loan."""
    if months <= 0:
        raise ValueError("months must be positive")
    r = annual_rate / 12
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** -months)


def is_first_week_of_month(ws: date) -> bool:
    return ws.day <= 7


def week_contains_day(ws: date, day: int) -> bool:
    for i in range(7):
        d = ws + timedelta(days=i)
        if d.day == day:
            return True
    return False


def week_index_of(d: date, first_week: date) -> int:
    """1-based projection week that contains date d (0 or less = before the projection)."""
    return (d - first_week).days // 7 + 1


def load_business(conn, business_id: int) -> dict:
    b = conn.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
    if b is None:
        raise KeyError("Business not found")
    return dict(b)


def weekly(conn, business_id: int, n: int = None):
    q = "SELECT * FROM weekly_records WHERE business_id = ? ORDER BY week_start"
    rows = [dict(r) for r in conn.execute(q, (business_id,))]
    return rows[-n:] if n else rows


def profile_params(conn, business_id: int) -> dict:
    """Behavioural parameters estimated from the business's own history."""
    rows = weekly(conn, business_id)
    if not rows:
        raise ValueError("No financial records for this business yet.")
    last12, last52 = rows[-12:], rows[-52:]
    sales12 = sum(r["sales"] for r in last12)
    sales52 = sum(r["sales"] for r in last52)
    b = load_business(conn, business_id)
    loans = [dict(r) for r in conn.execute("SELECT * FROM loans WHERE business_id = ?", (business_id,))]
    return {
        "credit_share": sum(r["credit_sales"] for r in last12) / sales12 if sales12 else 0.0,
        "purchase_ratio": sum(r["stock_purchases"] for r in last52) / sales52 if sales52 else 0.0,
        "weekly_util_other": float(np.mean([r["utilities"] + r["other_expenses"] for r in last12])),
        "monthly_rent": b["monthly_rent"],
        "monthly_salaries": b["monthly_salaries"],
        "loans": loans,
        "last_week": date.fromisoformat(rows[-1]["week_start"]),
        "cash": rows[-1]["cash_balance"],
        "safety_buffer": round(0.5 * (b["monthly_rent"] + b["monthly_salaries"]), -3),
    }


def financial_summary(conn, business_id: int) -> dict:
    rows = weekly(conn, business_id)
    if not rows:
        raise ValueError("No financial records for this business yet.")
    b = load_business(conn, business_id)
    p = profile_params(conn, business_id)
    last4, last12, last52 = rows[-4:], rows[-12:], rows[-52:]

    def total(rs, k):
        return float(sum(r[k] for r in rs))

    gross_margin = 1 - p["purchase_ratio"]
    fixed_monthly = b["monthly_rent"] + b["monthly_salaries"] + p["weekly_util_other"] * 4.33
    op_cash_26 = [r["cash_sales"] + r["receivables_collected"] - r["stock_purchases"] - r["rent"] - r["salaries"]
                  - r["festival_bonus"] - r["utilities"] - r["other_expenses"] for r in rows[-26:]]
    monthly_op_cash = float(np.mean(op_cash_26)) * 4.33
    monthly_debt = sum(l["monthly_installment"] for l in p["loans"])
    as_of = p["last_week"] + timedelta(weeks=1)
    recv = [dict(r) for r in conn.execute(
        "SELECT * FROM receivables WHERE business_id = ? AND status = 'open'", (business_id,))]
    overdue = [r for r in recv if date.fromisoformat(r["due_date"]) < as_of]
    pay = [dict(r) for r in conn.execute(
        "SELECT * FROM payables WHERE business_id = ? AND status IN ('open','extension_requested')",
        (business_id,))]
    yoy = None
    if len(rows) >= 64:
        prev = sum(r["sales"] for r in rows[-64:-52])
        yoy = total(last12, "sales") / prev - 1 if prev else None
    avg_weekly_out = float(np.mean([r["stock_purchases"] + r["rent"] + r["salaries"] + r["utilities"]
                                    + r["other_expenses"] + r["loan_repayment"] for r in last12]))
    return {
        "business": {k: b[k] for k in ("id", "name", "category", "district", "area", "founded", "staff")},
        "as_of_week": as_of.isoformat(),
        "cash_balance": round(p["cash"]),
        "sales_last_4_weeks": round(total(last4, "sales")),
        "sales_last_12_weeks": round(total(last12, "sales")),
        "sales_last_52_weeks": round(total(last52, "sales")),
        "sales_growth_yoy_12w": round(yoy, 4) if yoy is not None else None,
        "gross_margin_estimate": round(gross_margin, 4),
        "fixed_costs_monthly": round(fixed_monthly),
        "break_even_monthly_sales": round(fixed_monthly / gross_margin) if gross_margin > 0 else None,
        "avg_monthly_sales_12w": round(total(last12, "sales") / 12 * 4.33),
        "operating_cash_flow_monthly": round(monthly_op_cash),
        "debt_service_monthly": round(monthly_debt),
        "dscr": round(monthly_op_cash / monthly_debt, 2) if monthly_debt else None,
        "cash_runway_weeks": round(p["cash"] / avg_weekly_out, 1) if avg_weekly_out else None,
        "receivables_open": round(sum(r["amount"] for r in recv)),
        "receivables_overdue": round(sum(r["amount"] for r in overdue)),
        "overdue_customers": len(overdue),
        "payables_open": round(sum(r["amount"] for r in pay)),
        "owner_cash_injections_52w": int(sum(1 for r in last52 if r["owner_injection"] > 0)),
        "credit_sales_share": round(p["credit_share"], 4),
        "safety_buffer": p["safety_buffer"],
    }


def project_cash(conn, business_id: int, forecast: dict, which: str = "p50", sales_multiplier: float = 1.0,
                 purchase_multiplier: float = 1.0, payable_overrides: dict = None, extra_monthly_fixed: float = 0.0,
                 one_time_cost: float = 0.0, new_loan: dict = None) -> dict:
    """Week-by-week cash projection.

    inflow  = cash sales + collections of new credit sales (3-week lag) + expected collections of open dues
              (+ new loan disbursement in a scenario)
    outflow = routine stock purchases (historic purchase/sales ratio) + rent & salaries (first week of month)
              + festival bonus (week before Eid) + utilities/other + loan instalments + committed payables
              (+ scenario costs)
    """
    p = profile_params(conn, business_id)
    overrides = payable_overrides or {}
    weeks = forecast["weeks"]
    first = date.fromisoformat(weeks[0]["week_start"])
    sales = [w[which] * sales_multiplier for w in weeks]

    recv = [dict(r) for r in conn.execute(
        "SELECT * FROM receivables WHERE business_id = ? AND status = 'open'", (business_id,))]
    pays = [dict(r) for r in conn.execute(
        "SELECT * FROM payables WHERE business_id = ? AND status IN ('open','extension_requested')",
        (business_id,))]

    loan_payment_new = 0.0
    if new_loan:
        loan_payment_new = amortized_payment(new_loan["amount"], new_loan["annual_rate"], new_loan["months"])

    cash = p["cash"]
    out = []
    for i, ws_s in enumerate(weeks):
        wk = i + 1
        ws = date.fromisoformat(ws_s["week_start"])
        s = sales[i]
        inflow = {"cash_sales": (1 - p["credit_share"]) * s,
                  "credit_collections": p["credit_share"] * sales[i - CREDIT_LAG_WEEKS] if i >= CREDIT_LAG_WEEKS else 0.0,
                  "receivables": 0.0, "loan_disbursement": 0.0}
        for r in recv:
            due = date.fromisoformat(r["due_date"])
            idx = week_index_of(due, first)
            if idx < 1 and wk == 1:
                inflow["receivables"] += COLLECTION_PROB_OVERDUE * r["amount"]
            elif idx == wk:
                inflow["receivables"] += COLLECTION_PROB_CURRENT * r["amount"]
        if new_loan and wk == 1:
            inflow["loan_disbursement"] = new_loan["amount"]
        outflow = {"stock_purchases": p["purchase_ratio"] * purchase_multiplier * s,
                   "rent_salaries": 0.0, "festival_bonus": 0.0, "utilities_other": p["weekly_util_other"],
                   "loan_instalments": 0.0, "payables": 0.0, "scenario_costs": 0.0}
        if is_first_week_of_month(ws):
            outflow["rent_salaries"] = p["monthly_rent"] + p["monthly_salaries"]
            outflow["scenario_costs"] += extra_monthly_fixed
            if new_loan and wk > 4:
                outflow["loan_instalments"] += loan_payment_new
        if festival_in_week(ws):
            outflow["festival_bonus"] = p["monthly_salaries"]
        for l in p["loans"]:
            if week_contains_day(ws, int(l["due_day"])):
                outflow["loan_instalments"] += l["monthly_installment"]
        for pay in pays:
            due = date.fromisoformat(overrides.get(pay["id"], pay["due_date"]))
            idx = max(week_index_of(due, first), 1)
            if idx == wk:
                outflow["payables"] += pay["amount"]
        if wk == 1:
            outflow["scenario_costs"] += one_time_cost
        opening = cash
        cash = opening + sum(inflow.values()) - sum(outflow.values())
        out.append({"week": wk, "week_start": ws.isoformat(), "sales": round(s), "opening_cash": round(opening),
                    "inflow": {k: round(v) for k, v in inflow.items()},
                    "outflow": {k: round(v) for k, v in outflow.items()},
                    "total_in": round(sum(inflow.values())), "total_out": round(sum(outflow.values())),
                    "closing_cash": round(cash)})
    closing = [w["closing_cash"] for w in out]
    min_cash = min(closing)
    min_week = out[closing.index(min_cash)]
    neg = [w for w in out if w["closing_cash"] < 0]
    below = [w for w in out if w["closing_cash"] < p["safety_buffer"]]
    return {"scenario": which, "starting_cash": round(p["cash"]), "safety_buffer": p["safety_buffer"],
            "weeks": out, "min_cash": min_cash, "min_cash_week": min_week["week"],
            "min_cash_week_start": min_week["week_start"],
            "first_negative_week": neg[0]["week"] if neg else None,
            "first_below_buffer_week": below[0]["week"] if below else None}


def cash_outlook(conn, business_id: int, forecast: dict, payable_overrides: dict = None) -> dict:
    """Expected (P50) and pessimistic (low-sales) projections plus an alert level."""
    base = project_cash(conn, business_id, forecast, "p50", payable_overrides=payable_overrides)
    low = project_cash(conn, business_id, forecast, "low", payable_overrides=payable_overrides)
    if base["min_cash"] < 0:
        level = "critical"
    elif base["min_cash"] < base["safety_buffer"] or low["min_cash"] < 0:
        level = "warning"
    else:
        level = "healthy"
    return {"alert_level": level, "expected": base, "pessimistic": low}


def run_scenario(conn, business_id: int, forecast: dict, sales_change_pct: float = 0.0,
                 purchase_cost_change_pct: float = 0.0, extra_monthly_fixed: float = 0.0,
                 one_time_cost: float = 0.0, loan_amount: float = 0.0, loan_annual_rate: float = 0.12,
                 loan_months: int = 12) -> dict:
    """What-if analysis: compare the expected cash path with a changed one."""
    for name, v in [("sales_change_pct", sales_change_pct), ("purchase_cost_change_pct", purchase_cost_change_pct)]:
        if not -90 <= v <= 300:
            raise ValueError(f"{name} must be between -90 and 300 percent")
    for name, v in [("extra_monthly_fixed", extra_monthly_fixed), ("one_time_cost", one_time_cost),
                    ("loan_amount", loan_amount)]:
        if v < 0 or v > 100_000_000:
            raise ValueError(f"{name} must be between 0 and 10 crore taka")
    if loan_amount and not (1 <= loan_months <= 120 and 0 <= loan_annual_rate <= 0.5):
        raise ValueError("loan_months must be 1-120 and loan_annual_rate 0-0.5")
    base = project_cash(conn, business_id, forecast, "p50")
    new_loan = {"amount": loan_amount, "annual_rate": loan_annual_rate, "months": loan_months} if loan_amount else None
    scen = project_cash(conn, business_id, forecast, "p50", sales_multiplier=1 + sales_change_pct / 100,
                        purchase_multiplier=1 + purchase_cost_change_pct / 100,
                        extra_monthly_fixed=extra_monthly_fixed, one_time_cost=one_time_cost, new_loan=new_loan)
    summary = financial_summary(conn, business_id)
    gm = summary["gross_margin_estimate"]
    base_monthly_sales = summary["avg_monthly_sales_12w"]
    new_sales = base_monthly_sales * (1 + sales_change_pct / 100)
    new_gm = 1 - (1 - gm) * (1 + purchase_cost_change_pct / 100)
    base_profit = base_monthly_sales * gm - summary["fixed_costs_monthly"] - summary["debt_service_monthly"]
    loan_pay = amortized_payment(loan_amount, loan_annual_rate, loan_months) if loan_amount else 0.0
    new_profit = (new_sales * new_gm - summary["fixed_costs_monthly"] - extra_monthly_fixed
                  - summary["debt_service_monthly"] - loan_pay)
    return {
        "inputs": {"sales_change_pct": sales_change_pct, "purchase_cost_change_pct": purchase_cost_change_pct,
                   "extra_monthly_fixed": extra_monthly_fixed, "one_time_cost": one_time_cost,
                   "loan_amount": loan_amount, "loan_annual_rate": loan_annual_rate, "loan_months": loan_months},
        "baseline_min_cash": base["min_cash"], "scenario_min_cash": scen["min_cash"],
        "scenario_min_cash_week": scen["min_cash_week"],
        "scenario_first_negative_week": scen["first_negative_week"],
        "baseline_monthly_profit": round(base_profit), "scenario_monthly_profit": round(new_profit),
        "new_loan_monthly_instalment": round(loan_pay),
        "scenario_break_even_monthly_sales": round((summary["fixed_costs_monthly"] + extra_monthly_fixed) / new_gm)
        if new_gm > 0 else None,
        "safety_buffer": base["safety_buffer"],
        "affordable": scen["min_cash"] >= base["safety_buffer"] and new_profit > 0,
        "baseline_weeks": base["weeks"], "scenario_weeks": scen["weeks"],
    }
