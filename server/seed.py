"""Realistic demonstration dataset for ExamFlow AI.

All names are fictional. The data is intentionally seeded with the awkward cases
the engine must handle: a room that is too small for every examination in its
school, several examinations sharing a student group, faculty on leave, and very
different duty limits.
"""
import db
import auth


def seed_dataset(conn):
    now = db.now_iso()

    schools = [
        ("Northfield Institute of Technology", "NIT", "12 College Road, Northfield",
         "office@nit.example.edu", "+91 11 4000 1001"),
        ("Riverside College of Science", "RCS", "48 River Lane, Riverside",
         "admin@rcs.example.edu", "+91 11 4000 1002"),
        ("Greenfield Business School", "GBS", "7 Green Park, Greenfield",
         "hello@gbs.example.edu", "+91 11 4000 1003"),
    ]
    sids = {}
    for name, code, address, email, phone in schools:
        sid = db.new_id()
        sids[code] = sid
        conn.execute(
            """INSERT INTO schools (id, school_name, school_code, address, contact_email,
               contact_number, status, created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (sid, name, code, address, email, phone, "Active", now))

    depts = [
        (sids["NIT"], "Computer Science", "CSE"),
        (sids["NIT"], "Electronics", "ECE"),
        (sids["RCS"], "Physics", "PHY"),
        (sids["RCS"], "Mathematics", "MAT"),
        (sids["GBS"], "Management", "MGT"),
    ]
    dids = {}
    for school_id, name, code in depts:
        did = db.new_id()
        dids[code] = did
        conn.execute(
            "INSERT INTO departments (id, school_id, department_name, department_code, created_at)"
            " VALUES (?,?,?,?,?)", (did, school_id, name, code, now))

    groups = [
        ("B.Tech CSE Sem 5", 5, "A", 60, "CSE"), ("B.Tech CSE Sem 5", 5, "B", 55, "CSE"),
        ("B.Tech CSE Sem 3", 3, "A", 58, "CSE"), ("B.Tech ECE Sem 5", 5, "A", 45, "ECE"),
        ("B.Tech ECE Sem 3", 3, "A", 40, "ECE"), ("BSc Physics Sem 4", 4, "A", 35, "PHY"),
        ("BSc Mathematics Sem 4", 4, "A", 40, "MAT"), ("BSc Mathematics Sem 6", 6, "A", 30, "MAT"),
        ("BBA Sem 2", 2, "A", 50, "MGT"), ("BBA Sem 4", 4, "A", 48, "MGT"),
    ]
    gids = {}
    for name, sem, section, count, dept in groups:
        gid = db.new_id()
        gids[f"{name}-{section}"] = gid
        conn.execute(
            """INSERT INTO student_groups (id, school_id, department_id, group_name, semester,
               section, student_count, academic_year, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (gid, conn.execute("SELECT school_id FROM departments WHERE id=?",
                               (dids[dept],)).fetchone()["school_id"],
             dids[dept], name, sem, section, count, "2026-27", now))

    rooms = [
        ("N-101", "Main Block", 1, 120, "Computer Lab", 1, ["computer lab", "projector"]),
        ("N-102", "Main Block", 1, 120, "Exam Hall", 1, ["projector"]),
        ("N-204", "Academic Block", 2, 90, "Classroom", 1, []),
        ("R-201", "Science Block", 2, 60, "Classroom", 1, []),
        ("R-202", "Science Block", 2, 100, "Exam Hall", 1, ["projector"]),
        ("R-305", "Science Block", 3, 25, "Seminar Room", 1, []),
        ("G-01", "Business Block", 1, 120, "Exam Hall", 1, ["projector"]),
        ("G-02", "Business Block", 1, 45, "Classroom", 1, []),
    ]
    room_schools = [sids["NIT"], sids["NIT"], sids["NIT"], sids["RCS"], sids["RCS"], sids["RCS"],
                    sids["GBS"], sids["GBS"]]
    for (number, building, floor, capacity, rtype, accessible, facilities), school_id in zip(
            rooms, room_schools):
        conn.execute(
            """INSERT INTO rooms (id, school_id, room_number, building, floor, capacity, room_type,
               is_accessible, facilities, is_active, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (db.new_id(), school_id, number, building, floor, capacity, rtype, accessible,
             db.encode_value(facilities), 1, now))

    group_size = {}
    for name, sem, section, count, dept in groups:
        group_size[f"{name}-{section}"] = count

    def capacity_of(keys):
        return sum(group_size[k] for k in keys)

    exams = [
        ("Data Structures", "CS301", sids["NIT"], dids["CSE"], ["B.Tech CSE Sem 5-A", "B.Tech CSE Sem 3-A"],
         180, "High", ["computer lab"], "2026-11-16"),
        ("Operating Systems", "CS302", sids["NIT"], dids["CSE"], ["B.Tech CSE Sem 5-A", "B.Tech CSE Sem 5-B"],
         180, "Critical", [], "2026-11-16"),
        ("Digital Electronics", "EC301", sids["NIT"], dids["ECE"], ["B.Tech ECE Sem 5-A", "B.Tech ECE Sem 3-A"],
         120, "Medium", [], "2026-11-17"),
        ("Microprocessors", "EC302", sids["NIT"], dids["ECE"], ["B.Tech ECE Sem 5-A"],
         120, "Low", [], "2026-11-18"),
        ("Discrete Mathematics", "MA201", sids["NIT"], dids["CSE"],
         ["B.Tech CSE Sem 3-A", "B.Tech CSE Sem 5-B"], 180, "High", [], "2026-11-18"),
        ("Software Engineering", "CS303", sids["NIT"], dids["CSE"], ["B.Tech CSE Sem 5-B"],
         180, "Medium", [], "2026-11-19"),
        ("Classical Mechanics", "PH401", sids["RCS"], dids["PHY"], ["BSc Physics Sem 4-A"],
         120, "High", [], "2026-11-16"),
        ("Quantum Physics", "PH402", sids["RCS"], dids["PHY"], ["BSc Physics Sem 4-A"],
         120, "Medium", [], "2026-11-18"),
        ("Real Analysis", "MA401", sids["RCS"], dids["MAT"], ["BSc Mathematics Sem 4-A"],
         180, "Critical", [], "2026-11-17"),
        ("Linear Algebra", "MA402", sids["RCS"], dids["MAT"],
         ["BSc Mathematics Sem 4-A", "BSc Mathematics Sem 6-A"], 120, "Medium", [], "2026-11-19"),
        ("Numerical Methods", "MA403", sids["RCS"], dids["MAT"], ["BSc Mathematics Sem 6-A"],
         120, "Low", [], "2026-11-20"),
        ("Marketing Management", "BA201", sids["GBS"], dids["MGT"], ["BBA Sem 2-A"],
         180, "High", ["projector"], "2026-11-16"),
        ("Financial Accounting", "BA202", sids["GBS"], dids["MGT"], ["BBA Sem 2-A", "BBA Sem 4-A"],
         180, "Critical", [], "2026-11-17"),
        ("Business Statistics", "BA203", sids["GBS"], dids["MGT"], ["BBA Sem 4-A"],
         120, "Medium", [], "2026-11-19"),
        ("Organisational Behaviour", "BA204", sids["GBS"], dids["MGT"], ["BBA Sem 4-A"],
         120, "Low", [], "2026-11-20"),
    ]
    for (subject, code, school_id, dept_id, group_keys, duration, priority, facilities,
         preferred) in exams:
        conn.execute(
            """INSERT INTO examinations (id, school_id, department_id, subject_name, subject_code,
               examination_type, student_group_ids, duration_minutes, priority, preferred_dates,
               required_seating_capacity, required_facilities, special_requirements, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (db.new_id(), school_id, dept_id, subject, code, "Written",
             db.encode_value([gids[k] for k in group_keys]), duration, priority,
             db.encode_value([preferred]), capacity_of(group_keys),
             db.encode_value(facilities), "", "Pending", now))

    for i in range(1, 6):
        day = f"2026-11-{15 + i:02d}"
        for session, start, end in (("Morning", "09:30", "12:30"), ("Afternoon", "14:00", "17:00")):
            conn.execute(
                """INSERT INTO time_slots (id, examination_date, start_time, end_time, session,
                   is_active, created_at) VALUES (?,?,?,?,?,?,?)""",
                (db.new_id(), day, start, end, session, 1, now))

    faculty = [
        ("Dr. Ananya Rao", "NIT-F01", sids["NIT"], dids["CSE"], 2, 10, 5, "CSP"),
        ("Prof. Vikram Shetty", "NIT-F02", sids["NIT"], dids["CSE"], 2, 9, 5, "Databases"),
        ("Dr. Meera Nair", "NIT-F03", sids["NIT"], dids["ECE"], 1, 6, 3, "VLSI"),
        ("Prof. Arjun Das", "NIT-F04", sids["NIT"], dids["ECE"], 2, 8, 4, "Signals"),
        ("Dr. Kavya Iyer", "NIT-F05", sids["NIT"], dids["CSE"], 1, 5, 3, "Compilers"),
        ("Prof. Suresh Menon", "NIT-F06", sids["NIT"], dids["CSE"], 2, 10, 5, "Networks"),
        ("Dr. Ritu Bansal", "RCS-F07", sids["RCS"], dids["PHY"], 2, 9, 5, "Optics"),
        ("Prof. Nikhil Joshi", "RCS-F08", sids["RCS"], dids["MAT"], 1, 6, 3, "Algebra"),
        ("Dr. Farah Khan", "RCS-F09", sids["RCS"], dids["PHY"], 2, 8, 4, "Thermodynamics"),
        ("Prof. Aditya Verma", "RCS-F10", sids["RCS"], dids["MAT"], 2, 9, 4, "Analysis"),
        ("Dr. Shalini Gupta", "GBS-F11", sids["GBS"], dids["MGT"], 2, 8, 4, "Marketing"),
        ("Prof. Manoj Pillai", "GBS-F12", sids["GBS"], dids["MGT"], 1, 5, 3, "Accounting"),
    ]
    inv_ids = {}
    for name, code, school_id, dept_id, max_daily, max_total, preferred, qual in faculty:
        iid = db.new_id()
        inv_ids[code] = iid
        conn.execute(
            """INSERT INTO invigilators (id, user_id, school_id, department_id, employee_code, name,
               email, maximum_daily_duties, maximum_total_duties, preferred_duties, qualification,
               status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (iid, None, school_id, dept_id, code, name,
             name.split()[-1].lower() + "@example.edu", max_daily, max_total, preferred, qual,
             "Active", now))

    restrictions = [
        ("NIT-F03", "2026-11-16", "09:00", "13:00", "Unavailable", "Medical appointment"),
        ("RCS-F08", "2026-11-17", "00:00", "23:59", "Leave", "Approved leave"),
        ("RCS-F09", "2026-11-19", "13:00", "18:00", "Unavailable", "Conference presentation"),
        ("GBS-F12", "2026-11-18", "00:00", "23:59", "Leave", "Family leave"),
        ("NIT-F04", "2026-11-20", "09:00", "12:45", "Unavailable", "Doctor visit"),
        ("NIT-F01", "2026-11-19", "13:00", "17:30", "Unavailable", "Department review"),
    ]
    for code, date, start, end, status, reason in restrictions:
        conn.execute(
            """INSERT INTO invigilator_availability (id, invigilator_id, date, start_time, end_time,
               availability_status, reason, created_at) VALUES (?,?,?,?,?,?,?,?)""",
            (db.new_id(), inv_ids[code], date, start, end, status, reason, now))

    policies = [
        ("Room capacity must cover demand", "Hard", "room_capacity", 1, 0, 1, "Reject any room that seats fewer students than the examination needs."),
        ("Invigilators must be available", "Hard", "invigilator_availability", 1, 0, 1, "A duty cannot fall inside a declared leave or unavailability window."),
        ("Daily duty limit", "Hard", "daily_duty_limit", 1, 0, 1, "Never exceed an invigilator's maximum duties per day."),
        ("Student group clash prevention", "Hard", "group_overlap", 1, 0, 1, "Two examinations sharing a student group cannot overlap in time."),
        ("Room double-booking prevention", "Hard", "room_booking", 1, 0, 1, "A room hosts at most one examination at a time."),
        ("Invigilator clash prevention", "Hard", "invigilator_overlap", 1, 0, 1, "One invigilator cannot supervise two simultaneous examinations."),
        ("Total duty limit", "Hard", "total_duty_limit", 1, 0, 1, "Respect each invigilator's maximum duties for the whole run."),
        ("Slot duration fit", "Hard", "slot_duration", 1, 0, 1, "The examination duration must fit inside the chosen slot."),
        ("Room facilities required", "Hard", "room_facilities", 1, 0, 1, "Rooms must provide every facility the examination requires."),
        ("Inter-school invigilation", "Hard", "inter_school_invigilation", 0, 0, 0, "When enabled, only faculty from the examination's own school may be assigned."),
        ("Balanced invigilator workload", "Soft", "workload_balance", 0, 5.0, 1, "Spread duties evenly; penalised through standard deviation."),
        ("Avoid consecutive duties", "Soft", "avoid_consecutive_duties", 0, 3.0, 1, "Penalise back-to-back duties on the same day."),
        ("Respect preferred examination dates", "Soft", "preferred_dates", 0, 2.0, 1, "Penalise examinations placed away from their preferred date."),
        ("Efficient room utilisation", "Soft", "room_utilisation", 0, 1.0, 1, "Penalise large rooms used for small cohorts."),
    ]
    for name, ctype, rule_code, mandatory, weight, enabled, desc in policies:
        conn.execute(
            """INSERT INTO constraint_policies (id, policy_name, constraint_type, description,
               is_mandatory, penalty_weight, is_enabled, scope, school_id, rule_code, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (db.new_id(), name, ctype, desc, mandatory, weight, enabled, "global", None, rule_code,
             now))

    users = [
        ("System Administrator", "admin@examflow.ai", "Admin@123", "Super Admin", None, None),
        ("Rita Sharma", "rita@examflow.ai", "Examflow@123", "School Admin", sids["NIT"], dids["CSE"]),
        ("Samuel Fernandes", "samuel@examflow.ai", "Examflow@123", "School Admin", sids["RCS"], dids["MAT"]),
        ("Dr. Ananya Rao", "ananya@examflow.ai", "Examflow@123", "Invigilator", sids["NIT"], dids["CSE"]),
    ]
    for full_name, email, password, role, school_id, dept_id in users:
        conn.execute(
            """INSERT INTO users (id, full_name, email, password_hash, role, school_id, department_id,
               is_active, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
            (db.new_id(), full_name, email, auth.hash_password(password), role, school_id, dept_id,
             1, now))

    conn.commit()
    print("Seeded demonstration dataset.")


def seed_database():
    """Entry point used by db.init_db()."""
    conn = db.connect()
    try:
        seed_dataset(conn)
        conn.commit()
    finally:
        conn.close()
