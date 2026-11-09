"""First-Fit greedy baseline.

Examinations are processed in a fixed order (priority, then subject code). Each
one takes the first slot/room combination that satisfies every hard rule. No
look-ahead and no look-back: this is the baseline the AI search is measured
against, and it allocates invigilators naively so the fairness comparison is real.
"""
import time

from .constraints import PRIORITY_RANK, Problem, RuleEngine, required_invigilators
from .csp import CSPSolver, SolveResult


class FirstFitSolver:
    def __init__(self, problem: Problem, options: dict = None):
        self.p = problem
        self.options = options or {}
        self.state = {"slot": {}, "room": {}, "invig": {}}
        self.engine = RuleEngine(problem, self.state)

    def solve(self) -> SolveResult:
        started = time.time()
        result = SolveResult()
        ordered = sorted(self.p.examinations, key=lambda e: (
            PRIORITY_RANK.get(e.get("priority"), 3), e.get("subject_code") or "", e["id"]))

        for exam in ordered:
            placed = False
            for slot in self.p.slot_order:
                for room in sorted(self.p.rooms, key=lambda r: (r["capacity"], r["room_number"])):
                    if not all(c.allowed for c in self.engine.check_assignment(exam, slot, room)):
                        continue
                    self.state["slot"][exam["id"]] = slot["id"]
                    self.state["room"][exam["id"]] = room["id"]
                    result.assignments.append({
                        "examination_id": exam["id"], "room_id": room["id"], "time_slot_id": slot["id"],
                        "examination_date": slot["examination_date"], "start_time": slot["start_time"],
                        "end_time": slot["end_time"], "priority": exam.get("priority"),
                        "assignment_status": "Scheduled", "invigilator_ids": [], "invigilators": [],
                    })
                    result.explanations.append({
                        "examination_id": exam["id"],
                        "decision_reason": (
                            f"First-Fit placed {exam['subject_name']} in the first slot/room pair that "
                            f"satisfied every hard rule: {slot['examination_date']} {slot['start_time']} in "
                            f"room {room['room_number']}. No look-ahead is performed, so this choice may "
                            f"reduce the options left for later examinations."),
                        "alternatives_considered": 1,
                        "constraints_satisfied": [
                            f"Room capacity {room['capacity']} >= {exam.get('required_seating_capacity')}",
                            "No group or room conflict at insertion time"],
                        "rejected_alternatives": [], "explanation_type": "assignment",
                    })
                    placed = True
                    break
                if placed:
                    break
            if not placed:
                result.unscheduled.append({"examination_id": exam["id"],
                                           "subject_name": exam["subject_name"],
                                           "reason": "No valid slot/room available in first-fit order"})

        # naive invigilator allocation (first eligible person by id) - intentionally unbalanced
        result.conflicts = []
        inv_state = {"slot": dict(self.state["slot"]), "room": dict(self.state["room"]), "invig": {}}
        engine = RuleEngine(self.p, inv_state)
        for a in result.assignments:
            exam = self.p.exam_by_id[a["examination_id"]]
            slot = self.p.slot_by_id[a["time_slot_id"]]
            need = required_invigilators(exam)
            chosen = []
            for inv in sorted(self.p.invigilators, key=lambda i: i["id"]):
                if len(chosen) >= need:
                    break
                if all(c.allowed for c in engine.check_invigilator(exam, slot, inv)):
                    chosen.append(inv["id"])
            inv_state["invig"][a["examination_id"]] = chosen
            a["invigilator_ids"] = chosen
            a["invigilators"] = [self.p.inv_by_id[i]["name"] for i in chosen if i in self.p.inv_by_id]
            if len(chosen) < need:
                a["assignment_status"] = "Understaffed"
                result.conflicts.append({
                    "conflict_type": "Invigilator unavailability",
                    "description": f"First-Fit found only {len(chosen)} of {need} invigilator(s) for "
                                   f"{exam['subject_name']} at {slot['start_time']} on "
                                   f"{slot['examination_date']}.",
                    "severity": "High", "affected_examination": exam["id"],
                    "suggested_resolution": "Use the AI allocator or add eligible faculty.",
                })
        allocator = CSPSolver(self.p)
        allocator.state = inv_state
        allocator.engine = RuleEngine(self.p, inv_state)

        for u in result.unscheduled:
            exam = self.p.exam_by_id[u["examination_id"]]
            result.conflicts.append({
                "conflict_type": "Unscheduled examination",
                "description": f"First-Fit could not place {exam['subject_name']} without breaking a hard rule.",
                "severity": "High", "affected_examination": exam["id"],
                "suggested_resolution": "Re-run with the AI search, add rooms or extend the slot window.",
            })
        result.soft_penalty = allocator.compute_soft_penalty(result.assignments)
        result.execution_time = round(time.time() - started, 4)
        result.stats = {"algorithm": "First-Fit greedy baseline", "nodes_explored": len(ordered),
                        "backtracks": 0, "forward_checks": 0}
        result.solver_status = ("INFEASIBLE" if result.unscheduled
                                else "FEASIBLE_BUT_NOT_PROVEN_OPTIMAL")
        return result
