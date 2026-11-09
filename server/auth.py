"""Authentication, sessions and role-based access control.

Passwords: PBKDF2-HMAC-SHA256 with a per-user salt (stdlib only).
Sessions: signed bearer tokens (HMAC-SHA256) with an expiry, no external deps.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time

import db

SECRET = os.environ.get("EXAMFLOW_SECRET", "examflow-dev-secret-change-in-production")
TOKEN_TTL_SECONDS = 12 * 60 * 60

ROLES = ("Super Admin", "School Admin", "Invigilator", "Student")

PERMISSIONS = {
    "schools": (("Super Admin", "School Admin"), ("Super Admin",)),
    "departments": (("Super Admin", "School Admin"), ("Super Admin", "School Admin")),
    "student-groups": (("Super Admin", "School Admin"), ("Super Admin", "School Admin")),
    "examinations": (("Super Admin", "School Admin"), ("Super Admin", "School Admin")),
    "rooms": (("Super Admin", "School Admin"), ("Super Admin", "School Admin")),
    "invigilators": (("Super Admin", "School Admin"), ("Super Admin", "School Admin")),
    "availability": (("Super Admin", "School Admin", "Invigilator"), ("Super Admin", "School Admin", "Invigilator")),
    "time-slots": (("Super Admin", "School Admin"), ("Super Admin", "School Admin")),
    "policies": (("Super Admin", "School Admin"), ("Super Admin", "School Admin")),
    "users": (("Super Admin",), ("Super Admin",)),
    "audit-logs": (("Super Admin", "School Admin"), ()),
    "conflicts": (("Super Admin", "School Admin"), ("Super Admin", "School Admin")),
    "runs": (("Super Admin", "School Admin", "Invigilator"), ("Super Admin", "School Admin")),
    "notifications": (("Super Admin", "School Admin", "Invigilator", "Student"),
                      ("Super Admin", "School Admin", "Invigilator")),
    "my-exams": (("Student",), ()),
}


def hash_password(password: str, salt: str = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2_sha256$120000${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, AttributeError):
        return False


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_token(user: dict) -> str:
    payload = {"sub": user["id"], "role": user["role"], "exp": int(time.time()) + TOKEN_TTL_SECONDS}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_token(token: str):
    try:
        body, sig = token.split(".")
        expected = _b64(hmac.new(SECRET.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_unb64(body))
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def authenticate(email: str, password: str):
    conn = db.connect()
    row = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (email.strip().lower(),)).fetchone()
    conn.close()
    if not row or not row["is_active"]:
        return None
    if not verify_password(password, row["password_hash"]):
        return None
    user = dict(row)
    user.pop("password_hash", None)
    user["is_active"] = bool(user["is_active"])
    return user


def find_user(email: str):
    """Active user lookup by email, without a password check (used by code sign-in)."""
    conn = db.connect()
    row = conn.execute("SELECT * FROM users WHERE lower(email) = ?", (email.strip().lower(),)).fetchone()
    conn.close()
    if not row or not row["is_active"]:
        return None
    user = dict(row)
    user.pop("password_hash", None)
    user["is_active"] = True
    return user


PORTAL_DEFAULT_ROLE = {"admin": "School Admin", "user": "Invigilator", "student": "Student"}


def provision_gmail_account(conn, email, password, portal, full_name=None):
    """Create a self-service account for an email address on first sign-in.

    The portal decides the starting role; new accounts are bound to the primary
    school so the dashboards open with real (seeded) data instead of a blank shell.
    """
    import db as _db  # local import keeps the module importable in script mode

    role = PORTAL_DEFAULT_ROLE.get(portal or "student", "Student")
    school = conn.execute("SELECT id FROM schools ORDER BY created_at LIMIT 1").fetchone()
    school_id = school["id"] if school else None
    name = (full_name or "").strip()
    if not name:
        handle = email.split("@")[0].replace(".", " ").replace("_", " ").strip()
        name = " ".join(part.capitalize() for part in handle.split()) or email

    user_id = "usr_" + secrets.token_hex(8)
    conn.execute(
        "INSERT INTO users (id, full_name, email, password_hash, role, school_id, department_id,"
        " is_active, created_at) VALUES (?,?,?,?,?,?,NULL,1,?)",
        (user_id, name, email.strip().lower(), hash_password(password), role, school_id, _db.now_iso()),
    )
    group_id = None
    if role == "Student" and school_id:
        group = conn.execute(
            "SELECT id FROM student_groups WHERE school_id = ? ORDER BY created_at LIMIT 1",
            (school_id,),
        ).fetchone()
        group_id = group["id"] if group else None
        if group_id:
            conn.execute("UPDATE users SET student_group_id = ? WHERE id = ?", (group_id, user_id))
    conn.commit()
    return find_user(email)


def current_user(token: str):
    payload = read_token(token or "")
    if not payload:
        return None
    conn = db.connect()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (payload["sub"],)).fetchone()
    conn.close()
    if not row or not row["is_active"]:
        return None
    user = dict(row)
    user.pop("password_hash", None)
    user["is_active"] = bool(user["is_active"])
    return user


def can_read(user: dict, resource: str) -> bool:
    read_roles, _ = PERMISSIONS.get(resource, (("Super Admin",), ()))
    return user["role"] in read_roles


def can_write(user: dict, resource: str) -> bool:
    _, write_roles = PERMISSIONS.get(resource, ((), ("Super Admin",)))
    return user["role"] in write_roles


class Unauthorized(Exception):
    pass


class Forbidden(Exception):
    pass


class NotFound(Exception):
    pass


class ValidationError(Exception):
    pass


def assert_school_access(user: dict, school_id: str):
    if user["role"] == "Super Admin":
        return
    if not school_id or school_id != user.get("school_id"):
        raise Forbidden("You may only access your own school's data.")
