"""The in-app assistant answers from stored rows, never from imagination.

These tests pin the three things that matter: a question is understood, the answer is
scoped to the asker's role, and a missing or broken language model never degrades the
assistant into an error.
"""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta

SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
sys.path.insert(0, SERVER)
os.environ["EXAMFLOW_DB"] = os.path.join(tempfile.mkdtemp(prefix="examflow-assist-"), "a.db")
os.environ.setdefault("EXAMFLOW_SECRET", "s" * 20)
os.environ["EXAMFLOW_QUIET"] = "1"
os.environ.pop("EXAMFLOW_LLM_API_KEY", None)

import assistant  # noqa: E402
import db  # noqa: E402
from solver_service import run_schedule  # noqa: E402


def connect():
    # init_db seeds only a brand-new file, so create the schema before opening it
    db.init_db(seed=True)
    return db.connect()


def isolated_admin():
    """A throwaway database of its own, so a destructive test cannot empty the shared one."""
    original = db.DB_PATH
    db.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="examflow-iso-"), "iso.db")
    try:
        db.init_db(seed=True)
        conn = db.connect()
    finally:
        db.DB_PATH = original
    admin = db.decode_row("users", conn.execute("SELECT * FROM users WHERE role='Super Admin'").fetchone())
    return conn, admin


def user(conn, email, role=None):
    row = conn.execute("SELECT * FROM users WHERE LOWER(email)=LOWER(?)", (email,)).fetchone()
    record = db.decode_row("users", row)
    if role:
        record["role"] = role
    return record


class DateTest(unittest.TestCase):
    def test_absolute_and_shorthand_dates(self):
        today = date(2026, 11, 14)
        self.assertEqual(assistant.parse_date("what is on 2026-12-02", today), date(2026, 12, 2))
        self.assertEqual(assistant.parse_date("exams on 2 dec", today), date(2026, 12, 2))
        self.assertEqual(assistant.parse_date("2 december 2026", today), date(2026, 12, 2))
        self.assertEqual(assistant.parse_date("02/12", today), date(2026, 12, 2))

    def test_relative_dates(self):
        today = date(2026, 11, 14)
        self.assertEqual(assistant.parse_date("what is scheduled tomorrow", today), today + timedelta(days=1))
        self.assertEqual(assistant.parse_date("today", today), today)
        monday = assistant.parse_date("monday", today)
        self.assertEqual(monday.weekday(), 0)
        self.assertGreaterEqual(monday, today)

    def test_no_date_is_none(self):
        self.assertIsNone(assistant.parse_date("who is overloaded", date(2026, 11, 14)))


class AssistantTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = connect()
        cls.admin = user(cls.conn, "admin@examflow.ai", "Super Admin")
        cls.invigilator = user(cls.conn, "ananya@examflow.ai", "Invigilator")
        cls.student = user(cls.conn, "student@examflow.ai", "Student")
        run_schedule(cls.conn, cls.admin, {"algorithm": "csp"})

    def ask(self, who, message, history=None):
        return assistant.ask(self.conn, who, {"message": message, "history": history or []})

    def test_status_reports_the_engine_without_leaking_secrets(self):
        status = assistant.status()
        self.assertTrue(status["enabled"])
        self.assertIn(status["mode"], ("grounded", "llm"))
        self.assertNotIn("EXAMFLOW_LLM_API_KEY", str(status))

    def test_empty_and_overlong_messages_are_rejected(self):
        with self.assertRaises(assistant.AssistantError):
            self.ask(self.admin, "   ")
        with self.assertRaises(assistant.AssistantError):
            self.ask(self.admin, "x" * (assistant.MAX_MESSAGE + 1))

    def test_schedule_question_answers_from_the_live_run(self):
        row = self.conn.execute("SELECT examination_date FROM schedule_assignments LIMIT 1").fetchone()
        self.assertIsNotNone(row, "the generated run should place at least one examination")
        when = row["examination_date"]
        reply = self.ask(self.admin, "what is scheduled on %s" % when)
        self.assertEqual(reply["mode"], "grounded")
        self.assertIn("examination", reply["reply"].lower())
        self.assertTrue(reply["suggestions"])

    def test_room_question_lists_utilisation(self):
        reply = self.ask(self.admin, "how busy are the rooms?")
        self.assertEqual(reply["intent"], "rooms")
        self.assertIn("room", reply["reply"].lower())

    def test_conflict_question_reports_the_validator_result(self):
        reply = self.ask(self.admin, "any conflicts?")
        self.assertEqual(reply["intent"], "conflicts")
        self.assertTrue("conflict" in reply["reply"].lower() or "clean" in reply["reply"].lower())

    def test_workload_question_names_invigilators(self):
        reply = self.ask(self.admin, "which invigilators are overloaded?")
        self.assertEqual(reply["intent"], "workload")
        self.assertIn("duties", reply["reply"].lower())
        self.assertIn("Heaviest", reply["reply"])

    def test_rules_and_algorithm_questions_are_explained(self):
        rules = self.ask(self.admin, "what are the scheduling rules?")
        self.assertIn("R1", rules["reply"])
        algorithm = self.ask(self.admin, "compare csp and first fit")
        self.assertEqual(algorithm["intent"], "algorithm")
        self.assertIn("First-Fit", algorithm["reply"])

    def test_student_is_never_answered_with_institution_data(self):
        reply = self.ask(self.student, "how many students and rooms are there?")
        self.assertNotIn("invigilator", reply["reply"].lower())
        self.assertNotIn("departments", reply["reply"].lower())
        exams = self.ask(self.student, "when is my exam?")
        self.assertIn("paper", exams["reply"].lower())

    def test_invigilator_is_answered_with_duties_only(self):
        reply = self.ask(self.invigilator, "how many rooms are free?")
        self.assertEqual(reply["intent"], "duties")
        self.assertNotIn("idle", reply["reply"].lower())

    def test_no_timetable_still_produces_an_answer(self):
        conn, fresh = isolated_admin()
        reply = assistant.ask(conn, fresh, {"message": "what is scheduled tomorrow"})
        self.assertTrue(reply["reply"])
        self.assertIn("no timetable", reply["reply"].lower())

    def test_broken_language_model_falls_back_to_the_grounded_answer(self):
        os.environ["EXAMFLOW_LLM_API_KEY"] = "test-key"
        os.environ["EXAMFLOW_LLM_BASE"] = "http://127.0.0.1:9/v1"
        try:
            import importlib
            importlib.reload(assistant)
            self.assertTrue(assistant.llm_enabled())
            reply = assistant.ask(self.conn, self.admin, {"message": "any conflicts?"})
            self.assertEqual(reply["mode"], "grounded-after-llm")
            self.assertTrue(reply["reply"])
        finally:
            os.environ.pop("EXAMFLOW_LLM_API_KEY", None)
            os.environ.pop("EXAMFLOW_LLM_BASE", None)
            import importlib
            importlib.reload(assistant)

    def test_rate_limit_stops_a_flood(self):
        who = dict(self.admin, id="rate-limit-user")
        for _ in range(assistant.RATE_LIMIT):
            assistant.ask(self.conn, who, {"message": "any conflicts?"})
        with self.assertRaises(assistant.AssistantError):
            assistant.ask(self.conn, who, {"message": "any conflicts?"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
