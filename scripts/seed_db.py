"""Create a fresh SQLite database from the synthetic CSVs.

Run:  python scripts/seed_db.py            (writes data/hishab.db, replacing any old copy)
      python scripts/seed_db.py --db path/to/other.db
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import db  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=db.DEFAULT_DB)
    args = ap.parse_args()
    if os.path.exists(args.db):
        os.remove(args.db)
    conn = db.connect(args.db)
    db.seed(conn)
    conn.close()
    print(f"Database ready: {args.db}")
    print("Demo logins (synthetic data only):")
    for username, full, pw, _ in db.DEMO_USERS:
        print(f"  {username:12s} {pw:18s} {full}")


if __name__ == "__main__":
    main()
