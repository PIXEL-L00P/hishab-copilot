"""Tamper-evident audit log (hash chain).

Each entry stores SHA-256(prev_hash + its own content). Editing or deleting any past row
breaks the chain, which `verify_chain` detects.
"""
import hashlib
import json
from datetime import datetime, timezone

GENESIS = "0" * 64


def _digest(prev_hash, ts, user_id, business_id, event, detail_json):
    payload = json.dumps([prev_hash, ts, user_id, business_id, event, detail_json], ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def log(conn, user_id, business_id, event: str, detail: dict):
    last = conn.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    prev = last["hash"] if last else GENESIS
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    detail_json = json.dumps(detail, default=str, ensure_ascii=False, sort_keys=True)
    h = _digest(prev, ts, user_id, business_id, event, detail_json)
    conn.execute("INSERT INTO audit_log (ts, user_id, business_id, event, detail_json, prev_hash, hash) "
                 "VALUES (?,?,?,?,?,?,?)", (ts, user_id, business_id, event, detail_json, prev, h))
    conn.commit()
    return h


def verify_chain(conn) -> dict:
    prev = GENESIS
    n = 0
    for r in conn.execute("SELECT * FROM audit_log ORDER BY id"):
        expected = _digest(prev, r["ts"], r["user_id"], r["business_id"], r["event"], r["detail_json"])
        if r["prev_hash"] != prev or r["hash"] != expected:
            return {"valid": False, "broken_at_id": r["id"], "entries_checked": n}
        prev = r["hash"]
        n += 1
    return {"valid": True, "entries_checked": n}


def recent(conn, business_id: int, limit: int = 50):
    return [dict(r) for r in conn.execute(
        "SELECT id, ts, user_id, event, detail_json FROM audit_log WHERE business_id = ? "
        "ORDER BY id DESC LIMIT ?", (business_id, limit))]
