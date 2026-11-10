"""The academic catalogue behind student self-registration.

A student signs up by choosing a branch (an LPU school), then the course inside that
branch, then the semester. Without this the account was dropped into whichever school
happened to be seeded first, so a new student saw the wrong timetable or none at all.

The catalogue is server-side on purpose: the sign-up form cannot invent a branch, and
the examination office extends the list in one file. Codes that already exist in the
demonstration dataset (CSE, DSC, ECE, EEE, MGT) are reused, so a student who picks
B.Tech CSE Semester 5 lands in the same student group the seeded timetable was built for.
"""
import db
import institution

CAMPUS = institution.ADDRESS

SCHOOLS = [
    {
        "code": "SCSE",
        "name": "School of Computer Science and Engineering",
        "block": "Block 34",
        "programmes": [
            {"code": "CSE", "name": "B.Tech Computer Science and Engineering",
             "level": "B.Tech", "semesters": 8},
            {"code": "DSC", "name": "B.Tech Data Science and Artificial Intelligence",
             "level": "B.Tech", "semesters": 8},
            {"code": "AIML", "name": "B.Tech Artificial Intelligence and Machine Learning",
             "level": "B.Tech", "semesters": 8},
            {"code": "CYBR", "name": "B.Tech Cyber Security", "level": "B.Tech",
             "semesters": 8},
        ],
    },
    {
        "code": "SCA",
        "name": "School of Computer Applications",
        "block": "Block 34",
        "programmes": [
            {"code": "BCA", "name": "Bachelor of Computer Applications", "level": "BCA",
             "semesters": 6},
            {"code": "MCA", "name": "Master of Computer Applications", "level": "MCA",
             "semesters": 4},
        ],
    },
    {
        "code": "SEEE",
        "name": "School of Electronics and Electrical Engineering",
        "block": "Block 32",
        "programmes": [
            {"code": "ECE", "name": "B.Tech Electronics and Communication Engineering",
             "level": "B.Tech", "semesters": 8},
            {"code": "EEE", "name": "B.Tech Electrical and Electronics Engineering",
             "level": "B.Tech", "semesters": 8},
        ],
    },
    {
        "code": "SME",
        "name": "School of Mechanical Engineering",
        "block": "Block 31",
        "programmes": [
            {"code": "ME", "name": "B.Tech Mechanical Engineering", "level": "B.Tech",
             "semesters": 8},
            {"code": "RAE", "name": "B.Tech Robotics and Automation", "level": "B.Tech",
             "semesters": 8},
        ],
    },
    {
        "code": "SCE",
        "name": "School of Civil Engineering",
        "block": "Block 30",
        "programmes": [
            {"code": "CE", "name": "B.Tech Civil Engineering", "level": "B.Tech",
             "semesters": 8},
        ],
    },
    {
        "code": "SCEPS",
        "name": "School of Chemical Engineering and Physical Sciences",
        "block": "Block 33",
        "programmes": [
            {"code": "CHE", "name": "B.Tech Chemical Engineering", "level": "B.Tech",
             "semesters": 8},
            {"code": "PSC", "name": "M.Sc Physics", "level": "M.Sc", "semesters": 4},
            {"code": "CHY", "name": "M.Sc Chemistry", "level": "M.Sc", "semesters": 4},
        ],
    },
    {
        "code": "SBB",
        "name": "School of Bioengineering and Biosciences",
        "block": "Block 36",
        "programmes": [
            {"code": "BT", "name": "B.Tech Biotechnology", "level": "B.Tech", "semesters": 8},
            {"code": "MIC", "name": "M.Sc Microbiology", "level": "M.Sc", "semesters": 4},
        ],
    },
    {
        "code": "SOA",
        "name": "School of Agriculture",
        "block": "Block 27",
        "programmes": [
            {"code": "BSCAG", "name": "B.Sc Agriculture (Hons.)", "level": "B.Sc",
             "semesters": 8},
            {"code": "MSCAG", "name": "M.Sc Agronomy", "level": "M.Sc", "semesters": 4},
        ],
    },
    {
        "code": "SOP",
        "name": "School of Pharmacy",
        "block": "Block 26",
        "programmes": [
            {"code": "BPHARM", "name": "Bachelor of Pharmacy", "level": "B.Pharm",
             "semesters": 8},
            {"code": "MPHARM", "name": "Master of Pharmacy", "level": "M.Pharm",
             "semesters": 4},
        ],
    },
    {
        "code": "MSB",
        "name": "Mittal School of Business",
        "block": "Block 26",
        "programmes": [
            {"code": "MBA", "name": "Master of Business Administration", "level": "MBA",
             "semesters": 4},
            {"code": "BBA", "name": "Bachelor of Business Administration", "level": "BBA",
             "semesters": 6},
            {"code": "BCOM", "name": "Bachelor of Commerce (Hons.)", "level": "B.Com",
             "semesters": 6},
        ],
    },
    {
        "code": "LFBA",
        "name": "Lovely Faculty of Business and Arts",
        "block": "Block 26",
        "programmes": [
            {"code": "MGT", "name": "Management (BBA / MBA)", "level": "UG / PG",
             "semesters": 6},
        ],
    },
    {
        "code": "SOL",
        "name": "School of Law",
        "block": "Block 25",
        "programmes": [
            {"code": "BALLB", "name": "BA LL.B (Hons.)", "level": "Integrated", "semesters": 10},
            {"code": "LLB", "name": "LL.B", "level": "LL.B", "semesters": 6},
            {"code": "LLM", "name": "LL.M", "level": "LL.M", "semesters": 2},
        ],
    },
    {
        "code": "SOAD",
        "name": "School of Architecture and Design",
        "block": "Block 24",
        "programmes": [
            {"code": "BARCH", "name": "Bachelor of Architecture", "level": "B.Arch",
             "semesters": 10},
            {"code": "BDES", "name": "B.Des Fashion and Product Design", "level": "B.Des",
             "semesters": 8},
        ],
    },
    {
        "code": "SHMT",
        "name": "School of Hotel Management and Tourism",
        "block": "Block 23",
        "programmes": [
            {"code": "BHM", "name": "Bachelor of Hotel Management", "level": "BHM",
             "semesters": 8},
            {"code": "BTTM", "name": "B.Tech Travel and Tourism Management", "level": "B.Tech",
             "semesters": 8},
        ],
    },
    {
        "code": "SLCA",
        "name": "School of Liberal and Creative Arts",
        "block": "Block 22",
        "programmes": [
            {"code": "BAJMC", "name": "BA Journalism and Mass Communication", "level": "BA",
             "semesters": 6},
            {"code": "BAHONS", "name": "BA English (Hons.)", "level": "BA", "semesters": 6},
        ],
    },
    {
        "code": "SOE",
        "name": "School of Education",
        "block": "Block 21",
        "programmes": [
            {"code": "BED", "name": "Bachelor of Education", "level": "B.Ed", "semesters": 4},
            {"code": "MED", "name": "Master of Education", "level": "M.Ed", "semesters": 4},
        ],
    },
    {
        "code": "SPPS",
        "name": "School of Physiotherapy and Paramedical Sciences",
        "block": "Block 20",
        "programmes": [
            {"code": "BPT", "name": "Bachelor of Physiotherapy", "level": "BPT", "semesters": 8},
            {"code": "MPT", "name": "Master of Physiotherapy", "level": "MPT", "semesters": 4},
        ],
    },
]

SECTIONS = ["A", "B", "C"]


class EnrolmentError(ValueError):
    """A choice the catalogue cannot honour, worded for the person signing up."""


def payload():
    """What the sign-up form is allowed to show: branches, courses and semesters."""
    return [{"code": school["code"], "name": school["name"], "block": school["block"],
             "programmes": [dict(programme) for programme in school["programmes"]]}
            for school in SCHOOLS]


def find_school(code):
    wanted = (code or "").strip().upper()
    for school in SCHOOLS:
        if school["code"] == wanted:
            return school
    return None


def find_programme(school, code):
    wanted = (code or "").strip().upper()
    for programme in school["programmes"]:
        if programme["code"] == wanted:
            return programme
    return None


def resolve(school_code, programme_code, semester):
    """Validate a branch, course and semester together, or say what is wrong."""
    school = find_school(school_code)
    if not school:
        raise EnrolmentError("Choose your branch (school) from the list.")
    programme = find_programme(school, programme_code)
    if not programme:
        raise EnrolmentError("Choose the course you are studying in %s." % school["name"])
    try:
        semester_number = int(semester)
    except (TypeError, ValueError):
        raise EnrolmentError("Choose your current semester.")
    if not 1 <= semester_number <= programme["semesters"]:
        raise EnrolmentError("%s runs for %d semesters, so pick a semester between 1 and %d."
                            % (programme["name"], programme["semesters"],
                               programme["semesters"]))
    return school, programme, semester_number


def _school_row(conn, school):
    """The school row for a catalogue branch, created the first time someone picks it."""
    row = conn.execute("SELECT * FROM schools WHERE UPPER(school_code) = ?",
                       (school["code"],)).fetchone()
    if row:
        return dict(row)
    school_id = "sch_" + db.new_id()
    conn.execute(
        """INSERT INTO schools (id, school_name, school_code, address, contact_email,
           contact_number, status, created_at) VALUES (?,?,?,?,?,?,?,?)""",
        (school_id, school["name"], school["code"],
         "%s, %s" % (school["block"], CAMPUS), institution.EMAIL, institution.PHONE,
         "Active", db.now_iso()))
    return {"id": school_id, "school_name": school["name"], "school_code": school["code"]}


def _department_row(conn, school_row, programme):
    row = conn.execute(
        "SELECT * FROM departments WHERE school_id = ? AND UPPER(department_code) = ?",
        (school_row["id"], programme["code"])).fetchone()
    if row:
        return dict(row)
    department_id = "dep_" + db.new_id()
    conn.execute(
        "INSERT INTO departments (id, school_id, department_name, department_code, created_at)"
        " VALUES (?,?,?,?,?)",
        (department_id, school_row["id"], programme["name"], programme["code"], db.now_iso()))
    return {"id": department_id, "department_name": programme["name"],
            "department_code": programme["code"]}


def _group_row(conn, school_row, department_row, programme, semester, section):
    row = conn.execute(
        """SELECT * FROM student_groups WHERE department_id = ? AND semester = ?
           AND UPPER(COALESCE(section, '')) = ?""",
        (department_row["id"], semester, section)).fetchone()
    if row:
        return dict(row)
    group_id = "grp_" + db.new_id()
    conn.execute(
        """INSERT INTO student_groups (id, school_id, department_id, group_name, semester,
           section, student_count, academic_year, created_at) VALUES (?,?,?,?,?,?,?,?,?)""",
        (group_id, school_row["id"], department_row["id"],
         "%s Sem %d" % (programme["name"], semester), semester, section, 0,
         institution.SESSION, db.now_iso()))
    return {"id": group_id, "group_name": "%s Sem %d" % (programme["name"], semester),
            "semester": semester, "section": section}


def enrol(conn, user_id, school_code, programme_code, semester, section="A"):
    """Bind a self-registered student to the branch, course and group they chose.

    Returns the school, course and group that were written, so the caller can tell the
    person what they joined. The rows are created on demand: a branch only exists in the
    database once somebody studies there, which keeps the office's school list honest.
    """
    school, programme, semester_number = resolve(school_code, programme_code, semester)
    section = (section or "A").strip().upper()[:1] or "A"
    if section not in SECTIONS:
        section = "A"
    school_row = _school_row(conn, school)
    department_row = _department_row(conn, school_row, programme)
    group_row = _group_row(conn, school_row, department_row, programme, semester_number,
                           section)
    conn.execute(
        "UPDATE users SET school_id = ?, department_id = ?, student_group_id = ? WHERE id = ?",
        (school_row["id"], department_row["id"], group_row["id"], user_id))
    return {"school": school_row["school_name"], "school_code": school["code"],
            "course": programme["name"], "course_code": programme["code"],
            "semester": semester_number, "section": section,
            "group": group_row["group_name"]}
