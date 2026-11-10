"""Vercel entry point.

Vercel's filesystem is read-only apart from /tmp, so the SQLite database lives
in /tmp and is seeded on a cold start. That keeps the deployment fully working
as a demo; data resets whenever the function instance is recycled. For durable
storage point EXAMFLOW_DB at a mounted volume or move to Postgres.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))

os.environ.setdefault("EXAMFLOW_DB", "/tmp/examflow.db")
os.environ.setdefault("EXAMFLOW_QUIET", "1")

import db  # noqa: E402

if not os.path.exists(db.DB_PATH):
    db.init_db(seed=os.environ.get("EXAMFLOW_SEED", "1") != "0")

# A restored snapshot can predate the university identity, and a warm instance would keep
# serving the old generic schools. Re-cut on every cold start: the rename matches old rows
# only, so it is a no-op once the data already speaks the university's words.
if os.environ.get("EXAMFLOW_RETHEME", "1") != "0":
    try:
        import retheme
        _conn = db.connect()
        try:
            retheme.apply(_conn)
        finally:
            _conn.close()
    except Exception:  # a cosmetic rename must never stop the deployment from serving
        import traceback
        traceback.print_exc()

from wsgi import application  # noqa: E402,F401
