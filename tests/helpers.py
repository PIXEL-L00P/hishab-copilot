import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import agent, db, security  # noqa: E402

_TEMPLATE = None


def fresh_db():
    """A brand-new seeded database in a temp folder (seeded once, then copied for speed)."""
    global _TEMPLATE
    if _TEMPLATE is None:
        d = tempfile.mkdtemp(prefix="hishab_tpl_")
        _TEMPLATE = os.path.join(d, "template.db")
        c = db.connect(_TEMPLATE)
        db.seed(c, verbose=False)
        c.close()
    d = tempfile.mkdtemp(prefix="hishab_test_")
    path = os.path.join(d, "test.db")
    shutil.copy(_TEMPLATE, path)
    return path, db.connect(path)


PASSWORDS = {u: pw for u, _, pw, _ in db.DEMO_USERS}


def user(conn, username):
    tok = security.login(conn, username, PASSWORDS[username])
    return security.user_from_token(conn, tok)


def ctx(conn, username, business_id=1):
    return agent.Ctx(conn, user(conn, username), business_id)
