"""Re-cut an existing demonstration dataset to the university's own vocabulary.

A deployment that was seeded before the university identity existed still carries the old
generic schools, rooms and course codes, and the browser shows them verbatim. This module
renames those rows in place so the identifiers that other tables point at survive. Every
statement matches the old value exactly, so running it twice changes nothing.

Names are illustrative. The department and school identifiers are the university's own.
"""

CAMPUS = "Jalandhar - Delhi G.T. Road, Phagwara, Punjab 144411"
OFFICE_EMAIL = "examinations@lpu.co.in"
OFFICE_PHONE = "+91 1824 404404"

SCHOOLS = {
    "NIT": ("School of Computer Science and Engineering", "SCSE", "Block 34, " + CAMPUS),
    "RCS": ("School of Electronics and Electrical Engineering", "SEEE", "Block 32, " + CAMPUS),
    "GBS": ("Lovely Faculty of Business and Arts", "LFBA", "Block 26, " + CAMPUS),
}

DEPARTMENTS = {
    "CSE": ("Computer Science and Engineering", "CSE"),
    "ECE": ("Electronics and Communication Engineering", "ECE"),
    "PHY": ("Data Science and Artificial Intelligence", "DSC"),
    "MAT": ("Electrical and Electronics Engineering", "EEE"),
    "MGT": ("Management", "MGT"),
}

GROUPS = {
    "BSc Physics Sem 4": "B.Tech DSAI Sem 3",
    "BSc Mathematics Sem 4": "B.Tech DSAI Sem 5",
    "BSc Mathematics Sem 6": "B.Tech EEE Sem 4",
    "BBA Sem 2": "MBA Sem 2",
}

# number: (new number, building, floor, capacity, room type)
ROOMS = {
    "N-101": ("34-401", "Block 34", 4, 120, "Computer Lab"),
    "N-102": ("34-402", "Block 34", 4, 120, "Examination Hall"),
    "N-204": ("34-403", "Block 34", 4, 90, "Classroom"),
    "R-201": ("32-305", "Block 32", 3, 60, "Classroom"),
    "R-202": ("32-306", "Block 32", 3, 100, "Examination Hall"),
    "R-305": ("32-401", "Block 32", 4, 25, "Seminar Room"),
    "G-01": ("26-201", "Block 26", 2, 120, "Examination Hall"),
    "G-02": ("26-202", "Block 26", 2, 45, "Classroom"),
}

# old course code: (new subject name, new course code)
EXAMINATIONS = {
    "CS301": ("Data Structures", "CSE205"),
    "CS302": ("Operating Systems", "CSE310"),
    "CS303": ("Software Engineering", "CSE315"),
    "EC301": ("Digital Electronics", "ECE205"),
    "EC302": ("Microprocessors", "ECE310"),
    "MA201": ("Discrete Mathematics", "MTH201"),
    "PH401": ("Machine Learning", "DSC301"),
    "PH402": ("Data Mining", "DSC305"),
    "MA401": ("Electrical Machines", "EEE210"),
    "MA402": ("Power Systems", "EEE320"),
    "MA403": ("Computer Networks", "CSE320"),
    "BA201": ("Marketing Management", "MGT201"),
    "BA202": ("Financial Accounting", "MGT202"),
    "BA203": ("Business Statistics", "MGT203"),
    "BA204": ("Organisational Behaviour", "MGT204"),
}

EMPLOYEE_PREFIXES = {"NIT-": "SCSE-", "RCS-": "SEEE-", "GBS-": "LFBA-"}


def apply(conn):
    """Rename the generic demonstration rows. Returns how many rows changed."""
    counts = {}

    def changed(label, cursor):
        counts[label] = counts.get(label, 0) + max(cursor.rowcount, 0)

    for old_code, (name, code, address) in SCHOOLS.items():
        changed("schools", conn.execute(
            """UPDATE schools SET school_name=?, school_code=?, address=?, contact_email=?,
               contact_number=? WHERE school_code=?""",
            (name, code, address, OFFICE_EMAIL, OFFICE_PHONE, old_code)))

    for old_code, (name, code) in DEPARTMENTS.items():
        changed("departments", conn.execute(
            "UPDATE departments SET department_name=?, department_code=? WHERE department_code=?",
            (name, code, old_code)))

    for old_name, new_name in GROUPS.items():
        changed("student_groups", conn.execute(
            "UPDATE student_groups SET group_name=? WHERE group_name=?", (new_name, old_name)))

    for old_number, (number, building, floor, capacity, rtype) in ROOMS.items():
        changed("rooms", conn.execute(
            """UPDATE rooms SET room_number=?, building=?, floor=?, capacity=?, room_type=?
               WHERE room_number=?""",
            (number, building, floor, capacity, rtype, old_number)))

    for old_code, (subject, code) in EXAMINATIONS.items():
        changed("examinations", conn.execute(
            """UPDATE examinations SET subject_name=?, subject_code=?, examination_type='Theory'
               WHERE subject_code=?""", (subject, code, old_code)))

    for old_prefix, new_prefix in EMPLOYEE_PREFIXES.items():
        rows = conn.execute(
            "SELECT id, employee_code FROM invigilators WHERE employee_code LIKE ?",
            (old_prefix + "%",)).fetchall()
        for row in rows:
            code = new_prefix + row["employee_code"][len(old_prefix):]
            conn.execute("UPDATE invigilators SET employee_code=?, email=REPLACE("
                         "REPLACE(email, '@example.edu', '@lpu.co.in'), "
                         "'@examflow.ai', '@lpu.co.in') WHERE id=?", (code, row["id"]))
        if rows:
            counts["invigilators"] = counts.get("invigilators", 0) + len(rows)

    conn.commit()
    return {"changed": counts}
