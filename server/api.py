"""REST API handlers: role-aware CRUD, dashboard, reports and scheduling."""
import csv
import io
import json

import db
import auth
import solver_service
from scheduler.constraints import PRIORITY_RANK  # noqa: F401  (documented dependency)

TABLES = {
    "schools": "schools",
    "departments": "departments",
    "student-groups": "student_groups",
    "examinations": "examinations",
    "rooms": "rooms",
    "invigilators": "invigilators",
    "availability": "invigilator_availability",
    "time-slots": "time_slots",
    "policies": "constraint_policies",
    "users": "users",
    "audit-logs": "audit_logs",
    "conflicts": "conflict_logs",
    "runs": "scheduling_runs",
    "notifications": "notifications",
    "assignments": "schedule_assignments",
}

SEARCH_FIELDS = {
    "schools": ["school_name", "school_code", "contact_email"],
    "departments": ["department_name", "department_code"],
    "student-groups": ["group_name", "section", "academic_year"],
    "examinations": ["subject_name", "subject_code", "examination_type"],
    "rooms": ["room_number", "building", "room_type"],
    "invigilators": ["name", "employee_code", "email", "qualification"],
    "availability": ["reason", "availability_status", "date"],
    "time-slots": ["session", "examination_date"],
    "policies": ["policy_name", "constraint_type", "rule_code"],
    "users": ["full_name", "email", "role"],
    "audit-logs": ["action", "entity_type", "details"],
    "conflicts": ["conflict_type", "description", "severity"],
    "runs": ["run_name", "algorithm_name", "status", "solver_status"],
    "notifications": ["title", "message"],
    "assignments": ["assignment_status"],
}

SCOPED = {"departments", "student-groups", "examinations", "rooms", "invigilators", "policies"}


# ------------------------------------------------------------------ utilities
def _columns(conn, table):
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _clean(table, body, conn):
    cols = set(_columns(conn, table))
    out = {}
    for key, value in (body or {}).items():
        if key in cols and key not in ("id", "created_at", "password_hash"):
            out[key] = db.encode_value(value) if isinstance(value, (list, dict)) else value
    return out


def _need(conn, table, record_id):
    row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
    if not row:
        raise auth.NotFound("Record not found")
    return row


def _scope_filter(conn, user, resource, params):
    """Return (extra_sql, args) enforcing row-level school isolation."""
    if user["role"] == "Super Admin":
        if params.get("school_id"):
            return " AND school_id = ?", [params["school_id"]]
        return "", []
    if resource in SCOPED or resource in ("time-slots", "conflicts", "runs"):
        return "", []
    return "", []


def list_resource(conn, user, resource, params):
    if resource not in TABLES:
        raise auth.NotFound("Unknown resource")
    if not auth.can_read(user, resource):
        raise auth.Forbidden("Your role cannot view this data")
    table = TABLES[resource]
    where, args = ["1=1"], []

    if resource == "notifications":
        where.append("user_id = ?")
        args.append(user["id"])
    if resource == "audit-logs" and user["role"] != "Super Admin":
        where.append("(user_id = ? OR details LIKE ?)")
        args.extend([user["id"], f"%{user['full_name']}%"])

    if resource == "schools" and user["role"] != "Super Admin" and user.get("school_id"):
        where.append("id = ?")
        args.append(user["school_id"])
    elif user["role"] != "Super Admin" and resource in SCOPED and user.get("school_id"):
        where.append("school_id = ?")
        args.append(user["school_id"])
    elif params.get("school_id") and resource in SCOPED:
        where.append("school_id = ?")
        args.append(params["school_id"])

    for key in ("role", "status", "severity", "resolution_status", "priority", "session",
                "academic_year", "semester", "is_active", "department_id", "examination_id",
                "scheduling_run_id", "invigilator_id", "solver_status", "constraint_type",
                "assignment_status", "is_read", "date"):
        if params.get(key) not in (None, ""):
            where.append(f"{key} = ?")
            args.append(params[key])

    if resource == "availability" and user["role"] == "Invigilator":
        inv = conn.execute("SELECT id FROM invigilators WHERE user_id=?", (user["id"],)).fetchone()
        where.append("invigilator_id = ?")
        args.append(inv["id"] if inv else "__none__")

    q = params.get("q")
    if q:
        like = f"%{q.strip()}%"
        cols = [c for c in SEARCH_FIELDS.get(resource, []) if c in _columns(conn, table)]
        if cols:
            where.append("(" + " OR ".join(f"{c} LIKE ?" for c in cols) + ")")
            args.extend([like] * len(cols))

    clause = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE {clause}", args).fetchone()["c"]

    try:
        page = max(1, int(params.get("page") or 1))
        page_size = min(500, max(1, int(params.get("page_size") or 25)))
    except (TypeError, ValueError):
        page, page_size = 1, 25
    sort = params.get("sort") or "created_date"
    cols = _columns(conn, table)
    sort_col = "created_at" if "created_at" in cols else cols[0]
    order = "DESC"
    if sort.startswith("-"):
        sort = sort[1:]
    else:
        order = "ASC" if params.get("order") == "asc" else "DESC"
    if sort in cols:
        sort_col = sort

    rows = conn.execute(
        f"SELECT * FROM {table} WHERE {clause} ORDER BY {sort_col} {order} LIMIT ? OFFSET ?",
        args + [page_size, (page - 1) * page_size]).fetchall()
    items = [db.decode_row(table, r) for r in rows]
    if resource == "users":
        for item in items:
            item.pop("password_hash", None)
    return {"items": items, "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size))}


def get_resource(conn, user, resource, record_id):
    if not auth.can_read(user, resource):
        raise auth.Forbidden("Your role cannot view this data")
    table = TABLES[resource]
    record = db.decode_row(table, _need(conn, table, record_id))
    if resource == "users":
        record.pop("password_hash", None)
    if user["role"] != "Super Admin" and resource in SCOPED and record.get("school_id") \
            and record["school_id"] != user.get("school_id"):
        raise auth.Forbidden("This record belongs to another school")
    return record


def create_resource(conn, user, resource, body):
    if not auth.can_write(user, resource):
        raise auth.Forbidden("Your role cannot create this record")
    table = TABLES[resource]
    body = dict(body or {})
    _validate(conn, user, resource, body, creating=True)

    if resource == "users":
        password = body.pop("password", None) or "Examflow@123"
        body["password_hash"] = auth.hash_password(password)
    data = _clean(table, body, conn)
    data["id"] = db.new_id()
    data["created_at"] = db.now_iso()
    if resource == "users":
        data["password_hash"] = body["password_hash"]
    cols = ", ".join(data.keys())
    marks = ", ".join("?" for _ in data)
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", list(data.values()))
    conn.commit()
    db.audit(conn, user, f"Created {resource}", table, data["id"])
    conn.commit()
    return get_resource(conn, user, resource, data["id"])


def update_resource(conn, user, resource, record_id, body):
    if not auth.can_write(user, resource):
        raise auth.Forbidden("Your role cannot edit this record")
    table = TABLES[resource]
    _need(conn, table, record_id)
    body = dict(body or {})
    _validate(conn, user, resource, body, creating=False)
    if resource == "users" and body.get("password"):
        body["password_hash"] = auth.hash_password(body.pop("password"))
    data = _clean(table, body, conn)
    if resource == "users" and body.get("password_hash"):
        data["password_hash"] = body["password_hash"]
    if "updated_at" in _columns(conn, table):
        data["updated_at"] = db.now_iso()
    if not data:
        return get_resource(conn, user, resource, record_id)
    sets = ", ".join(f"{k} = ?" for k in data)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", list(data.values()) + [record_id])
    conn.commit()
    db.audit(conn, user, f"Updated {resource}", table, record_id,
             ", ".join(sorted(k for k in data if k != "password_hash")))
    conn.commit()
    return get_resource(conn, user, resource, record_id)


def delete_resource(conn, user, resource, record_id):
    if not auth.can_write(user, resource):
        raise auth.Forbidden("Your role cannot delete this record")
    table = TABLES[resource]
    _need(conn, table, record_id)
    _check_dependencies(conn, resource, record_id)
    conn.execute(f"DELETE FROM {table} WHERE id=?", (record_id,))
    conn.commit()
    db.audit(conn, user, f"Deleted {resource}", table, record_id)
    conn.commit()
    return {"deleted": record_id}


def _check_dependencies(conn, resource, record_id):
    checks = {
        "schools": [("departments", "departments"), ("examinations", "examinations"),
                    ("rooms", "rooms"), ("student_groups", "student groups")],
        "departments": [("student_groups", "student groups"), ("examinations", "examinations")],
        "examinations": [("schedule_assignments", "schedule assignments")],
        "rooms": [("schedule_assignments", "schedule assignments")],
        "invigilators": [("invigilator_assignments", "invigilation duties")],
        "student-groups": [("examinations", "examinations")],
    }
    for table, label in checks.get(resource, []):
        col = "school_id" if resource in ("schools",) else \
            ("department_id" if resource == "departments" else
             ("examination_id" if resource == "examinations" else
              ("room_id" if resource == "rooms" else
               ("invigilator_id" if resource == "invigilators" else "id"))))
        if resource == "student-groups":
            rows = conn.execute("SELECT student_group_ids FROM examinations").fetchall()
            used = [r for r in rows if record_id in json.loads(r["student_group_ids"] or "[]")]
            if used:
                raise auth.ValidationError(
                    f"This student group is used by {len(used)} examination(s). Remove it from them first.")
            continue
        count = conn.execute(f"SELECT COUNT(*) c FROM {table} WHERE {col}=?",
                             (record_id,)).fetchone()["c"]
        if count:
            raise auth.ValidationError(
                f"Cannot delete: {count} {label} still reference this record.")


def _validate(conn, user, resource, body, creating):
    if resource == "schools":
        code = body.get("school_code")
        if code:
            dup = conn.execute("SELECT id FROM schools WHERE UPPER(school_code)=UPPER(?) AND id!=?",
                               (code, body.get("id") or "")).fetchone()
            if dup:
                raise auth.ValidationError("School code must be unique.")
        if creating and not body.get("school_name"):
            raise auth.ValidationError("School name is required.")
    if resource in SCOPED and user["role"] != "Super Admin" and creating:
        if not body.get("school_id"):
            body["school_id"] = user.get("school_id")
        elif body["school_id"] != user.get("school_id"):
            raise auth.Forbidden("You can only create records for your own school.")
    if resource == "student-groups" and creating:
        dup = conn.execute(
            "SELECT id FROM student_groups WHERE school_id=? AND group_name=? AND semester=? AND section=?",
            (body.get("school_id"), body.get("group_name"), body.get("semester"),
             body.get("section"))).fetchone()
        if dup:
            raise auth.ValidationError("A group with the same name, semester and section already exists.")
        if not body.get("student_count"):
            raise auth.ValidationError("Student count is required.")
    if resource == "rooms":
        try:
            if int(body.get("capacity") or 0) <= 0:
                raise auth.ValidationError("Room capacity must be greater than zero.")
        except (TypeError, ValueError):
            raise auth.ValidationError("Room capacity must be a number.")
    if resource == "time-slots":
        start, end = body.get("start_time"), body.get("end_time")
        if start and end and _minutes(end) <= _minutes(start):
            raise auth.ValidationError("End time must be later than start time.")
        if creating and not body.get("examination_date"):
            raise auth.ValidationError("Examination date is required.")
    if resource == "availability":
        start, end = body.get("start_time"), body.get("end_time")
        if start and end and _minutes(end) <= _minutes(start):
            raise auth.ValidationError("End time must be later than start time.")
        if not body.get("invigilator_id") and creating:
            raise auth.ValidationError("Select an invigilator.")
    if resource == "examinations":
        if creating:
            if not body.get("subject_name") or not body.get("subject_code"):
                raise auth.ValidationError("Subject name and code are required.")
            if not body.get("school_id") or not body.get("student_group_ids"):
                raise auth.ValidationError("Select a school and at least one student group.")
        groups = body.get("student_group_ids")
        if groups:
            if isinstance(groups, str):
                groups = [g for g in groups.split(",") if g]
                body["student_group_ids"] = groups
            marks = ",".join("?" for _ in groups)
            rows = conn.execute(
                f"SELECT id, school_id, student_count FROM student_groups WHERE id IN ({marks})",
                groups).fetchall()
            if len(rows) != len(groups):
                raise auth.ValidationError("One or more student groups no longer exist.")
            school_id = body.get("school_id") or (rows[0]["school_id"] if rows else None)
            if any(r["school_id"] != school_id for r in rows):
                raise auth.ValidationError("All selected student groups must belong to the same school.")
            body["school_id"] = school_id
            body["required_seating_capacity"] = sum(r["student_count"] for r in rows)
        duration = body.get("duration_minutes")
        if duration is not None:
            try:
                if int(duration) <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                raise auth.ValidationError("Duration must be a positive number of minutes.")
    if resource == "users":
        email = body.get("email")
        if email:
            dup = conn.execute("SELECT id FROM users WHERE LOWER(email)=LOWER(?) AND id!=?",
                               (email, body.get("id") or "")).fetchone()
            if dup:
                raise auth.ValidationError("That email address is already registered.")
        if creating and not email:
            raise auth.ValidationError("Email is required.")


def _minutes(value):
    try:
        h, m = [int(x) for x in str(value).split(":")[:2]]
        return h * 60 + m
    except (ValueError, AttributeError):
        return 0


# ----------------------------------------------------------------- CSV import
def import_csv(conn, user, resource, text):
    if resource not in ("examinations", "student-groups", "rooms", "invigilators"):
        raise auth.ValidationError("CSV import is available for examinations, student groups, rooms and invigilators.")
    reader = csv.DictReader(io.StringIO(text or ""))
    created, errors = 0, []
    for index, row in enumerate(reader, start=2):
        try:
            body = _map_import_row(conn, user, resource, row)
            create_resource(conn, user, resource, body)
            created += 1
        except (auth.ValidationError, auth.Forbidden, KeyError, ValueError) as exc:
            errors.append(f"Row {index}: {exc}")
    return {"created": created, "errors": errors, "total": created + len(errors)}


def _map_import_row(conn, user, resource, row):
    clean = {k.strip().lower().replace(" ", "_"): (v or "").strip() for k, v in row.items() if k}
    if resource == "student-groups":
        school = conn.execute("SELECT id FROM schools WHERE school_code=?",
                              (clean.get("school_code", ""),)).fetchone()
        dept = conn.execute("SELECT id FROM departments WHERE department_code=?",
                            (clean.get("department_code", ""),)).fetchone()
        if not school or not dept:
            raise ValueError("unknown school_code or department_code")
        return {"school_id": school["id"], "department_id": dept["id"],
                "group_name": clean.get("group_name"), "semester": int(clean.get("semester") or 1),
                "section": clean.get("section") or "A",
                "student_count": int(clean.get("student_count") or 0),
                "academic_year": clean.get("academic_year") or "2026-27"}
    if resource == "examinations":
        school = conn.execute("SELECT id FROM schools WHERE school_code=?",
                              (clean.get("school_code", ""),)).fetchone()
        if not school:
            raise ValueError("unknown school_code")
        codes = [c.strip() for c in (clean.get("group_codes") or "").split(";") if c.strip()]
        groups = []
        for code in codes:
            g = conn.execute(
                "SELECT id FROM student_groups WHERE group_name LIKE ? AND school_id=?",
                (f"%{code}%", school["id"])).fetchone()
            if g:
                groups.append(g["id"])
        if not groups:
            raise ValueError("no matching group_codes")
        return {"school_id": school["id"], "subject_name": clean.get("subject_name"),
                "subject_code": clean.get("subject_code"),
                "examination_type": clean.get("examination_type") or "Written",
                "student_group_ids": groups,
                "duration_minutes": int(clean.get("duration_minutes") or 120),
                "priority": clean.get("priority") or "Medium",
                "preferred_dates": [clean["preferred_date"]] if clean.get("preferred_date") else [],
                "required_facilities": [f.strip() for f in (clean.get("facilities") or "").split(";") if f.strip()],
                "status": "Pending"}
    if resource == "rooms":
        school = conn.execute("SELECT id FROM schools WHERE school_code=?",
                              (clean.get("school_code", ""),)).fetchone()
        if not school:
            raise ValueError("unknown school_code")
        return {"school_id": school["id"], "room_number": clean.get("room_number"),
                "building": clean.get("building") or "Main Block",
                "floor": int(clean.get("floor") or 1),
                "capacity": int(clean.get("capacity") or 0),
                "room_type": clean.get("room_type") or "Classroom",
                "is_accessible": 1, "is_active": 1,
                "facilities": [f.strip() for f in (clean.get("facilities") or "").split(";") if f.strip()]}
    if resource == "invigilators":
        school = conn.execute("SELECT id FROM schools WHERE school_code=?",
                              (clean.get("school_code", ""),)).fetchone()
        if not school:
            raise ValueError("unknown school_code")
        return {"school_id": school["id"], "name": clean.get("name"),
                "employee_code": clean.get("employee_code"),
                "email": clean.get("email"), "status": "Active",
                "maximum_daily_duties": int(clean.get("maximum_daily_duties") or 2),
                "maximum_total_duties": int(clean.get("maximum_total_duties") or 8)}
    raise ValueError("unsupported resource")


# ------------------------------------------------------------------- metadata
def meta(conn, user):
    def rows(sql, args=()):
        return [dict(r) for r in conn.execute(sql, args).fetchall()]

    schools = db and [db.decode_row("schools", r) for r in conn.execute(
        "SELECT * FROM schools ORDER BY school_name").fetchall()]
    if user["role"] != "Super Admin" and user.get("school_id"):
        schools = [s for s in schools if s["id"] == user["school_id"]]
    depts = [{"id": r["id"], "name": r["department_name"], "school_id": r["school_id"],
              "code": r["department_code"]} for r in conn.execute(
        "SELECT * FROM departments ORDER BY department_name").fetchall()]
    groups = [{"id": r["id"], "name": r["group_name"], "school_id": r["school_id"],
               "student_count": r["student_count"], "semester": r["semester"],
               "section": r["section"]} for r in conn.execute(
        "SELECT * FROM student_groups ORDER BY group_name").fetchall()]
    rooms = [{"id": r["id"], "name": r["room_number"], "school_id": r["school_id"],
              "capacity": r["capacity"]} for r in conn.execute(
        "SELECT * FROM rooms WHERE is_active=1 ORDER BY room_number").fetchall()]
    invs = [{"id": r["id"], "name": r["name"], "school_id": r["school_id"],
             "code": r["employee_code"]} for r in conn.execute(
        "SELECT * FROM invigilators ORDER BY name").fetchall()]
    exams = [{"id": r["id"], "name": f"{r['subject_code']} · {r['subject_name']}",
              "school_id": r["school_id"], "priority": r["priority"],
              "status": r["status"]} for r in conn.execute(
        "SELECT * FROM examinations WHERE COALESCE(status,'Active')!='Cancelled' ORDER BY subject_code").fetchall()]
    policies = [db.decode_row("constraint_policies", r) for r in conn.execute(
        "SELECT * FROM constraint_policies ORDER BY constraint_type DESC, policy_name").fetchall()]
    slots = [db.decode_row("time_slots", r) for r in conn.execute(
        "SELECT * FROM time_slots ORDER BY examination_date, start_time").fetchall()]
    return {
        "schools": schools, "departments": depts, "groups": groups, "rooms": rooms,
        "invigilators": invs, "examinations": exams, "policies": policies,
        "slots": slots, "sessions": ["2026-27", "2027-28"],
        "priorities": ["Critical", "High", "Medium", "Low"],
        "roles": ["Super Admin", "School Admin", "Invigilator"],
        "algorithms": [{"key": k, "name": v} for k, v in solver_service.ALGORITHMS.items()],
        "cpsat": {"available": False, "note": "OR-Tools CP-SAT is not installed in this deployment. "
                                              "The CSP engine runs locally; a FastAPI solver can be "
                                              "plugged into /api/solver/endpoint later."},
    }


# ------------------------------------------------------------------ dashboard
def dashboard(conn, user):
    school_id = user.get("school_id") if user["role"] != "Super Admin" else None
    where, args = ("WHERE school_id = ?", [school_id]) if school_id else ("", [])

    def one(sql, params=()):
        return conn.execute(sql, params).fetchone()["c"]

    counts = {
        "schools": 1 if school_id else one("SELECT COUNT(*) c FROM schools"),
        "departments": one(f"SELECT COUNT(*) c FROM departments {where}", args),
        "examinations": one(f"SELECT COUNT(*) c FROM examinations {where}", args),
        "student_groups": one(f"SELECT COUNT(*) c FROM student_groups {where}", args),
        "students": one(f"SELECT COALESCE(SUM(student_count),0) c FROM student_groups {where}", args),
        "rooms": one(f"SELECT COUNT(*) c FROM rooms {where}", args),
        "invigilators": one(f"SELECT COUNT(*) c FROM invigilators {where}", args),
        "scheduled": one(f"SELECT COUNT(*) c FROM examinations {where} "
                         + ("AND" if where else "WHERE") + " status='Scheduled'", args),
        "pending": one(f"SELECT COUNT(*) c FROM examinations {where} "
                       + ("AND" if where else "WHERE") + " COALESCE(status,'Pending')!='Scheduled'", args),
        "conflicts": one("SELECT COUNT(*) c FROM conflict_logs WHERE resolution_status='Open'"),
        "runs": one("SELECT COUNT(*) c FROM scheduling_runs"),
        "published": one("SELECT COUNT(*) c FROM scheduling_runs WHERE status='Published'"),
    }

    exams_by_school = [{"label": r["school_code"], "value": r["c"]} for r in conn.execute(
        "SELECT s.school_code, COUNT(e.id) c FROM schools s LEFT JOIN examinations e "
        "ON e.school_id = s.id GROUP BY s.id ORDER BY c DESC").fetchall()]

    latest = conn.execute(
        "SELECT * FROM scheduling_runs WHERE solver_status LIKE 'FEASIBLE%' OR solver_status='INFEASIBLE' "
        "ORDER BY created_at DESC LIMIT 1").fetchone()
    latest_id = latest["id"] if latest else None
    daily, room_usage, workload = [], [], []
    if latest_id:
        daily = [{"label": r["d"], "value": r["c"]} for r in conn.execute(
            "SELECT examination_date d, COUNT(*) c FROM schedule_assignments "
            "WHERE scheduling_run_id=? GROUP BY examination_date ORDER BY examination_date",
            (latest_id,)).fetchall()]
        room_usage = [{"label": r["room_number"] or "-", "value": round(100 * (r["used"] or 0) / 1, 1),
                       "capacity": r["capacity"] or 0, "bookings": r["c"]} for r in conn.execute(
            """SELECT r.room_number, r.capacity, COUNT(sa.id) c, SUM(e.required_seating_capacity) used
               FROM schedule_assignments sa JOIN rooms r ON r.id = sa.room_id
               JOIN examinations e ON e.id = sa.examination_id
               WHERE sa.scheduling_run_id=? GROUP BY r.id ORDER BY c DESC""", (latest_id,)).fetchall()]
        workload = [{"label": r["name"], "value": r["c"]} for r in conn.execute(
            """SELECT i.name, COUNT(ia.id) c FROM invigilator_assignments ia
               JOIN schedule_assignments sa ON sa.id = ia.schedule_assignment_id
               JOIN invigilators i ON i.id = ia.invigilator_id
               WHERE sa.scheduling_run_id=? GROUP BY i.id ORDER BY c DESC""", (latest_id,)).fetchall()]

    csp_run = conn.execute(
        "SELECT * FROM scheduling_runs WHERE algorithm_name LIKE 'CSP%' ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    ff_run = conn.execute(
        "SELECT * FROM scheduling_runs WHERE algorithm_name LIKE 'First-Fit%' ORDER BY created_at DESC "
        "LIMIT 1").fetchone()
    comparison = None
    if csp_run and ff_run:
        comparison = solver_service.compare_runs(conn, ff_run["id"], csp_run["id"])

    upcoming = []
    if latest_id:
        upcoming = [dict(r) for r in conn.execute(
            """SELECT sa.examination_date, sa.start_time, sa.end_time, e.subject_name, e.subject_code,
                      s.school_code, r.room_number
               FROM schedule_assignments sa JOIN examinations e ON e.id = sa.examination_id
               LEFT JOIN schools s ON s.id = e.school_id LEFT JOIN rooms r ON r.id = sa.room_id
               WHERE sa.scheduling_run_id=? ORDER BY sa.examination_date, sa.start_time LIMIT 6""",
            (latest_id,)).fetchall()]

    recent = [dict(r) for r in conn.execute(
        "SELECT action, entity_type, details, timestamp AS created_at FROM audit_logs "
        "ORDER BY timestamp DESC LIMIT 6"
    ).fetchall()]
    conflicts = [dict(r) for r in conn.execute(
        "SELECT conflict_type, description, severity, created_at FROM conflict_logs "
        "WHERE resolution_status='Open' ORDER BY created_at DESC LIMIT 5").fetchall()]

    return {
        "counts": counts, "exams_by_school": exams_by_school,
        "daily": daily, "room_usage": room_usage, "workload": workload,
        "latest_run": db.decode_row("scheduling_runs", latest) if latest else None,
        "comparison": comparison, "upcoming": upcoming, "recent": recent, "conflicts": conflicts,
        "scheduled_split": [{"label": "Scheduled", "value": counts["scheduled"]},
                            {"label": "Pending", "value": counts["pending"]}],
        "fairness": solver_service.fairness_for_run(conn, latest_id)["summary"] if latest_id else {},
    }


# -------------------------------------------------------------------- reports
def _run_assignments(conn, run_id):
    return solver_service.assignments_for_run(conn, run_id)


def _resolve_run(conn, params):
    if params.get("run_id"):
        return params["run_id"]
    row = conn.execute(
        "SELECT id FROM scheduling_runs WHERE status='Published' ORDER BY published_at DESC LIMIT 1"
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT id FROM scheduling_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        raise auth.ValidationError("No scheduling run exists yet. Generate a timetable first.")
    return row["id"]


def report(conn, user, kind, params):
    run_id = _resolve_run(conn, params) if kind not in ("performance",) else None
    school_filter = params.get("school_id")

    def filtered(rows):
        return [r for r in rows if not school_filter or r.get("school_id") == school_filter]

    if kind in ("timetable", "school", "group"):
        rows = filtered(_run_assignments(conn, run_id))
        columns = [
            ("examination_date", "Date"), ("start_time", "Start"), ("end_time", "End"),
            ("subject_code", "Code"), ("subject_name", "Examination"), ("school_code", "School"),
            ("room_number", "Room"), ("required_seating_capacity", "Students"),
            ("invigilator_names", "Invigilators"), ("assignment_status", "Status"),
        ]
        return {"title": "Complete examination timetable", "columns": columns,
                "rows": rows, "run_id": run_id, "count": len(rows)}

    if kind == "invigilator":
        rows = filtered(_run_assignments(conn, run_id))
        out = {}
        for a in rows:
            for inv in a["invigilators"]:
                entry = out.setdefault(inv["invigilator_id"], {
                    "invigilator": inv["name"], "employee_code": inv["employee_code"],
                    "school_id": inv["school_id"], "duties": 0, "dates": []})
                entry["duties"] += 1
                entry["dates"].append(f"{a['examination_date']} {a['start_time']}")
        data = sorted(out.values(), key=lambda r: r["duties"], reverse=True)
        columns = [("invigilator", "Invigilator"), ("employee_code", "Code"),
                   ("duties", "Duties"), ("dates", "Duty dates")]
        for row in data:
            row["dates"] = ", ".join(row["dates"])
        return {"title": "Invigilator duty report", "columns": columns, "rows": data,
                "run_id": run_id, "count": len(data)}

    if kind == "room":
        rows = filtered(_run_assignments(conn, run_id))
        usage = {}
        for a in rows:
            key = a.get("room_number") or "Unassigned"
            entry = usage.setdefault(key, {"room": key, "bookings": 0, "seats_used": 0,
                                           "capacity": a.get("room_capacity") or 0})
            entry["bookings"] += 1
            entry["seats_used"] += a.get("required_seating_capacity") or 0
        data = sorted(usage.values(), key=lambda r: r["bookings"], reverse=True)
        for row in data:
            cap = row["capacity"] * max(row["bookings"], 1)
            row["utilisation"] = f"{round(100 * row['seats_used'] / cap, 1)}%" if cap else "0%"
        columns = [("room", "Room"), ("bookings", "Bookings"), ("seats_used", "Seats used"),
                   ("utilisation", "Seat utilisation")]
        return {"title": "Room utilisation report", "columns": columns, "rows": data,
                "run_id": run_id, "count": len(data)}

    if kind == "conflict":
        rows = [db.decode_row("conflict_logs", r) for r in conn.execute(
            "SELECT * FROM conflict_logs WHERE scheduling_run_id=? ORDER BY severity, created_at",
            (run_id,)).fetchall()]
        columns = [("conflict_type", "Type"), ("severity", "Severity"), ("description", "Description"),
                   ("suggested_resolution", "Suggested resolution"), ("resolution_status", "Status")]
        return {"title": "Conflict report", "columns": columns, "rows": rows, "run_id": run_id,
                "count": len(rows)}

    if kind == "fairness":
        fair = solver_service.fairness_for_run(conn, run_id)
        rows = [{"invigilator": p["name"], "duties": p["duties"]} for p in fair["per_invigilator"]]
        columns = [("invigilator", "Invigilator"), ("duties", "Duties")]
        return {"title": "Fairness report", "columns": columns, "rows": rows, "run_id": run_id,
                "count": len(rows), "summary": fair["summary"]}

    if kind == "comparison":
        csp = conn.execute("SELECT id FROM scheduling_runs WHERE algorithm_name LIKE 'CSP%' "
                           "ORDER BY created_at DESC LIMIT 1").fetchone()
        ff = conn.execute("SELECT id FROM scheduling_runs WHERE algorithm_name LIKE 'First-Fit%' "
                          "ORDER BY created_at DESC LIMIT 1").fetchone()
        if not (csp and ff):
            raise auth.ValidationError("Run both the AI search and the First-Fit baseline to compare them.")
        cmp = solver_service.compare_runs(conn, ff["id"], csp["id"])
        rows = []
        labels = {"scheduled_examinations": "Scheduled examinations",
                  "unscheduled_examinations": "Unscheduled examinations",
                  "hard_constraint_violations": "Hard constraint violations",
                  "soft_constraint_penalty": "Soft constraint penalty",
                  "workload_standard_deviation": "Workload standard deviation",
                  "fairness_score": "Fairness score",
                  "room_utilization": "Room utilisation (%)",
                  "execution_time": "Execution time (s)"}
        for key, label in labels.items():
            rows.append({"metric": label, "baseline": cmp["baseline"][key],
                         "candidate": cmp["candidate"][key], "difference": cmp["deltas"][key]})
        columns = [("metric", "Metric"), ("baseline", "First-Fit"),
                   ("candidate", "AI (CSP)"), ("difference", "Difference")]
        return {"title": "AI vs First-Fit comparison", "columns": columns, "rows": rows,
                "run_id": None, "count": len(rows), "detail": cmp}

    if kind == "performance":
        rows = [db.decode_row("scheduling_runs", r) for r in conn.execute(
            "SELECT * FROM scheduling_runs ORDER BY created_at DESC LIMIT 25").fetchall()]
        for row in rows:
            notes = row.get("notes")
            stats = (json.loads(notes) if isinstance(notes, str) else notes or {}).get("stats", {})
            row["nodes"] = stats.get("nodes_explored", 0)
            row["backtracks"] = stats.get("backtracks", 0)
        columns = [("run_name", "Run"), ("algorithm_name", "Algorithm"), ("solver_status", "Status"),
                   ("scheduled_examinations", "Scheduled"), ("hard_constraint_violations", "Violations"),
                   ("soft_constraint_penalty", "Penalty"), ("nodes", "Nodes"),
                   ("execution_time", "Seconds")]
        return {"title": "Scheduling performance report", "columns": columns, "rows": rows,
                "run_id": None, "count": len(rows)}

    raise auth.NotFound("Unknown report type")


def report_csv(conn, user, kind, params):
    data = report(conn, user, kind, params)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([label for _, label in data["columns"]])
    for row in data["rows"]:
        writer.writerow([row.get(key, "") for key, _ in data["columns"]])
    return buffer.getvalue(), f"{kind}-report.csv"


# ------------------------------------------------------------- invigilator API
def my_duties(conn, user):
    inv = conn.execute("SELECT * FROM invigilators WHERE user_id=?", (user["id"],)).fetchone()
    if not inv:
        inv = conn.execute("SELECT * FROM invigilators WHERE LOWER(email)=LOWER(?)",
                           (user.get("email") or "",)).fetchone()
    if not inv:
        return {"invigilator": None, "duties": [], "workload": {}, "availability": []}
    inv = db.decode_row("invigilators", inv)
    duties = [dict(r) for r in conn.execute(
        """SELECT sa.examination_date, sa.start_time, sa.end_time, e.subject_name, e.subject_code,
                  s.school_name, r.room_number, sr.run_name, sr.status run_status
           FROM invigilator_assignments ia
           JOIN schedule_assignments sa ON sa.id = ia.schedule_assignment_id
           JOIN scheduling_runs sr ON sr.id = sa.scheduling_run_id
           JOIN examinations e ON e.id = sa.examination_id
           LEFT JOIN schools s ON s.id = e.school_id
           LEFT JOIN rooms r ON r.id = sa.room_id
           WHERE ia.invigilator_id = ?
           ORDER BY sa.examination_date, sa.start_time""", (inv["id"],)).fetchall()]
    availability = [db.decode_row("invigilator_availability", r) for r in conn.execute(
        "SELECT * FROM invigilator_availability WHERE invigilator_id=? ORDER BY date",
        (inv["id"],)).fetchall()]
    dates = sorted({d["examination_date"] for d in duties})
    return {
        "invigilator": inv, "duties": duties,
        "workload": {"total": len(duties), "days": len(dates),
                     "maximum_total": inv.get("maximum_total_duties"),
                     "maximum_daily": inv.get("maximum_daily_duties")},
        "availability": availability,
    }


def report_availability_issue(conn, user, body):
    inv = conn.execute("SELECT * FROM invigilators WHERE user_id=?", (user["id"],)).fetchone()
    if not inv:
        raise auth.ValidationError("No invigilator profile is linked to your account.")
    body = body or {}
    if not body.get("date"):
        raise auth.ValidationError("Select the date you have an issue with.")
    conn.execute(
        """INSERT INTO invigilator_availability (id, invigilator_id, date, start_time, end_time,
           availability_status, reason, created_at) VALUES (?,?,?,?,?,?,?,?)""",
        (db.new_id(), inv["id"], body["date"], body.get("start_time") or "09:00",
         body.get("end_time") or "17:00", "Unavailable",
         body.get("reason") or "Reported by invigilator", db.now_iso()))
    conn.commit()
    for admin in conn.execute("SELECT id FROM users WHERE role='School Admin' AND school_id=?",
                              (inv["school_id"],)).fetchall():
        db.notify(conn, admin["id"], "Availability issue reported",
                  f"{inv['name']} reported an issue on {body['date']}.")
    conn.commit()
    db.audit(conn, user, "Availability issue reported", "invigilator", inv["id"], body.get("reason"))
    conn.commit()
    return {"ok": True}
