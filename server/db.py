"""ExamFlow AI - database layer (SQLite, stdlib only).

Every table maps to one of the 17 entities described in the project specification.
JSON-ish columns (lists) are stored as TEXT and serialised at the edges.
"""
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(BASE_DIR)
DB_PATH = os.environ.get("EXAMFLOW_DB", os.path.join(PROJECT_DIR, "examflow.db"))

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schools (
    id TEXT PRIMARY KEY,
    school_name TEXT NOT NULL,
    school_code TEXT NOT NULL UNIQUE,
    address TEXT,
    contact_email TEXT,
    contact_number TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    school_id TEXT REFERENCES schools(id) ON DELETE SET NULL,
    department_id TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS departments (
    id TEXT PRIMARY KEY,
    school_id TEXT NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    department_name TEXT NOT NULL,
    department_code TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS student_groups (
    id TEXT PRIMARY KEY,
    school_id TEXT NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    department_id TEXT REFERENCES departments(id) ON DELETE SET NULL,
    group_name TEXT NOT NULL,
    semester INTEGER,
    section TEXT,
    student_count INTEGER NOT NULL DEFAULT 0,
    academic_year TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS examinations (
    id TEXT PRIMARY KEY,
    school_id TEXT NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    department_id TEXT REFERENCES departments(id) ON DELETE SET NULL,
    subject_name TEXT NOT NULL,
    subject_code TEXT NOT NULL,
    examination_type TEXT,
    student_group_ids TEXT NOT NULL DEFAULT '[]',
    duration_minutes INTEGER NOT NULL DEFAULT 120,
    priority TEXT NOT NULL DEFAULT 'Medium',
    preferred_dates TEXT NOT NULL DEFAULT '[]',
    required_seating_capacity INTEGER NOT NULL DEFAULT 0,
    required_facilities TEXT NOT NULL DEFAULT '[]',
    special_requirements TEXT,
    status TEXT NOT NULL DEFAULT 'Pending',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rooms (
    id TEXT PRIMARY KEY,
    school_id TEXT NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    room_number TEXT NOT NULL,
    building TEXT,
    floor TEXT,
    capacity INTEGER NOT NULL DEFAULT 0,
    room_type TEXT,
    is_accessible INTEGER NOT NULL DEFAULT 0,
    facilities TEXT NOT NULL DEFAULT '[]',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invigilators (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    school_id TEXT NOT NULL REFERENCES schools(id) ON DELETE CASCADE,
    department_id TEXT REFERENCES departments(id) ON DELETE SET NULL,
    employee_code TEXT,
    name TEXT NOT NULL,
    email TEXT,
    maximum_daily_duties INTEGER NOT NULL DEFAULT 2,
    maximum_total_duties INTEGER NOT NULL DEFAULT 10,
    preferred_duties INTEGER NOT NULL DEFAULT 4,
    qualification TEXT,
    status TEXT NOT NULL DEFAULT 'Active',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS time_slots (
    id TEXT PRIMARY KEY,
    examination_date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    session TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invigilator_availability (
    id TEXT PRIMARY KEY,
    invigilator_id TEXT NOT NULL REFERENCES invigilators(id) ON DELETE CASCADE,
    date TEXT NOT NULL,
    start_time TEXT,
    end_time TEXT,
    availability_status TEXT NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS constraint_policies (
    id TEXT PRIMARY KEY,
    policy_name TEXT NOT NULL,
    constraint_type TEXT NOT NULL,
    description TEXT,
    is_mandatory INTEGER NOT NULL DEFAULT 1,
    penalty_weight REAL NOT NULL DEFAULT 1.0,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    scope TEXT NOT NULL DEFAULT 'global',
    school_id TEXT REFERENCES schools(id) ON DELETE CASCADE,
    rule_code TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scheduling_runs (
    id TEXT PRIMARY KEY,
    run_name TEXT NOT NULL,
    algorithm_name TEXT NOT NULL,
    start_time TEXT NOT NULL,
    completion_time TEXT,
    status TEXT NOT NULL DEFAULT 'Running',
    solver_status TEXT,
    total_examinations INTEGER NOT NULL DEFAULT 0,
    scheduled_examinations INTEGER NOT NULL DEFAULT 0,
    unscheduled_examinations INTEGER NOT NULL DEFAULT 0,
    hard_constraint_violations INTEGER NOT NULL DEFAULT 0,
    soft_constraint_penalty REAL NOT NULL DEFAULT 0,
    execution_time REAL NOT NULL DEFAULT 0,
    configuration TEXT NOT NULL DEFAULT '{}',
    created_by TEXT,
    created_at TEXT NOT NULL,
    published_at TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS schedule_assignments (
    id TEXT PRIMARY KEY,
    scheduling_run_id TEXT NOT NULL REFERENCES scheduling_runs(id) ON DELETE CASCADE,
    examination_id TEXT NOT NULL REFERENCES examinations(id) ON DELETE CASCADE,
    room_id TEXT REFERENCES rooms(id) ON DELETE SET NULL,
    time_slot_id TEXT REFERENCES time_slots(id) ON DELETE SET NULL,
    examination_date TEXT,
    start_time TEXT,
    end_time TEXT,
    assignment_status TEXT NOT NULL DEFAULT 'Scheduled',
    priority TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS invigilator_assignments (
    id TEXT PRIMARY KEY,
    schedule_assignment_id TEXT NOT NULL REFERENCES schedule_assignments(id) ON DELETE CASCADE,
    invigilator_id TEXT NOT NULL REFERENCES invigilators(id) ON DELETE CASCADE,
    duty_status TEXT NOT NULL DEFAULT 'Assigned',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_explanations (
    id TEXT PRIMARY KEY,
    scheduling_run_id TEXT NOT NULL REFERENCES scheduling_runs(id) ON DELETE CASCADE,
    schedule_assignment_id TEXT REFERENCES schedule_assignments(id) ON DELETE CASCADE,
    decision_reason TEXT,
    alternatives_considered INTEGER NOT NULL DEFAULT 0,
    constraints_satisfied TEXT,
    rejected_alternatives TEXT,
    explanation_type TEXT NOT NULL DEFAULT 'assignment',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conflict_logs (
    id TEXT PRIMARY KEY,
    scheduling_run_id TEXT REFERENCES scheduling_runs(id) ON DELETE CASCADE,
    conflict_type TEXT NOT NULL,
    description TEXT,
    severity TEXT NOT NULL DEFAULT 'Medium',
    affected_examination TEXT,
    affected_room TEXT,
    affected_invigilator TEXT,
    suggested_resolution TEXT,
    resolution_status TEXT NOT NULL DEFAULT 'Open',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fairness_metrics (
    id TEXT PRIMARY KEY,
    scheduling_run_id TEXT NOT NULL REFERENCES scheduling_runs(id) ON DELETE CASCADE,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    metric_description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    user_name TEXT,
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id TEXT,
    timestamp TEXT NOT NULL,
    details TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
    id TEXT PRIMARY KEY,
    user_id TEXT,
    title TEXT NOT NULL,
    message TEXT,
    type TEXT NOT NULL DEFAULT 'info',
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_exam_school ON examinations(school_id);
CREATE INDEX IF NOT EXISTS idx_assign_run ON schedule_assignments(scheduling_run_id);
"""

JSON_FIELDS = {
    "student_group_ids": "examinations",
    "preferred_dates": "examinations",
    "required_facilities": "examinations",
    "facilities": "rooms",
    "configuration": "scheduling_runs",
    "constraints_satisfied": "schedule_explanations",
    "rejected_alternatives": "schedule_explanations",
}

BOOL_FIELDS = {"is_active", "is_accessible", "is_mandatory", "is_enabled", "is_read"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id() -> str:
    return uuid.uuid4().hex[:24]


def connect() -> sqlite3.Connection:
    import persistence
    persistence.ensure_restored()
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(seed: bool = True) -> None:
    import persistence
    persistence.ensure_restored()
    fresh = not os.path.exists(DB_PATH)
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    if seed and fresh:
        from seed import seed_database
        seed_database()


def decode_row(table: str, row: sqlite3.Row) -> dict:
    data = dict(row)
    for field, tbl in JSON_FIELDS.items():
        if tbl == table and field in data and isinstance(data[field], str):
            try:
                data[field] = json.loads(data[field])
            except (ValueError, TypeError):
                data[field] = []
    for field in BOOL_FIELDS:
        if field in data and data[field] is not None:
            data[field] = bool(data[field])
    return data


def encode_value(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    if isinstance(value, bool):
        return 1 if value else 0
    return value


def audit(conn, user, action, entity_type=None, entity_id=None, details=None):
    conn.execute(
        "INSERT INTO audit_logs (id,user_id,user_name,action,entity_type,entity_id,timestamp,details)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (new_id(), user.get("id") if user else None, user.get("full_name") if user else "system",
         action, entity_type, entity_id, now_iso(), details))


def notify(conn, user_id, title, message, ntype="info"):
    conn.execute(
        "INSERT INTO notifications (id,user_id,title,message,type,is_read,created_at)"
        " VALUES (?,?,?,?,?,0,?)",
        (new_id(), user_id, title, message, ntype, now_iso()))
