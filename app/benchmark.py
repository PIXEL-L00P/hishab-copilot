"""Peer benchmarking: how does this shop compare with similar shops?

Privacy by design:
  * Peers = other businesses in the same category and district (never the business itself).
  * Results are released only when at least MIN_PEERS peers exist (k-anonymity).
  * Only aggregates leave this module: peer median, 25th/75th percentiles and the shop's own
    percentile rank. No peer's name, id or individual value is ever returned.

Every tip is a deterministic calculation with a taka figure, e.g. "matching the peer median
margin would add about ৳X per month".
"""
import numpy as np

from app import finance_engine as fe
from app.finance_engine import fmt_bdt

MIN_PEERS = 5

# key, label, higher_is_better, unit
METRICS = [
    ("gross_margin", "Gross margin", True, "pct"),
    ("sales_growth_yoy", "Sales growth vs last year (12 weeks)", True, "pct"),
    ("fixed_cost_ratio", "Rent + salaries + overheads as share of sales", False, "pct"),
    ("overdue_ratio", "Overdue customer dues as share of monthly sales", False, "pct"),
    ("cash_buffer_weeks", "Cash buffer (weeks of spending)", True, "weeks"),
    ("dscr", "Debt-service coverage (DSCR)", True, "x"),
]


def business_metrics(conn, business_id: int) -> dict:
    s = fe.financial_summary(conn, business_id)
    monthly_sales = s["avg_monthly_sales_12w"] or 0
    return {
        "gross_margin": s["gross_margin_estimate"],
        "sales_growth_yoy": s["sales_growth_yoy_12w"],
        "fixed_cost_ratio": s["fixed_costs_monthly"] / monthly_sales if monthly_sales else None,
        "overdue_ratio": s["receivables_overdue"] / monthly_sales if monthly_sales else None,
        "cash_buffer_weeks": s["cash_runway_weeks"],
        "dscr": s["dscr"],                         # None for shops without loans -> excluded from that metric
        "_monthly_sales": monthly_sales,
        "_fixed_costs": s["fixed_costs_monthly"],
        "_overdue": s["receivables_overdue"],
    }


def _percentile_rank(value, peers, higher_is_better):
    """Share of peers this shop does better than (0-100)."""
    peers = np.asarray(peers, dtype=float)
    if higher_is_better:
        better = np.sum(peers < value) + 0.5 * np.sum(peers == value)
    else:
        better = np.sum(peers > value) + 0.5 * np.sum(peers == value)
    return round(100.0 * better / len(peers))


def _fmt(v, unit):
    if v is None:
        return "—"
    if unit == "pct":
        return f"{v * 100:.1f}%"
    if unit == "weeks":
        return f"{v:.1f} weeks"
    return f"{v:.2f}"


def _tip(key, me, median, m):
    """One concrete, quantified suggestion when the shop is behind the peer median."""
    sales = m["_monthly_sales"]
    if key == "gross_margin":
        gain = (median - me) * sales
        return (f"Matching the peer median margin would add about {fmt_bdt(gain)} profit per month. "
                f"Review supplier prices and discounting on slow-moving stock.")
    if key == "fixed_cost_ratio":
        excess = (me - median) * sales
        return (f"Your fixed costs are about {fmt_bdt(excess)} per month above what similar shops carry for "
                f"the same sales. Rent and staffing are the usual places to look.")
    if key == "overdue_ratio":
        excess = (me - median) * sales
        return (f"Bringing overdue dues down to the peer level would free about {fmt_bdt(excess)} of cash. "
                f"Ask the agent to send reminders, and set a credit limit for repeat late payers.")
    if key == "cash_buffer_weeks":
        return "Similar shops hold a larger cash cushion. Keep part of each Eid surplus as a reserve before restocking."
    if key == "sales_growth_yoy":
        return "Sales are growing slower than similar shops. Compare your best-selling lines and prices with the season's demand."
    if key == "dscr":
        return "Loan repayments take a larger share of cash flow than at similar shops. Avoid new debt until this improves."
    return None


def compare_with_peers(conn, business_id: int) -> dict:
    me_row = conn.execute("SELECT category, district FROM businesses WHERE id = ?", (business_id,)).fetchone()
    if me_row is None:
        raise KeyError("Business not found")
    peer_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM businesses WHERE category = ? AND district = ? AND id != ?",
        (me_row["category"], me_row["district"], business_id))]
    group = {"category": me_row["category"], "district": me_row["district"], "peer_count": len(peer_ids)}
    if len(peer_ids) < MIN_PEERS:
        return {"available": False, "peer_group": group,
                "message": f"Not enough similar businesses yet (need at least {MIN_PEERS}) to compare without "
                           f"revealing anyone's data."}
    me = business_metrics(conn, business_id)
    peers = []
    for pid in peer_ids:
        try:
            peers.append(business_metrics(conn, pid))
        except ValueError:          # a peer with no records yet
            continue
    rows, strengths, attention = [], [], []
    for key, label, hib, unit in METRICS:
        vals = [p[key] for p in peers if p[key] is not None]
        mine = me[key]
        if mine is None or len(vals) < MIN_PEERS:
            rows.append({"metric": key, "label": label, "available": False,
                         "reason": "not applicable" if mine is None else "too few peers with this metric"})
            continue
        med = float(np.median(vals))
        q25, q75 = (float(x) for x in np.percentile(vals, [25, 75]))
        rank = _percentile_rank(mine, vals, hib)
        status = "strong" if rank >= 70 else ("attention" if rank < 35 else "average")
        row = {"metric": key, "label": label, "available": True, "unit": unit, "higher_is_better": hib,
               "you": round(mine, 4), "peer_median": round(med, 4), "peer_p25": round(q25, 4),
               "peer_p75": round(q75, 4), "you_display": _fmt(mine, unit), "median_display": _fmt(med, unit),
               "percentile_rank": rank, "status": status, "peers_compared": len(vals)}
        if status == "attention":
            row["tip"] = _tip(key, mine, med, me)
            attention.append(row)
        elif status == "strong":
            strengths.append(row)
        rows.append(row)
    ranks = [r["percentile_rank"] for r in rows if r.get("available")]
    return {"available": True, "peer_group": group, "metrics": rows,
            "overall_percentile": round(float(np.mean(ranks))) if ranks else None,
            "strengths": [r["label"] for r in strengths],
            "needs_attention": [{"label": r["label"], "tip": r["tip"]} for r in attention],
            "privacy": f"Compared with {len(peers)} anonymised similar businesses. Only medians and quartiles "
                       f"are shown; no individual business can be identified.",
            "data_note": "Peer data in this prototype is synthetic."}


def lender_peer_context(conn, business_id: int):
    """Short percentile summary for the loan-readiness report (no peer values beyond rank)."""
    b = compare_with_peers(conn, business_id)
    if not b["available"]:
        return {"available": False, "message": b["message"]}
    return {"available": True, "peer_count": b["peer_group"]["peer_count"],
            "overall_percentile": b["overall_percentile"],
            "metric_percentiles": {r["label"]: r["percentile_rank"] for r in b["metrics"] if r.get("available")}}
