"""Authentication, sessions and role-based access control.

* Passwords: PBKDF2-HMAC-SHA256, 200,000 iterations, random 16-byte salt.
* Sessions: random 256-bit tokens; only their SHA-256 hash is stored; 8-hour expiry.
* Brute force: 5 failed logins lock the account for 15 minutes.
* Access: every business-scoped call checks the caller's membership role.
"""
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

PBKDF2_ITERATIONS = 200_000
SESSION_HOURS = 8
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15

# What each role may do on a business it belongs to.
ROLE_PERMISSIONS = {
    "owner": {"view_finance", "edit_records", "run_agent", "request_actions", "approve_actions",
              "view_audit", "view_outbox"},
    "accountant": {"view_finance", "edit_records", "run_agent"},
    "lender": {"view_shared_reports"},
}


class AuthError(Exception):
    """Authentication failed (HTTP 401)."""


class PermissionDenied(Exception):
    """Authenticated but not allowed (HTTP 403)."""


def _now():
    return datetime.now(timezone.utc)


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def hash_password(password: str, salt: str = None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), PBKDF2_ITERATIONS)
    return digest.hex(), salt


def validate_password_strength(password: str):
    if len(password) < 10 or password.lower() == password or not any(c.isdigit() for c in password):
        raise ValueError("Password must be at least 10 characters with an upper-case letter and a digit.")


def create_user(conn, username, full_name, password) -> int:
    validate_password_strength(password)
    h, salt = hash_password(password)
    cur = conn.execute("INSERT INTO users (username, full_name, password_hash, salt) VALUES (?,?,?,?)",
                       (username, full_name, h, salt))
    conn.commit()
    return cur.lastrowid


def login(conn, username: str, password: str) -> str:
    from app import audit
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if row is None:
        hash_password(password)  # spend the same time so usernames can't be probed by timing
        audit.log(conn, None, None, "login_failed", {"username": username, "reason": "unknown_user"})
        raise AuthError("Invalid username or password.")
    if row["locked_until"] and row["locked_until"] > _iso(_now()):
        audit.log(conn, row["id"], None, "login_blocked_locked", {"username": username})
        raise AuthError("Account temporarily locked after repeated failed logins. Try again later.")
    h, _ = hash_password(password, row["salt"])
    if not hmac.compare_digest(h, row["password_hash"]):
        failed = row["failed_logins"] + 1
        locked = _iso(_now() + timedelta(minutes=LOCK_MINUTES)) if failed >= MAX_FAILED_LOGINS else None
        conn.execute("UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?",
                     (0 if locked else failed, locked, row["id"]))
        conn.commit()
        audit.log(conn, row["id"], None, "login_failed",
                  {"username": username, "failed_count": failed, "locked": bool(locked)})
        raise AuthError("Invalid username or password.")
    conn.execute("UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", (row["id"],))
    token = secrets.token_urlsafe(32)
    conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?,?,?)",
                 (hashlib.sha256(token.encode()).hexdigest(), row["id"],
                  _iso(_now() + timedelta(hours=SESSION_HOURS))))
    conn.commit()
    audit.log(conn, row["id"], None, "login_success", {"username": username})
    return token


def logout(conn, token: str):
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
    conn.commit()


def user_from_token(conn, token: str) -> dict:
    if not token:
        raise AuthError("Missing session token.")
    row = conn.execute(
        "SELECT u.id, u.username, u.full_name, s.expires_at FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if row is None or row["expires_at"] <= _iso(_now()):
        raise AuthError("Session expired or invalid. Please log in again.")
    return {"id": row["id"], "username": row["username"], "full_name": row["full_name"]}


def memberships(conn, user_id: int):
    return [dict(r) for r in conn.execute(
        "SELECT m.business_id, m.role, b.name FROM memberships m JOIN businesses b ON b.id = m.business_id "
        "WHERE m.user_id = ? ORDER BY m.business_id", (user_id,))]


def role_for(conn, user_id: int, business_id: int):
    row = conn.execute("SELECT role FROM memberships WHERE user_id = ? AND business_id = ?",
                       (user_id, business_id)).fetchone()
    return row["role"] if row else None


def require(conn, user: dict, business_id: int, permission: str) -> str:
    """Raise PermissionDenied unless the user holds `permission` on `business_id`. Returns the role."""
    from app import audit
    role = role_for(conn, user["id"], business_id)
    if role is None or permission not in ROLE_PERMISSIONS[role]:
        audit.log(conn, user["id"], business_id, "access_denied",
                  {"permission": permission, "role": role})
        raise PermissionDenied(f"Your role ({role or 'none'}) is not allowed to {permission.replace('_', ' ')} "
                               f"for this business.")
    return role
