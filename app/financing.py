"""Financing-option matcher.

For a financing need it checks every product in the catalogue against explicit eligibility
rules, computes the instalment and the resulting debt-service coverage ratio (DSCR), and ranks
eligible options by speed (can the money arrive before the shortfall?) and then by cost.
The catalogue terms are illustrative (see app/db.py); the logic is what this module provides.
"""
from datetime import date

from app.finance_engine import DSCR_MIN, amortized_payment, financial_summary, fmt_bdt


def months_operating(founded: str, as_of: date) -> int:
    f = date.fromisoformat(founded)
    return (as_of.year - f.year) * 12 + as_of.month - f.month


def match_financing(conn, business_id: int, need_amount: float, needed_by_date: str = None,
                    include_supplier_credit: bool = True) -> dict:
    if need_amount <= 0 or need_amount > 100_000_000:
        raise ValueError("need_amount must be between 1 and 10 crore taka")
    s = financial_summary(conn, business_id)
    b = conn.execute("SELECT * FROM businesses WHERE id = ?", (business_id,)).fetchone()
    as_of = date.fromisoformat(s["as_of_week"])
    days_available = (date.fromisoformat(needed_by_date) - as_of).days if needed_by_date else None
    months = months_operating(b["founded"], as_of)
    monthly_rev = s["avg_monthly_sales_12w"]
    op_cash = s["operating_cash_flow_monthly"]
    existing_debt = s["debt_service_monthly"]
    flexible_supplier = sum(r["amount"] for r in conn.execute(
        "SELECT amount FROM payables WHERE business_id = ? AND status = 'open' AND flexible = 1 "
        "AND category = 'supplier'", (business_id,)))
    results = []
    for p in conn.execute("SELECT * FROM financing_products ORDER BY id"):
        p = dict(p)
        reasons_fail, reasons_ok = [], []
        amount = min(max(need_amount, p["min_amount"]), p["max_amount"])
        if p["provider_type"] == "supplier":
            # an extension can only cover bills the business actually owes its suppliers
            if flexible_supplier <= 0 or not include_supplier_credit:
                continue
            amount = min(need_amount, flexible_supplier)
            p["max_amount"] = flexible_supplier
        if need_amount > p["max_amount"]:
            reasons_fail.append(f"covers at most {fmt_bdt(p['max_amount'])} of the {fmt_bdt(need_amount)} needed")
        if months < p["min_months_operating"]:
            reasons_fail.append(f"needs {p['min_months_operating']} months in business (has {months})")
        else:
            reasons_ok.append(f"{months} months in business")
        if monthly_rev < p["min_monthly_revenue"]:
            reasons_fail.append(f"needs monthly sales of {fmt_bdt(p['min_monthly_revenue'])} "
                                f"(has {fmt_bdt(monthly_rev)})")
        if p["collateral_required"] and not b["has_collateral"]:
            reasons_fail.append("requires collateral, which the business has not listed")
        if p["trade_license_required"] and not b["has_trade_license"]:
            reasons_fail.append("requires a valid trade licence")
        if p["women_only"]:
            if b["owner_is_woman"]:
                reasons_ok.append("women-led business qualifies for the concessional scheme")
            else:
                reasons_fail.append("only for women-led businesses")
        rate = (p["rate_min"] + p["rate_max"]) / 2
        instalment = amortized_payment(amount, rate, p["tenure_months"])
        if p["provider_type"] == "supplier":
            dscr = None   # an extension defers an existing bill; it adds no new debt service
            instalment = 0.0
            reasons_ok.append("defers existing supplier bills (timing help only, the bill still has to be paid)")
        else:
            dscr = op_cash / (existing_debt + instalment) if (existing_debt + instalment) > 0 else None
            if dscr is not None and dscr < DSCR_MIN:
                reasons_fail.append(f"repayments would take too much of cash flow (DSCR {dscr:.2f} < {DSCR_MIN})")
            elif dscr is not None:
                reasons_ok.append(f"affordable: DSCR {dscr:.2f} (≥ {DSCR_MIN})")
        fast_enough = days_available is None or p["processing_days"] <= max(days_available, 0)
        results.append({
            "product_id": p["id"], "name": p["name"], "provider_type": p["provider_type"],
            "eligible": not reasons_fail, "fast_enough": fast_enough, "amount": round(amount),
            "indicative_rate": f"{p['rate_min']*100:.0f}–{p['rate_max']*100:.0f}% per year",
            "tenure_months": p["tenure_months"], "monthly_instalment": round(instalment),
            "total_interest": 0 if p["provider_type"] == "supplier" else round(instalment * p["tenure_months"] - amount),
            "dscr_after": round(dscr, 2) if dscr is not None else None,
            "processing_days": p["processing_days"], "why_eligible": reasons_ok, "why_not": reasons_fail,
            "notes": p["notes"]})
    results.sort(key=lambda r: (not r["eligible"], not r["fast_enough"],
                                r["total_interest"] if r["provider_type"] != "supplier" else -1))
    return {"need_amount": round(need_amount), "needed_by": needed_by_date, "days_available": days_available,
            "business_months_operating": months, "avg_monthly_sales": monthly_rev,
            "monthly_operating_cash_flow": op_cash, "existing_debt_service": existing_debt,
            "options": results,
            "disclaimer": "Product terms are illustrative for this prototype. Final eligibility and pricing are "
                          "decided by the lender; HishabAI does not approve or submit loans."}


def _peer_context(conn, business_id):
    from app import benchmark
    return benchmark.lender_peer_context(conn, business_id)


def loan_readiness_report(conn, business_id: int, forecast: dict = None) -> dict:
    """Structured summary a lender can review. Drafted by the agent; shared only with owner approval."""
    s = financial_summary(conn, business_id)
    rows = [dict(r) for r in conn.execute(
        "SELECT substr(week_start,1,7) AS month, SUM(sales) AS sales, SUM(stock_purchases) AS purchases, "
        "SUM(owner_injection) AS injections FROM weekly_records WHERE business_id = ? GROUP BY month "
        "ORDER BY month DESC LIMIT 12", (business_id,))]
    rows.reverse()
    return {"report_type": "loan_readiness_summary", "business": s["business"], "as_of": s["as_of_week"],
            "key_figures": {k: s[k] for k in ("avg_monthly_sales_12w", "gross_margin_estimate", "fixed_costs_monthly",
                                              "operating_cash_flow_monthly", "debt_service_monthly", "dscr",
                                              "cash_balance", "receivables_open", "receivables_overdue",
                                              "payables_open", "owner_cash_injections_52w", "sales_growth_yoy_12w")},
            "monthly_history": [{"month": r["month"], "sales": round(r["sales"]),
                                 "stock_purchases": round(r["purchases"])} for r in rows],
            "forecast_next_8_weeks": [{"week_start": w["week_start"], "expected_sales": w["p50"],
                                       "range": [w["low"], w["high"]]} for w in (forecast or {}).get("weeks", [])],
            "peer_comparison": _peer_context(conn, business_id),
            "data_provenance": "Self-reported records entered in HishabAI (synthetic demo data). Not audited.",
            "limitations": ["Figures are not audited financial statements.",
                            "Forecasts are estimates with an 80% uncertainty band, not guarantees.",
                            "This report does not constitute a credit decision."]}
