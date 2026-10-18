"""SQLite database: schema, connection helper and seeding from the synthetic CSVs."""
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB = os.environ.get("HISHAB_DB", os.path.join(ROOT, "data", "hishab.db"))

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    failed_logins INTEGER NOT NULL DEFAULT 0,
    locked_until TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS businesses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    district TEXT NOT NULL,
    area TEXT NOT NULL,
    founded TEXT NOT NULL,
    owner_is_woman INTEGER NOT NULL DEFAULT 0,
    has_collateral INTEGER NOT NULL DEFAULT 0,
    has_trade_license INTEGER NOT NULL DEFAULT 1,
    staff INTEGER NOT NULL DEFAULT 1,
    monthly_rent REAL NOT NULL DEFAULT 0,
    monthly_salaries REAL NOT NULL DEFAULT 0,
    synthetic INTEGER NOT NULL DEFAULT 1
);

-- role: owner | accountant | lender
CREATE TABLE IF NOT EXISTS memberships (
    user_id INTEGER NOT NULL REFERENCES users(id),
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    role TEXT NOT NULL CHECK (role IN ('owner','accountant','lender')),
    PRIMARY KEY (user_id, business_id)
);

CREATE TABLE IF NOT EXISTS weekly_records (
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    week_start TEXT NOT NULL,
    sales REAL NOT NULL, cash_sales REAL NOT NULL, credit_sales REAL NOT NULL,
    receivables_collected REAL NOT NULL, stock_purchases REAL NOT NULL,
    rent REAL NOT NULL, salaries REAL NOT NULL, festival_bonus REAL NOT NULL,
    utilities REAL NOT NULL, other_expenses REAL NOT NULL, loan_repayment REAL NOT NULL,
    owner_drawings REAL NOT NULL, owner_injection REAL NOT NULL, cash_balance REAL NOT NULL,
    PRIMARY KEY (business_id, week_start)
);

CREATE TABLE IF NOT EXISTS receivables (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    customer_name TEXT NOT NULL, customer_phone TEXT NOT NULL,
    amount REAL NOT NULL, due_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open', note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS payables (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    counterparty TEXT NOT NULL, description TEXT NOT NULL,
    amount REAL NOT NULL, due_date TEXT NOT NULL,
    category TEXT NOT NULL, flexible INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS loans (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    lender TEXT NOT NULL, outstanding REAL NOT NULL,
    monthly_installment REAL NOT NULL, due_day INTEGER NOT NULL, annual_rate REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS financing_products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL, provider_type TEXT NOT NULL,
    min_amount REAL NOT NULL, max_amount REAL NOT NULL,
    rate_min REAL NOT NULL, rate_max REAL NOT NULL,
    tenure_months INTEGER NOT NULL, min_months_operating INTEGER NOT NULL,
    min_monthly_revenue REAL NOT NULL, collateral_required INTEGER NOT NULL,
    trade_license_required INTEGER NOT NULL, women_only INTEGER NOT NULL DEFAULT 0,
    processing_days INTEGER NOT NULL, notes TEXT NOT NULL
);

-- every tool call the agent makes, with its permission tier and outcome
CREATE TABLE IF NOT EXISTS agent_actions (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    tool TEXT NOT NULL, tier INTEGER NOT NULL,
    status TEXT NOT NULL,   -- executed | drafted | pending_approval | approved | rejected | expired | blocked | denied
    params_json TEXT NOT NULL, result_json TEXT,
    requested_by INTEGER REFERENCES users(id), decided_by INTEGER REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now')), decided_at TEXT, expires_at TEXT
);

-- sandbox: messages the agent "sends" land here instead of a real SMS/WhatsApp gateway
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    channel TEXT NOT NULL, recipient TEXT NOT NULL, message TEXT NOT NULL,
    action_id INTEGER REFERENCES agent_actions(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shared_reports (
    id INTEGER PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id),
    lender_user_id INTEGER NOT NULL REFERENCES users(id),
    report_json TEXT NOT NULL,
    action_id INTEGER REFERENCES agent_actions(id),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- tamper-evident audit log: each row stores the hash of the previous row
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    user_id INTEGER, business_id INTEGER,
    event TEXT NOT NULL, detail_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
"""

# Illustrative financing catalogue. Provider names are generic categories, and the
# amounts, rates and timelines are ILLUSTRATIVE ranges for the prototype only.
# A production version must load verified product terms from partner institutions.
FINANCING_PRODUCTS = [
    dict(name="Supplier trade-credit extension", provider_type="supplier",
         min_amount=10_000, max_amount=1_000_000, rate_min=0.0, rate_max=0.02, tenure_months=1,
         min_months_operating=6, min_monthly_revenue=0, collateral_required=0,
         trade_license_required=0, women_only=0, processing_days=2,
         notes="Ask an existing supplier to extend the due date by 2-4 weeks. Depends on relationship."),
    dict(name="Digital merchant working-capital loan", provider_type="mfs_partner",
         min_amount=20_000, max_amount=300_000, rate_min=0.12, rate_max=0.16, tenure_months=6,
         min_months_operating=12, min_monthly_revenue=200_000, collateral_required=0,
         trade_license_required=1, women_only=0, processing_days=3,
         notes="Small, fast unsecured loan based on digital transaction history (illustrative terms)."),
    dict(name="Bank SME working-capital loan", provider_type="bank",
         min_amount=300_000, max_amount=5_000_000, rate_min=0.12, rate_max=0.15, tenure_months=12,
         min_months_operating=24, min_monthly_revenue=400_000, collateral_required=1,
         trade_license_required=1, women_only=0, processing_days=21,
         notes="Standard bank facility; usually needs collateral or guarantor and audited records."),
    dict(name="Refinance-scheme CMSME loan (via participating bank)", provider_type="bank_refinance",
         min_amount=100_000, max_amount=2_500_000, rate_min=0.07, rate_max=0.09, tenure_months=24,
         min_months_operating=24, min_monthly_revenue=250_000, collateral_required=0,
         trade_license_required=1, women_only=0, processing_days=30,
         notes="Lower-rate loan funded through a central-bank refinance scheme for small enterprises "
               "(illustrative terms; scheme rules change and must be verified)."),
    dict(name="Women entrepreneur SME loan (participating bank)", provider_type="bank_refinance",
         min_amount=100_000, max_amount=2_500_000, rate_min=0.05, rate_max=0.07, tenure_months=24,
         min_months_operating=12, min_monthly_revenue=150_000, collateral_required=0,
         trade_license_required=1, women_only=1, processing_days=21,
         notes="Concessional loan for women-led small enterprises (illustrative terms)."),
    dict(name="Microfinance enterprise loan", provider_type="mfi",
         min_amount=50_000, max_amount=1_000_000, rate_min=0.20, rate_max=0.24, tenure_months=12,
         min_months_operating=6, min_monthly_revenue=0, collateral_required=0,
         trade_license_required=0, women_only=0, processing_days=7,
         notes="Accessible without collateral but expensive; weekly instalments are common."),
]

DEMO_USERS = [
    # username, full name, password, [(business_id, role), ...]
    ("farhana", "Farhana Akter (owner, Style Corner)", "StyleCorner#2026", [(1, "owner")]),
    ("rakib", "Rakib Hasan (accountant, Style Corner)", "Accounts#2026", [(1, "accountant")]),
    ("lender_demo", "Demo Bank SME Desk (lender)", "LenderDesk#2026", [(1, "lender")]),
    ("owner2", "Second shop owner (business 2)", "SecondShop#2026", [(2, "owner")]),
]


def connect(path: str = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or DEFAULT_DB, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn):
    conn.executescript(SCHEMA)
    conn.commit()


def rows(cur):
    return [dict(r) for r in cur.fetchall()]


def seed(conn, synthetic_dir=None, verbose=True):
    """Load synthetic CSVs, the financing catalogue and the demo users into a fresh DB."""
    import pandas as pd
    from app import security

    d = synthetic_dir or os.path.join(ROOT, "data", "synthetic")
    init_schema(conn)
    biz = pd.read_csv(os.path.join(d, "businesses.csv"))
    fixed = pd.read_csv(os.path.join(d, "fixed_costs.csv"))
    biz = biz.merge(fixed, on="business_id")
    for r in biz.itertuples():
        conn.execute(
            "INSERT INTO businesses (id,name,category,district,area,founded,owner_is_woman,has_collateral,"
            "has_trade_license,staff,monthly_rent,monthly_salaries,synthetic) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1)",
            (r.business_id, r.name, r.category, r.district, r.area, r.founded, r.owner_is_woman,
             r.has_collateral, r.has_trade_license, r.staff, r.monthly_rent, r.monthly_salaries))
    weekly = pd.read_csv(os.path.join(d, "weekly_records.csv"))
    cols = list(weekly.columns)
    conn.executemany(
        f"INSERT INTO weekly_records ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
        weekly.itertuples(index=False, name=None))
    for name, table in [("receivables.csv", "receivables"), ("payables.csv", "payables"),
                        ("loans.csv", "loans")]:
        df = pd.read_csv(os.path.join(d, name)).fillna("")
        c = list(df.columns)
        conn.executemany(f"INSERT INTO {table} ({','.join(c)}) VALUES ({','.join('?' * len(c))})",
                         df.itertuples(index=False, name=None))
    for p in FINANCING_PRODUCTS:
        k = list(p.keys())
        conn.execute(f"INSERT INTO financing_products ({','.join(k)}) VALUES ({','.join('?' * len(k))})",
                     [p[x] for x in k])
    for username, full, pw, members in DEMO_USERS:
        uid = security.create_user(conn, username, full, pw)
        for bid, role in members:
            conn.execute("INSERT INTO memberships (user_id, business_id, role) VALUES (?,?,?)",
                         (uid, bid, role))
    conn.commit()
    from app import audit
    audit.log(conn, None, None, "database_seeded",
              {"businesses": int(len(biz)), "weekly_records": int(len(weekly))})
    if verbose:
        print(f"Seeded {len(biz)} businesses, {len(weekly)} weekly records, "
              f"{len(FINANCING_PRODUCTS)} financing products, {len(DEMO_USERS)} demo users.")


def to_json(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)
