import hashlib
import unittest

from tests.helpers import PASSWORDS, fresh_db, user
from app import audit, security


class Authentication(unittest.TestCase):
    def setUp(self):
        self.path, self.conn = fresh_db()

    def test_passwords_are_salted_hashes(self):
        row = self.conn.execute("SELECT * FROM users WHERE username = 'farhana'").fetchone()
        self.assertNotIn(PASSWORDS["farhana"], row["password_hash"])
        self.assertEqual(len(row["salt"]), 32)
        h, _ = security.hash_password(PASSWORDS["farhana"], row["salt"])
        self.assertEqual(h, row["password_hash"])

    def test_weak_passwords_rejected(self):
        for pw in ["short1A", "alllowercase123", "NoDigitsHere!"]:
            with self.assertRaises(ValueError):
                security.create_user(self.conn, "x" + pw, "X", pw)

    def test_wrong_password_and_unknown_user(self):
        with self.assertRaises(security.AuthError):
            security.login(self.conn, "farhana", "wrong-Password1")
        with self.assertRaises(security.AuthError):
            security.login(self.conn, "nobody", "whatever-Pass1")

    def test_lockout_after_repeated_failures(self):
        for _ in range(security.MAX_FAILED_LOGINS):
            with self.assertRaises(security.AuthError):
                security.login(self.conn, "farhana", "wrong-Password1")
        with self.assertRaises(security.AuthError) as e:
            security.login(self.conn, "farhana", PASSWORDS["farhana"])    # correct password, still locked
        self.assertIn("locked", str(e.exception))

    def test_tokens_stored_only_as_hash_and_expire(self):
        tok = security.login(self.conn, "farhana", PASSWORDS["farhana"])
        stored = [r["token_hash"] for r in self.conn.execute("SELECT token_hash FROM sessions")]
        self.assertNotIn(tok, stored)
        self.assertIn(hashlib.sha256(tok.encode()).hexdigest(), stored)
        self.conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00Z'")
        with self.assertRaises(security.AuthError):
            security.user_from_token(self.conn, tok)
        with self.assertRaises(security.AuthError):
            security.user_from_token(self.conn, "")

    def test_logout_invalidates_token(self):
        tok = security.login(self.conn, "farhana", PASSWORDS["farhana"])
        security.logout(self.conn, tok)
        with self.assertRaises(security.AuthError):
            security.user_from_token(self.conn, tok)


class Authorization(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path, cls.conn = fresh_db()

    def test_role_matrix(self):
        expect = {
            "farhana": {"view_finance": True, "edit_records": True, "request_actions": True, "approve_actions": True,
                        "view_audit": True},
            "rakib": {"view_finance": True, "edit_records": True, "request_actions": False, "approve_actions": False,
                      "view_audit": False},
            "lender_demo": {"view_finance": False, "edit_records": False, "request_actions": False,
                            "approve_actions": False, "view_audit": False},
        }
        for uname, perms in expect.items():
            u = user(self.conn, uname)
            for perm, allowed in perms.items():
                if allowed:
                    security.require(self.conn, u, 1, perm)
                else:
                    with self.assertRaises(security.PermissionDenied, msg=f"{uname} {perm}"):
                        security.require(self.conn, u, 1, perm)

    def test_no_cross_business_access(self):
        owner1 = user(self.conn, "farhana")
        owner2 = user(self.conn, "owner2")
        with self.assertRaises(security.PermissionDenied):
            security.require(self.conn, owner1, 2, "view_finance")
        with self.assertRaises(security.PermissionDenied):
            security.require(self.conn, owner2, 1, "view_finance")


class AuditChain(unittest.TestCase):
    def test_chain_detects_tampering(self):
        path, conn = fresh_db()
        user(conn, "farhana")
        self.assertTrue(audit.verify_chain(conn)["valid"])
        conn.execute("UPDATE audit_log SET detail_json = '{\"forged\": true}' WHERE id = 2")
        res = audit.verify_chain(conn)
        self.assertFalse(res["valid"])
        self.assertEqual(res["broken_at_id"], 2)


if __name__ == "__main__":
    unittest.main()
