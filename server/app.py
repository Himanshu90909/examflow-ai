"""ExamFlow AI HTTP server (Python standard library only).

Run:  python3 server/app.py  ->  http://localhost:8000
"""
import collections
import json
import os
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import auth
import api
import persistence
import google_auth
import mailer
import otp
import sms
import solver_service

AUTH_MODE = (os.environ.get("EXAMFLOW_AUTH_MODE") or "both").strip().lower()

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PORTAL_ROLES = {"admin": ("Super Admin", "School Admin"),
                "user": ("Invigilator",),
                "student": ("Student",)}

def _portal_mismatch_message(portal):
    """One sentence telling someone they are on the wrong sign-in page."""
    if portal == "admin":
        return ("This is the administrator portal. Invigilators and students sign in from "
                "their own portal.")
    if portal == "student":
        return ("This is the student portal. Staff sign in from the administrator or "
                "invigilator portal.")
    return ("This is the invigilator portal. Administrators and students sign in from their "
            "own portal.")


def _password_sign_in_available():
    if AUTH_MODE == "google" and google_auth.ENABLED:
        return False
    if AUTH_MODE == "otp" and mailer.ENABLED:
        return False
    return True
STATIC = os.path.join(ROOT, "static")
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon",
                 ".json": "application/json"}


# --- incident trail -----------------------------------------------------------
# A 500 on a hosted instance is otherwise invisible: the log line disappears with
# the container. Keep the last few failures in memory and behind a keyed endpoint
# so an operator can see what broke without redeploying.
INCIDENTS = collections.deque(maxlen=10)


def record_incident(method, path, exc):
    incident = os.urandom(3).hex()
    INCIDENTS.append({
        "id": incident,
        "at": db.now_iso(),
        "request": "%s %s" % (method, path),
        "kind": type(exc).__name__,
        "message": str(exc)[:400],
        "trace": "".join(traceback.format_exception_only(type(exc), exc)).strip(),
    })
    return incident


def diag_key():
    """The diagnostics endpoint answers only when a key is configured for it."""
    return (os.environ.get("EXAMFLOW_DIAG_KEY") or "").strip()


class Handler(BaseHTTPRequestHandler):
    server_version = "ExamFlowAI/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- plumbing
    def log_message(self, fmt, *args):
        if os.environ.get("EXAMFLOW_QUIET") != "1":
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _origin(self):
        proto = self.headers.get("X-Forwarded-Proto") or "http"
        host = self.headers.get("Host") or "localhost:8000"
        return "%s://%s" % (proto, host)

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send(self, status, payload=None, content_type="application/json", raw=None):
        path = self.path or ""
        if (status < 400 and self.command in ("POST", "PUT", "PATCH", "DELETE")
                and path.startswith("/api") and not path.startswith("/api/auth")):
            persistence.save_now()
        body = raw if raw is not None else (
            json.dumps(payload).encode("utf-8") if payload is not None else b"")
        if not isinstance(body, bytes):
            body = str(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except json.JSONDecodeError:
            raise api.auth.ValidationError("Request body must be valid JSON")

    def _user(self, conn):
        header = self.headers.get("Authorization") or ""
        token = header[7:].strip() if header.lower().startswith("bearer ") else None
        if not token:
            raise api.auth.Forbidden("Sign in to continue")
        user = auth.current_user(token)
        if not user:
            # A stale or unknown token is an authentication problem, not a server
            # fault: answer 401 so the browser clears it and shows the login page.
            raise auth.Unauthorized("Your session expired. Please sign in again.")
        return user

    def _dispatch(self, method):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}

        if not path.startswith("/api"):
            return self._static(path)

        if path == "/api/health":
            return self._send(200, {"status": "ok", "app": "ExamFlow AI"})

        conn = db.connect()
        try:
            if method == "GET" and path == "/api/diag":
                expected = diag_key()
                if not expected or (self.headers.get("X-Diag-Key") or "") != expected:
                    raise auth.NotFound("Endpoint not found")
                return self._send(200, {
                    "ok": True,
                    "now": db.now_iso(),
                    "db_path": db.DB_PATH,
                    "db_bytes": os.path.getsize(db.DB_PATH) if os.path.exists(db.DB_PATH) else 0,
                    "incidents": list(INCIDENTS),
                    "persistence": persistence.status(),
                })

            if path == "/api/diag/sms-test" and method == "POST":
                expected = diag_key()
                if not expected or (self.headers.get("X-Diag-Key") or "") != expected:
                    raise auth.NotFound("Endpoint not found")
                body = self._json_body()
                try:
                    to = sms.normalize(body.get("phone"))
                    sms.send(to, body.get("text") or "ExamFlow AI test message.")
                except ValueError as exc:
                    raise auth.ValidationError(str(exc))
                except Exception as exc:  # noqa: BLE001 - the provider's words matter here
                    return self._send(502, {"sent": False, "transport": sms.TRANSPORT or None,
                                            "error": str(exc)})
                return self._send(200, {"sent": True, "to": to, "transport": sms.TRANSPORT})

            if method == "GET" and path == "/api/auth/providers":
                return self._send(200, {"password": _password_sign_in_available(),
                                        "google": google_auth.ENABLED,
                                        "otp": mailer.ENABLED,
                                        "phone": sms.available(),
                                        "phone_demo": sms.DEMO and not sms.ENABLED,
                                        "mode": AUTH_MODE})

            if method == "GET" and path == "/api/auth/google/start":
                if not google_auth.ENABLED:
                    return self._redirect("/?google_error=not_configured#/login")
                portal = (query.get("portal") or "user").strip().lower()
                origin = self._origin()
                redirect_uri = google_auth.callback_uri(origin)
                state = google_auth.sign_state(redirect_uri, portal, origin)
                return self._redirect(google_auth.authorize_url(redirect_uri, state))

            if method == "GET" and path == "/api/auth/google/callback":
                if query.get("error"):
                    return self._redirect("/?google_error=cancelled#/login")
                # read_state returns the signed payload: "r" is the registered callback
                # Google redirected to, "p" the portal, "o" the host to return to.
                state = google_auth.read_state(query.get("state") or "") or {}
                redirect_uri = (state.get("r") or "").partition("|")[0]
                portal = (state.get("p") or "student").strip().lower() or "student"
                # The host the visitor started on, signed into the state. It lets an
                # alternative domain complete the flow through the registered callback
                # and still land back on the address the visitor typed.
                site = (state.get("o") or "").strip().rstrip("/")
                if not site.startswith(("http://", "https://")):
                    site = ""
                if not redirect_uri:
                    return self._redirect(site + "/?google_error=expired#/login")
                try:
                    profile = google_auth.exchange_code(query.get("code") or "", redirect_uri)
                except google_auth.GoogleAuthError:
                    return self._redirect(site + "/?google_error=google#/login")

                row = conn.execute("SELECT * FROM users WHERE LOWER(email) = ?",
                                   (profile["email"],)).fetchone()
                if row is None:
                    if portal != "student":
                        return self._redirect(site + "/?google_error=no_account#/login/student")
                    conn.execute(
                        """INSERT INTO users (id, full_name, email, password_hash, role,
                                              school_id, department_id, student_group_id,
                                              is_active, created_at)
                           VALUES (?,?,?,?,?,NULL,NULL,NULL,1,?)""",
                        (db.new_id(), profile["name"], profile["email"],
                         auth.hash_password(db.new_id() + db.new_id()), "Student", db.now_iso()))
                    conn.commit()
                    row = conn.execute("SELECT * FROM users WHERE LOWER(email) = ?",
                                       (profile["email"],)).fetchone()

                user = db.decode_row("users", row)
                if not user.get("is_active", 1):
                    return self._redirect(site + "/?google_error=inactive#/login")
                allowed = {"admin": ("Super Admin", "School Admin"),
                           "user": ("Invigilator",),
                           "student": ("Student",)}.get(portal, ())
                if allowed and user["role"] not in allowed:
                    return self._redirect(site + "/?google_error=wrong_portal#/login/%s" % portal)

                db.audit(conn, user, "User login (Google)", "user", user["id"])
                conn.commit()
                # A GET redirect cannot pass through the write hook in _send, so a
                # brand-new Google account has to be snapshotted right here; otherwise
                # the token reaches an instance whose database has never seen the user.
                persistence.save_now()
                return self._redirect(site + "/#google_token=" + quote(auth.make_token(user)))

            if method == "POST" and path == "/api/auth/request-code":
                body = self._json_body()
                portal = (body.get("portal") or "").strip().lower()
                email = (body.get("email") or "").strip().lower()
                if "@" not in email or len(email) < 5:
                    raise auth.ValidationError("Enter the email address on your account.")
                user = auth.find_user(email)
                allowed_roles = PORTAL_ROLES.get(portal)
                known = bool(user) and (not allowed_roles or user["role"] in allowed_roles)
                if known and otp.recent_request_blocked(conn, "email", email):
                    raise auth.ValidationError(
                        "A code was sent a moment ago. Wait a minute before asking for another.")
                if known:
                    code = otp.issue(conn, "email", email, portal)
                    conn.commit()
                    sent = False
                    if mailer.ENABLED:
                        try:
                            mailer.send(
                                email,
                                "Your ExamFlow AI sign-in code",
                                "Your ExamFlow AI sign-in code is %s. It expires in %d minutes."
                                % (code, otp.CODE_TTL_MINUTES),
                                "<p>Your ExamFlow AI sign-in code is <strong>%s</strong>.</p>"
                                "<p>It expires in %d minutes. If you did not try to sign in, ignore this "
                                "email.</p>" % (code, otp.CODE_TTL_MINUTES),
                            )
                            sent = True
                            db.audit(conn, None, "Sign-in code emailed", "user", user["id"], email)
                            conn.commit()
                        except Exception:  # noqa: BLE001
                            traceback.print_exc()
                # identical response either way: never reveal whether an address exists
                return self._send(200, {"sent": True, "delivered": bool(mailer.ENABLED), "email": email,
                                        "expires_in": otp.CODE_TTL_MINUTES * 60})

            if method == "POST" and path == "/api/auth/verify-code":
                body = self._json_body()
                portal = (body.get("portal") or "").strip().lower()
                email = (body.get("email") or "").strip().lower()
                ok, reason = otp.confirm(conn, "email", email, portal, body.get("code"))
                conn.commit()
                if not ok:
                    raise auth.Unauthorized(reason)
                user = auth.find_user(email)
                if not user:
                    raise auth.Unauthorized("No active account is linked to that address.")
                allowed_roles = PORTAL_ROLES.get(portal)
                if allowed_roles and user["role"] not in allowed_roles:
                    db.audit(conn, user, "Blocked sign-in (wrong portal)", "user", user["id"],
                             "Tried the %s portal as %s" % (portal, user["role"]))
                    conn.commit()
                    raise auth.Unauthorized(_portal_mismatch_message(portal))
                db.audit(conn, user, "User login (email code)", "user", user["id"],
                         "Portal: %s" % (portal or "default"))
                conn.commit()
                return self._send(200, {"token": auth.make_token(user), "user": user})

            if method == "POST" and path == "/api/auth/request-phone-code":
                body = self._json_body()
                portal = (body.get("portal") or "").strip().lower()
                try:
                    phone = sms.normalize(body.get("phone"))
                except ValueError as exc:
                    raise auth.ValidationError(str(exc))
                if not sms.available():
                    raise auth.ValidationError(
                        "Phone sign-in is not switched on for this deployment yet.")
                user = auth.find_user_by_phone(phone)
                allowed_roles = PORTAL_ROLES.get(portal)
                known = bool(user) and (not allowed_roles or user["role"] in allowed_roles)
                demo_code = None
                deliver = False
                if known and not otp.hourly_cap_reached(conn, "phone", phone):
                    if otp.recent_request_blocked(conn, "phone", phone):
                        raise auth.ValidationError(
                            "A code was sent a moment ago. Wait a minute before asking for another.")
                    code = otp.issue(conn, "phone", phone, portal)
                    conn.commit()
                    if sms.ENABLED:
                        try:
                            sms.send(phone, "ExamFlow AI sign-in code: %s. It expires in %d minutes. "
                                            "Do not share it." % (code, otp.CODE_TTL_MINUTES))
                            deliver = True
                            db.audit(conn, None, "Sign-in code texted", "user", user["id"], phone)
                            conn.commit()
                        except Exception:  # noqa: BLE001
                            traceback.print_exc()
                    elif sms.DEMO:
                        demo_code = code
                elif not known and portal == "student":
                    # Students may create their own account from a phone number, so the
                    # code is issued before an account exists. Staff roles cannot self-serve.
                    if not otp.recent_request_blocked(conn, "phone", phone):
                        code = otp.issue(conn, "phone", phone, portal)
                        conn.commit()
                        if sms.ENABLED:
                            try:
                                sms.send(phone, "ExamFlow AI sign-in code: %s. It expires in %d "
                                                "minutes. Do not share it."
                                         % (code, otp.CODE_TTL_MINUTES))
                                deliver = True
                            except Exception:  # noqa: BLE001
                                traceback.print_exc()
                        elif sms.DEMO:
                            demo_code = code
                elif sms.DEMO and not otp.recent_request_blocked(conn, "phone", phone):
                    # Demonstration mode: no text can be sent, so refusing to issue a code
                    # leaves the visitor staring at an empty form. Issue one and let the
                    # verification step explain that the number has no staff account yet.
                    code = otp.issue(conn, "phone", phone, portal)
                    conn.commit()
                    demo_code = code
                payload = {"sent": True, "delivered": deliver, "phone": phone,
                           "registered": known,
                           "expires_in": otp.CODE_TTL_MINUTES * 60}
                if demo_code:
                    payload["demo_code"] = demo_code
                if sms.DEMO and not known and portal != "student":
                    payload["hint"] = (
                        "This number is not linked to a staff account yet, so the code will be "
                        "refused at the next step. Sign in with your password, or ask the "
                        "examination office to add this number to your account.")
                return self._send(200, payload)

            if method == "POST" and path == "/api/auth/verify-phone-code":
                body = self._json_body()
                portal = (body.get("portal") or "student").strip().lower()
                try:
                    phone = sms.normalize(body.get("phone"))
                except ValueError as exc:
                    raise auth.ValidationError(str(exc))
                ok, reason = otp.confirm(conn, "phone", phone, portal, body.get("code"))
                conn.commit()
                if not ok:
                    raise auth.Unauthorized(reason)
                user = auth.find_user_by_phone(phone)
                created = False
                if not user:
                    if portal != "student":
                        raise auth.Unauthorized(
                            "No ExamFlow account uses that phone number. Ask the examination office "
                            "to add it.")
                    user = auth.provision_phone_account(conn, phone, portal, body.get("full_name"))
                    created = True
                allowed_roles = PORTAL_ROLES.get(portal)
                if allowed_roles and user["role"] not in allowed_roles:
                    db.audit(conn, user, "Blocked sign-in (wrong portal)", "user", user["id"],
                             "Tried the %s portal by phone as %s" % (portal, user["role"]))
                    conn.commit()
                    raise auth.Unauthorized(_portal_mismatch_message(portal))
                db.audit(conn, user, "User login (phone code)", "user", user["id"],
                         "Portal: %s · %s" % (portal or "default", sms.display(phone)))
                conn.commit()
                if created:
                    persistence.save_now()
                return self._send(200, {"token": auth.make_token(user), "user": user,
                                        "created": created})

            if method == "POST" and path == "/api/auth/gmail":
                body = self._json_body()
                portal = (body.get("portal") or "student").strip().lower()
                email = (body.get("email") or "").strip().lower()
                password = body.get("password") or ""
                if "@" not in email or "." not in email.split("@")[-1]:
                    raise auth.ValidationError("Enter your email address.")
                if len(password) < 8:
                    raise auth.ValidationError("Choose a password of at least 8 characters.")
                row = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (email,)).fetchone()
                if row and not row["is_active"]:
                    raise auth.Unauthorized("This account has been deactivated. Contact your administrator.")
                if row:
                    user = auth.authenticate(email, password)
                    if not user:
                        raise auth.Unauthorized(
                            "This email already has an account. Enter its password, or sign up with a "
                            "different address.")
                    allowed_roles = PORTAL_ROLES.get(portal)
                    if allowed_roles and user["role"] not in allowed_roles:
                        raise auth.Unauthorized(
                            "That account belongs to a different portal. Use the right sign-in page "
                            "for its role.")
                    db.audit(conn, user, "User login (email account)", "user", user["id"],
                             "Portal: %s" % (portal or "default"))
                    conn.commit()
                    return self._send(200, {"token": auth.make_token(user), "user": user,
                                            "created": False})
                user = auth.provision_gmail_account(conn, email, password, portal, body.get("full_name"))
                if not user:
                    raise auth.ValidationError("Could not create that account. Try another address.")
                db.audit(conn, user, "Self-service account created", "user", user["id"],
                         "Portal: %s" % (portal or "default"))
                db.notify(conn, user["id"], "Welcome to ExamFlow AI",
                          "Your %s access is ready. Explore your dashboard to get started."
                          % user["role"])
                conn.commit()
                # a new account must survive the next cold start, so snapshot it now
                persistence.save_now()
                return self._send(201, {"token": auth.make_token(user), "user": user, "created": True})

            if method == "POST" and path == "/api/auth/login":
                body = self._json_body()
                portal = (body.get("portal") or "").strip().lower()
                if not _password_sign_in_available():
                    raise auth.Unauthorized(
                        "Password sign-in is switched off on this deployment.")
                user = auth.authenticate(body.get("email") or "", body.get("password") or "")
                if not user:
                    raise auth.Unauthorized("Email or password is incorrect.")
                allowed_roles = {"admin": ("Super Admin", "School Admin"),
                                 "user": ("Invigilator",),
                                 "student": ("Student",)}.get(portal)
                if allowed_roles and user["role"] not in allowed_roles:
                    db.audit(conn, user, "Blocked sign-in (wrong portal)", "user", user["id"],
                             "Tried the %s portal as %s" % (portal, user["role"]))
                    conn.commit()
                    if portal == "admin":
                        raise auth.Unauthorized(
                            "This is the administrator portal. Invigilators and students sign in from their own portal.")
                    if portal == "student":
                        raise auth.Unauthorized(
                            "This is the student portal. Staff sign in from the administrator or invigilator portal.")
                    raise auth.Unauthorized(
                        "This is the invigilator portal. Administrators and students sign in from their own portal.")
                db.audit(conn, user, "User login", "user", user["id"],
                         "Portal: %s" % (portal or "default"))
                conn.commit()
                return self._send(200, {"token": auth.make_token(user), "user": user})

            user = self._user(conn)

            if path == "/api/auth/me":
                return self._send(200, {"user": user})
            if method == "POST" and path == "/api/auth/logout":
                db.audit(conn, user, "User logout", "user", user["id"])
                conn.commit()
                return self._send(200, {"ok": True})
            if path == "/api/meta":
                return self._send(200, api.meta(conn, user))
            if path == "/api/dashboard":
                return self._send(200, api.dashboard(conn, user))
            if path == "/api/my-duties":
                return self._send(200, api.my_duties(conn, user))
            if path == "/api/my-exams":
                return self._send(200, api.my_exams(conn, user))
            if method == "POST" and path == "/api/my-duties/report-issue":
                return self._send(200, api.report_availability_issue(conn, user, self._json_body()))

            if method == "POST" and path == "/api/scheduling/run":
                body = self._json_body()
                if user["role"] == "Invigilator":
                    raise auth.Forbidden("Invigilators cannot generate timetables")
                if user["role"] == "School Admin" and not body.get("school_ids"):
                    body["school_ids"] = [user["school_id"]]
                return self._send(201, solver_service.run_schedule(conn, user, body))

            m = re.match(r"^/api/runs/([0-9a-zA-Z]+)/(validate|fairness|assignments|approve|publish|repair)$",
                         path)
            if m:
                run_id, action = m.groups()
                if method == "GET" and action == "validate":
                    return self._send(200, solver_service.validate_run(conn, run_id))
                if method == "GET" and action == "fairness":
                    return self._send(200, solver_service.fairness_for_run(conn, run_id))
                if method == "GET" and action == "assignments":
                    return self._send(200, {"assignments": solver_service.assignments_for_run(conn, run_id)})
                if method == "POST" and action == "approve":
                    return self._send(200, solver_service.approve_run(conn, user, run_id))
                if method == "POST" and action == "publish":
                    return self._send(200, solver_service.publish_run(conn, user, run_id))
                if method == "POST" and action == "repair":
                    return self._send(200, solver_service.repair_run(conn, user, run_id))

            m = re.match(r"^/api/runs/([0-9a-zA-Z]+)$", path)
            if m and method == "GET":
                return self._send(200, solver_service.get_run(conn, m.group(1)))

            if path == "/api/comparison":
                a, b = query.get("a"), query.get("b")
                if not a or not b:
                    csp = conn.execute("SELECT id FROM scheduling_runs WHERE algorithm_name LIKE 'CSP%' "
                                       "ORDER BY created_at DESC LIMIT 1").fetchone()
                    ff = conn.execute("SELECT id FROM scheduling_runs WHERE algorithm_name LIKE 'First-Fit%' "
                                      "ORDER BY created_at DESC LIMIT 1").fetchone()
                    if not (csp and ff):
                        raise auth.ValidationError(
                            "Generate one AI run and one First-Fit run to compare them.")
                    a, b = ff["id"], csp["id"]
                return self._send(200, solver_service.compare_runs(conn, a, b))

            if method == "PUT" and re.match(r"^/api/assignments/[0-9a-zA-Z]+/reschedule$", path):
                assignment_id = path.split("/")[3]
                body = self._json_body()
                if user["role"] == "Invigilator":
                    raise auth.Forbidden("Invigilators cannot reschedule examinations")
                return self._send(200, solver_service.reschedule_assignment(
                    conn, user, assignment_id, body.get("time_slot_id"), body.get("room_id")))

            m = re.match(r"^/api/notifications/([0-9a-zA-Z]+)/read$", path)
            if m and method == "POST":
                conn.execute("UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?",
                             (m.group(1), user["id"]))
                conn.commit()
                return self._send(200, {"ok": True})
            if path == "/api/notifications/read-all" and method == "POST":
                conn.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (user["id"],))
                conn.commit()
                return self._send(200, {"ok": True})

            m = re.match(r"^/api/import/([a-z-]+)$", path)
            if m and method == "POST":
                body = self._json_body()
                return self._send(200, api.import_csv(conn, user, m.group(1), body.get("csv") or ""))

            m = re.match(r"^/api/reports/([a-z-]+)(\.csv)?$", path)
            if m and method == "GET":
                kind, csv_flag = m.group(1), m.group(2)
                if csv_flag:
                    text, filename = api.report_csv(conn, user, kind, query)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8")
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    data = text.encode("utf-8")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                return self._send(200, api.report(conn, user, kind, query))

            m = re.match(r"^/api/([a-z-]+)/([0-9a-zA-Z_]+)$", path)
            if m:
                resource, record_id = m.groups()
                if method == "GET":
                    return self._send(200, api.get_resource(conn, user, resource, record_id))
                if method in ("PUT", "PATCH"):
                    return self._send(200, api.update_resource(
                        conn, user, resource, record_id, self._json_body()))
                if method == "DELETE":
                    return self._send(200, api.delete_resource(conn, user, resource, record_id))

            m = re.match(r"^/api/([a-z-]+)$", path)
            if m:
                resource = m.group(1)
                if method == "GET":
                    return self._send(200, api.list_resource(conn, user, resource, query))
                if method == "POST":
                    return self._send(201, api.create_resource(
                        conn, user, resource, self._json_body()))

            raise auth.NotFound("Endpoint not found")
        except auth.Unauthorized as exc:
            self._send(401, {"error": str(exc)})
        except auth.Forbidden as exc:
            self._send(403, {"error": str(exc)})
        except auth.NotFound as exc:
            self._send(404, {"error": str(exc)})
        except auth.ValidationError as exc:
            self._send(422, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            traceback.print_exc()
            incident = record_incident(method, path, exc)
            self._send(500, {
                "error": "Unexpected server error. Check the server console for details.",
                "incident": incident,
                "kind": type(exc).__name__,
            })
        finally:
            conn.close()

    def _static(self, path):
        if path in ("/", "/index.html"):
            target = os.path.join(STATIC, "index.html")
        else:
            target = os.path.join(ROOT, path.lstrip("/"))
            if not os.path.abspath(target).startswith(ROOT):
                return self._send(403, {"error": "Forbidden"})
        if not os.path.isfile(target):
            return self._send(404, {"error": "Not found"})
        ext = os.path.splitext(target)[1].lower()
        with open(target, "rb") as handle:
            data = handle.read()
        self._send(200, None, CONTENT_TYPES.get(ext, "application/octet-stream"), raw=data)

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_PUT(self):
        self._dispatch("PUT")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_HEAD(self):
        self._dispatch("GET")


def main():
    port = int(os.environ.get("PORT") or 8000)
    db.init_db(seed=os.environ.get("EXAMFLOW_SEED", "1") != "0")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"ExamFlow AI running on http://localhost:{port}")
    print("Demo logins: admin@examflow.ai / Admin@123  ·  rita@examflow.ai / Examflow@123")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping ExamFlow AI.")


if __name__ == "__main__":
    main()
