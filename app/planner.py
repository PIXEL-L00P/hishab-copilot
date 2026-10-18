"""Payment planner: proposes how to get through a projected cash shortfall.

Algorithm (greedy, deterministic, explainable):
 1. Project cash (P50). Find the first week that closes below the safety buffer.
 2. Among FLEXIBLE open payables due on or before that week (supplier orders, non-essential
    costs; never salaries, rent, tax or loan instalments), pick the largest one not yet moved.
 3. Try moving it 1-4 weeks later (a typical supplier extension). Keep the option that pushes
    the first below-buffer week furthest out (buying time for financing to arrive), then the one
    with the highest minimum cash; ties -> shortest delay.
 4. Repeat until no week is below the buffer or no movable payable is left.
 5. Overdue customer dues become reminder actions (upside, not counted in the plan).
 6. Whatever gap remains becomes a financing need, rounded up to the next ৳10,000.
"""
import math
from datetime import date, timedelta

from app.finance_engine import fmt_bdt, project_cash, week_index_of

MAX_EXTENSION_WEEKS = 4
NON_DEFERRABLE = {"salary", "rent", "tax", "loan", "utility"}


def draft_payment_plan(conn, business_id: int, forecast: dict) -> dict:
    before = project_cash(conn, business_id, forecast, "p50")
    buffer = before["safety_buffer"]
    horizon = len(forecast["weeks"])
    first = date.fromisoformat(forecast["weeks"][0]["week_start"])
    pays = [dict(r) for r in conn.execute(
        "SELECT * FROM payables WHERE business_id = ? AND status = 'open' AND flexible = 1", (business_id,))]
    pays = [p for p in pays if p["category"] not in NON_DEFERRABLE]

    overrides, steps = {}, []
    current = before
    for _ in range(len(pays)):
        problem = current["first_below_buffer_week"]
        if problem is None:
            break
        movable = [p for p in pays if p["id"] not in overrides
                   and week_index_of(date.fromisoformat(p["due_date"]), first) <= problem]
        if not movable:
            break
        pay = max(movable, key=lambda p: p["amount"])
        due = date.fromisoformat(pay["due_date"])
        def key(proj):
            return (proj["first_below_buffer_week"] or horizon + 1, proj["min_cash"])

        best = None
        for k in range(1, MAX_EXTENSION_WEEKS + 1):
            new_due = due + timedelta(weeks=k)
            if week_index_of(new_due, first) > horizon:
                break
            trial = project_cash(conn, business_id, forecast, "p50",
                                 payable_overrides={**overrides, pay["id"]: new_due.isoformat()})
            if best is None or key(trial) > key(best[1]):
                best = (new_due, trial)
        if best is None or key(best[1]) <= key(current):
            overrides[pay["id"]] = pay["due_date"]          # mark as tried, no improvement
            continue
        overrides[pay["id"]] = best[0].isoformat()
        steps.append({"type": "request_supplier_extension", "payable_id": pay["id"],
                      "counterparty": pay["counterparty"], "description": pay["description"],
                      "amount": pay["amount"], "original_due": pay["due_date"], "proposed_due": best[0].isoformat(),
                      "weeks_moved": (best[0] - due).days // 7,
                      "min_cash_after_step": best[1]["min_cash"],
                      "first_problem_week_after_step": best[1]["first_below_buffer_week"],
                      "why": f"Paying {pay['counterparty']} {fmt_bdt(pay['amount'])} on {pay['due_date']} pushes cash "
                             f"below the safety buffer in week {problem}. Asking to pay on {best[0].isoformat()} "
                             + (f"moves the first tight week to week {best[1]['first_below_buffer_week']}"
                                if best[1]["first_below_buffer_week"] else "removes the shortfall")
                             + f" and changes the lowest projected balance from {fmt_bdt(current['min_cash'])} "
                               f"to {fmt_bdt(best[1]['min_cash'])}."})
        current = best[1]

    real_overrides = {s["payable_id"]: s["proposed_due"] for s in steps}
    after = project_cash(conn, business_id, forecast, "p50", payable_overrides=real_overrides)
    as_of = first
    overdue = [dict(r) for r in conn.execute(
        "SELECT id, customer_name, amount, due_date FROM receivables WHERE business_id = ? AND status = 'open' "
        "AND due_date < ? ORDER BY amount DESC", (business_id, as_of.isoformat()))]
    for r in overdue:
        steps.append({"type": "send_payment_reminder", "receivable_id": r["id"], "customer_name": r["customer_name"],
                      "amount": r["amount"], "due_date": r["due_date"],
                      "why": f"{r['customer_name']} owes {fmt_bdt(r['amount'])}, overdue since {r['due_date']}. "
                             f"Collecting it is extra cash not yet counted in the plan."})
    gap = max(0.0, buffer - after["min_cash"])
    need = int(math.ceil(gap / 10_000.0) * 10_000) if gap > 0 else 0
    if need:
        steps.append({"type": "seek_financing", "amount": need, "needed_by_week": after["first_below_buffer_week"],
                      "needed_by_date": after["weeks"][after["first_below_buffer_week"] - 1]["week_start"],
                      "why": f"Even after rescheduling, cash would fall to {fmt_bdt(after['min_cash'])} in week "
                             f"{after['min_cash_week']}. About {fmt_bdt(need)} of short-term financing keeps the "
                             f"balance above the {fmt_bdt(buffer)} safety buffer."})
    return {"status": "draft", "safety_buffer": buffer,
            "before": {"min_cash": before["min_cash"], "min_cash_week": before["min_cash_week"],
                       "first_negative_week": before["first_negative_week"]},
            "after": {"min_cash": after["min_cash"], "min_cash_week": after["min_cash_week"],
                      "first_negative_week": after["first_negative_week"]},
            "payable_overrides": real_overrides, "financing_need": need, "steps": steps,
            "projection_before": before["weeks"], "projection_after": after["weeks"]}
