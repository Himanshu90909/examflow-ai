"""ExamFlow AI HTTP server (Python standard library only).

Run:  python3 server/app.py  ->  http://localhost:8000
"""
import json
import os
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import db
import auth
import api
import solver_service

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml",
                 ".png": "image/png", ".jpg": "image/jpeg", ".ico": "image/x-icon",
                 ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    server_version = "ExamFlowAI/1.0"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- plumbing
    def log_message(self, fmt, *args):
        if os.environ.get("EXAMFLOW_QUIET") != "1":
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status, payload=None, content_type="application/json", raw=None):
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
        return auth.current_user(token)

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
            if method == "POST" and path == "/api/auth/login":
                body = self._json_body()
                user = auth.authenticate(body.get("email") or "", body.get("password") or "")
                db.audit(conn, user, "User login", "user", user["id"])
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

            m = re.match(r"^/api/([a-z-]+)/([0-9a-zA-Z]+)$", path)
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
        except auth.Forbidden as exc:
            self._send(403, {"error": str(exc)})
        except auth.NotFound as exc:
            self._send(404, {"error": str(exc)})
        except auth.ValidationError as exc:
            self._send(422, {"error": str(exc)})
        except Exception:  # noqa: BLE001
            traceback.print_exc()
            self._send(500, {"error": "Unexpected server error. Check the server console for details."})
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
