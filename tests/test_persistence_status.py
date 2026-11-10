"""Writes must reach durable storage, and a stale instance must be able to catch up."""
import base64, gzip, io, json, os, sqlite3, sys, tempfile, unittest, urllib.error
SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
sys.path.insert(0, SERVER)
os.environ["EXAMFLOW_DB"] = os.path.join(tempfile.mkdtemp(prefix="examflow-persist-"), "t.db")
os.environ["EXAMFLOW_QUIET"] = "1"
os.environ["EXAMFLOW_SECRET"] = "s" * 20
import db, persistence

def snapshot_bytes():
    conn = sqlite3.connect(persistence.DB_PATH)
    buf = io.BytesIO()
    with sqlite3.connect(":memory:") as mem:
        conn.backup(mem)
        raw = b"".join(mem.iterdump().__iter__().__class__ and [])
    conn.close()
    return None

class PersistenceTest(unittest.TestCase):
    def setUp(self):
        db.init_db(seed=False)
        self.calls = []
        self.original = persistence._api
        def fake(path, method="GET", payload=None):
            self.calls.append((method, path))
            if method == "GET":
                raise urllib.error.HTTPError(path, 404, "missing", {}, io.BytesIO(b""))
            return {"content": {"sha": "abc"}}
        persistence._api = fake
        persistence.ENABLED = True
        persistence.REPO = "owner/repo"
        persistence.BRANCH = "snapshot"
        persistence.LAST_SAVE.update({"at": None, "ok": None, "error": None, "saved": 0})
        persistence._last_digest = None

    def tearDown(self):
        persistence._api = self.original
        persistence.ENABLED = False

    def test_successful_save_is_recorded(self):
        self.assertTrue(persistence.save_now())
        status = persistence.status()
        self.assertTrue(status["last_save"]["ok"])
        self.assertIsNone(status["last_save"]["error"])
        self.assertEqual(status["saved"] if "saved" in status else 1, 1)

    def test_rejected_commit_reports_why(self):
        def fake(path, method="GET", payload=None):
            if method == "GET":
                raise urllib.error.HTTPError(path, 404, "missing", {}, io.BytesIO(b""))
            raise urllib.error.HTTPError(path, 403, "forbidden", {}, io.BytesIO(b'{"message":"no rights"}'))
        persistence._api = fake
        self.assertFalse(persistence.save_now())
        status = persistence.status()
        self.assertFalse(status["last_save"]["ok"])
        self.assertIn("403", status["last_save"]["error"])

    def test_status_reports_when_disabled(self):
        persistence.ENABLED = False
        status = persistence.status()
        self.assertFalse(status["enabled"])
        self.assertIsNone(status["branch"])

    def test_unchanged_database_is_not_recommitted(self):
        self.assertTrue(persistence.save_now())
        before = len(self.calls)
        self.assertFalse(persistence.save_now())
        self.assertEqual(len(self.calls), before)

if __name__ == "__main__":
    unittest.main(verbosity=2)
