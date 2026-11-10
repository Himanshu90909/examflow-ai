# ExamFlow AI

Examination scheduling for **Lovely Professional University**: a real constraint-programming engine, a
production rule system, an independent validator and explainable decisions. Every screen reads and
writes persistent data; nothing is mocked.

The engine is generic and the university is configuration. The seeded dataset speaks the campus
vocabulary a reviewer recognises: schools `SCSE` / `SEEE` / `LFBA`, B.Tech and BBA student groups,
block-and-room venues such as `34-401` in Block 34, and course codes like `CSE205`. Every person in it
is fictional.

### Serving a different university

No page hard-codes a university. These variables drive the masthead, the sign-in screen, the document
titles and the seeded wording:

| Variable | Default |
| --- | --- |
| `EXAMFLOW_INSTITUTION` | `Lovely Professional University` |
| `EXAMFLOW_INSTITUTION_SHORT` | `LPU` |
| `EXAMFLOW_EXAM_OFFICE` | `Division of Examination` |
| `EXAMFLOW_INSTITUTION_ADDRESS` | `Jalandhar - Delhi G.T. Road, Phagwara, Punjab 144411` |
| `EXAMFLOW_INSTITUTION_PHONE` / `_EMAIL` | `+91 1824 404404` / `examination.office@lpu.co.in` |
| `EXAMFLOW_TERM_NAME` | `Term End Examination` |
| `EXAMFLOW_SESSION` | `2026-27` |

A deployment seeded before this identity existed still shows the old generic rows. Re-cut them in
place, keeping every identifier other tables point at (safe to run more than once, Super Admin only):

```bash
curl -X POST <origin>/api/institution/retheme -H "Authorization: Bearer <super admin token>"
```

Built with the Python standard library (SQLite + `http.server`) and a dependency-free frontend, so it
runs anywhere Python 3.9+ exists.

---

## 1. Run it

```bash
cd examflow-ai
python3 server/app.py
# open http://localhost:8000
```

The database (`examflow.db`) is created and seeded on first start. Delete that file to reset.

Environment variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PORT` | `8000` | HTTP port |
| `EXAMFLOW_DB` | `./examflow.db` | SQLite file location |
| `EXAMFLOW_SECRET` | dev value | HMAC secret for session tokens — **set this in production** |
| `EXAMFLOW_SEED` | on | `0` skips demo seeding |

### Demonstration accounts

| Role | Email | Password |
| --- | --- | --- |
| Super Admin | `admin@examflow.ai` | `Admin@123` |
| School Admin (Northfield) | `rita@examflow.ai` | `Examflow@123` |
| School Admin (Riverside) | `samuel@examflow.ai` | `Examflow@123` |
| Invigilator | `ananya@examflow.ai` | `Examflow@123` |

All schools, faculty and students are fictional demonstration data.

---

## 2. What is inside

**Three roles with enforced isolation**

- **Super Admin** — every school, every record, user management, full audit log.
- **School Admin** — only their own school's departments, groups, examinations, rooms and faculty.
  Scoping is applied server-side on every list, read, write and delete; the UI never receives other
  schools' rows.
- **Invigilator** — read-only duty list, own availability, issue reporting. Attempts at scheduling
  actions return `403` from the API, not just a hidden button.

**20 modules** — Dashboard · Schools · Departments · Student Groups · Examinations · Examination
Calendar · Rooms Management · Invigilators · Faculty Availability · Time Slots · Constraints &
Policies · AI Timetable Generator · Generated Timetable · Conflict Management · Fairness Analysis ·
Algorithm Comparison · My Duties · Reports & Analytics · Notifications · Audit Logs · User Management ·
Settings.

**Generator workflow** — a ten-step run configuration (schools → session → date window →
examinations → rooms → invigilators → policies → optimisation weights → algorithm → generate). The
configuration is stored with the run, so every result is reproducible.

**Timetable views** — calendar, daily, weekly, school-wise, room-wise, group-wise and
invigilator-wise, with search, date and school filters, CSV export, printing, per-assignment detail
and manual reschedule with immediate revalidation.

---

## 3. Scheduling engine

`server/scheduler/` is deliberately isolated from the web layer. It receives a plain `Problem`
dataclass and returns a `SolveResult`; nothing in it imports the database or HTTP code. That seam is
where an external solver (OR-Tools CP-SAT over FastAPI) plugs in later:

```
POST /api/scheduling/run
        └── solver_service.load_problem()      # DB  -> Problem
              └── scheduler.csp.CSPSolver      # Problem -> SolveResult
                    └── scheduler.conflicts     # independent validation
                    └── scheduler.fairness      # workload metrics
        └── solver_service.persist()           # SolveResult -> DB
```

### Hard constraints (never relaxed)

| Rule | Meaning |
| --- | --- |
| R1 room capacity | Room seats ≥ the examination's candidate count |
| R2 invigilator availability | No duty inside a declared leave/unavailability window |
| R3 daily duty limit | Per-day cap for each invigilator |
| R4 student group clash | Two examinations sharing a group never overlap |
| R5 room double booking | A room hosts at most one examination at a time |
| R6 invigilator clash | One invigilator cannot supervise two simultaneous examinations |
| R7 total duty limit | Whole-run cap per invigilator |
| R8 policy rules | Slot duration fit, required facilities, inter-school policy, active status |

Every rule is a named, testable function in `scheduler/constraints.py`. Policies are rows in
`constraint_policies` and can be enabled or disabled per run; a disabled mandatory rule is recorded
in the run configuration rather than silently applied.

### Soft objectives

Workload balance, consecutive-duty avoidance, preferred dates and room utilisation are weighted soft
penalties. They influence value ordering and are reported as a penalty score; they never override a
hard rule.

### Search: CSP with heuristics

1. **Domain construction** — every (slot, room) pair that satisfies all hard rules.
2. **Variable ordering — MRV**, tie-broken by **degree heuristic** (number of examinations sharing a
   student group), then priority, then id.
3. **Value ordering — LCV** — the value eliminating the fewest options from the remaining
   examinations, tie-broken by preferred date, slot rank and smallest adequate room.
4. **Forward checking + propagation** — after each placement, prune every remaining domain; a wipe-out
   backtracks immediately.
5. **Chronological backtracking** with node and time limits.

No randomness anywhere: the same dataset produces the same timetable every time, so explanations stay
valid and runs are comparable.

When the exact search proves infeasible, the engine keeps a **maximal partial timetable** (greedy
placement under the same hard rules) instead of discarding the work, and reports the rest as
unscheduled with the blocking reason.

**Status vocabulary** — `FEASIBLE_BUT_NOT_PROVEN_OPTIMAL` (every hard rule satisfied, optimality not
proven), `INFEASIBLE` (some mandatory rule is violated or an examination is unplaced),
`TIME_LIMIT_REACHED`. Nothing is ever labelled "optimal" unless a proven optimiser says so.

### First-Fit baseline

`scheduler/firstfit.py` places examinations in a fixed order into the first slot/room that satisfies
the rules, with a naive invigilator pick. It is the comparison baseline, not a fallback: it
demonstrably scores worse (higher penalty, wider workload spread) on the same data.

### Independent validation and repair

`ConflictEngine.validate()` re-checks every hard rule from scratch against the final assignment list.
The solver is never trusted, and **publishing is blocked** while any mandatory violation exists.

`repair()` then tries alternative slots and rooms for the flagged examinations, and reassigns
invigilators who are over a daily/total cap or inside an unavailable window. Anything it cannot fix is
reported with its blocking constraint.

### Explanations (XAI)

Each placement stores a decision reason, how many alternatives existed, which constraints were
satisfied, and the strongest rejected alternatives with the reason each was rejected. They are shown
in the timetable detail panel and stored in `schedule_explanations`.

### Fairness

Workload balance is scored as:

```
Fairness Score = 100 × (1 − SD / max(mean, 1)), clamped to 0..100
```

This is a **project-defined workload balance indicator**, not an industry standard. Read it together
with availability, eligibility and duty caps — it is derived from real duty counts, and improving it
never relaxes a hard constraint.

---

## 4. Data model

SQLite with foreign keys enabled, plus JSON columns for lists such as student groups and facilities.

`schools`, `departments`, `student_groups`, `examinations`, `rooms`, `invigilators`,
`time_slots`, `invigilator_availability`, `constraint_policies`, `scheduling_runs`,
`schedule_assignments`, `invigilator_assignments`, `schedule_explanations`, `conflict_logs`,
`fairness_metrics`, `audit_logs`, `users` — plus `notifications`.

Referential integrity is enforced by foreign keys, and deletes that would orphan dependent records are
refused with an explanatory message (examination → assignments, school → departments, and so on).

---

## 5. API

Authenticated with `Authorization: Bearer <token>` from `POST /api/auth/login`.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/auth/login` | Sign in, returns token |
| GET | `/api/auth/me` | Current user |
| GET | `/api/meta` | Reference data for forms (schools, groups, rooms, policies…) |
| GET | `/api/dashboard` | Counts, charts, latest run, comparison, activity |
| GET/POST | `/api/{resource}` | List (paged, searchable, filterable) / create |
| GET/PUT/DELETE | `/api/{resource}/{id}` | Read / update / delete |
| POST | `/api/import/{resource}` | CSV import for examinations, groups, rooms, invigilators |
| POST | `/api/scheduling/run` | Execute a scheduling run |
| GET | `/api/runs/{id}` | Run detail with fairness summary |
| GET | `/api/runs/{id}/assignments` | Assignments with invigilators and explanations |
| GET | `/api/runs/{id}/validate` | Independent validation result |
| POST | `/api/runs/{id}/approve` \| `/publish` \| `/repair` | Lifecycle actions |
| PUT | `/api/assignments/{id}/reschedule` | Manual move with revalidation |
| GET | `/api/comparison` | First-Fit vs AI metrics |
| GET | `/api/reports/{kind}` | Report data (`timetable`, `school`, `invigilator`, `room`, `group`, `conflict`, `fairness`, `comparison`, `performance`) |
| GET | `/api/reports/{kind}.csv` | The same report as a CSV download |
| GET | `/api/my-duties`, POST `/api/my-duties/report-issue` | Invigilator self-service |

`resource` is one of `schools`, `departments`, `student-groups`, `examinations`, `rooms`,
`invigilators`, `availability`, `time-slots`, `policies`, `users`, `runs`, `conflicts`,
`audit-logs`, `notifications`, `assignments`.

Failures use real status codes: `403` (role or school isolation), `404`, `422` (validation), `500`.

### Sign-in options

Four ways in, all issued against the same signed bearer token:

| Route | What it does |
| --- | --- |
| POST `/api/auth/login` | Email and password (demo and staff accounts) |
| GET `/api/auth/google/start?portal=…` → `/api/auth/google/callback` | Google sign-in; a first-time Gmail becomes an account in that portal |
| POST `/api/auth/request-code` \| `/api/auth/verify-code` | Six-digit code emailed to the address on the account |
| POST `/api/auth/request-phone-code` \| `/api/auth/verify-phone-code` | Six-digit code texted to a phone number; a new number becomes a **student** account on first use, staff portals only accept numbers already on file |

`GET /api/auth/providers` tells the sign-in page which of the four are configured.

Google needs `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` (redirect URI
`<origin>/api/auth/google/callback`). Email codes need `RESEND_API_KEY` or `SMTP_HOST` +
`SMTP_USER` + `SMTP_PASSWORD`. Phone codes need a gateway:

```bash
FAST2SMS_API_KEY=…            # India, quick/bulk route (set EXAMFLOW_FAST2SMS_ROUTE if needed)
# or
TWILIO_ACCOUNT_SID=… TWILIO_AUTH_TOKEN=… TWILIO_FROM=+1…
EXAMFLOW_PHONE_COUNTRY=91     # country code assumed for bare national numbers
```

Turning a gateway on is the only step needed; the demonstration flag must then be removed,
because a configured gateway always wins and the code is no longer returned to the page:

1. Create a Twilio trial account, verify your own mobile number under *Phone numbers → Verified
   caller IDs*, and copy the Account SID, the auth token and a sender number (a trial
   `+1 555…` sender works; trial accounts can only text numbers you have verified).
2. Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` and `TWILIO_FROM` in the deployment and delete
   `EXAMFLOW_SMS_DEMO`.
3. Prove delivery before trusting the login form:
   `curl -X POST <origin>/api/diag/sms-test -H "X-Diag-Key: $EXAMFLOW_DIAG_KEY" \
        -H "Content-Type: application/json" -d '{"phone":"98xxxxxxxx"}'`
   A `200` means the gateway accepted the message and the phone rang; a `502` carries the
   provider's own words (`21608 unverified number`, `insufficient funds`, and so on).

Fast2SMS is the cheaper Indian option the code already speaks, but its OTP route needs DLT
template registration before it will deliver to Indian numbers, so Twilio is the shorter path
for a review link.

Without a gateway, `EXAMFLOW_SMS_DEMO=1` runs a demonstration: the requested code is returned to
the sign-in page and prefilled so a reviewer can complete the flow. It is off unless that
variable is set and it must never be set on a real deployment. Numbers are stored in E.164 form;
the seeded demonstration accounts use `+91 90000 00001`…`00004` (staff) and
`…00011`…`00013` (students).

---

## 6. Tests

```bash
python3 tests/test_engine.py         # 17 engine tests, no dependencies
python3 tests/test_google_signin.py  # 8 Google sign-in / account provisioning tests
python3 tests/test_phone_signin.py   # 13 phone sign-in tests (numbers, codes, provisioning, throttling)
```

Covers the invigilator-per-candidate rule, room capacity rejection, daily duty limits, group-overlap
and room-clash prevention, infeasibility handling, determinism, the fairness formula, plus end-to-end
runs asserting that all examinations are scheduled, no hard rule is violated, AI beats First-Fit on
soft penalty and workload spread, every assignment has an explanation, and that an injected clash is
detected, blocks publishing and is repaired.

Browser-side smoke test (renders all 22 routes against the live API through a DOM shim):

```bash
node tests/smoke_ui.js http://localhost:8000
```

---

## 7. Layout

```
examflow-ai/
├── server/
│   ├── app.py                HTTP server, routing, static files
│   ├── api.py                REST handlers, role-aware CRUD, reports
│   ├── auth.py               password hashing, signed sessions, permissions
│   ├── db.py                 schema, connection, JSON helpers, audit
│   ├── seed.py               demonstration dataset
│   ├── solver_service.py     orchestration + persistence  ← engine boundary
│   └── scheduler/            NO database, NO HTTP
│       ├── constraints.py    Problem, RuleEngine (R1–R8)
│       ├── csp.py            MRV / degree / LCV / forward checking / backtracking
│       ├── firstfit.py       baseline
│       ├── conflicts.py      independent validator + repair
│       └── fairness.py       workload metrics
├── static/
│   ├── index.html
│   ├── css/styles.css        design system
│   └── js/{core,pages,scheduling,reports}.js
└── tests/
    ├── test_engine.py
    └── smoke_ui.js
```

---

## 8. Design system

Navy sidebar `#0F172A`, primary blue `#2563EB`, background `#F8FAFC`, text `#1E293B`, 14px card
radius, 1px `#E2E8F0` borders, Inter with a system fallback. Tables stay readable on small screens,
the shell collapses to a drawer under 1000px, and print styles strip navigation so a timetable prints
cleanly.

---

## 9. Honest limitations

- **No CP-SAT in this build.** OR-Tools is not installed, so results are reported as feasible, never
  optimal. The `Problem → SolveResult` seam is designed so a CP-SAT solver can be dropped in, with
  `/api/scheduling/run` selecting it.
- **One invigilator per 75 candidates** (min 1, max 2) is a project rule defined in
  `required_invigilators()`; change it there if your institution differs.
- **SQLite, single process.** Fine for a school group; a multi-tenant deployment would move to
  Postgres and a WSGI/ASGI server.
- **Sessions are stateless HMAC tokens** with expiry; there is no server-side revocation list, so
  rotating `EXAMFLOW_SECRET` invalidates existing sessions.
- The database file stores software hashes (PBKDF2-SHA256, 120k iterations), not plaintext passwords.
- Notifications are in-app only; no email or SMS transport is wired in.

---

## 10. Deploying to Vercel

The app ships with a Vercel build: `api/index.py` is the serverless entry point and
`server/wsgi.py` adapts the existing request handler to WSGI, so no routing is duplicated.

```bash
npm i -g vercel
cd examflow-ai
vercel          # preview deployment
vercel --prod   # production URL
```

`vercel.json` routes every request to the Python function and bundles `server/**` and
`static/**` with it.

**Storage on Vercel.** Serverless filesystems are read-only apart from `/tmp`, so the SQLite
database is created at `/tmp/examflow.db` and seeded on each cold start. The deployment is fully
functional, but data resets when a new instance starts — fine for a demo or a review link, not for
keeping real timetables. For durable data, deploy the same code to a host with a persistent disk
(Render, Railway, Fly.io, a VPS) with `EXAMFLOW_DB` pointing at the volume, or replace `server/db.py`
with Postgres.

Never commit a real `EXAMFLOW_SECRET`; set it as a Vercel environment variable.

**Live demo:** https://examflow-ai-api.vercel.app (Vercel, SQLite in /tmp, reseeds on cold start)

## Persistence on Vercel

Vercel functions only have a throw-away `/tmp`, so the application keeps its SQLite
database in this repository as `data/examflow.db.gz`:

* cold start: the snapshot is restored into `EXAMFLOW_DB` before the app boots
* every write (POST/PUT/DELETE): the database is backed up, gzipped and committed
* disable it by clearing `EXAMFLOW_SNAPSHOT_REPO`

Environment variables on Vercel: `EXAMFLOW_SNAPSHOT_REPO`, `EXAMFLOW_GITHUB_TOKEN`,
`EXAMFLOW_SECRET`, `EXAMFLOW_DB=/tmp/examflow.db`, `EXAMFLOW_GOOGLE_ADMIN_EMAILS`.
Treat the snapshot store as demo-grade: two instances writing at the same instant keep
the last commit. Move to a managed Postgres for real multi-user deployments.

## One-click deploy

- Render: https://render.com/deploy?repo=https://github.com/yogesh9-max/examflow-ai
- Vercel: https://vercel.com/new/clone?repository-url=https://github.com/yogesh9-max/examflow-ai
