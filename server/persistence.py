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


def save_now():
    """Commit the current database file to the snapshot repository (no-op when the
    bytes have not changed or persistence is not configured)."""
    global _last_digest
    if not ENABLED:
        return False
    with _lock:
        try:
            payload = _snapshot_bytes()
        except (sqlite3.Error, OSError):
            return False
        if not payload:
            return False
        digest = hashlib.sha256(payload).hexdigest()
        if digest == _last_digest:
            return False
        try:
            current = _api("/repos/%s/contents/%s?ref=%s" % (REPO, SNAPSHOT_PATH, BRANCH))
            sha = current.get("sha")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                return False
            sha = None
        except urllib.error.URLError:
            return False
        body = {"message": "ExamFlow data snapshot", "branch": BRANCH,
                "content": base64.b64encode(payload).decode("ascii")}
        if sha:
            body["sha"] = sha
        try:
            _api("/repos/%s/contents/%s" % (REPO, SNAPSHOT_PATH), "PUT", body)
        except (urllib.error.URLError, urllib.error.HTTPError):
            return False
        _last_digest = digest
        return True
