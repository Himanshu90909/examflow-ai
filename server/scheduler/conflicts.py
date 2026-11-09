"""Independent validation and automatic repair of generated schedules.

The validator never trusts the solver: it re-checks every hard constraint
directly against the assignment list, so a buggy heuristic cannot publish an
invalid timetable.
"""
from .constraints import intervals_conflict, ranges_overlap, to_minutes


class ConflictEngine:
    def __init__(self, problem):
        self.p = problem
        self.exams = {e["id"]: e for e in problem.examinations}
        self.rooms = {r["id"]: r for r in problem.rooms}
        self.slots = {s["id"]: s for s in problem.slots}
        self.invs = {i["id"]: i for i in problem.invigilators}

    # ------------------------------------------------------------------ checks
    def validate(self, assignments):
        out = []
        # the slot is the source of truth for time; denormalised columns may be stale
        for a in assignments:
            slot = self.slots.get(a.get("time_slot_id"))
            if slot:
                a["examination_date"] = slot["examination_date"]
                a["start_time"] = slot["start_time"]
                a["end_time"] = slot["end_time"]

        def add(kind, severity, description, exam=None, room=None, inv=None, suggestion=""):
            out.append({
                "conflict_type": kind,
                "severity": severity,
                "description": description,
                "affected_examination": exam,
                "affected_room": room,
                "affected_invigilator": inv,
                "suggested_resolution": suggestion,
            })

        for a in assignments:
            exam = self.exams.get(a["examination_id"])
            room = self.rooms.get(a.get("room_id"))
            slot = self.slots.get(a.get("time_slot_id"))
            if not exam:
                continue
            label = f"{exam['subject_code']} {exam['subject_name']}"
            if not room or not slot:
                add("Unscheduled examination", "High",
                    f"{label} has no room or time slot assigned.",
                    exam["id"], None, None,
                    "Run the generator again or assign a room and slot manually.")
                continue

            if not room.get("is_active", 1):
                add("Inactive room selected", "High",
                    f"{label} is booked into inactive room {room['room_number']}.",
                    exam["id"], room["id"], None, "Choose an active room.")
            if room["capacity"] < (exam.get("required_seating_capacity") or 0):
                add("Insufficient seating capacity", "Critical",
                    f"{label} needs {exam['required_seating_capacity']} seats but "
                    f"room {room['room_number']} seats {room['capacity']}.",
                    exam["id"], room["id"], None,
                    "Move the examination to a larger room or split the groups.")
            missing = [f for f in exam.get("required_facilities") or []
                       if f not in (room.get("facilities") or [])]
            if missing:
                add("Missing room facilities", "High",
                    f"{label} requires {', '.join(missing)} which room "
                    f"{room['room_number']} does not provide.",
                    exam["id"], room["id"], None, "Select a room with the required facilities.")
            slot_minutes = _minutes(slot["start_time"], slot["end_time"])
            if not slot.get("is_active", 1) or slot_minutes < exam["duration_minutes"]:
                add("Invalid time slot", "High",
                    f"{label} ({exam['duration_minutes']} min) does not fit slot "
                    f"{slot['start_time']}–{slot['end_time']}.",
                    exam["id"], room["id"], None, "Use a longer or active time slot.")

            # per-invigilator checks
            for inv_id in a.get("invigilator_ids") or []:
                inv = self.invs.get(inv_id)
                if not inv:
                    continue
                emp = f"{inv['name']} ({inv['employee_code']})"
                if (inv.get("status") or "Active") != "Active":
                    add("Invigilator unavailable", "Critical",
                        f"{emp} is marked {inv.get('status')} but is assigned to {label}.",
                        exam["id"], room["id"], inv_id, "Reassign the duty to an active invigilator.")
                for rec in self.p.config.get("availability_by_inv", {}).get(inv_id, []):
                    if rec["date"] != a.get("examination_date"):
                        continue
                    if (rec.get("availability_status") or "Unavailable") == "Available":
                        continue
                    if not (rec.get("start_time") and rec.get("end_time")) or ranges_overlap(
                            to_minutes(rec["start_time"]), to_minutes(rec["end_time"]),
                            to_minutes(a["start_time"]), to_minutes(a["end_time"])):
                        add("Invigilator unavailability", "Critical",
                            f"{emp} is unavailable on {rec['date']} "
                            f"{rec.get('start_time') or ''}–{rec.get('end_time') or ''}"
                            f"{' (' + rec['reason'] + ')' if rec.get('reason') else ''} "
                            f"but supervises {label}.",
                            exam["id"], room["id"], inv_id,
                            "Assign another available invigilator.")

        # pairwise checks
        by_id = {a["examination_id"]: a for a in assignments}
        items = [a for a in assignments if a.get("room_id") and a.get("time_slot_id")]
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, b = items[i], items[j]
                if a.get("examination_date") != b.get("examination_date"):
                    continue
                if not ranges_overlap(to_minutes(a["start_time"]), to_minutes(a["end_time"]),
                                      to_minutes(b["start_time"]), to_minutes(b["end_time"])):
                    continue
                ea, eb = self.exams.get(a["examination_id"]), self.exams.get(b["examination_id"])
                if not ea or not eb:
                    continue
                shared = set(ea.get("student_group_ids") or []) & set(eb.get("student_group_ids") or [])
                if shared:
                    add("Student group overlap", "Critical",
                        f"{ea['subject_code']} and {eb['subject_code']} overlap on "
                        f"{a['examination_date']} {a['start_time']} and share "
                        f"{len(shared)} student group(s).",
                        ea["id"], None, None,
                        "Move one examination to a different time slot.")
                if a.get("room_id") == b.get("room_id"):
                    add("Room double-booking", "Critical",
                        f"Room {self.rooms.get(a['room_id'], {}).get('room_number')} is booked for "
                        f"{ea['subject_code']} and {eb['subject_code']} at the same time.",
                        ea["id"], a["room_id"], None,
                        "Move one examination to another room.")
                common = set(a.get("invigilator_ids") or []) & set(b.get("invigilator_ids") or [])
                for inv_id in common:
                    add("Invigilator overlap", "Critical",
                        f"{self.invs.get(inv_id, {}).get('name', inv_id)} is supervising "
                        f"{ea['subject_code']} and {eb['subject_code']} simultaneously.",
                        ea["id"], None, inv_id, "Remove one of the two duties.")

        # workload limits
        daily, total = {}, {}
        for a in assignments:
            for inv_id in a.get("invigilator_ids") or []:
                daily.setdefault((inv_id, a.get("examination_date")), []).append(a["examination_id"])
                total[inv_id] = total.get(inv_id, 0) + 1
        for (inv_id, date), ids in daily.items():
            inv = self.invs.get(inv_id)
            if inv and len(ids) > (inv.get("maximum_daily_duties") or 2):
                add("Maximum daily duty limit exceeded", "High",
                    f"{inv['name']} has {len(ids)} duties on {date}; the limit is "
                    f"{inv.get('maximum_daily_duties')}.",
                    ids[-1], None, inv_id, "Move a duty to another eligible invigilator.")
        for inv_id, count in total.items():
            inv = self.invs.get(inv_id)
            if inv and count > (inv.get("maximum_total_duties") or 10):
                add("Maximum total duty limit exceeded", "High",
                    f"{inv['name']} has {count} total duties; the limit is "
                    f"{inv.get('maximum_total_duties')}.",
                    None, None, inv_id, "Redistribute duties.")

        for e_id, exam in self.exams.items():
            if e_id not in by_id:
                add("Unscheduled examination", "High",
                    f"{exam['subject_code']} {exam['subject_name']} could not be scheduled.",
                    e_id, None, None,
                    "Relax a constraint, add a room or slot, or extend the date range.")
        return out

    # ------------------------------------------------------------------ repair
    def repair(self, assignments):
        """Try alternative rooms/slots/invigilators for conflicting placements."""
        actions = []
        for a in assignments:
            slot = self.slots.get(a.get("time_slot_id"))
            if slot:
                a["examination_date"] = slot["examination_date"]
                a["start_time"] = slot["start_time"]
                a["end_time"] = slot["end_time"]
        state = {"slot": {}, "room": {}}
        for a in assignments:
            state["slot"][a["examination_id"]] = a.get("time_slot_id")
            state["room"][a["examination_id"]] = a.get("room_id")

        for a in assignments:
            exam = self.exams.get(a["examination_id"])
            if not exam or not a.get("time_slot_id"):
                continue
            problems = [c for c in self._local_conflicts(a, assignments)]
            if not problems:
                continue
            fixed = False
            for slot in sorted(self.p.slots, key=lambda s: (s["examination_date"], s["start_time"])):
                if slot["id"] == a["time_slot_id"]:
                    continue
                for room in sorted(self.p.rooms, key=lambda r: r["capacity"]):
                    if room["school_id"] != exam["school_id"] or not room.get("is_active", 1):
                        continue
                    if room["capacity"] < (exam.get("required_seating_capacity") or 0):
                        continue
                    if any(f not in (room.get("facilities") or []) for f in exam.get("required_facilities") or []):
                        continue
                    if _minutes(slot["start_time"], slot["end_time"]) < exam["duration_minutes"]:
                        continue
                    if not slot.get("is_active", 1):
                        continue
                    ok = True
                    for other in assignments:
                        if other is a or not other.get("time_slot_id"):
                            continue
                        if other["time_slot_id"] != slot["id"]:
                            continue
                        if other.get("room_id") == room["id"]:
                            ok = False
                            break
                        if set(self.exams.get(other["examination_id"], {}).get("student_group_ids") or []) & \
                                set(exam.get("student_group_ids") or []):
                            ok = False
                            break
                    if not ok:
                        continue
                    state["slot"].pop(a["examination_id"], None)
                    state["room"].pop(a["examination_id"], None)
                    a["time_slot_id"] = slot["id"]
                    a["room_id"] = room["id"]
                    a["examination_date"] = slot["examination_date"]
                    a["start_time"] = slot["start_time"]
                    a["end_time"] = slot["end_time"]
                    actions.append({
                        "examination_id": exam["id"],
                        "action": "Rescheduled",
                        "detail": f"Moved {exam['subject_code']} to {slot['examination_date']} "
                                  f"{slot['start_time']} room {room['room_number']} to clear "
                                  f"{len(problems)} conflict(s).",
                    })
                    fixed = True
                    break
                if fixed:
                    break
            if not fixed and problems:
                actions.append({
                    "examination_id": exam["id"],
                    "action": "No alternative",
                    "detail": f"{exam['subject_code']} could not be moved; every alternative room or "
                              f"slot breaks another hard constraint.",
                })
        return actions

    def _local_conflicts(self, a, assignments):
        found = []
        exam = self.exams.get(a["examination_id"])
        if not exam:
            return found
        for other in assignments:
            if other is a or other.get("examination_date") != a.get("examination_date"):
                continue
            if not ranges_overlap(to_minutes(a["start_time"]), to_minutes(a["end_time"]),
                                  to_minutes(other["start_time"]), to_minutes(other["end_time"])):
                continue
            if other.get("room_id") == a.get("room_id"):
                found.append("room")
            other_exam = self.exams.get(other["examination_id"])
            if other_exam and set(other_exam.get("student_group_ids") or []) & set(exam.get("student_group_ids") or []):
                found.append("group")
        return found


def _minutes(start, end):
    def mins(t):
        try:
            h, m = [int(x) for x in (t or "0:0").split(":")[:2]]
            return h * 60 + m
        except (ValueError, AttributeError):
            return 0
    return max(0, mins(end) - mins(start))
