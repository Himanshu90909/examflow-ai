"""The database has to survive several workers opening it at the same time.

A hosted host starts a handful of workers on a cold start and they all reach for
the same SQLite file. A lock error there reached the browser as a 500 on the
sign-in request, so these tests pin the waiting behaviour down.
"""
import os
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
os.environ.setdefault("EXAMFLOW_DB", os.path.join(tempfile.mkdtemp(), "concurrency.db"))
os.environ.setdefault("EXAMFLOW_SECRET", "test-secret")

import db  # noqa: E402


class ConnectWaitsForTheWriterTest(unittest.TestCase):
    def test_a_second_writer_waits_instead_of_failing(self):
        db.init_db(seed=True)
        holder = db.connect()
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("INSERT INTO audit_logs (id, action, entity_type, details, timestamp)"
                       " VALUES ('lock_probe','x','y','z',?)", (db.now_iso(),))

        started = time.time()
        later = db.connect()  # must not raise "database is locked"
        try:
            self.assertGreaterEqual(later.execute("PRAGMA busy_timeout").fetchone()[0], 1000)
        finally:
            later.close()
            holder.rollback()
            holder.close()
        self.assertLess(time.time() - started, 10)


class InitIsSerialisedTest(unittest.TestCase):
    def test_parallel_cold_starts_build_one_dataset(self):
        path = os.path.join(tempfile.mkdtemp(), "cold.db")
        os.environ["EXAMFLOW_DB"] = path
        db.DB_PATH = path  # the module reads this at import time
        db.init_db(seed=True)

        errors = []

        def worker():
            try:
                db.init_db(seed=True)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        conn = db.connect()
        try:
            users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            schools = conn.execute("SELECT COUNT(*) FROM schools").fetchone()[0]
            phones = conn.execute(
                "SELECT COUNT(*) FROM users WHERE phone IS NOT NULL").fetchone()[0]
        finally:
            conn.close()
        self.assertGreaterEqual(users, 7)
        self.assertEqual(schools, 3)
        self.assertGreaterEqual(phones, 7)


class ExecuteWhenFreeTest(unittest.TestCase):
    def test_retries_through_a_locked_file(self):
        path = os.path.join(tempfile.mkdtemp(), "retry.db")
        db.DB_PATH = path
        db.init_db(seed=False)

        refused = {"count": 0}

        def work(conn):
            if refused["count"] < 2:
                refused["count"] += 1
                raise sqlite3.OperationalError("database is locked")
            return "done"

        self.assertEqual(db._execute_when_free(work, attempts=4, pause=0.01), "done")
        self.assertEqual(refused["count"], 2)

    def test_other_errors_are_not_retried(self):
        path = os.path.join(tempfile.mkdtemp(), "fatal.db")
        db.DB_PATH = path
        db.init_db(seed=False)

        def work(conn):
            raise sqlite3.OperationalError("no such table: nowhere")

        with self.assertRaises(sqlite3.OperationalError):
            db._execute_when_free(work, attempts=3, pause=0.01)


if __name__ == "__main__":
    unittest.main(verbosity=2)
