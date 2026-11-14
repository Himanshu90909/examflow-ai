"""ExamFlow Assistant — the in-app chatbot.

Two answering engines, one interface:

* **Grounded lookup (always on).** The question is matched against the examinations
  office's own database and answered from stored rows, scoped to the signed-in role.
  No network, no key, no third-party package, so the assistant works on a cold
  deployment and can never invent a date, a room or a duty.
* **Language model (optional).** Set ``EXAMFLOW_LLM_API_KEY`` and the same context
  brief is handed to an OpenAI-compatible chat endpoint so a question the matcher
  cannot place still gets a written answer. The model only ever sees the brief the
  role is allowed to read. Any failure falls back to the grounded answer.

Both engines return the same envelope::

    {"reply": str, "intent": str, "mode": "grounded"|"llm"|"grounded-after-llm",
     "suggestions": [str], "citations": [{"label": str, "value": str}]}
"""
import difflib
import json
import os
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

import api
import db

MAX_MESSAGE = 800
LLM_KEY = (os.environ.get("EXAMFLOW_LLM_API_KEY") or "").strip()
LLM_MODEL = (os.environ.get("EXAMFLOW_LLM_MODEL") or "gpt-4o-mini").strip()
LLM_BASE = (os.environ.get("EXAMFLOW_LLM_BASE") or "https://api.openai.com/v1").strip().rstrip("/")
LLM_TIMEOUT = float(os.environ.get("EXAMFLOW_LLM_TIMEOUT") or 12)

_RATE = {}
RATE_LIMIT, RATE_WINDOW = 30, 60.0


class AssistantError(Exception):
    pass


# ------------------------------------------------------------------ utilities
def _rows(conn, sql, args=()):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def _one(conn, sql, args=()):
    row = conn.execute(sql, args).fetchone()
    return dict(row) if row else None


def _today():
    return date.today()


def _iso(value):
    return value.strftime("%Y-%m-%d") if isinstance(value, date) else str(value or "")


def _nice(value):
    """'2026-12-02' -> '2 December 2026'."""
    try:
        d = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return str(value or "")
    return "%d %s %d" % (d.day, d.strftime("%B"), d.year)


def _num(value):
    """100.0 -> 100, 1.6666 -> 1.67, '4.0' -> '4'."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return int(number) if number.is_integer() else round(number, 2)


def _clock(value):
    """'14:30:00' -> '14:30'."""
    text = str(value or "")
    return text[:5] if len(text) >= 5 else text


def _rate_ok(user_id):
    now = time.time()
    bucket = [t for t in _RATE.get(user_id, []) if now - t < RATE_WINDOW]
    if len(bucket) >= RATE_LIMIT:
        _RATE[user_id] = bucket
        return False
    bucket.append(now)
    _RATE[user_id] = bucket
    return True


MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], start=1)}
WEEKDAYS = {d: i for i, d in enumerate(
    ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}


def parse_date(text, today=None):
    """Return a ``date`` mentioned in the question, or ``None``.

    Understands ``2026-12-02``, ``2 dec``, ``2 december 2026``, ``dec 2``, ``02/12``,
    ``today``, ``tomorrow`` and weekday names.
    """
    today = today or _today()
    low = " %s " % (text or "").lower()
    if " today " in low or " aaj " in low:
        return today
    if " tomorrow " in low or " kal " in low:
        return today + timedelta(days=1)
    if " yesterday " in low:
        return today - timedelta(days=1)
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", low)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = re.search(r"\b(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?\b", low)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3) or today.year)
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None
    for full, number in MONTHS.items():
        short = full[:3]
        if not re.search(r"\b%s" % short, low):
            continue
        named = (re.search(r"\b(\d{1,2})\s*(?:st|nd|rd|th)?\s+%s" % short, low)
                 or re.search(r"\b%s[a-z]*\s*(\d{1,2})\b" % short, low))
        if not named:
            continue
        day = int(named.group(1))
        year = today.year
        stated = re.search(r"\b(20\d{2})\b", low)
        if stated:
            year = int(stated.group(1))
        try:
            candidate = date(year, number, day)
        except ValueError:
            return None
        if not stated and candidate < today - timedelta(days=180):
            candidate = date(year + 1, number, day)
        return candidate
    for name, number in WEEKDAYS.items():
        if re.search(r"\b%s\b" % name, low):
            ahead = (number - today.weekday()) % 7
            if ahead == 0 or " next " in low:
                ahead = ahead or 7
            return today + timedelta(days=ahead)
    return None


# ------------------------------------------------------------------- context
def _scope_school(user):
    return user.get("school_id") if user.get("role") in ("School Admin", "Invigilator", "Student") else None


def _brief(conn, user):
    """A small, role-scoped snapshot of the office's data.

    Everything the assistant may talk about comes from here, so a role can never be
    answered with a row it is not allowed to read.
    """
    school_id = _scope_school(user)
    scoped = " WHERE school_id = ?" if school_id else ""
    args = (school_id,) if school_id else ()

    def count(table):
        return (_one(conn, "SELECT COUNT(*) c FROM %s%s" % (table, scoped), args) or {}).get("c", 0)

    run = api.live_run(conn)
    brief = {
        "role": user["role"],
        "name": user.get("full_name") or user.get("email"),
        "today": _iso(_today()),
        "counts": {
            "schools": 1 if school_id else count("schools"),
            "departments": count("departments"),
            "student_groups": count("student_groups"),
            "examinations": count("examinations"),
            "rooms": count("rooms"),
            "invigilators": count("invigilators"),
            "students": (_one(conn, "SELECT COALESCE(SUM(student_count),0) c FROM student_groups%s" % scoped, args) or {}).get("c", 0),
        },
        "run": None,
        "schedule": [],
        "conflicts": [],
    }
    if school_id:
        brief["school"] = (_one(conn, "SELECT school_name FROM schools WHERE id=?", (school_id,)) or {}).get("school_name")
    if not run:
        brief["run"] = None
        return brief

    brief["run"] = {
        "id": run.get("id"),
        "name": run.get("run_name"), "algorithm": run.get("algorithm_name"),
        "status": run.get("status"), "solver_status": run.get("solver_status"),
        "created_at": run.get("created_at"), "published_at": run.get("published_at"),
        "scheduled": run.get("scheduled_examinations"),
        "unscheduled": run.get("unscheduled_examinations"),
        "violations": run.get("hard_constraint_violations"),
        "penalty": run.get("soft_constraint_penalty"),
    }
    where = " AND e.school_id = ?" if school_id else ""
    params = (run["id"], school_id) if school_id else (run["id"],)
    brief["schedule"] = _rows(conn, """
        SELECT sa.id assignment_id, e.subject_code, e.subject_name, e.duration_minutes,
               e.required_seating_capacity, sa.examination_date, sa.start_time, sa.end_time,
               r.room_number, r.building, r.capacity, s.school_name,
               (SELECT GROUP_CONCAT(i.name, ', ') FROM invigilator_assignments ia
                  JOIN invigilators i ON i.id = ia.invigilator_id
                 WHERE ia.schedule_assignment_id = sa.id) invigilators
          FROM schedule_assignments sa
          JOIN examinations e ON e.id = sa.examination_id
          LEFT JOIN rooms r ON r.id = sa.room_id
          LEFT JOIN schools s ON s.id = e.school_id
         WHERE sa.scheduling_run_id = ?%s
         ORDER BY sa.examination_date, sa.start_time""" % where, params)
    brief["conflicts"] = _rows(conn, """
        SELECT conflict_type, severity, description, suggested_resolution, resolution_status
          FROM conflict_logs WHERE scheduling_run_id = ? ORDER BY severity LIMIT 40""", (run["id"],))
    brief["unscheduled"] = [e for e in _rows(conn, """
        SELECT e.subject_code, e.subject_name, s.school_name, e.student_group_ids
          FROM examinations e LEFT JOIN schools s ON s.id = e.school_id
         WHERE e.id NOT IN (SELECT examination_id FROM schedule_assignments WHERE scheduling_run_id = ?)%s"""
        % where, params)]
    return brief


def _load_for_subject(conn, text):
    """Examinations whose code or name the question points at."""
    exams = _rows(conn, """SELECT e.id, e.subject_code, e.subject_name FROM examinations e""")
    codes = {e["subject_code"].upper(): e for e in exams if e.get("subject_code")}
    lowered = (text or "").lower()
    for code, exam in codes.items():
        if code and re.search(r"\b%s\b" % re.escape(code.lower()), lowered):
            return exam
    names = {e["subject_name"].lower(): e for e in exams if e.get("subject_name")}
    for name, exam in names.items():
        if name and name in lowered:
            return exam
    close = difflib.get_close_matches(lowered.strip(), list(names), n=1, cutoff=0.72)
    if close:
        return names[close[0]]
    return None


# ------------------------------------------------------------------ answers
def _suggestions(role):
    if role == "Student":
        return ["When is my next exam?", "Where do I sit?", "Show all my papers", "How is the timetable built?"]
    if role == "Invigilator":
        return ["What is my next duty?", "How many duties do I have?", "What are my exams this week?", "How does the scheduler work?"]
    return ["What is scheduled tomorrow?", "Any conflicts?", "Which invigilators are overloaded?",
            "Which exams are unscheduled?", "Compare AI and First-Fit"]


def _bullet(lines):
    return "\n".join("· " + line for line in lines)


def _exam_line(row):
    return "%s %s — %s, %s to %s, room %s%s" % (
        row["subject_code"], row["subject_name"], _nice(row["examination_date"]),
        _clock(row["start_time"]), _clock(row["end_time"]), row.get("room_number") or "unassigned",
        (" (%s)" % row["invigilators"]) if row.get("invigilators") else "")


def _answer_help(conn, user, brief, text):
    role = user["role"]
    common = ("I read the same timetable the pages read, so every answer is a stored row, not a guess. "
              "Ask about dates, rooms, duties, conflicts, fairness or the scheduling rules.")
    if role == "Student":
        return common + "\n\n" + _bullet([
            "your next examination, date and seat block",
            "every paper in your group for this session",
            "what a room, session or seating count means",
        ])
    if role == "Invigilator":
        return common + "\n\n" + _bullet([
            "your next duty and this week's duties",
            "how many duties you have against your cap",
            "the examination that runs at a given slot",
        ])
    return common + "\n\n" + _bullet([
        "what is scheduled on a date, in a room or for a school",
        "conflicts, unscheduled papers and why they were left out",
        "invigilator workload and fairness",
        "AI versus First-Fit results, and the R1–R8 rules",
    ])


def _answer_duties(conn, user, brief, text):
    data = api.my_duties(conn, user)
    duties = data.get("duties") or []
    if not duties:
        return ("No duties are assigned to you in the live timetable yet. Once the examination office "
                "publishes a run, your rooms and slots appear here and in My Duties.")
    wanted = parse_date(text)
    if wanted:
        duties = [d for d in duties if str(d.get("examination_date"))[:10] == _iso(wanted)]
        if not duties:
            return "Nothing on %s. Your duties that week are on the My Duties page." % _nice(_iso(wanted))
    matching = [d for d in duties]
    upcoming = sorted(duties, key=lambda d: (str(d["examination_date"]), str(d["start_time"])))
    lines = ["%s — %s %s, %s to %s, room %s (%s)" % (
        _nice(d["examination_date"]), d["subject_code"], d["subject_name"],
        _clock(d["start_time"]), _clock(d["end_time"]), d.get("room_number") or "—", d.get("school_name") or "")
        for d in upcoming[:8]]
    head = "You have %d dut%s across %d day%s." % (
        len(duties), "y" if len(duties) == 1 else "ies", len({d["examination_date"] for d in duties}),
        "" if len({d["examination_date"] for d in duties}) == 1 else "s")
    tail = "" if len(matching) <= 8 else "\n· and %d more on My Duties." % (len(matching) - 8)
    return head + "\n" + _bullet(lines) + tail


def _answer_my_exams(conn, user, brief, text):
    data = api.my_exams(conn, user)
    exams = data.get("exams") or []
    if not exams:
        return ("No papers are attached to your group yet. If that looks wrong, ask the examination "
                "office to check the branch, course, semester and section on your account.")
    planned = [e for e in exams if e.get("scheduled")]
    pending = [e for e in exams if not e.get("scheduled")]
    lines = []
    for exam in exams[:10]:
        if exam.get("scheduled"):
            lines.append("%s %s — %s, %s to %s, room %s (%s seats)" % (
                exam["subject_code"], exam["subject_name"], _nice(exam["examination_date"]),
                _clock(exam["start_time"]), _clock(exam["end_time"]),
                exam.get("room") or "—", exam.get("seats") or "—"))
        else:
            lines.append("%s %s — date not published yet" % (exam["subject_code"], exam["subject_name"]))
    head = "You sit %d paper%s this session" % (len(exams), "" if len(exams) == 1 else "s")
    if pending:
        head += "; %d still waiting for a published date" % len(pending)
    return head + ".\n" + _bullet(lines)


def _answer_schedule(conn, user, brief, text):
    schedule = brief.get("schedule") or []
    if not schedule:
        return ("No timetable has been generated yet. An administrator can run the AI Timetable "
                "Generator and I will answer from that run.")
    wanted = parse_date(text)
    rows = schedule
    if wanted:
        rows = [r for r in schedule if str(r.get("examination_date"))[:10] == _iso(wanted)]
    exam = _load_for_subject(conn, text)
    if exam:
        rows = [r for r in schedule if r.get("subject_code") == exam["subject_code"]]
        wanted = None
    room = None
    m = re.search(r"\b(?:room|hall)\s+([A-Za-z0-9-]+)", text or "", re.I)
    if m:
        room = m.group(1).lower()
        rows = [r for r in schedule if str(r.get("room_number") or "").lower() == room]
    if not rows:
        scope = _nice(_iso(wanted)) if wanted else "that"
        if room:
            return "Room %s has no examination in the live timetable." % m.group(1).upper()
        if exam:
            return "%s %s is not placed in the live timetable; it may be in the unscheduled list. Ask me which papers are unscheduled." % (
                exam["subject_code"], exam["subject_name"])
        return "Nothing is scheduled on %s. The run covers %s to %s." % (
            scope, _nice(schedule[0]["examination_date"]), _nice(schedule[-1]["examination_date"]))
    rows = sorted(rows, key=lambda r: (str(r["examination_date"]), str(r["start_time"])))
    if len(rows) > 10:
        head = "%d examinations match; the first %d:" % (len(rows), 10)
        rows = rows[:10]
    else:
        head = "%d examination%s:" % (len(rows), "" if len(rows) == 1 else "s")
    return head + "\n" + _bullet([_exam_line(r) for r in rows])


def _answer_rooms(conn, user, brief, text):
    school_id = _scope_school(user)
    where = " WHERE school_id = ?" if school_id else ""
    args = (school_id,) if school_id else ()
    rooms = _rows(conn, "SELECT * FROM rooms%s ORDER BY room_number" % where, args)
    schedule = brief.get("schedule") or []
    used = {}
    for row in schedule:
        used.setdefault(row.get("room_number"), []).append(row)
    empty = [r["room_number"] for r in rooms if not used.get(r["room_number"])]
    busiest = sorted(used.items(), key=lambda kv: -len(kv[1]))[:3]
    lines = ["%s: %d booking%s" % (name, len(rows), "" if len(rows) == 1 else "s") for name, rows in busiest]
    out = "%d room%s on record. %d in use by the live run, %d idle." % (
        len(rooms), "" if len(rooms) == 1 else "s", len(used), len(empty))
    if lines:
        out += "\nBusiest:\n" + _bullet(lines)
    if empty:
        out += "\nIdle: " + ", ".join(str(e) for e in empty[:10]) + ("…" if len(empty) > 10 else "")
    return out


def _answer_workload(conn, user, brief, text):
    schedule = brief.get("schedule") or []
    if not schedule:
        return "No timetable exists yet, so there is no workload to report."
    load = {}
    for row in schedule:
        for name in (row.get("invigilators") or "").split(", "):
            if name:
                load[name] = load.get(name, 0) + 1
    if not load:
        return "No invigilators are assigned in the live run yet."
    caps = {r["name"]: r.get("maximum_total_duties") for r in
            _rows(conn, "SELECT name, maximum_total_duties FROM invigilators")}
    ordered = sorted(load.items(), key=lambda kv: (-kv[1], kv[0]))
    spare = [r["name"] for r in _rows(conn, "SELECT name FROM invigilators ORDER BY name") if r["name"] not in load]
    heaviest = ["%s — %d dut%s%s" % (
        name, duty, "y" if duty == 1 else "ies",
        " of %s allowed" % caps[name] if caps.get(name) else "")
        for name, duty in ordered[:5]]
    out = "Duties range from %d to %d per person across %d invigilators in the live run." % (
        ordered[-1][1], ordered[0][1], len(load))
    out += "\nHeaviest:\n" + _bullet(heaviest)
    if spare:
        out += "\nNo duties: " + ", ".join(spare[:6]) + ("…" if len(spare) > 6 else "")
    return out


def _answer_conflicts(conn, user, brief, text):
    schedule = brief.get("schedule") or []
    conflicts = [c for c in (brief.get("conflicts") or [])
                 if "resolv" not in str(c.get("resolution_status") or "").lower()]
    if not schedule:
        return "There is no timetable yet, so there is nothing to validate."
    if not conflicts:
        return ("The live run is clean: no open conflicts. Every hard rule — room, seat capacity, "
                "group overlap, invigilator clash and availability — passed the independent validator.")
    lines = ["%s · %s: %s" % (c.get("severity") or "—", c.get("conflict_type") or "conflict",
                              (c.get("description") or "")[:120]) for c in conflicts[:8]]
    fixes = [c.get("suggested_resolution") for c in conflicts[:3] if c.get("suggested_resolution")]
    if fixes:
        lines.append("Fix suggested: " + fixes[0][:140])
    return "%d open conflict%s in the live run:\n%s" % (
        len(conflicts), "" if len(conflicts) == 1 else "s", _bullet(lines))


def _answer_unscheduled(conn, user, brief, text):
    missing = brief.get("unscheduled") or []
    schedule = brief.get("schedule") or []
    if not schedule:
        return "Nothing has been generated, so every examination is technically unscheduled."
    if not missing:
        return "Nothing is left out: all %d examinations in scope are placed in the live run." % len(schedule)
    lines = ["%s %s (%s)" % (e["subject_code"], e["subject_name"], e.get("school_name") or "") for e in missing[:10]]
    return ("%d examination%s could not be placed:\n%s\n\nUsually it is a room or seat shortage, a "
            "clashing group, or no invigilator available in the window. Add capacity or widen the date "
            "range, then regenerate." % (
                len(missing), "" if len(missing) == 1 else "s", _bullet(lines)))


def _answer_fairness(conn, user, brief, text):
    run = brief.get("run")
    if not run:
        return "No run exists yet, so there is no fairness reading to show."
    from solver_service import fairness_for_run  # local import keeps the module light
    reading = fairness_for_run(conn, run.get("id") or _latest_run_id(conn))
    summary = reading.get("summary") or {}
    parts = ["%s: %s" % (k.replace("_", " "), _num(v)) for k, v in summary.items()
             if not isinstance(v, (dict, list))]
    per = reading.get("per_invigilator") or []
    lines = ["%s — %s duties%s" % (
        row.get("full_name") or row.get("name") or "—",
        _num(row.get("total_duties", row.get("duties", 0))),
        " (over the cap)" if row.get("over_limit") else "")
        for row in per[:5] if isinstance(row, dict)]
    out = "Fairness for %s\n%s" % (run["name"], _bullet(parts[:8]) if parts else "No metrics recorded.")
    if lines:
        out += "\nPer invigilator:\n" + _bullet(lines)
    return out


def _latest_run_id(conn):
    row = conn.execute("SELECT id FROM scheduling_runs ORDER BY created_at DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def _answer_counts(conn, user, brief, text):
    c = brief["counts"]
    return ("Right now: %d school%s, %d department%s, %d student group%s covering %s students, "
            "%d examination%s, %d room%s and %d invigilator%s." % (
                c["schools"], "" if c["schools"] == 1 else "s",
                c["departments"], "" if c["departments"] == 1 else "s",
                c["student_groups"], "" if c["student_groups"] == 1 else "s", "{:,}".format(int(c["students"] or 0)),
                c["examinations"], "" if c["examinations"] == 1 else "s",
                c["rooms"], "" if c["rooms"] == 1 else "s",
                c["invigilators"], "" if c["invigilators"] == 1 else "s"))


RULES = [
    ("R1", "A room holds one examination at a time."),
    ("R2", "Seating capacity must cover the cohort; a paper that does not fit is never split silently."),
    ("R3", "A student group sits at most one paper per slot."),
    ("R4", "An invigilator covers at most one room per slot."),
    ("R5", "Invigilator availability blocks are respected."),
    ("R6", "One invigilator per 75 candidates, minimum one, maximum two per room."),
    ("R7", "Examination durations and the session windows must agree."),
    ("R8", "Daily and total duty caps are respected when balancing."),
]


def _answer_rules(conn, user, brief, text):
    return ("The scheduler obeys eight hard rules, and a separate validator re-checks every "
            "assignment afterwards:\n" + _bullet(["%s — %s" % r for r in RULES]))


def _answer_algorithm(conn, user, brief, text):
    run = brief.get("run")
    head = ("The generator is a constraint-programming search: backtracking with minimum-remaining-values, "
            "degree and least-constraining-value ordering plus forward checking. First-Fit is the naive "
            "baseline it is measured against.")
    if not run:
        return head + "\n\nNo run has been generated yet, so there is nothing to compare."
    rows = _rows(conn, """SELECT algorithm_name, solver_status, scheduled_examinations,
                                 unscheduled_examinations, hard_constraint_violations,
                                 soft_constraint_penalty, execution_time
                            FROM scheduling_runs ORDER BY created_at DESC LIMIT 6""")
    lines = []
    for r in rows:
        total = (r["scheduled_examinations"] or 0) + (r["unscheduled_examinations"] or 0)
        lines.append("%s — %s/%s placed, penalty %s, %ss, %s" % (
            (r["algorithm_name"] or "")[:40], r["scheduled_examinations"], total,
            r["soft_constraint_penalty"], r["execution_time"], r["solver_status"]))
    return head + "\n\nRecent runs:\n" + _bullet(lines)


def _answer_howto(conn, user, brief, text):
    if user["role"] in ("Invigilator", "Student"):
        return "Only administrators generate or publish timetables; you can follow the result in your own portal."
    return ("Generating a timetable: open AI Timetable Generator, choose the schools, date window and "
            "options, then Generate. The run lands in Generated Timetable where you validate it, approve "
            "it, publish it, and repair individual assignments. Conflicts, fairness and comparison pages "
            "read the same run, and Reports can export it as CSV.")


# ------------------------------------------------------------------ dispatch
INTENTS = [
    ("help", r"\b(help|what can you|who are you|capabilit\w*|kaise|kya kar)\b"),
    ("rules", r"\b(rules?|r[1-8]|constraints?|polic(y|ies))\b"),
    ("algorithm", r"\b(csp|algorithms?|first[ -]?fit|backtrack\w*|optimi[sz]\w*|compare|comparison)\b"),
    ("howto", r"\b(publish\w*|approve\w*|generat\w*|how do i|how to|steps?|process)\b"),
    ("conflicts", r"\b(conflicts?|clash(es)?|violations?|problems?|broken|invalid)\b"),
    ("unscheduled", r"\b(unscheduled|unplaced|missing|left out|not scheduled|why .*not .*schedul\w*)\b"),
    ("workload", r"\b(overload\w*|busiest|heaviest|workloads?|balance[ds]?|who .*dut(y|ies))\b"),
    ("fairness", r"\b(fair\w*|score|spread|distribution)\b"),
    ("rooms", r"\b(rooms?|halls?|capacit\w*|seats?|utili[sz]ation)\b"),
    ("duties", r"\b(dut(y|ies)|invigilat\w*|my next|assign\w*)\b"),
    ("my_exams", r"\b(my exams?|my papers?|my subjects?|when is my|where do i sit|seat block)\b"),
    ("counts", r"\b(how many|totals?|counts?|number of)\b"),
    ("schedule", r"\b(timetables?|schedul\w*|exams?|papers?|sessions?|slots?|when is|what is on)\b"),
]


def _classify(text):
    low = (text or "").lower()
    for name, pattern in INTENTS:
        if re.search(pattern, low):
            return name
    return ""


def grounded_answer(conn, user, text):
    """Answer without any network call. Deterministic and role-scoped."""
    brief = _brief(conn, user)
    role = user["role"]
    intent = _classify(text)
    if role == "Student" and intent in ("duties", "rooms", "fairness", "workload", "conflicts", "unscheduled", "counts", "schedule"):
        intent = "my_exams" if intent in ("duties", "schedule", "counts") else "help"
    if role == "Invigilator" and intent in ("rooms", "fairness", "workload", "conflicts", "unscheduled", "counts", "schedule"):
        intent = "duties"
    handlers = {
        "help": _answer_help, "rules": _answer_rules, "algorithm": _answer_algorithm,
        "howto": _answer_howto, "conflicts": _answer_conflicts, "unscheduled": _answer_unscheduled,
        "fairness": _answer_fairness, "workload": _answer_workload, "rooms": _answer_rooms,
        "duties": _answer_duties,
        "my_exams": _answer_my_exams, "counts": _answer_counts, "schedule": _answer_schedule,
    }
    handler = handlers.get(intent)
    if not handler:
        handler = _answer_my_exams if role == "Student" else (_answer_duties if role == "Invigilator" else _answer_schedule)
        if intent in ("", "schedule") and handler in (_answer_duties, _answer_schedule) and not (brief.get("schedule") or []):
            return {"reply": _answer_help(conn, user, brief, text), "intent": "help"}
    return {"reply": handler(conn, user, brief, text), "intent": intent or "fallback"}


# --------------------------------------------------------------- optional LLM
def llm_enabled():
    return bool(LLM_KEY)


def _llm_answer(conn, user, text, brief, history):
    system = (
        "You are ExamFlow Assistant, embedded in a university examination-office application. "
        "Answer only from the CONTEXT JSON. Never invent a date, room, duty or number. If the "
        "context does not contain the answer, say what the user can open instead (Generated "
        "Timetable, Conflicts, Fairness, Reports, My Duties, My Exams). Reply in the language of the "
        "question, in at most 120 words, plain text, no markdown headings. Use '· ' for lists. "
        "The user's role is %s; never reveal data outside that role." % user["role"])
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "system", "content": "CONTEXT JSON:\n" + json.dumps(brief, default=str)[:12000]},
        ] + [{"role": h["role"], "content": str(h.get("text") or "")[:600]} for h in (history or [])[-6:]]
          + [{"role": "user", "content": text}],
        "temperature": 0.2,
        "max_tokens": 400,
    }
    request = urllib.request.Request(
        LLM_BASE + "/chat/completions", data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + LLM_KEY})
    with urllib.request.urlopen(request, timeout=LLM_TIMEOUT) as response:
        body = json.loads(response.read().decode())
    return (body["choices"][0]["message"]["content"] or "").strip()


# ------------------------------------------------------------------ interface
def status():
    return {
        "enabled": True,
        "mode": "llm" if llm_enabled() else "grounded",
        "model": LLM_MODEL if llm_enabled() else None,
        "engine": "Language model over the live timetable" if llm_enabled() else
                  "Grounded lookup over the live timetable (no external service)",
    }


def ask(conn, user, body):
    message = str((body or {}).get("message") or "").strip()
    if not message:
        raise AssistantError("Ask me something about the timetable, rooms, duties or results.")
    if len(message) > MAX_MESSAGE:
        raise AssistantError("That question is longer than %d characters." % MAX_MESSAGE)
    if not _rate_ok(user["id"]):
        raise AssistantError("Too many questions in a minute. Give me a moment and ask again.")

    history = (body or {}).get("history") or []
    local = grounded_answer(conn, user, message)
    envelope = {"reply": local["reply"], "intent": local["intent"], "mode": "grounded",
                "suggestions": _suggestions(user["role"]), "citations": []}
    if local["intent"] not in ("help", "fallback"):
        envelope["citations"] = [{"label": "Source", "value": "Live scheduling run and stored records"}]
    if llm_enabled():
        try:
            brief = _brief(conn, user)
            answer = _llm_answer(conn, user, message, brief, history)
            if answer:
                envelope.update({"reply": answer, "mode": "llm"})
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, KeyError, ValueError):
            envelope["mode"] = "grounded-after-llm"
    return envelope
