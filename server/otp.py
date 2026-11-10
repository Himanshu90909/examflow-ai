"""One-time sign-in codes delivered to a user's mailbox or phone.

The code itself never changes shape: six digits, hashed with a per-row salt, ten
minute lifetime, five attempts. Only the identifier channel differs, so email and
phone sign-in share the same storage, throttling and verification rules.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

CODE_TTL_MINUTES = 10
MAX_ATTEMPTS = 5
REQUEST_WINDOW_SECONDS = 60
REQUEST_HOURLY_CAP = 5

CHANNELS = {"email": "email", "phone": "phone"}


def _column(channel):
    try:
        return CHANNELS[channel]
    except KeyError:
        raise ValueError("unsupported sign-in channel: %r" % (channel,))


def _hash(code, salt):
    return hashlib.sha256((salt + ":" + code).encode()).hexdigest()


def _now():
    return datetime.utcnow()


def _iso(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def _recent(conn, channel, identifier, seconds):
    column = _column(channel)
    row = conn.execute(
        "SELECT created_at FROM login_codes WHERE %s = ? ORDER BY created_at DESC LIMIT 1" % column,
        (identifier,),
    ).fetchone()
    if not row:
        return False
    try:
        created = datetime.strptime(row["created_at"][:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:  # noqa: BLE001
        return False
    return (_now() - created).total_seconds() < seconds


def recent_request_blocked(conn, channel, identifier):
    """True when a code was issued for this identifier in the last minute."""
    return _recent(conn, channel, identifier, REQUEST_WINDOW_SECONDS)


def hourly_cap_reached(conn, channel, identifier):
    """True after REQUEST_HOURLY_CAP codes in the last hour. Keeps a public endpoint
    from turning into an SMS or mailbox cannon."""
    return _recent(conn, channel, identifier, 3600) and _count_since(
        conn, channel, identifier, 3600) >= REQUEST_HOURLY_CAP


def _count_since(conn, channel, identifier, seconds):
    column = _column(channel)
    cutoff = _iso(_now() - timedelta(seconds=seconds))
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM login_codes WHERE %s = ? AND created_at >= ?" % column,
        (identifier, cutoff),
    ).fetchone()
    return int(row["n"] if row else 0)


def issue(conn, channel, identifier, portal):
    column = _column(channel)
    code = "%06d" % secrets.randbelow(1000000)
    salt = secrets.token_hex(8)
    now = _now()
    conn.execute("DELETE FROM login_codes WHERE %s = ? AND consumed_at IS NULL" % column,
                 (identifier,))
    conn.execute(
        "INSERT INTO login_codes (id, email, phone, portal, code_hash, salt, attempts,"
        " expires_at, consumed_at, created_at) VALUES (?,?,?,?,?,?,0,?,NULL,?)",
        ("lc_" + secrets.token_hex(8),
         identifier if channel == "email" else "",
         identifier if channel == "phone" else "",
         portal or "", _hash(code, salt), salt,
         _iso(now + timedelta(minutes=CODE_TTL_MINUTES)), _iso(now)),
    )
    return code


def confirm(conn, channel, identifier, portal, code):
    column = _column(channel)
    row = conn.execute(
        "SELECT * FROM login_codes WHERE %s = ? AND consumed_at IS NULL"
        " ORDER BY created_at DESC LIMIT 1" % column,
        (identifier,),
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
