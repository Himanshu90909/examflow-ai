"""Constraint model and production rule engine for ExamFlow AI.

The scheduling engine is dependency-free so it runs inside the project's own
backend. Every rule that can reject a candidate lives here, so the CSP solver,
the First-Fit baseline, the conflict detector and the post-publish validator all
share exactly the same semantics.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


# ---------------------------------------------------------------- time helpers
def to_minutes(hhmm: str) -> int:
    if not hhmm:
        return 0
    parts = str(hhmm).strip().split(":")
    return int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)


def slot_window(slot: dict) -> Tuple[int, int]:
    return to_minutes(slot["start_time"]), to_minutes(slot["end_time"])


def ranges_overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def intervals_conflict(slot_a: dict, slot_b: dict) -> bool:
    if slot_a["examination_date"] != slot_b["examination_date"]:
        return False
    a0, a1 = slot_window(slot_a)
    b0, b1 = slot_window(slot_b)
    return ranges_overlap(a0, a1, b0, b1)


PRIORITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def required_invigilators(examination: dict) -> int:
    """Project rule: one invigilator per 75 candidates, minimum one, maximum two."""
    students = int(examination.get("required_seating_capacity") or 0)
    return max(1, min(2, -(-students // 75)))


# ------------------------------------------------------------- problem wrapper
@dataclass
class Problem:
    examinations: List[dict]
    rooms: List[dict]
    slots: List[dict]
    invigilators: List[dict]
    availability: List[dict]
    policies: List[dict] = field(default_factory=list)
    config: dict = field(default_factory=dict)

    def __post_init__(self):
        self.exam_by_id = {e["id"]: e for e in self.examinations}
        self.room_by_id = {r["id"]: r for r in self.rooms}
        self.slot_by_id = {s["id"]: s for s in self.slots}
        self.inv_by_id = {i["id"]: i for i in self.invigilators}
        self.slot_order = sorted(self.slots, key=lambda s: (s["examination_date"], s["start_time"]))
        self.slot_rank = {s["id"]: i for i, s in enumerate(self.slot_order)}
        self.date_rank = {}
        for s in self.slot_order:
            self.date_rank.setdefault(s["examination_date"], len(self.date_rank))
        self.group_index: Dict[str, List[str]] = {}
        for e in self.examinations:
            for gid in e.get("student_group_ids") or []:
                self.group_index.setdefault(gid, []).append(e["id"])
        self.conflict_degree = {
            e["id"]: len({x for gid in (e.get("student_group_ids") or [])
                          for x in self.group_index.get(gid, [])} - {e["id"]})
            for e in self.examinations
        }
        self.policy = {p.get("rule_code") or p["policy_name"]: p for p in self.policies}

    def policy_on(self, code: str) -> bool:
        p = self.policy.get(code)
        return bool(p and p.get("is_enabled"))

    def weight(self, code: str, default: float = 1.0) -> float:
        p = self.policy.get(code)
        return float(p.get("penalty_weight") or default) if p else default

    def required_facility_policy(self) -> bool:
        return self.policy_on("room_facilities")


# --------------------------------------------------------------- rule engine
@dataclass
class RuleResult:
    allowed: bool
    rule: str
    reason: str = ""
    conflict_type: str = ""

    def reject(self):
        return not self.allowed


class RuleEngine:
    """IF-THEN production rules. First rejection wins; every rejection is explained."""

    def __init__(self, problem: Problem, state: dict, testing_exam: str = None):
        self.p = problem
        self.state = state
        self._testing_exam = testing_exam

    # ---- helpers
    def _assigned_slot(self, exam_id):
        sid = self.state["slot"].get(exam_id)
        return self.p.slot_by_id.get(sid) if sid else None

    def _invigilator_load(self, inv_id, date=None):
        total = 0
        daily = 0
        for exam_id, ids in self.state.get("invig", {}).items():
            if inv_id not in ids:
                continue
            total += 1
            slot = self._assigned_slot(exam_id)
            if date and slot and slot["examination_date"] == date:
                daily += 1
        return total, daily

    # ---- R1 room capacity
    def r1_room_capacity(self, exam, room) -> RuleResult:
        need = int(exam.get("required_seating_capacity") or 0)
        if int(room.get("capacity") or 0) < need:
            return RuleResult(False, "R1_ROOM_CAPACITY",
                              f"Room {room['room_number']} seats {room['capacity']} but {exam['subject_name']} "
                              f"needs {need}.", "Insufficient seating capacity")
        return RuleResult(True, "R1_ROOM_CAPACITY")

    # ---- R2 invigilator availability
    def r2_availability(self, inv, slot) -> RuleResult:
        date = slot["examination_date"]
        s0, s1 = slot_window(slot)
        for record in self.p.config.get("availability_by_inv", {}).get(inv["id"], []):
            if record["date"] != date:
                continue
            if record["availability_status"] in ("Unavailable", "Leave"):
                r0 = to_minutes(record["start_time"]) if record.get("start_time") else 0
                r1 = to_minutes(record["end_time"]) if record.get("end_time") else 24 * 60
                if ranges_overlap(s0, s1, r0, r1):
                    return RuleResult(False, "R2_INVIGILATOR_AVAILABILITY",
                                      f"{inv['name']} is marked {record['availability_status']} on {date}"
                                      + (f" ({record.get('reason')})" if record.get("reason") else "") + ".",
                                      "Invigilator unavailable")
        return RuleResult(True, "R2_INVIGILATOR_AVAILABILITY")

    # ---- R3 daily duty limit
    def r3_daily_limit(self, inv, slot) -> RuleResult:
        _, daily = self._invigilator_load(inv["id"], slot["examination_date"])
        if daily >= int(inv.get("maximum_daily_duties") or 0):
            return RuleResult(False, "R3_DAILY_DUTY_LIMIT",
                              f"{inv['name']} already has {daily} duty(ies) on {slot['examination_date']} "
                              f"(limit {inv['maximum_daily_duties']}).", "Maximum duty limit exceeded")
        return RuleResult(True, "R3_DAILY_DUTY_LIMIT")

    # ---- R4 shared student group
    def r4_group_overlap(self, exam, slot) -> RuleResult:
        for gid in exam.get("student_group_ids") or []:
            for other_id in self.p.group_index.get(gid, []):
                if other_id == exam["id"]:
                    continue
                other_slot = self._assigned_slot(other_id)
                if other_slot and intervals_conflict(other_slot, slot):
                    other = self.p.exam_by_id[other_id]
                    return RuleResult(False, "R4_GROUP_OVERLAP",
                                      f"Student group is already examined in {other['subject_name']} at "
                                      f"{other_slot['start_time']} on {other_slot['examination_date']}.",
                                      "Student group overlap")
        return RuleResult(True, "R4_GROUP_OVERLAP")

    # ---- R5 room double booking
    def r5_room_booking(self, room, slot) -> RuleResult:
        for exam_id, rid in self.state["room"].items():
            if rid != room["id"]:
                continue
            if self._testing_exam and exam_id == self._testing_exam:
                continue  # ignore the candidate currently staged in state
            other_slot = self._assigned_slot(exam_id)
            if other_slot and intervals_conflict(other_slot, slot):
                other = self.p.exam_by_id[exam_id]
                return RuleResult(False, "R5_ROOM_DOUBLE_BOOKING",
                                  f"Room {room['room_number']} already hosts {other['subject_name']} at "
                                  f"{other_slot['start_time']} on {other_slot['examination_date']}.",
                                  "Room double-booking")
        return RuleResult(True, "R5_ROOM_DOUBLE_BOOKING")

    # ---- R6 workload balance (advisory: drives ordering, never rejects alone)
    def r6_workload_hint(self, inv, avg_load) -> RuleResult:
        total, _ = self._invigilator_load(inv["id"])
        if avg_load and total > avg_load * 1.5:
            return RuleResult(True, "R6_WORKLOAD_BALANCE",
                              f"{inv['name']} is above the average workload; another eligible invigilator "
                              f"was preferred.")
        return RuleResult(True, "R6_WORKLOAD_BALANCE")

    # ---- R8 remaining mandatory policies
    def r8_policies(self, exam, slot, room) -> RuleResult:
        if not slot.get("is_active"):
            return RuleResult(False, "R8_MANDATORY_POLICY", "Selected time slot is disabled.", "Invalid time slot")
        if not room.get("is_active"):
            return RuleResult(False, "R8_MANDATORY_POLICY", "Selected room is inactive.", "Room inactive")
        if room.get("school_id") != exam.get("school_id"):
            return RuleResult(False, "R8_MANDATORY_POLICY",
                              "Room belongs to a different school than the examination.", "Invalid room")
        s0, s1 = slot_window(slot)
        if (s1 - s0) < int(exam.get("duration_minutes") or 0):
            return RuleResult(False, "R8_MANDATORY_POLICY",
                              f"Slot {slot['start_time']}-{slot['end_time']} is shorter than the "
                              f"{exam['duration_minutes']} minute examination.", "Invalid time slot")
        if self.p.required_facility_policy():
            have = {f.lower() for f in (room.get("facilities") or [])}
            need = {f.lower() for f in (exam.get("required_facilities") or [])}
            missing = need - have
            if missing:
                return RuleResult(False, "R8_MANDATORY_POLICY",
                                  f"Room {room['room_number']} lacks required facilities: "
                                  f"{', '.join(sorted(missing))}.", "Missing room facilities")
        preferred = exam.get("preferred_dates") or []
        if self.p.policy_on("preferred_dates_hard") and preferred and slot["examination_date"] not in preferred:
            return RuleResult(False, "R8_MANDATORY_POLICY",
                              "Examination must fall on one of its preferred dates.",
                              "Preferred date violation")
        return RuleResult(True, "R8_MANDATORY_POLICY")

    def check_assignment(self, exam, slot, room) -> List[RuleResult]:
        return [self.r8_policies(exam, slot, room),
                self.r1_room_capacity(exam, room),
                self.r4_group_overlap(exam, slot),
                self.r5_room_booking(room, slot)]

    def check_invigilator(self, exam, slot, inv) -> List[RuleResult]:
        results = [self.r2_availability(inv, slot), self.r3_daily_limit(inv, slot)]
        total, _ = self._invigilator_load(inv["id"])
        if total >= int(inv.get("maximum_total_duties") or 0):
            results.insert(0, RuleResult(False, "R3_DAILY_DUTY_LIMIT",
                                         f"{inv['name']} reached the maximum total duties "
                                         f"({inv['maximum_total_duties']}).", "Maximum duty limit exceeded"))
        if inv.get("status") != "Active":
            results.insert(0, RuleResult(False, "R8_MANDATORY_POLICY",
                                         f"{inv['name']} is not active.", "Invigilator unavailable"))
        if not self.p.policy_on("inter_school_invigilation") and inv.get("school_id") != exam.get("school_id"):
            results.insert(0, RuleResult(False, "R8_MANDATORY_POLICY",
                                         f"{inv['name']} belongs to another school and inter-school "
                                         f"invigilation is disabled.", "Invigilator unavailable"))
        for exam_id, ids in self.state.get("invig", {}).items():
            if inv["id"] not in ids:
                continue
            if self._testing_exam and exam_id == self._testing_exam:
                continue
            other_slot = self._assigned_slot(exam_id)
            if other_slot and intervals_conflict(other_slot, slot):
                results.insert(0, RuleResult(False, "R5_ROOM_DOUBLE_BOOKING",
                                             f"{inv['name']} already supervises another examination at that time.",
                                             "Invigilator overlap"))
        return results
