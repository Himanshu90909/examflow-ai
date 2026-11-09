"""Engine tests: constraints, solver behaviour, fairness and validation.

Run with either:
    python3 tests/test_engine.py          (unittest, no dependencies)
    python3 -m pytest tests/test_engine.py
"""
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(os.path.dirname(HERE), "server")
sys.path.insert(0, SERVER)

TMP_DB = os.path.join(tempfile.gettempdir(), "examflow-test.db")
if os.path.exists(TMP_DB):
    os.remove(TMP_DB)
os.environ["EXAMFLOW_DB"] = TMP_DB

import db  # noqa: E402
import solver_service  # noqa: E402
from scheduler import conflicts as conflict_engine  # noqa: E402
from scheduler import fairness as fairness_engine  # noqa: E402
from scheduler.constraints import (  # noqa: E402
    Problem, RuleEngine, required_invigilators, to_minutes,
)
from scheduler.csp import CSPSolver  # noqa: E402
from scheduler.firstfit import FirstFitSolver  # noqa: E402


def setUpModule():
    db.init_db(seed=True)


def _admin():
    conn = db.connect()
    user = db.decode_row("users", conn.execute(
        "SELECT * FROM users WHERE role='Super Admin' LIMIT 1").fetchone())
    conn.close()
    return user


def _mini_problem(exams, rooms, slots, invs, policies=None, config=None):
    return Problem(examinations=exams, rooms=rooms, slots=slots, invigilators=invs,
                   availability=[], policies=policies or [], config=config or {})


def _exam(eid, groups, students, duration=120, priority="Medium", school="s1"):
    return {"id": eid, "subject_name": f"Subject {eid}", "subject_code": eid.upper(),
            "school_id": school, "department_id": "d1", "student_group_ids": groups,
            "required_seating_capacity": students, "duration_minutes": duration,
            "priority": priority, "preferred_dates": [], "required_facilities": [],
            "status": "Pending"}


def _room(rid, capacity, school="s1", facilities=None):
    return {"id": rid, "room_number": rid.upper(), "capacity": capacity, "school_id": school,
            "is_active": 1, "facilities": facilities or []}


def _slot(sid, date, start, end, session="Morning"):
    return {"id": sid, "examination_date": date, "start_time": start, "end_time": end,
            "session": session, "is_active": 1}


def _inv(iid, school="s1", daily=2, total=10, status="Active"):
    return {"id": iid, "name": iid.upper(), "employee_code": iid.upper(), "school_id": school,
            "maximum_daily_duties": daily, "maximum_total_duties": total,
            "preferred_duties": 0, "status": status}


class RuleTests(unittest.TestCase):
    def test_invigilator_ratio_rule(self):
        self.assertEqual(required_invigilators({"required_seating_capacity": 20}), 1)
        self.assertEqual(required_invigilators({"required_seating_capacity": 90}), 2)
        self.assertEqual(required_invigilators({"required_seating_capacity": 1000}), 2)

    def test_capacity_rule_rejects_small_room(self):
        problem = _mini_problem([_exam("e1", ["g1"], 100)], [_room("r1", 60)],
                                [_slot("s1", "2026-11-16", "09:00", "12:00")], [_inv("i1")])
        engine = RuleEngine(problem, {"slot": {}, "room": {}, "invig": {}})
        results = engine.check_assignment(problem.exam_by_id["e1"], problem.slot_by_id["s1"],
                                          problem.room_by_id["r1"])
        self.assertFalse(all(r.allowed for r in results))
        self.assertTrue(any(not r.allowed for r in results))

    def test_daily_limit_rule(self):
        problem = _mini_problem([_exam("e1", ["g1"], 30), _exam("e2", ["g2"], 30)],
                                [_room("r1", 50)],
                                [_slot("s1", "2026-11-16", "09:00", "11:00"),
                                 _slot("s2", "2026-11-16", "14:00", "16:00")],
                                [_inv("i1", daily=1)])
        state = {"slot": {"e1": "s1"}, "room": {"e1": "r1"}, "invig": {"e1": ["i1"]}}
        engine = RuleEngine(problem, state)
        results = engine.check_invigilator(problem.exam_by_id["e2"], problem.slot_by_id["s2"],
                                           problem.inv_by_id["i1"])
        self.assertFalse(all(r.allowed for r in results))


class SolverTests(unittest.TestCase):
    def test_group_overlap_never_produced(self):
        problem = _mini_problem(
            [_exam("e1", ["g1"], 40), _exam("e2", ["g1"], 40), _exam("e3", ["g2"], 40)],
            [_room("r1", 60)], [_slot("s1", "2026-11-16", "09:00", "11:00"),
                                _slot("s2", "2026-11-16", "14:00", "16:00"),
                                _slot("s3", "2026-11-17", "09:00", "11:00")],
            [_inv("i1"), _inv("i2"), _inv("i3")])
        result = CSPSolver(problem).solve()
        self.assertEqual(len(result.assignments), 3)
        conflicts = conflict_engine.ConflictEngine(problem).validate(result.assignments)
        self.assertEqual([c for c in conflicts if c["severity"] == "Critical"], [])

    def test_room_double_booking_never_produced(self):
        problem = _mini_problem([_exam("e1", ["g1"], 30), _exam("e2", ["g2"], 30)],
                                [_room("r1", 40)],
                                [_slot("s1", "2026-11-16", "09:00", "11:00")],
                                [_inv("i1"), _inv("i2")])
        result = CSPSolver(problem).solve()
        self.assertEqual(len(result.assignments), 1)
        self.assertEqual(len(result.unscheduled), 1)

    def test_infeasible_when_no_room_fits(self):
        problem = _mini_problem([_exam("e1", ["g1"], 500)], [_room("r1", 40)],
                                [_slot("s1", "2026-11-16", "09:00", "11:00")], [_inv("i1")])
        result = CSPSolver(problem).solve()
        self.assertEqual(result.assignments, [])
        self.assertEqual(len(result.unscheduled), 1)
        self.assertTrue(any(c["conflict_type"] == "Unscheduled examination" for c in result.conflicts))

    def test_time_limit_status_reported(self):
        problem = _mini_problem([_exam("e1", ["g1"], 10)], [_room("r1", 40)],
                                [_slot("s1", "2026-11-16", "09:00", "11:00")], [_inv("i1")])
        solver = CSPSolver(problem, node_limit=1)
        result = solver.solve()
        self.assertIn(result.solver_status, ("FEASIBLE_BUT_NOT_PROVEN_OPTIMAL", "TIME_LIMIT_REACHED"))

    def test_solver_is_deterministic(self):
        problem = _mini_problem([_exam("e1", ["g1"], 30), _exam("e2", ["g2"], 30)],
                                [_room("r1", 50)], [_slot("s1", "2026-11-16", "09:00", "11:00"),
                                                    _slot("s2", "2026-11-17", "09:00", "11:00")],
                                [_inv("i1"), _inv("i2")])
        first = CSPSolver(problem).solve()
        second = CSPSolver(problem).solve()
        self.assertEqual([(a["examination_id"], a["time_slot_id"], a["room_id"]) for a in first.assignments],
                         [(a["examination_id"], a["time_slot_id"], a["room_id"]) for a in second.assignments])


class FairnessTests(unittest.TestCase):
    def test_fairness_score_formula(self):
        problem = _mini_problem([_exam("e1", ["g1"], 30), _exam("e2", ["g2"], 30)],
                                [_room("r1", 50)], [_slot("s1", "2026-11-16", "09:00", "11:00"),
                                                    _slot("s2", "2026-11-17", "09:00", "11:00")],
                                [_inv("i1"), _inv("i2")])
        assignments = [
            {"examination_id": "e1", "time_slot_id": "s1", "examination_date": "2026-11-16",
             "start_time": "09:00", "end_time": "11:00", "invigilator_ids": ["i1"]},
            {"examination_id": "e2", "time_slot_id": "s2", "examination_date": "2026-11-17",
             "start_time": "09:00", "end_time": "11:00", "invigilator_ids": ["i1"]},
        ]
        report = fairness_engine.evaluate(problem, assignments)
        summary = report["summary"]
        self.assertEqual(summary["total_assigned_duties"], 2)
        self.assertEqual(summary["average_workload"], 1.0)
        self.assertEqual(summary["maximum_workload"], 2)
        self.assertEqual(summary["minimum_workload"], 0)
        # sd = 1.0, mean = 1.0 -> score = 100 * (1 - 1) = 0
        self.assertAlmostEqual(summary["fairness_score"], 0.0, places=1)
        self.assertGreater(len(report["metrics"]), 5)

    def test_balanced_allocation_scores_higher(self):
        problem = _mini_problem([_exam("e1", ["g1"], 30), _exam("e2", ["g2"], 30)],
                                [_room("r1", 50)], [_slot("s1", "2026-11-16", "09:00", "11:00"),
                                                    _slot("s2", "2026-11-17", "09:00", "11:00")],
                                [_inv("i1"), _inv("i2")])
        balanced = [
            {"examination_id": "e1", "time_slot_id": "s1", "examination_date": "2026-11-16",
             "start_time": "09:00", "end_time": "11:00", "invigilator_ids": ["i1"]},
            {"examination_id": "e2", "time_slot_id": "s2", "examination_date": "2026-11-17",
             "start_time": "09:00", "end_time": "11:00", "invigilator_ids": ["i2"]},
        ]
        score = fairness_engine.evaluate(problem, balanced)["summary"]["fairness_score"]
        self.assertGreater(score, 90)


class IntegrationTests(unittest.TestCase):
    """End-to-end runs against the seeded database."""

    @classmethod
    def setUpClass(cls):
        cls.conn = db.connect()
        cls.admin = _admin()
        cls.csp = solver_service.run_schedule(cls.conn, cls.admin, {
            "algorithm": "csp", "run_name": "test csp", "options": {"auto_repair": True}})
        cls.ff = solver_service.run_schedule(cls.conn, cls.admin, {
            "algorithm": "first_fit", "run_name": "test first-fit", "options": {}})

    @classmethod
    def tearDownClass(cls):
        cls.conn.close()

    def test_all_examinations_scheduled(self):
        self.assertEqual(self.csp["scheduled_examinations"], self.csp["total_examinations"])
        self.assertEqual(self.csp["unscheduled_examinations"], 0)

    def test_hard_constraints_satisfied(self):
        result = solver_service.validate_run(self.conn, self.csp["id"])
        self.assertEqual(result["hard"], [])
        self.assertTrue(result["feasible"])

    def test_ai_beats_first_fit_on_soft_penalty(self):
        self.assertLessEqual(self.csp["soft_constraint_penalty"], self.ff["soft_constraint_penalty"])

    def test_ai_beats_first_fit_on_balance(self):
        self.assertLessEqual(self.csp["fairness"]["summary"]["standard_deviation"] + 0.001,
                             self.ff["fairness"]["summary"]["standard_deviation"])

    def test_explanations_stored_for_every_assignment(self):
        assignments = solver_service.assignments_for_run(self.conn, self.csp["id"])
        self.assertTrue(assignments)
        with_explanation = [a for a in assignments if a.get("explanation")]
        self.assertEqual(len(with_explanation), len(assignments))

    def test_publish_requires_valid_timetable(self):
        fresh = solver_service.run_schedule(self.conn, self.admin, {
            "algorithm": "csp", "run_name": "publish test", "options": {"auto_repair": True}})
        solver_service.publish_run(self.conn, self.admin, fresh["id"])
        published = solver_service.get_run(self.conn, fresh["id"])
        self.assertEqual(published["status"], "Published")
        self.assertIsNotNone(published["published_at"])

    def test_validator_catches_injected_clash(self):
        run = solver_service.run_schedule(self.conn, self.admin, {
            "algorithm": "csp", "run_name": "validator test", "options": {"auto_repair": True}})
        assignments = solver_service.assignments_for_run(self.conn, run["id"])
        pair = None
        for i, a in enumerate(assignments):
            for b in assignments[i + 1:]:
                if set(a["student_group_ids"]) & set(b["student_group_ids"]):
                    pair = (a, b)
                    break
            if pair:
                break
        self.assertIsNotNone(pair)
        a, b = pair
        self.conn.execute("UPDATE schedule_assignments SET time_slot_id=?, room_id=? WHERE id=?",
                          (a["time_slot_id"], b["room_id"], b["id"]))
        self.conn.commit()
        result = solver_service.validate_run(self.conn, run["id"])
        self.assertFalse(result["feasible"])
        self.assertTrue(any(c["conflict_type"] == "Student group overlap" for c in result["hard"]))
        with self.assertRaises(Exception):
            solver_service.publish_run(self.conn, self.admin, run["id"])
        # repair restores feasibility
        repaired = solver_service.repair_run(self.conn, self.admin, run["id"])
        self.assertEqual(repaired["hard"], [])
        solver_service.publish_run(self.conn, self.admin, run["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
