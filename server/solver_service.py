"""Scheduling orchestration: load data, run an algorithm, persist a full run."""
import json
import time

import db
import auth
from scheduler.constraints import Problem, PRIORITY_RANK, RuleEngine, required_invigilators
from scheduler.csp import CSPSolver
from scheduler.firstfit import FirstFitSolver
from scheduler import conflicts as conflict_engine
from scheduler import fairness as fairness_engine

ALGORITHMS = {
    "csp": "CSP Backtracking (MRV + Degree + LCV + Forward Checking)",
    "first_fit": "First-Fit Greedy Baseline",
}


def _pick_algorithm(config):
    key = (config.get("algorithm") or "csp").lower()
    if key in ("first_fit", "first-fit", "firstfit", "baseline"):
        return "first_fit", FirstFitSolver
    return "csp", CSPSolver


def _ids(conn, table, school_ids=None):
    if not school_ids:
        return [r["id"] for r in conn.execute(f"SELECT id FROM {table}").fetchall()]
    marks = ",".join("?" for _ in school_ids)
    return [r["id"] for r in conn.execute(
        f"SELECT id FROM {table} WHERE school_id IN ({marks})", school_ids).fetchall()]


def load_problem(conn, config):
    """Build a Problem from the database using the run configuration."""
    school_ids = [s for s in (config.get("school_ids") or []) if s]
    params = []
    where = ["1=1"]
    if config.get("examination_ids"):
        marks = ",".join("?" for _ in config["examination_ids"])
        where.append(f"e.id IN ({marks})")
        params.extend(config["examination_ids"])
    if school_ids:
        marks = ",".join("?" for _ in school_ids)
        where.append(f"e.school_id IN ({marks})")
        params.extend(school_ids)

    exams = [db.decode_row("examinations", r) for r in conn.execute(
        f"SELECT e.* FROM examinations e WHERE {' AND '.join(where)} "
        f"AND COALESCE(e.status,'Active') != 'Cancelled' ORDER BY e.subject_code", params)]

    room_ids = config.get("room_ids") or []
    rw = ["1=1"]
    rp = []
    if room_ids:
        marks = ",".join("?" for _ in room_ids)
        rw.append(f"id IN ({marks})")
        rp.extend(room_ids)
    if school_ids:
        marks = ",".join("?" for _ in school_ids)
        rw.append(f"school_id IN ({marks})")
        rp.extend(school_ids)
    rooms = [db.decode_row("rooms", r) for r in conn.execute(
        f"SELECT * FROM rooms WHERE {' AND '.join(rw)}", rp)]

    sw = ["1=1"]
    sp = []
    if config.get("date_from"):
        sw.append("examination_date >= ?")
        sp.append(config["date_from"])
    if config.get("date_to"):
        sw.append("examination_date <= ?")
        sp.append(config["date_to"])
    slots = [db.decode_row("time_slots", r) for r in conn.execute(
        f"SELECT * FROM time_slots WHERE {' AND '.join(sw)} ORDER BY examination_date, start_time", sp)]

    inv_ids = config.get("invigilator_ids") or []
    iw = ["1=1"]
    ip = []
    if inv_ids:
        marks = ",".join("?" for _ in inv_ids)
        iw.append(f"id IN ({marks})")
        ip.extend(inv_ids)
    invigilators = [db.decode_row("invigilators", r) for r in conn.execute(
        f"SELECT * FROM invigilators WHERE {' AND '.join(iw)}", ip)]

    availability = [db.decode_row("invigilator_availability", r) for r in conn.execute(
        "SELECT * FROM invigilator_availability")]

    policy_ids = config.get("policy_ids") or []
    policies = [db.decode_row("constraint_policies", r) for r in conn.execute(
        "SELECT * FROM constraint_policies WHERE is_enabled = 1")]
    if policy_ids:
        policies = [p for p in policies if p["id"] in policy_ids]

    availability_by_inv = {}
    for rec in availability:
        availability_by_inv.setdefault(rec["invigilator_id"], []).append(rec)

    cfg = dict(config)
    cfg["availability_by_inv"] = availability_by_inv
    return Problem(examinations=exams, rooms=rooms, slots=slots, invigilators=invigilators,
                   availability=availability, policies=policies, config=cfg)


def _normalise(result):
    for a in result.assignments:
        a["invigilator_ids"] = a.get("invigilator_ids") or []
        if a.get("invigilators") and isinstance(a["invigilators"][0], dict):
            a["invigilator_ids"] = [i["id"] for i in a["invigilators"]]
            a["invigilators"] = [i["name"] for i in a["invigilators"]]
        a["assignment_status"] = a.get("assignment_status") or "Scheduled"
    return result


def run_schedule(conn, user, config):
    config = dict(config or {})
    config.setdefault("algorithm", "csp")
    config.setdefault("options", {})
    alg_key, solver_cls = _pick_algorithm(config)

    started = time.time()
    started_iso = db.now_iso()
    problem = load_problem(conn, config)
    if not problem.examinations:
        raise auth.ValidationError("No examinations match this configuration.")
    if not problem.slots:
        raise auth.ValidationError("No time slots exist in the selected date range.")

    solver = solver_cls(problem, options=config.get("options") or {})
    result = _normalise(solver.solve())

    # independent validation of the produced timetable
    engine = conflict_engine.ConflictEngine(problem)
    conflicts = engine.validate(result.assignments)
    repair_actions = []
    if config["options"].get("auto_repair") and conflicts:
        repair_actions = engine.repair(result.assignments)
        conflicts = engine.validate(result.assignments)
    hard = [c for c in conflicts if c["severity"] in ("Critical", "High")]

    if not result.assignments:
        solver_status = result.solver_status if result.solver_status != "UNKNOWN" else "INFEASIBLE"
    elif hard or result.unscheduled:
        solver_status = "INFEASIBLE"
    else:
        solver_status = "FEASIBLE_BUT_NOT_PROVEN_OPTIMAL"
    if result.solver_status == "TIME_LIMIT_REACHED":
        solver_status = "TIME_LIMIT_REACHED"

    fairness = fairness_engine.evaluate(problem, result.assignments)

    run_id = db.new_id()
    conn.execute(
        """INSERT INTO scheduling_runs (id, run_name, algorithm_name, start_time, completion_time,
            status, solver_status, total_examinations, scheduled_examinations,
            unscheduled_examinations, hard_constraint_violations, soft_constraint_penalty,
            execution_time, configuration, created_by, created_at, version, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (run_id, config.get("run_name") or f"{ALGORITHMS[alg_key]} run",
         ALGORITHMS[alg_key], started_iso, db.now_iso(), "Completed", solver_status,
         len(problem.examinations), len(result.assignments), len(result.unscheduled),
         len(hard), round(result.soft_penalty, 2), round(time.time() - started, 4),
         json.dumps({k: v for k, v in config.items() if k != "availability_by_inv"}),
         user["id"], db.now_iso(), 1,
         json.dumps({"stats": result.stats, "repair_actions": repair_actions,
                     "nodes": result.nodes_explored, "backtracks": result.backtracks})))

    explanations = {e["examination_id"]: e for e in result.explanations}
    for a in result.assignments:
        aid = db.new_id()
        conn.execute(
            """INSERT INTO schedule_assignments (id, scheduling_run_id, examination_id, room_id,
               time_slot_id, examination_date, start_time, end_time, assignment_status, priority, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, run_id, a["examination_id"], a.get("room_id"), a.get("time_slot_id"),
             a.get("examination_date"), a.get("start_time"), a.get("end_time"),
             a.get("assignment_status") or "Scheduled", a.get("priority"), db.now_iso()))
        for inv_id in a.get("invigilator_ids") or []:
            conn.execute(
                """INSERT INTO invigilator_assignments (id, schedule_assignment_id, invigilator_id,
                   duty_status, created_at) VALUES (?,?,?,?,?)""",
                (db.new_id(), aid, inv_id, "Assigned", db.now_iso()))
        ex = explanations.get(a["examination_id"])
        if ex:
            conn.execute(
                """INSERT INTO schedule_explanations (id, scheduling_run_id, schedule_assignment_id,
                   decision_reason, alternatives_considered, constraints_satisfied,
                   rejected_alternatives, explanation_type, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (db.new_id(), run_id, aid, ex.get("decision_reason"),
                 int(ex.get("alternatives_considered") or 0),
                 json.dumps(ex.get("constraints_satisfied") or []),
                 json.dumps(ex.get("rejected_alternatives") or []),
                 ex.get("explanation_type") or "assignment", db.now_iso()))

    all_conflicts = list(conflicts) + [c for c in result.conflicts if c.get("conflict_type")]
    seen = set()
    for c in all_conflicts:
        key = (c.get("conflict_type"), c.get("description"))
        if key in seen:
            continue
        seen.add(key)
        conn.execute(
            """INSERT INTO conflict_logs (id, scheduling_run_id, conflict_type, description, severity,
               affected_examination, affected_room, affected_invigilator, suggested_resolution,
               resolution_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (db.new_id(), run_id, c.get("conflict_type"), c.get("description"),
             c.get("severity") or "Medium", c.get("affected_examination"), c.get("affected_room"),
             c.get("affected_invigilator"), c.get("suggested_resolution"), "Open", db.now_iso()))

    for m in fairness["metrics"]:
        conn.execute(
            """INSERT INTO fairness_metrics (id, scheduling_run_id, metric_name, metric_value,
               metric_description, created_at) VALUES (?,?,?,?,?,?)""",
            (db.new_id(), run_id, m["metric_name"], m["metric_value"], m["metric_description"],
             db.now_iso()))

    for exam_id in [a["examination_id"] for a in result.assignments]:
        conn.execute("UPDATE examinations SET status='Scheduled' WHERE id=?", (exam_id,))
    for u in result.unscheduled:
        conn.execute("UPDATE examinations SET status='Pending' WHERE id=?", (u["examination_id"],))

    conn.commit()
    db.audit(conn, user, "Timetable generated", "scheduling_run", run_id,
             f"{ALGORITHMS[alg_key]}: {len(result.assignments)} scheduled, "
             f"{len(result.unscheduled)} unscheduled, {len(hard)} hard violations")
    db.notify(conn, user["id"], "Timetable generated",
              f"{config.get('run_name') or 'Scheduling run'} finished with status {solver_status}.")
    conn.commit()
    return get_run(conn, run_id)


def _rebalance_invigilators(problem, assignments, targets=None):
    """Replace invigilators that break a limit with an eligible colleague.

    Handles per-day caps, whole-run caps and availability windows. Duties for
    examinations outside `targets` are only touched when the invigilator is over
    a hard limit (so a limit breach introduced by a move is always repaired)."""
    state = {
        "slot": {a["examination_id"]: a.get("time_slot_id") for a in assignments},
        "room": {a["examination_id"]: a.get("room_id") for a in assignments},
        "invig": {a["examination_id"]: list(a.get("invigilator_ids") or []) for a in assignments},
    }
    engine = RuleEngine(problem, state)

    def day_count(inv_id, date):
        total = 0
        for exam_id, ids in state["invig"].items():
            if inv_id in ids:
                slot = problem.slot_by_id.get(state["slot"].get(exam_id))
                if slot and slot["examination_date"] == date:
                    total += 1
        return total

    def total_count(inv_id):
        return sum(1 for ids in state["invig"].values() if inv_id in ids)

    actions = []
    for a in sorted(assignments, key=lambda x: (x.get("examination_date") or "", x.get("start_time") or "")):
        exam = problem.exam_by_id.get(a["examination_id"])
        slot = problem.slot_by_id.get(a.get("time_slot_id"))
        if not exam or not slot:
            continue
        current = list(a.get("invigilator_ids") or [])
        replaced = False
        for inv_id in list(current):
            inv = problem.inv_by_id.get(inv_id)
            if not inv:
                current.remove(inv_id)
                replaced = True
                continue
            daily_cap = int(inv.get("maximum_daily_duties") or 0)
            total_cap = int(inv.get("maximum_total_duties") or 0)
            over_limit = ((daily_cap and day_count(inv_id, slot["examination_date"]) > daily_cap)
                          or (total_cap and total_count(inv_id) > total_cap))
            if not over_limit:
                if targets is not None and exam["id"] not in targets:
                    continue
                if all(r.allowed for r in engine.check_invigilator(exam, slot, inv)):
                    continue
            trial = [x for x in current if x != inv_id]
            state["invig"][a["examination_id"]] = trial
            for cand in sorted(problem.invigilators, key=lambda i: (total_count(i["id"]), i["id"])):
                if cand["id"] in trial or cand.get("status") != "Active":
                    continue
                if not all(r.allowed for r in engine.check_invigilator(exam, slot, cand)):
                    continue
                current[current.index(inv_id)] = cand["id"]
                state["invig"][a["examination_id"]] = list(current)
                actions.append({
                    "examination_id": exam["id"], "action": "Invigilator reassigned",
                    "detail": f"{inv['name']} replaced by {cand['name']} for {exam['subject_code']} "
                              f"on {slot['examination_date']} {slot['start_time']} to respect a duty limit.",
                })
                replaced = True
                break
            state["invig"][a["examination_id"]] = list(current)
        if replaced:
            a["invigilator_ids"] = current
    return actions


def get_run(conn, run_id):
    row = conn.execute("SELECT * FROM scheduling_runs WHERE id=?", (run_id,)).fetchone()
    if not row:
        raise auth.NotFound("Scheduling run not found")
    run = db.decode_row("scheduling_runs", row)
    conf = run["configuration"] if isinstance(run["configuration"], dict) else {}
    conf = conf or {}
    run["notes"] = json.loads(run["notes"]) if isinstance(run["notes"], str) else (run["notes"] or {})
    run["fairness"] = fairness_for_run(conn, run_id)
    run["stats"] = run["notes"].get("stats", {})
    run["configuration"] = conf
    run["conflicts_open"] = conn.execute(
        "SELECT COUNT(*) c FROM conflict_logs WHERE scheduling_run_id=? AND resolution_status='Open'",
        (run_id,)).fetchone()["c"]
    run["feasible"] = run["hard_constraint_violations"] == 0 and run["unscheduled_examinations"] == 0
    run["status_label"] = run["solver_status"]
    return run


def assignments_for_run(conn, run_id):
    rows = conn.execute(
        """SELECT sa.*, e.subject_name, e.subject_code, e.school_id, e.department_id,
                  e.duration_minutes, e.student_group_ids, e.required_seating_capacity,
                  s.school_name, s.school_code, r.room_number, r.building, r.capacity,
                  ts.session
           FROM schedule_assignments sa
           JOIN examinations e ON e.id = sa.examination_id
           LEFT JOIN schools s ON s.id = e.school_id
           LEFT JOIN rooms r ON r.id = sa.room_id
           LEFT JOIN time_slots ts ON ts.id = sa.time_slot_id
           WHERE sa.scheduling_run_id = ?
           ORDER BY sa.examination_date, sa.start_time, s.school_name""", (run_id,)).fetchall()
    out = []
    for row in rows:
        a = db.decode_row("schedule_assignments", row)
        a.update({
            "subject_name": row["subject_name"], "subject_code": row["subject_code"],
            "school_id": row["school_id"], "school_name": row["school_name"],
            "school_code": row["school_code"], "room_number": row["room_number"],
            "building": row["building"], "room_capacity": row["capacity"],
            "session": row["session"], "duration_minutes": row["duration_minutes"],
            "student_group_ids": db.encode_value(row["student_group_ids"]) if False else
            json.loads(row["student_group_ids"] or "[]"),
            "required_seating_capacity": row["required_seating_capacity"],
        })
        invs = conn.execute(
            """SELECT ia.invigilator_id, ia.duty_status, i.name, i.employee_code, i.school_id
               FROM invigilator_assignments ia JOIN invigilators i ON i.id = ia.invigilator_id
               WHERE ia.schedule_assignment_id = ? ORDER BY i.name""", (a["id"],)).fetchall()
        a["invigilators"] = [dict(x) for x in invs]
        a["invigilator_ids"] = [x["invigilator_id"] for x in invs]
        a["invigilator_names"] = ", ".join(x["name"] for x in invs)
        ex = conn.execute(
            "SELECT * FROM schedule_explanations WHERE schedule_assignment_id=?", (a["id"],)).fetchone()
        if ex:
            e = db.decode_row("schedule_explanations", ex)
            a["explanation"] = e
        out.append(a)
    return out


def fairness_for_run(conn, run_id):
    rows = conn.execute(
        "SELECT * FROM fairness_metrics WHERE scheduling_run_id=? ORDER BY metric_name",
        (run_id,)).fetchall()
    metrics = [db.decode_row("fairness_metrics", r) for r in rows]
    summary = {m["metric_name"]: m["metric_value"] for m in metrics
               if "::" not in m["metric_name"]}
    per_inv = [{"name": m["metric_name"].split("::", 1)[1], "duties": m["metric_value"]}
               for m in metrics if m["metric_name"].startswith("duties::")]
    per_inv.sort(key=lambda x: x["duties"], reverse=True)
    avg = summary.get("average_workload", 0) or 0
    return {
        "summary": summary, "metrics": metrics, "per_invigilator": per_inv,
        "overloaded": [p for p in per_inv if p["duties"] > avg + 1],
        "underutilised": [p for p in per_inv if p["duties"] < max(avg - 1, 0)],
    }


def validate_run(conn, run_id):
    run = get_run(conn, run_id)
    config = run["configuration"] or {}
    problem = load_problem(conn, config)
    assignments = assignments_for_run(conn, run_id)
    conflicts = conflict_engine.ConflictEngine(problem).validate(assignments)
    hard = [c for c in conflicts if c["severity"] in ("Critical", "High")]
    return {"run": run, "conflicts": conflicts, "hard": hard,
            "feasible": not hard, "status": "FEASIBLE" if not hard else "INFEASIBLE"}


def repair_run(conn, user, run_id):
    run = get_run(conn, run_id)
    config = run["configuration"] or {}
    problem = load_problem(conn, config)
    assignments = assignments_for_run(conn, run_id)
    engine = conflict_engine.ConflictEngine(problem)
    actions = engine.repair(assignments)
    flagged = {c["affected_examination"] for c in engine.validate(assignments)
               if c.get("affected_examination") and c.get("severity") in ("Critical", "High")
               and c["conflict_type"] in (
                   "Invigilator unavailability", "Maximum daily duty limit exceeded",
                   "Maximum total duty limit exceeded", "Invigilator overlap")}
    actions += _rebalance_invigilators(problem, assignments, flagged)
    for a in assignments:
        conn.execute(
            """UPDATE schedule_assignments SET room_id=?, time_slot_id=?, examination_date=?,
               start_time=?, end_time=? WHERE id=?""",
            (a.get("room_id"), a.get("time_slot_id"), a.get("examination_date"),
             a.get("start_time"), a.get("end_time"), a["id"]))
        conn.execute("DELETE FROM invigilator_assignments WHERE schedule_assignment_id=?", (a["id"],))
        for inv_id in a.get("invigilator_ids") or []:
            conn.execute(
                """INSERT INTO invigilator_assignments (id, schedule_assignment_id, invigilator_id,
                   duty_status, created_at) VALUES (?,?,?,?,?)""",
                (db.new_id(), a["id"], inv_id, "Assigned", db.now_iso()))
    after = engine.validate(assignments)
    hard = [c for c in after if c["severity"] in ("Critical", "High")]
    conn.execute("UPDATE conflict_logs SET resolution_status='Resolved' "
                 "WHERE scheduling_run_id=? AND resolution_status='Open'", (run_id,))
    for c in after:
        conn.execute(
            """INSERT INTO conflict_logs (id, scheduling_run_id, conflict_type, description, severity,
               affected_examination, affected_room, affected_invigilator, suggested_resolution,
               resolution_status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (db.new_id(), run_id, c.get("conflict_type"), c.get("description"),
             c.get("severity") or "Medium", c.get("affected_examination"), c.get("affected_room"),
             c.get("affected_invigilator"), c.get("suggested_resolution"), "Open", db.now_iso()))
    conn.execute("UPDATE scheduling_runs SET hard_constraint_violations=? WHERE id=?",
                 (len(hard), run_id))
    conn.commit()
    db.audit(conn, user, "Timetable repaired", "scheduling_run", run_id,
             f"{len(actions)} repair action(s), {len(hard)} conflict(s) remain")
    return {"actions": actions, "after": after, "hard": hard, "run": get_run(conn, run_id)}


def approve_run(conn, user, run_id):
    run = validate_run(conn, run_id)
    if not run["feasible"]:
        raise auth.ValidationError(
            f"Cannot approve: {len(run['hard'])} mandatory constraint violation(s). Resolve them first.")
    conn.execute("UPDATE scheduling_runs SET status='Approved' WHERE id=?", (run_id,))
    conn.commit()
    db.audit(conn, user, "Timetable approved", "scheduling_run", run_id)
    db.notify(conn, user["id"], "Timetable approved", "A timetable was approved and is ready to publish.")
    conn.commit()
    return get_run(conn, run_id)


def publish_run(conn, user, run_id):
    run = validate_run(conn, run_id)
    if not run["feasible"]:
        raise auth.ValidationError(
            f"Cannot publish: {len(run['hard'])} mandatory constraint violation(s) detected "
            f"by the independent validator.")
    conn.execute("UPDATE scheduling_runs SET status='Published', published_at=? WHERE id=?",
                 (db.now_iso(), run_id))
    conn.commit()
    db.audit(conn, user, "Timetable published", "scheduling_run", run_id)
    conn.execute("SELECT DISTINCT created_by FROM scheduling_runs")
    db.notify(conn, user["id"], "Timetable published",
              "The timetable is published and visible to invigilators.")
    conn.commit()
    return get_run(conn, run_id)


def reschedule_assignment(conn, user, assignment_id, slot_id, room_id):
    row = conn.execute("SELECT * FROM schedule_assignments WHERE id=?", (assignment_id,)).fetchone()
    if not row:
        raise auth.NotFound("Assignment not found")
    assignment = db.decode_row("schedule_assignments", row)
    slot = conn.execute("SELECT * FROM time_slots WHERE id=?", (slot_id,)).fetchone()
    if not slot:
        raise auth.ValidationError("Select a valid time slot.")
    if room_id:
        room = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
        if not room:
            raise auth.ValidationError("Select a valid room.")
        exam = conn.execute("SELECT * FROM examinations WHERE id=?",
                            (assignment["examination_id"],)).fetchone()
        if room["school_id"] != exam["school_id"]:
            raise auth.ValidationError("The room belongs to a different school than the examination.")
        if room["capacity"] < (exam["required_seating_capacity"] or 0):
            raise auth.ValidationError(
                f"Room capacity {room['capacity']} is below the required "
                f"{exam['required_seating_capacity']} seats.")
    conn.execute(
        """UPDATE schedule_assignments SET time_slot_id=?, room_id=?, examination_date=?,
           start_time=?, end_time=?, assignment_status='Manually rescheduled' WHERE id=?""",
        (slot_id, room_id, slot["examination_date"], slot["start_time"], slot["end_time"], assignment_id))
    conn.commit()
    db.audit(conn, user, "Manual reschedule", "schedule_assignment", assignment_id,
             f"Moved to {slot['examination_date']} {slot['start_time']}")
    return validate_run(conn, assignment["scheduling_run_id"])


def compare_runs(conn, a_id, b_id):
    a = get_run(conn, a_id)
    b = get_run(conn, b_id)
    a_stats = run_stats(conn, a_id)
    b_stats = run_stats(conn, b_id)

    def pack(run, stats, key):
        return {
            "id": run["id"], "algorithm": run["algorithm_name"], "role": key,
            "scheduled_examinations": run["scheduled_examinations"],
            "unscheduled_examinations": run["unscheduled_examinations"],
            "hard_constraint_violations": run["hard_constraint_violations"],
            "soft_constraint_penalty": run["soft_constraint_penalty"],
            "workload_standard_deviation": run["fairness"]["summary"].get("standard_deviation", 0),
            "fairness_score": run["fairness"]["summary"].get("fairness_score", 0),
            "room_utilization": stats["room_utilization"],
            "execution_time": run["execution_time"],
            "solver_status": run["solver_status"],
            "feasible": run["feasible"],
        }

    baseline = pack(a, a_stats, "baseline")
    candidate = pack(b, b_stats, "candidate")
    deltas = {}
    for key in ("scheduled_examinations", "unscheduled_examinations", "hard_constraint_violations",
                "soft_constraint_penalty", "workload_standard_deviation", "room_utilization",
                "execution_time", "fairness_score"):
        deltas[key] = round((candidate[key] or 0) - (baseline[key] or 0), 3)
    return {"baseline": baseline, "candidate": candidate, "deltas": deltas}


def run_stats(conn, run_id):
    rows = conn.execute(
        """SELECT sa.room_id, r.capacity, e.required_seating_capacity, sa.examination_date,
                  sa.start_time
           FROM schedule_assignments sa
           JOIN examinations e ON e.id = sa.examination_id
           LEFT JOIN rooms r ON r.id = sa.room_id
           WHERE sa.scheduling_run_id=?""", (run_id,)).fetchall()
    used = [r for r in rows if r["room_id"]]
    seats = sum((r["required_seating_capacity"] or 0) for r in used)
    capacity = sum((r["capacity"] or 0) for r in used)
    per_day = {}
    for r in rows:
        per_day[r["examination_date"]] = per_day.get(r["examination_date"], 0) + 1
    return {
        "room_utilization": round(100 * seats / capacity, 1) if capacity else 0.0,
        "rooms_used": len({r["room_id"] for r in used}),
        "examinations": len(rows),
        "per_day": per_day,
    }
