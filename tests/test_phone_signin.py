"""Phone-number sign-in: number handling, code issue/verify and provisioning.

The HTTP handler runs in-process with the SMS gateway switched to demonstration
mode, so the code the phone would have received comes back in the response.
"""
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

SERVER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
sys.path.insert(0, SERVER_DIR)

DB_FILE = os.path.join(tempfile.mkdtemp(prefix="examflow-phone-"), "test.db")
os.environ["EXAMFLOW_DB"] = DB_FILE
os.environ["EXAMFLOW_QUIET"] = "1"
os.environ["EXAMFLOW_SECRET"] = "test-secret-for-unit-tests"
os.environ["EXAMFLOW_SMS_DEMO"] = "1"
os.environ["EXAMFLOW_PHONE_COUNTRY"] = "91"
os.environ.pop("FAST2SMS_API_KEY", None)

import app  # noqa: E402
import auth  # noqa: E402
import db  # noqa: E402
import sms  # noqa: E402


class PhoneNormalisationTest(unittest.TestCase):
    def test_accepted_shapes(self):
        for value in ("+91 90000 00001", "919000000001", "090000 00001", "9000000001",
                      "+91-90000-00001", "  +919000000001  "):
            self.assertEqual(sms.normalize(value), "+919000000001", value)

    def test_rejects_junk(self):
        for value in ("", "abc", "12", "900000000123456789"):
            with self.assertRaises(ValueError):
                sms.normalize(value)

    def test_display_groups_indian_numbers(self):
        self.assertEqual(sms.display("+919000000001"), "+91 90000 00001")


class PhoneSignInTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db(seed=False)
        conn = db.connect()
        conn.execute("INSERT INTO schools (id, school_name, school_code, status, created_at)"
                     " VALUES ('sch_1','Test School','TS1','Active',?)", (db.now_iso(),))
        conn.execute(
            "INSERT INTO users (id, full_name, email, password_hash, role, school_id, phone,"
            " is_active, created_at) VALUES ('usr_admin','Admin','admin@example.com',?,"
            " 'Super Admin','sch_1','+919000000001',1,?)",
            (auth.hash_password("x"), db.now_iso()))
        conn.execute(
            "INSERT INTO users (id, full_name, email, password_hash, role, school_id, phone,"
            " is_active, created_at) VALUES ('usr_student','Rohit Verma','student@example.com',?,"
            " 'Student','sch_1','+919000000011',1,?)",
            (auth.hash_password("x"), db.now_iso()))
        conn.commit()
        conn.close()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        conn = db.connect()
        conn.execute("DELETE FROM login_codes")
        conn.commit()
        conn.close()

    def call(self, path, payload):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        body = json.dumps(payload).encode()
        conn.request("POST", path, body=body, headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        try:
            return response.status, json.loads(raw or b"{}")
        except ValueError:
            return response.status, {"raw": raw.decode("utf-8", "replace")}

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        conn.request("GET", path)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        return response.status, json.loads(raw or b"{}")

    def test_providers_advertise_phone_sign_in(self):
        status, payload = self.get("/api/auth/providers")
        self.assertEqual(status, 200)
        self.assertTrue(payload["phone"])
        self.assertTrue(payload["phone_demo"])

    def test_admin_can_sign_in_with_a_texted_code(self):
        status, payload = self.call("/api/auth/request-phone-code",
                                    {"phone": "9000000001", "portal": "admin"})
        self.assertEqual(status, 200, payload)
        self.assertIn("demo_code", payload)
        code = payload["demo_code"]

        status, payload = self.call("/api/auth/verify-phone-code",
                                    {"phone": "+91 90000 00001", "portal": "admin", "code": code})
        self.assertEqual(status, 200, payload)
        user = payload["user"]
        self.assertEqual(user["email"], "admin@example.com")
        self.assertEqual(user["role"], "Super Admin")
        self.assertEqual(payload["created"], False)
        self.assertEqual(auth.read_token(payload["token"])["sub"], "usr_admin")

    def test_wrong_code_is_refused(self):
        self.call("/api/auth/request-phone-code", {"phone": "9000000001", "portal": "admin"})
        status, payload = self.call("/api/auth/verify-phone-code",
                                    {"phone": "9000000001", "portal": "admin", "code": "000000"})
        self.assertEqual(status, 401)
        self.assertIn("not correct", payload["error"])

    def test_code_cannot_be_reused(self):
        _, issued = self.call("/api/auth/request-phone-code",
                              {"phone": "9000000002", "portal": "student"})
        code = issued["demo_code"]
        status, _ = self.call("/api/auth/verify-phone-code",
                              {"phone": "9000000002", "portal": "student", "code": code})
        self.assertEqual(status, 200)
        status, payload = self.call("/api/auth/verify-phone-code",
                                    {"phone": "9000000002", "portal": "student", "code": code})
        self.assertEqual(status, 401)

    def test_new_student_is_created_from_a_phone_number(self):
        _, issued = self.call("/api/auth/request-phone-code",
                              {"phone": "9812345678", "portal": "student"})
        status, payload = self.call("/api/auth/verify-phone-code",
                                    {"phone": "9812345678", "portal": "student",
                                     "code": issued["demo_code"]})
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["user"]["role"], "Student")
        self.assertTrue(payload["created"])
        self.assertEqual(payload["user"]["phone"], "+919812345678")
        self.assertTrue(payload["user"]["email"].endswith("@students.examflow.local"))

    def test_unknown_number_cannot_reach_a_staff_portal(self):
        status, _ = self.call("/api/auth/request-phone-code",
                              {"phone": "9899999999", "portal": "admin"})
        self.assertEqual(status, 200)
        status, payload = self.call("/api/auth/verify-phone-code",
                                    {"phone": "9899999999", "portal": "admin", "code": "123456"})
        self.assertEqual(status, 401)

    def test_staff_account_is_refused_on_the_student_portal(self):
        _, issued = self.call("/api/auth/request-phone-code",
                              {"phone": "9000000001", "portal": "student"})
        status, payload = self.call("/api/auth/verify-phone-code",
                                    {"phone": "9000000001", "portal": "student",
                                     "code": issued["demo_code"]})
        self.assertEqual(status, 401)
        self.assertIn("student portal", payload["error"].lower())

    def test_student_cannot_use_the_admin_portal(self):
        _, issued = self.call("/api/auth/request-phone-code",
                              {"phone": "9000000011", "portal": "admin"})
        self.assertNotIn("demo_code", issued)
        status, payload = self.call("/api/auth/verify-phone-code",
                                    {"phone": "9000000011", "portal": "admin", "code": "123456"})
        self.assertEqual(status, 401)

    def test_second_request_inside_a_minute_is_throttled(self):
        status, _ = self.call("/api/auth/request-phone-code",
                              {"phone": "9000000011", "portal": "student"})
        self.assertEqual(status, 200)
        status, payload = self.call("/api/auth/request-phone-code",
                                    {"phone": "9000000011", "portal": "student"})
        self.assertEqual(status, 422)
        self.assertIn("wait a minute", payload["error"].lower())

    def test_bad_number_is_rejected_with_a_readable_message(self):
        status, payload = self.call("/api/auth/request-phone-code",
                                    {"phone": "12", "portal": "student"})
        self.assertEqual(status, 422)
        self.assertIn("phone number", payload["error"].lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
