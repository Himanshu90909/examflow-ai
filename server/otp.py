"""One-time sign-in codes delivered to a user's mailbox."""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta

import db

CODE_TTL_MINUTES = 10
MAX_ATTEMPTS = 5
REQUEST_WINDOW_SECONDS = 60


def _hash(code, salt):
    return hashlib.sha256((salt + ":" + code).encode()).hexdigest()


def _now():
    return datetime.utcnow()


def _iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def recent_request_blocked(conn, email):
    row = conn.execute(
        "SELECT created_at FROM login_codes WHERE email = ? ORDER BY created_at DESC LIMIT 1",
        (email,),
    ).fetchone()
    if not row:
        return False
    try:
        created = datetime.strptime(row["created_at"][:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return False
    return (_now() - created).total_seconds() < REQUEST_WINDOW_SECONDS


def issue(conn, email, portal):
    code = "%06d" % secrets.randbelow(1000000)
    salt = secrets.token_hex(8)
    now = _now()
    conn.execute("DELETE FROM login_codes WHERE email = ? AND consumed_at IS NULL", (email,))
    conn.execute(
        "INSERT INTO login_codes (id, email, portal, code_hash, salt, attempts, expires_at, consumed_at, created_at)"
        " VALUES (?,?,?,?,?,0,?,NULL,?)",
        ("lc_" + secrets.token_hex(8), email, portal or "", _hash(code, salt), salt,
         _iso(now + timedelta(minutes=CODE_TTL_MINUTES)), _iso(now)),
    )
    return code


def confirm(conn, email, portal, code):
    row = conn.execute(
        "SELECT * FROM login_codes WHERE email = ? AND consumed_at IS NULL ORDER BY created_at DESC LIMIT 1",
        (email,),
    ).fetchone()
    if not row:
        return False, "Request a fresh sign-in code."
    if row["attempts"] >= MAX_ATTEMPTS:
        return False, "Too many attempts. Request a new code."
    if row["expires_at"] < _iso(_now()):
        return False, "That code has expired. Request a new one."
    if row["portal"] and portal and row["portal"] != portal:
        return False, "This code was requested for a different portal."
    if not hmac.compare_digest(row["code_hash"], _hash((code or "").strip(), row["salt"])):
        conn.execute("UPDATE login_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        conn.commit()
        return False, "That code is not correct."
    conn.execute("UPDATE login_codes SET consumed_at = ? WHERE id = ?", (_iso(_now()), row["id"]))
    return True, ""
