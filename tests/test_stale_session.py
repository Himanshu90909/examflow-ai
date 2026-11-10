"""A session that reaches an instance which has not seen the user must not 500.

Every Vercel instance keeps its own copy of the SQLite file and restores it from the
snapshot repository on a cold start. A sign-in completed on one instance can therefore
arrive at another instance that has not restored that user row yet; that used to
surface as "Unexpected server error" from /api/meta. Now the row is adopted from the
snapshot, and anything still unknown answers 401 so the browser re-authenticates.
"""
import http.client
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
sys.path.insert(0, SERVER_DIR)

os.environ["EXAMFLOW_DB"] = os.path.join(tempfile.mkdtemp(prefix="examflow-stale-"), "test.db")
os.environ["EXAMFLOW_QUIET"] = "1"
os.environ["EXAMFLOW_SECRET"] = "test-secret-for-stale-sessions"

import app  # noqa: E402
import auth  # noqa: E402
import db  # noqa: E402
import persistence  # noqa: E402


def seed():
    db.init_db(seed=False)
    conn = db.connect()
    conn.execute("INSERT INTO users (id, full_name, email, password_hash, role, is_active,"
                 " created_at) VALUES ('usr_known','Known','known@example.com',?,"
                 " 'Super Admin',1,?)", (auth.hash_password("x"), db.now_iso()))
    conn.commit()
    conn.close()


class StaleSessionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        headers = {"Authorization": "Bearer " + token} if token else {}
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response.status, body

    def token_for(self, user_id, role="Student"):
        return auth.make_token({"id": user_id, "role": role})

    def setUp(self):
        self._real_fetch = persistence.fetch_user
        persistence.fetch_user = lambda user_id: None

    def tearDown(self):
        persistence.fetch_user = self._real_fetch

    def test_unknown_user_gets_401_not_a_server_error(self):
        status, body = self.get("/api/meta", self.token_for("usr_ghost"))
        self.assertEqual(status, 401, body[:200])
        self.assertIn(b"sign in again", body.lower())

    def test_snapshot_row_is_adopted_so_the_session_survives(self):
        persistence.fetch_user = lambda user_id: {
            "id": user_id, "full_name": "Snapshot Student",
            "email": "snapshot@example.com", "password_hash": auth.hash_password("x"),
            "role": "Student", "school_id": None, "department_id": None,
            "student_group_id": None, "phone": None, "is_active": 1,
            "created_at": db.now_iso(),
        }
        token = self.token_for("usr_from_snapshot")
        user = auth.current_user(token)
        self.assertIsNotNone(user)
        self.assertEqual(user["email"], "snapshot@example.com")

        status, body = self.get("/api/meta", token)
        self.assertEqual(status, 200, body[:200])
        conn = db.connect()
        row = conn.execute("SELECT email FROM users WHERE id = 'usr_from_snapshot'").fetchone()
        conn.close()
        self.assertEqual(row["email"], "snapshot@example.com")

    def test_snapshot_lookup_is_disabled_without_storage(self):
        self.assertIsNone(persistence.fetch_user("usr_anyone"))

    def test_known_user_is_unaffected(self):
        status, body = self.get("/api/meta", self.token_for("usr_known", "Super Admin"))
        self.assertEqual(status, 200, body[:200])


if __name__ == "__main__":
    unittest.main(verbosity=2)
