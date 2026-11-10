"""Sign-in flow tests: Google OAuth callback routing and account provisioning.

Runs the real HTTP handler in-process with Google's token exchange stubbed out, so the
callback, session token redirect and first-time student provisioning are all exercised.
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

DB_FILE = os.path.join(tempfile.mkdtemp(prefix="examflow-google-"), "test.db")
os.environ["EXAMFLOW_DB"] = DB_FILE
os.environ["EXAMFLOW_QUIET"] = "1"
os.environ["EXAMFLOW_SECRET"] = "test-secret-for-unit-tests"
os.environ["GOOGLE_CLIENT_ID"] = "test-client-id.apps.googleusercontent.com"
os.environ["GOOGLE_CLIENT_SECRET"] = "test-client-secret"

import app  # noqa: E402
import auth  # noqa: E402
import db  # noqa: E402
import google_auth  # noqa: E402


def seed():
    db.init_db(seed=False)
    conn = db.connect()
    conn.execute(
        "INSERT INTO schools (id, school_name, school_code, status, created_at)"
        " VALUES ('sch_1','Test School','TS1','Active',?)", (db.now_iso(),))
    conn.execute(
        "INSERT INTO users (id, full_name, email, password_hash, role, school_id,"
        " is_active, created_at) VALUES ('usr_admin','Admin','admin@example.com',?,"
        " 'Super Admin','sch_1',1,?)",
        (auth.hash_password("x"), db.now_iso()))
    conn.execute(
        "INSERT INTO users (id, full_name, email, password_hash, role, school_id,"
        " is_active, created_at) VALUES ('usr_student','Student','student@example.com',?,"
        " 'Student','sch_1',1,?)",
        (auth.hash_password("x"), db.now_iso()))
    conn.commit()
    conn.close()


class GoogleSignInTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = "http://127.0.0.1:%d" % cls.port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def request(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response.status, response.getheader("Location") or "", body

    def setUp(self):
        google_auth.exchange_code = lambda code, redirect_uri: {
            "email": "new.student@example.com", "name": "New Student",
            "picture": None, "email_verified": True}

    def test_state_round_trip_returns_payload(self):
        state = google_auth.sign_state(
            "https://site.test/api/auth/google/callback", "admin", "https://site.test")
        payload = google_auth.read_state(state)
        self.assertEqual(payload["r"], "https://site.test/api/auth/google/callback")
        self.assertEqual(payload["p"], "admin")
        self.assertEqual(payload["o"], "https://site.test")

    def test_legacy_packed_state_is_still_read(self):
        state = google_auth.sign_state("https://site.test/api/auth/google/callback|student")
        payload = google_auth.read_state(state)
        self.assertEqual(payload["r"], "https://site.test/api/auth/google/callback")
        self.assertEqual(payload["p"], "student")

    def test_callback_uri_follows_the_visitor_when_no_public_url_is_set(self):
        self.assertEqual(google_auth.PUBLIC_URL, "")
        self.assertEqual(google_auth.callback_uri("https://getexamflow.vercel.app/"),
                         "https://getexamflow.vercel.app/api/auth/google/callback")

    def test_callback_uri_prefers_the_registered_public_url(self):
        google_auth.PUBLIC_URL = "https://examflow-ai-inky.vercel.app"
        try:
            self.assertEqual(google_auth.callback_uri("https://getexamflow.vercel.app"),
                             "https://examflow-ai-inky.vercel.app/api/auth/google/callback")
        finally:
            google_auth.PUBLIC_URL = ""

    def test_second_domain_signs_in_through_the_registered_callback(self):
        """A visitor on the clean domain must still finish on the clean domain."""
        google_auth.PUBLIC_URL = "https://examflow-ai-inky.vercel.app"
        try:
            status, location, _ = self.request("/api/auth/google/start?portal=student")
            self.assertEqual(status, 302)
            self.assertIn("redirect_uri=https%3A%2F%2Fexamflow-ai-inky.vercel.app"
                          "%2Fapi%2Fauth%2Fgoogle%2Fcallback", location)
            state = location.split("state=", 1)[1].split("&", 1)[0]

            status, location, body = self.request(
                "/api/auth/google/callback?code=stub&state=" + state)
            self.assertEqual(status, 302, body[:200])
            self.assertTrue(location.startswith(self.origin + "/#google_token="), location)
            token = location.split("#google_token=", 1)[1]
            self.assertIsNotNone(auth.read_token(token))
        finally:
            google_auth.PUBLIC_URL = ""

    def test_failed_sign_in_returns_to_the_originating_domain(self):
        google_auth.PUBLIC_URL = "https://examflow-ai-inky.vercel.app"
        try:
            state = google_auth.sign_state(
                "https://examflow-ai-inky.vercel.app/api/auth/google/callback",
                "student", "https://getexamflow.vercel.app")

            def boom(code, redirect_uri):
                raise google_auth.GoogleAuthError("nope")

            original = google_auth.exchange_code
            google_auth.exchange_code = boom
            try:
                status, location, _ = self.request(
                    "/api/auth/google/callback?code=stub&state=" + state)
            finally:
                google_auth.exchange_code = original
            self.assertEqual(status, 302)
            self.assertEqual(location,
                             "https://getexamflow.vercel.app/?google_error=google#/login")
        finally:
            google_auth.PUBLIC_URL = ""

    def test_start_redirects_to_google_with_registered_redirect_uri(self):
        status, location, _ = self.request("/api/auth/google/start?portal=student")
        self.assertEqual(status, 302)
        self.assertIn("accounts.google.com", location)
        self.assertIn("redirect_uri=" + "http%3A%2F%2F127.0.0.1%3A" + str(self.port), location)

    def test_new_student_is_provisioned_and_signed_in(self):
        redirect_uri = self.origin + "/api/auth/google/callback"
        state = google_auth.sign_state(redirect_uri + "|student")
        status, location, body = self.request(
            "/api/auth/google/callback?code=stub&state=" + state)
        self.assertEqual(status, 302, body[:200])
        self.assertTrue(location.startswith("/#google_token="), location)

        token = location.split("#google_token=", 1)[1]
        payload = auth.read_token(token)
        self.assertIsNotNone(payload)

        conn = db.connect()
        row = conn.execute("SELECT role, email FROM users WHERE id = ?",
                           (payload["sub"],)).fetchone()
        conn.close()
        self.assertEqual(row["email"], "new.student@example.com")
        self.assertEqual(row["role"], "Student")

    def test_new_google_account_is_snapshotted_before_the_token_is_returned(self):
        """The row must be durable before the browser uses the token.

        The callback is a GET redirect, so it never passes through the write hook that
        saves every other mutation; without an explicit save the token arrived at an
        instance that had never seen the account and the visitor was logged straight
        back out with "session expired".
        """
        import persistence
        saved = []
        original = persistence.save_now
        persistence.save_now = lambda: saved.append(1) or True
        try:
            redirect_uri = self.origin + "/api/auth/google/callback"
            state = google_auth.sign_state(redirect_uri + "|student")
            status, location, body = self.request(
                "/api/auth/google/callback?code=stub&state=" + state)
        finally:
            persistence.save_now = original
        self.assertEqual(status, 302, body[:200])
        self.assertIn("#google_token=", location)
        self.assertTrue(saved, "the new account was never persisted")

    def test_bad_state_is_rejected_without_a_server_error(self):
        status, location, body = self.request("/api/auth/google/callback?code=stub&state=bogus")
        self.assertEqual(status, 302, body[:200])
        self.assertEqual(location, "/?google_error=expired#/login")

    def test_missing_state_is_rejected(self):
        status, location, _ = self.request("/api/auth/google/callback")
        self.assertEqual(status, 302)
        self.assertEqual(location, "/?google_error=expired#/login")

    def test_cancelled_consent_returns_to_login(self):
        status, location, _ = self.request("/api/auth/google/callback?error=access_denied")
        self.assertEqual(status, 302)
        self.assertEqual(location, "/?google_error=cancelled#/login")

    def as_google_user(self, email, name="Person"):
        google_auth.exchange_code = lambda code, redirect_uri: {
            "email": email, "name": name, "picture": None, "email_verified": True}

    def sign_in_through(self, portal):
        state = google_auth.sign_state(
            self.origin + "/api/auth/google/callback", portal, self.origin)
        status, location, body = self.request(
            "/api/auth/google/callback?code=stub&state=" + state)
        self.assertEqual(status, 302, body[:200])
        self.assertTrue(location.startswith(self.origin + "/#google_token="), location)
        token = location.split("#google_token=", 1)[1].split("&", 1)[0]
        return location, auth.read_token(token)

    def test_admin_on_the_student_page_is_signed_in_and_told_its_own_portal(self):
        """A real account on the wrong sign-in page must not be a dead end."""
        self.as_google_user("admin@example.com", "Admin")
        location, payload = self.sign_in_through("student")
        self.assertIsNotNone(payload)
        self.assertIn("portal=admin", location)
        self.assertIn("asked=student", location)

    def test_student_on_the_admin_page_is_sent_to_the_student_portal(self):
        self.as_google_user("student@example.com", "Student")
        location, payload = self.sign_in_through("admin")
        self.assertIsNotNone(payload)
        self.assertIn("portal=student", location)
        self.assertIn("asked=admin", location)

    def test_matching_portal_carries_no_redirect_notice(self):
        self.as_google_user("student@example.com", "Student")
        location, payload = self.sign_in_through("student")
        self.assertIsNotNone(payload)
        self.assertNotIn("portal=", location)

    def test_providers_reports_google_when_configured(self):
        status, _, body = self.request("/api/auth/providers")
        self.assertEqual(status, 200)
        self.assertIn(b'"google": true', body)


if __name__ == "__main__":
    unittest.main(verbosity=2)
