"""Durable storage for the SQLite database on an ephemeral host (Vercel).

Vercel gives every function instance a throw-away ``/tmp``, so a plain SQLite file
would reset on each cold start. When ``EXAMFLOW_SNAPSHOT_REPO`` and
``EXAMFLOW_GITHUB_TOKEN`` are configured, ExamFlow keeps the database file in the
project's GitHub repository:

* cold start  -> restore ``data/examflow.db.gz`` into the local database path
* every write -> gzip the (consistently backed-up) database and commit it back

This keeps the application dependency-free and works without a hosted database
account. It is a single-writer snapshot store: two instances that write at the
exact same moment keep the last commit, which is fine for a demonstration build
and is replaced by a managed Postgres instance for real deployments.
"""
import base64
import gzip
import hashlib
import io
import json
import os
import sqlite3
import threading
import urllib.error
import urllib.request

REPO = (os.environ.get("EXAMFLOW_SNAPSHOT_REPO") or "").strip()
TOKEN = (os.environ.get("EXAMFLOW_GITHUB_TOKEN") or "").strip()
SNAPSHOT_PATH = (os.environ.get("EXAMFLOW_SNAPSHOT_PATH") or "data/examflow.db.gz").strip()
BRANCH = (os.environ.get("EXAMFLOW_SNAPSHOT_BRANCH") or "main").strip()
ENABLED = bool(REPO and TOKEN)

DB_PATH = os.environ.get("EXAMFLOW_DB") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examflow.db")

_lock = threading.RLock()
_restored = False
_last_digest = None
LAST_SAVE = {"at": None, "ok": None, "error": None, "saved": 0}


class SnapshotError(Exception):
    pass


def _api(path, method="GET", payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        "https://api.github.com" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + TOKEN,
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json",
                 "User-Agent": "ExamFlowAI"})
    with urllib.request.urlopen(request, timeout=25) as response:
        return json.loads(response.read() or b"{}")


def _gzip_bytes(raw):
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as handle:
        handle.write(raw)
    return buffer.getvalue()


def _snapshot_bytes():
    """Read the database through the sqlite backup API so a concurrent writer cannot
    hand us a half-written file."""
    handle, temp_path = None, None
    try:
        if not os.path.exists(DB_PATH):
            return None
        temp_path = DB_PATH + ".snapshot"
        source = sqlite3.connect(DB_PATH, timeout=10)
        target = sqlite3.connect(temp_path)
        with target:
            source.backup(target)
        source.close()
        target.close()
        with open(temp_path, "rb") as fh:
            return _gzip_bytes(fh.read())
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def ensure_restored():
    """Restore the last committed snapshot when this instance has no database yet."""
    global _restored, _last_digest
    if not ENABLED or _restored:
        return False
    with _lock:
        if _restored:
            return False
        _restored = True
        if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
            return False
        try:
            blob = _api("/repos/%s/contents/%s?ref=%s" % (REPO, SNAPSHOT_PATH, BRANCH))
            payload = base64.b64decode(blob.get("content") or "")
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, SnapshotError):
            return False
        try:
            raw = gzip.decompress(payload)
        except OSError:
            return False
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        with open(DB_PATH, "wb") as fh:
            fh.write(raw)
        _last_digest = hashlib.sha256(payload).hexdigest()
        return True


_USER_CACHE = {}
_USER_CACHE_TTL = 15.0


def fetch_user(user_id):
    """Read one user row from the latest committed snapshot.

    Instances each keep a private copy of the database, so a session issued while one
    instance was signing a user in can reach another instance that has not restored
    that row yet. Rather than dropping the session, pull the row out of the snapshot
    the sign-in instance already committed.
    """
    if not ENABLED or not user_id:
        return None
    import time as _time
    cached = _USER_CACHE.get(user_id)
    if cached and (_time.time() - cached[0]) < _USER_CACHE_TTL:
        return cached[1]
    row = None
    try:
        blob = _api("/repos/%s/contents/%s?ref=%s" % (REPO, SNAPSHOT_PATH, BRANCH))
        raw = gzip.decompress(base64.b64decode(blob.get("content") or ""))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError,
            OSError, SnapshotError):
        return None
    temp_path = DB_PATH + ".lookup"
    try:
        with open(temp_path, "wb") as handle:
            handle.write(raw)
        source = sqlite3.connect(temp_path, timeout=10)
        source.row_factory = sqlite3.Row
        try:
            found = source.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            row = dict(found) if found else None
        finally:
            source.close()
    except (sqlite3.Error, OSError):
        row = None
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    _USER_CACHE[user_id] = (_time.time(), row)
    return row


def _note_save(ok, error):
    import time as _time
    LAST_SAVE["at"] = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
    LAST_SAVE["ok"] = ok
    LAST_SAVE["error"] = error
    if ok:
        LAST_SAVE["saved"] = LAST_SAVE.get("saved", 0) + 1


def status():
    """Whether writes are being persisted, and how the last attempt went."""
    return {
        "enabled": ENABLED,
        "repo": REPO or None,
        "branch": BRANCH if ENABLED else None,
        "path": SNAPSHOT_PATH if ENABLED else None,
        "restored": _restored,
        "last_save": dict(LAST_SAVE),
    }

def save_now():
    """Commit the current database file to the snapshot repository (no-op when the
    bytes have not changed or persistence is not configured)."""
    global _last_digest
    if not ENABLED:
        return False
    with _lock:
        try:
            payload = _snapshot_bytes()
        except (sqlite3.Error, OSError) as exc:
            _note_save(False, "snapshot read failed: %s" % exc)
            return False
        if not payload:
            _note_save(False, "database file is empty")
            return False
        digest = hashlib.sha256(payload).hexdigest()
        if digest == _last_digest:
            return False
        try:
            current = _api("/repos/%s/contents/%s?ref=%s" % (REPO, SNAPSHOT_PATH, BRANCH))
            sha = current.get("sha")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                _note_save(False, "cannot read current snapshot: HTTP %s" % exc.code)
                return False
            sha = None
        except urllib.error.URLError as exc:
            _note_save(False, "cannot reach GitHub: %s" % exc)
            return False
        body = {"message": "ExamFlow data snapshot", "branch": BRANCH,
                "content": base64.b64encode(payload).decode("ascii")}
        if sha:
            body["sha"] = sha
        try:
            _api("/repos/%s/contents/%s" % (REPO, SNAPSHOT_PATH), "PUT", body)
        except urllib.error.HTTPError as exc:
            _note_save(False, "snapshot commit rejected: HTTP %s %s"
                       % (exc.code, (exc.read() or b"").decode("utf-8", "replace")[:160]))
            return False
        except urllib.error.URLError as exc:
            _note_save(False, "cannot reach GitHub: %s" % exc)
            return False
        _last_digest = digest
        _note_save(True, None)
        return True
