"""CSP solver: MRV + degree heuristic, LCV value ordering, forward checking,
constraint propagation and chronological backtracking.

Nothing is random: variable and value ordering are deterministic, so the same
dataset always yields the same schedule and the explanations stay reproducible.
"""
import time
from dataclasses import dataclass, field

from .constraints import (
    PRIORITY_RANK,
    Problem,
    RuleEngine,
    intervals_conflict,
    required_invigilators,
    slot_window,
    to_minutes,
)


@dataclass
class SolveResult:
    assignments: list = field(default_factory=list)
    unscheduled: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    explanations: list = field(default_factory=list)
    nodes_explored: int = 0
    backtracks: int = 0
    forward_checks: int = 0
    execution_time: float = 0.0
    solver_status: str = "UNKNOWN"
    soft_penalty: float = 0.0
    stats: dict = field(default_factory=dict)


def s1_of(slot):
    return to_minutes(slot["end_time"])


class CSPSolver:
    def __init__(self, problem: Problem, options: dict = None, node_limit: int = 200_000,
                 time_limit: float = 20.0):
        self.p = problem
        self.options = options or {}
        self.node_limit = node_limit
        self.time_limit = time_limit
        self.state = {"slot": {}, "room": {}, "invig": {}}
        self.engine = RuleEngine(problem, self.state)
        self.nodes = 0
        self.backtracks = 0
        self.forward_checks = 0
        self.started = time.time()
        self.deadline_hit = False
        self.conflicts = []

    # ----------------------------------------------------------- domain build
    def build_domains(self) -> dict:
        domains = {}
        for exam in self.p.examinations:
            candidates = []
            for slot in self.p.slot_order:
                for room in self.p.rooms:
                    if room.get("school_id") != exam.get("school_id"):
                        continue
                    if all(c.allowed for c in self.engine.check_assignment(exam, slot, room)):
                        candidates.append((slot["id"], room["id"]))
            domains[exam["id"]] = candidates
        return domains

    # ------------------------------------------------------------ heuristics
    def select_variable(self, unassigned, domains):
        best, best_key = None, None
        for exam_id in unassigned:
            exam = self.p.exam_by_id[exam_id]
            key = (len(domains[exam_id]),                                  # MRV
                   -self.p.conflict_degree.get(exam_id, 0),                # degree heuristic
                   PRIORITY_RANK.get(exam.get("priority"), 3),             # R7 critical first
                   exam_id)
            if best_key is None or key < best_key:
                best, best_key = exam_id, key
        return best

    def order_values(self, exam_id, domains, unassigned):
        exam = self.p.exam_by_id[exam_id]
        preferred = set(exam.get("preferred_dates") or [])
        scored = []
        for slot_id, room_id in domains[exam_id]:
            slot = self.p.slot_by_id[slot_id]
            room = self.p.room_by_id[room_id]
            eliminated = 0
            for other_id in unassigned:
                if other_id == exam_id:
                    continue
                for (s_id, r_id) in domains[other_id]:
                    if r_id == room_id and intervals_conflict(self.p.slot_by_id[s_id], slot):
                        eliminated += 1
                    elif s_id == slot_id and self._shares_group(exam_id, other_id):
                        eliminated += 1
            spare = int(room["capacity"]) - int(exam.get("required_seating_capacity") or 0)
            scored.append((eliminated, 0 if slot["examination_date"] in preferred else 1,
                           self.p.slot_rank.get(slot_id, 0), 0 if spare <= 60 else 1, room_id, slot_id))
        scored.sort()
        return [(s, r) for *_, r, s in scored]

    def _shares_group(self, a_id, b_id) -> bool:
        a = set(self.p.exam_by_id[a_id].get("student_group_ids") or [])
        b = set(self.p.exam_by_id[b_id].get("student_group_ids") or [])
        return bool(a & b)

    # --------------------------------------------------- forward checking
    def propagate(self, exam_id, slot, room_id, domains, unassigned) -> bool:
        for other_id in list(unassigned):
            if other_id == exam_id:
                continue
            remaining = []
            for (s_id, r_id) in domains[other_id]:
                self.forward_checks += 1
                if r_id == room_id and intervals_conflict(self.p.slot_by_id[s_id], slot):
                    continue
                if s_id == slot["id"] and self._shares_group(exam_id, other_id):
                    continue
                remaining.append((s_id, r_id))
            if not remaining:
                return False
            domains[other_id] = remaining
        return True

    # ------------------------------------------------------ backtracking
    def solve(self) -> SolveResult:
        domains = self.build_domains()
        empty_domains = [e["id"] for e in self.p.examinations if not domains.get(e["id"])]
        assignable = [e["id"] for e in self.p.examinations if domains.get(e["id"])]
        for exam_id in empty_domains:
            exam = self.p.exam_by_id[exam_id]
            self.conflicts.append({
                "conflict_type": "Unscheduled examination",
                "description": f"{exam['subject_name']} has no valid date/slot/room combination with the "
                               f"current constraints and resources.",
                "severity": "High", "affected_examination": exam_id,
                "suggested_resolution": "Add more rooms, extend the examination window or relax a hard policy.",
            })

        solved = self._backtrack(assignable, domains, {}) if assignable or not empty_domains else {}

        result = SolveResult()
        exact = solved is not None
        if solved is None:
            result.solver_status = "TIME_LIMIT_REACHED" if self.deadline_hit else "INFEASIBLE"
            # keep a maximal partial timetable instead of discarding all the work
            self.state = {"slot": {}, "room": {}, "invig": {}}
            self.engine = RuleEngine(self.p, self.state)
            partial = self._greedy_partial(assignable)
            solved = partial
            for exam_id in assignable:
                if exam_id in partial:
                    continue
                exam = self.p.exam_by_id[exam_id]
                self.conflicts.append({
                    "conflict_type": "Unscheduled examination",
                    "description": f"No consistent assignment found for {exam['subject_name']} within "
                                   f"{self.nodes} nodes explored; it is left unscheduled.",
                    "severity": "Critical", "affected_examination": exam_id,
                    "suggested_resolution": "Increase slots/rooms or relax hard policies.",
                })
        if solved is not None:
            self.state["slot"] = {k: v[0] for k, v in solved.items()}
            self.state["room"] = {k: v[1] for k, v in solved.items()}
            allocations = self.allocate_invigilators(solved)
            for exam_id, (slot_id, room_id) in solved.items():
                slot = self.p.slot_by_id[slot_id]
                exam = self.p.exam_by_id[exam_id]
                alloc = allocations.get(exam_id, {})
                result.assignments.append({
                    "examination_id": exam_id, "room_id": room_id, "time_slot_id": slot_id,
                    "examination_date": slot["examination_date"], "start_time": slot["start_time"],
                    "end_time": slot["end_time"], "priority": exam.get("priority"),
                    "assignment_status": "Understaffed" if alloc.get("understaffed") else "Scheduled",
                    "invigilator_ids": alloc.get("ids", []), "invigilators": alloc.get("names", []),
                })
                if room_id and room_id in self.p.room_by_id and slot_id in self.p.slot_by_id:
                    result.explanations.append(
                        self.explain(exam, slot, self.p.room_by_id[room_id], domains, len(solved)))
            if exact and all(k in solved for k in assignable):
                result.solver_status = "FEASIBLE_BUT_NOT_PROVEN_OPTIMAL"
            elif result.solver_status == "UNKNOWN":
                result.solver_status = "INFEASIBLE"

        placed = set((solved or {}).keys())
        result.unscheduled = [
            {"examination_id": eid, "subject_name": self.p.exam_by_id[eid]["subject_name"],
             "reason": "No valid date/slot/room combination" if not domains.get(eid)
                       else "No conflict-free placement found"}
            for eid in [e["id"] for e in self.p.examinations] if eid not in placed
        ]
        result.nodes_explored = self.nodes
        result.backtracks = self.backtracks
        result.forward_checks = self.forward_checks
        result.execution_time = round(time.time() - self.started, 4)
        result.conflicts.extend(self.conflicts)
        result.soft_penalty = self.compute_soft_penalty(result.assignments)
        result.stats = {
            "algorithm": "CSP (MRV + Degree + LCV + Forward Checking + Backtracking)",
            "nodes_explored": self.nodes, "backtracks": self.backtracks,
            "forward_checks": self.forward_checks,
            "domains": {k: len(v) for k, v in domains.items()},
        }
        return result

    def _greedy_partial(self, exam_ids):
        """Best-effort placement used when the exact search proves infeasible.
        Deterministic, respects every hard rule, maximises the number placed."""
        placed = {}
        pending = list(exam_ids)
        progress = True
        while pending and progress:
            progress = False
            for exam_id in sorted(pending, key=lambda e: (
                    len(self._candidate_pairs(e)), PRIORITY_RANK.get(
                        self.p.exam_by_id[e].get("priority"), 3), e)):
                for slot_id, room_id in self._candidate_pairs(exam_id):
                    slot = self.p.slot_by_id[slot_id]
                    room = self.p.room_by_id[room_id]
                    self.state["slot"][exam_id] = slot_id
                    self.state["room"][exam_id] = room_id
                    self.engine._testing_exam = exam_id
                    if all(c.allowed for c in self.engine.check_assignment(
                            self.p.exam_by_id[exam_id], slot, room)):
                        placed[exam_id] = (slot_id, room_id)
                        pending.remove(exam_id)
                        progress = True
                        break
                    self.state["slot"].pop(exam_id, None)
                    self.state["room"].pop(exam_id, None)
        self.engine._testing_exam = None
        return placed

    def _candidate_pairs(self, exam_id):
        exam = self.p.exam_by_id[exam_id]
        pairs = []
        for slot in self.p.slot_order:
            for room in self.p.rooms:
                if room.get("school_id") != exam.get("school_id") or not room.get("is_active", 1):
                    continue
                if int(room.get("capacity") or 0) < int(exam.get("required_seating_capacity") or 0):
                    continue
                if self.p.required_facility_policy():
                    need = {f.lower() for f in (exam.get("required_facilities") or [])}
                    have = {f.lower() for f in (room.get("facilities") or [])}
                    if need - have:
                        continue
                if slot_window(slot)[1] - slot_window(slot)[0] < int(exam.get("duration_minutes") or 0):
                    continue
                if not slot.get("is_active", 1):
                    continue
                pairs.append((slot["id"], room["id"]))
        return pairs

    def _backtrack(self, unassigned, domains, assigned):
        if not unassigned:
            return assigned
        self.nodes += 1
        if self.nodes > self.node_limit or (time.time() - self.started) > self.time_limit:
            self.deadline_hit = True
            return None

        exam_id = self.select_variable(unassigned, domains)
        rest = [e for e in unassigned if e != exam_id]

        for slot_id, room_id in self.order_values(exam_id, domains, unassigned):
            slot = self.p.slot_by_id[slot_id]
            room = self.p.room_by_id[room_id]
            self.state["slot"][exam_id] = slot_id
            self.state["room"][exam_id] = room_id
            self.engine._testing_exam = exam_id
            if not all(c.allowed for c in self.engine.check_assignment(self.p.exam_by_id[exam_id], slot, room)):
                self.state["slot"].pop(exam_id, None)
                self.state["room"].pop(exam_id, None)
                continue

            snapshot = {k: list(v) for k, v in domains.items()}
            if self.propagate(exam_id, slot, room_id, domains, rest):
                assigned[exam_id] = (slot_id, room_id)
                solved = self._backtrack(rest, domains, assigned)
                if solved is not None:
                    return solved
                assigned.pop(exam_id, None)
            self.backtracks += 1
            domains.clear()
            domains.update(snapshot)
            self.state["slot"].pop(exam_id, None)
            self.state["room"].pop(exam_id, None)
        return None

    # ------------------------------------------------ invigilator allocation
    def allocate_invigilators(self, solved: dict) -> dict:
        ordered = sorted(solved.items(), key=lambda kv: (
            self.p.slot_rank.get(kv[1][0], 0),
            PRIORITY_RANK.get(self.p.exam_by_id[kv[0]].get("priority"), 3)))
        allocations = {}
        self.state["invig"] = {}
        consecutive_policy = self.p.weight("avoid_consecutive_duties", 1.0)
        for exam_id, (slot_id, room_id) in ordered:
            exam = self.p.exam_by_id[exam_id]
            slot = self.p.slot_by_id[slot_id]
            need = required_invigilators(exam)
            chosen, chosen_names = [], []
            pool = [i for i in self.p.invigilators if i.get("status") == "Active"]
            pool.sort(key=lambda i: (
                self._load(i["id"]),
                self._daily(i["id"], slot["examination_date"]),
                abs(int(i.get("preferred_duties") or 0) - self._load(i["id"])),
                i["id"],
            ))
            for inv in pool:
                if len(chosen) >= need:
                    break
                if not all(c.allowed for c in self.engine.check_invigilator(exam, slot, inv)):
                    continue
                if self._would_be_consecutive(inv["id"], slot) and consecutive_policy and chosen:
                    continue
                chosen.append(inv["id"])
                chosen_names.append(inv["name"])
                self.state["invig"].setdefault(exam_id, []).append(inv["id"])
            if len(chosen) < need:
                self.conflicts.append({
                    "conflict_type": "Invigilator unavailability",
                    "description": f"{exam['subject_name']} needs {need} invigilator(s) but only "
                                   f"{len(chosen)} eligible one(s) were available at {slot['start_time']} "
                                   f"on {slot['examination_date']}.",
                    "severity": "High", "affected_examination": exam_id,
                    "suggested_resolution": "Add availability for more faculty or move the examination.",
                })
            allocations[exam_id] = {"ids": chosen, "names": chosen_names,
                                    "understaffed": len(chosen) < need, "required": need}
        return allocations

    def _load(self, inv_id):
        return sum(1 for ids in self.state["invig"].values() if inv_id in ids)

    def _daily(self, inv_id, date):
        total = 0
        for exam_id, ids in self.state["invig"].items():
            if inv_id in ids:
                slot = self.p.slot_by_id.get(self.state["slot"].get(exam_id))
                if slot and slot["examination_date"] == date:
                    total += 1
        return total

    def _would_be_consecutive(self, inv_id, slot):
        s0, _ = slot_window(slot)
        for exam_id, ids in self.state["invig"].items():
            if inv_id not in ids:
                continue
            other = self.p.slot_by_id.get(self.state["slot"].get(exam_id))
            if not other or other["examination_date"] != slot["examination_date"]:
                continue
            o0, o1 = slot_window(other)
            if abs(o0 - s1_of(slot)) <= 150 or abs(s0 - o1) <= 150:
                return True
        return False

    # ---------------------------------------------------------- soft penalty
    def compute_soft_penalty(self, assignments) -> float:
        if not assignments:
            return 0.0
        penalty = 0.0
        w_pref = self.p.weight("preferred_dates", 3.0)
        w_priority = self.p.weight("priority_ordering", 2.0)
        w_consecutive = self.p.weight("avoid_consecutive_duties", 2.0)
        w_room = self.p.weight("room_utilization", 1.0)
        w_gap = self.p.weight("reduce_gaps", 1.0)
        w_balance = self.p.weight("workload_balance", 4.0)

        for a in assignments:
            exam = self.p.exam_by_id[a["examination_id"]]
            preferred = exam.get("preferred_dates") or []
            if preferred and a["examination_date"] not in preferred:
                penalty += w_pref
            day = self.p.date_rank.get(a["examination_date"], 0)
            span = max(1, len(self.p.date_rank) - 1)
            priority_factor = {"Critical": 3, "High": 2, "Medium": 1, "Low": 0.5}.get(exam.get("priority"), 1)
            penalty += w_priority * priority_factor * (day / span)
            room = self.p.room_by_id.get(a["room_id"])
            if room and room["capacity"]:
                waste = (room["capacity"] - (exam.get("required_seating_capacity") or 0)) / room["capacity"]
                penalty += w_room * max(0.0, waste)

        loads = {i["id"]: 0 for i in self.p.invigilators}
        for a in assignments:
            for inv_id in a.get("invigilator_ids") or []:
                loads[inv_id] = loads.get(inv_id, 0) + 1
        per_date = {}
        for a in assignments:
            per_date[a["examination_date"]] = per_date.get(a["examination_date"], 0) + 1
        for date, count in per_date.items():
            if count > 6:
                penalty += w_gap * (count - 6)

        invs = [i for i in self.p.invigilators if i.get("status") == "Active"]
        if invs:
            values = [loads.get(i["id"], 0) for i in invs]
            avg = sum(values) / len(values)
            variance = sum((v - avg) ** 2 for v in values) / len(values)
            penalty += w_balance * (variance ** 0.5)
            for i in invs:
                if loads.get(i["id"], 0) > max(1, avg) * 1.5:
                    penalty += w_consecutive
        return round(penalty, 2)

    # ------------------------------------------------------------ explanation
    def explain(self, exam, slot, room, domains, assigned_count) -> dict:
        domain_count = len(domains.get(exam["id"], [])) or 0
        students = exam.get("required_seating_capacity") or 0
        preferred = exam.get("preferred_dates") or []
        satisfied = [
            f"Room {room['room_number']} capacity {room['capacity']} >= required {students}",
            "No student group overlap with already placed examinations",
            f"Room {room['room_number']} free for {slot['start_time']}-{slot['end_time']}",
            f"Slot length covers the {exam['duration_minutes']} minute duration",
        ]
        if preferred:
            satisfied.append("Falls on a preferred date" if slot["examination_date"] in preferred
                             else "Preferred dates were unavailable, so the nearest feasible date was used")
        if exam.get("required_facilities"):
            satisfied.append("All required facilities present: " + ", ".join(exam["required_facilities"]))

        rejected = []
        for slot_id, room_id in domains.get(exam["id"], [])[:8]:
            if slot_id == slot["id"] and room_id == room["id"]:
                continue
            alt_slot = self.p.slot_by_id[slot_id]
            alt_room = self.p.room_by_id[room_id]
            if alt_room["id"] != room["id"] and int(alt_room["capacity"]) < students:
                reason = f"Room {alt_room['room_number']} too small ({alt_room['capacity']} < {students})"
            elif alt_slot["id"] != slot["id"] and self.p.slot_rank.get(alt_slot["id"], 0) < \
                    self.p.slot_rank.get(slot["id"], 0):
                reason = (f"Earlier slot {alt_slot['start_time']} on {alt_slot['examination_date']} "
                          f"constrained too many other examinations")
            else:
                reason = "Reserved for examinations with fewer remaining options (LCV ordering)"
            rejected.append({"date": alt_slot["examination_date"], "time": alt_slot["start_time"],
                             "room": alt_room["room_number"], "reason": reason})
            if len(rejected) >= 4:
                break

        reason_text = (
            f"{exam['subject_name']} was placed in room {room['room_number']} on {slot['examination_date']} "
            f"at {slot['start_time']}-{slot['end_time']}. The solver considered {domain_count} feasible "
            f"date/room combinations for this examination. This value was chosen because it removed the "
            f"fewest options from the remaining {max(0, assigned_count - 1)} examinations (Least Constraining "
            f"Value), the room seats {room['capacity']} for {students} candidates, and no student-group or "
            f"room overlap was introduced."
        )
        return {"examination_id": exam["id"], "decision_reason": reason_text,
                "alternatives_considered": domain_count, "constraints_satisfied": satisfied,
                "rejected_alternatives": rejected, "explanation_type": "assignment"}
