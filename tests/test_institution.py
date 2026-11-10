"""The deployment serves one university, and an old dataset can be re-cut for it.

These tests cover what a reviewer sees first (the sign-in screen and titles) and the
rename path that turns an earlier generic dataset into the university's own words without
losing the identifiers other tables point at.
"""
import os
import sys
import tempfile
import unittest

SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
sys.path.insert(0, SERVER)
os.environ["EXAMFLOW_DB"] = os.path.join(tempfile.mkdtemp(prefix="examflow-inst-"), "t.db")
os.environ.setdefault("EXAMFLOW_SECRET", "s" * 20)
os.environ["EXAMFLOW_QUIET"] = "1"


class InstitutionTest(unittest.TestCase):
    def test_defaults_name_the_university_and_carry_no_secrets(self):
        import institution
        public = institution.public()
        self.assertEqual(public["name"], "Lovely Professional University")
        self.assertEqual(public["short"], "LPU")
        self.assertIn("Phagwara", public["address"])
        self.assertEqual(public["session"], "2026-27")
        for leaked in ("secret", "token", "password", "key"):
            self.assertNotIn(leaked, " ".join(public).lower())

    def test_environment_can_point_the_same_build_at_another_university(self):
        import importlib
        import institution
        os.environ["EXAMFLOW_INSTITUTION"] = "Example State University"
        os.environ["EXAMFLOW_INSTITUTION_SHORT"] = "ESU"
        try:
            reloaded = importlib.reload(institution)
            self.assertEqual(reloaded.public()["name"], "Example State University")
            self.assertEqual(reloaded.title("Examinations"), "Examinations · ESU")
        finally:
            del os.environ["EXAMFLOW_INSTITUTION"]
            del os.environ["EXAMFLOW_INSTITUTION_SHORT"]
            importlib.reload(institution)

    def test_a_fresh_dataset_speaks_the_university_vocabulary(self):
        import db
        db.init_db()
        conn = db.connect()
        try:
            codes = [row["school_code"] for row in conn.execute(
                "SELECT school_code FROM schools ORDER BY school_code")]
            self.assertEqual(codes, ["LFBA", "SCSE", "SEEE"])
            room = conn.execute(
                "SELECT * FROM rooms WHERE room_number='34-401'").fetchone()
            self.assertIsNotNone(room)
            self.assertEqual(room["building"], "Block 34")
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) c FROM examinations WHERE subject_code LIKE 'CSE%'"
            ).fetchone()["c"], 4)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) c FROM invigilators WHERE email LIKE '%@lpu.co.in'"
            ).fetchone()["c"], 12)
            self.assertEqual(conn.execute(
                "SELECT COUNT(*) c FROM student_groups WHERE group_name LIKE '%Physics%'"
            ).fetchone()["c"], 0)
        finally:
            conn.close()

    def test_re_cutting_an_old_dataset_renames_in_place_and_is_idempotent(self):
        import db
        import retheme
        db.init_db(seed=False)          # schema only, as an old deployment would look
        conn = db.connect()
        try:
            for table in ("schools", "rooms", "departments", "student_groups",
                          "examinations", "invigilators"):
                conn.execute("DELETE FROM %s" % table)   # start from an empty, older dataset
            school_id = db.new_id()
            conn.execute(
                """INSERT INTO schools (id, school_name, school_code, address, contact_email,
                   contact_number, status, created_at) VALUES (?,?,?,?,?,?,?,?)""",
                (school_id, "Northfield Institute of Technology", "NIT", "12 College Road",
                 "office@nit.example.edu", "+91 11 4000 1001", "Active", db.now_iso()))
            conn.execute(
                "INSERT INTO rooms (id, school_id, room_number, building, floor, capacity,"
                " room_type, is_accessible, facilities, is_active, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (db.new_id(), school_id, "N-101", "Main Block", 1, 120, "Computer Lab", 1,
                 db.encode_value([]), 1, db.now_iso()))
            conn.commit()

            first = retheme.apply(conn)
            self.assertEqual(first["changed"]["schools"], 1)
            self.assertEqual(first["changed"]["rooms"], 1)
            school = conn.execute("SELECT * FROM schools WHERE id=?", (school_id,)).fetchone()
            self.assertEqual(school["school_code"], "SCSE")
            self.assertEqual(school["school_name"],
                             "School of Computer Science and Engineering")
            self.assertIn("Phagwara", school["address"])
            room = conn.execute("SELECT * FROM rooms WHERE room_number='34-401'").fetchone()
            self.assertIsNotNone(room)

            second = retheme.apply(conn)
            self.assertEqual(set(second["changed"].values()), {0},
                             "a second run must leave every row alone")
        finally:
            db.close_quietly(conn) if hasattr(db, "close_quietly") else conn.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
