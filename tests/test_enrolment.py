"""Student self-registration: choosing a branch, a course and a semester.

The demo dataset is seeded in full, so the tests can prove the interesting promise of the
catalogue: a student who picks B.Tech CSE Semester 3 joins the very group the timetable
was built for, and sees real examinations on their first sign-in.
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

DB_FILE = os.path.join(tempfile.mkdtemp(prefix="examflow-catalog-"), "test.db")
os.environ["EXAMFLOW_DB"] = DB_FILE
os.environ["EXAMFLOW_QUIET"] = "1"
os.environ["EXAMFLOW_SECRET"] = "test-secret-for-unit-tests"
os.environ.pop("FAST2SMS_API_KEY", None)

import app  # noqa: E402
import catalog  # noqa: E402
import db  # noqa: E402


class CatalogTest(unittest.TestCase):
    """The list the sign-up form is built from."""

    def test_every_school_offers_at_least_one_course(self):
        for school in catalog.SCHOOLS:
            self.assertTrue(school["programmes"], school["code"])
            for programme in school["programmes"]:
                self.assertGreaterEqual(programme["semesters"], 1, programme["code"])

    def test_codes_are_unique(self):
        codes = [school["code"] for school in catalog.SCHOOLS]
        self.assertEqual(len(codes), len(set(codes)))
        programmes = [p["code"] for school in catalog.SCHOOLS for p in school["programmes"]]
        self.assertEqual(len(programmes), len(set(programmes)))

    def test_lpu_branches_are_covered(self):
        codes = {school["code"] for school in catalog.SCHOOLS}
        for expected in ("SCSE", "SCA", "SEEE", "SME", "SCE", "MSB", "SOL", "SOA", "SOP"):
            self.assertIn(expected, codes)

    def test_resolve_reports_what_is_missing(self):
        with self.assertRaises(catalog.EnrolmentError):
            catalog.resolve("", "CSE", 3)
        with self.assertRaises(catalog.EnrolmentError):
            catalog.resolve("SCSE", "LLB", 3)  # a law course is not offered by SCSE
        with self.assertRaises(catalog.EnrolmentError):
            catalog.resolve("SCSE", "CSE", 9)  # B.Tech runs for eight semesters
        school, programme, semester = catalog.resolve("scse", "cse", "3")
        self.assertEqual(school["code"], "SCSE")
        self.assertEqual(programme["code"], "CSE")
        self.assertEqual(semester, 3)


class StudentSignUpTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db(seed=True)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, method, path, payload=None, token=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=25)
        body = json.dumps(payload).encode() if payload is not None else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        try:
            return response.status, json.loads(raw or b"{}")
        except ValueError:
            return response.status, {"raw": raw.decode("utf-8", "replace")}

    def sign_up(self, email, **choices):
        payload = {"email": email, "password": "StudentPass1", "portal": "student"}
        payload.update(choices)
        return self.call("POST", "/api/auth/gmail", payload)

    def test_catalog_is_public_and_lists_branches_with_courses(self):
        status, payload = self.call("GET", "/api/catalog")
        self.assertEqual(status, 200)
        codes = {school["code"] for school in payload["schools"]}
        self.assertIn("SCSE", codes)
        self.assertIn("MSB", codes)
        scse = [s for s in payload["schools"] if s["code"] == "SCSE"][0]
        self.assertIn("CSE", {p["code"] for p in scse["programmes"]})
        self.assertIn("A", payload["sections"])

    def test_student_lands_in_the_seeded_group_and_sees_its_exams(self):
        status, payload = self.sign_up("fresh.cse@example.com", school="SCSE",
                                       programme="CSE", semester="3", section="A")
        self.assertEqual(status, 201, payload)
        self.assertIsNotNone(payload["token"])
        status, exams = self.call("GET", "/api/my-exams", token=payload["token"])
        self.assertEqual(status, 200, exams)
        self.assertIsNotNone(exams["group"], exams)
        self.assertEqual(exams["group"]["semester"], 3)
        self.assertTrue(exams["exams"], "a new student saw an empty timetable")
        for exam in exams["exams"]:
            self.assertTrue(exam["subject_name"])

    def test_new_branch_is_created_on_first_sign_up(self):
        status, payload = self.sign_up("fresh.law@example.com", school="SOL",
                                       programme="LLB", semester="1")
        self.assertEqual(status, 201, payload)
        conn = db.connect()
        school = conn.execute("SELECT * FROM schools WHERE school_code = 'SOL'").fetchone()
        department = conn.execute(
            "SELECT * FROM departments WHERE UPPER(department_code) = 'LLB'").fetchone()
        group = conn.execute("SELECT * FROM student_groups WHERE department_id = ?",
                             (department["id"],)).fetchone()
        conn.close()
        self.assertEqual(school["school_name"], "School of Law")
        self.assertEqual(group["semester"], 1)

    def test_sign_up_without_a_branch_is_refused(self):
        status, payload = self.sign_up("no.branch@example.com")
        self.assertEqual(status, 422, payload)
        self.assertIn("branch", payload["error"])
        # nothing was created, so the same address can try again with a real choice
        status, payload = self.sign_up("no.branch@example.com", school="SCSE",
                                       programme="CSE", semester="1")
        self.assertEqual(status, 201, payload)

    def test_course_from_another_branch_is_refused(self):
        status, payload = self.sign_up("mixed@example.com", school="SME", programme="CSE",
                                       semester="3")
        self.assertEqual(status, 422, payload)
        self.assertIn("course", payload["error"])

    def test_semester_outside_the_course_is_refused(self):
        status, payload = self.sign_up("late@example.com", school="MSB", programme="MBA",
                                       semester="7")
        self.assertEqual(status, 422, payload)
        self.assertIn("4 semesters", payload["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
