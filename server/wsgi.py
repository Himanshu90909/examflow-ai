"""WSGI adapter so the existing BaseHTTPRequestHandler app can run on serverless
platforms (Vercel) that expect a WSGI callable instead of a socket server.

The handler is instantiated without a real socket: request bytes are fed in
through an in-memory rfile and the response is read back from an in-memory
wfile. No routing logic is duplicated here.
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import Handler  # noqa: E402


class _FakeServer:
    server_name = "examflow"
    server_port = 443
    server_version = "ExamFlowAI/1.0"
    sys_version = ""


def _build_environ_body(environ):
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except (TypeError, ValueError):
        length = 0
    stream = environ.get("wsgi.input")
    return stream.read(length) if (stream and length) else b""


def _raw_request(environ, body):
    method = (environ.get("REQUEST_METHOD") or "GET").upper()
    path = environ.get("PATH_INFO") or "/"
    query = environ.get("QUERY_STRING") or ""
    if query:
        path = f"{path}?{query}"
    lines = [f"{method} {path} HTTP/1.1"]
    for key, value in environ.items():
        if key.startswith("HTTP_"):
            lines.append(f"{key[5:].replace('_', '-').title()}: {value}")
    if body:
        lines.append(f"Content-Length: {len(body)}")
    lines.append("Host: " + (environ.get("HTTP_HOST") or "localhost"))
    head = "\r\n".join(lines).encode("latin-1") + b"\r\n\r\n"
    return head + body


def _split_response(raw):
    if b"\r\n\r\n" not in raw:
        return "500 Internal Server Error", [], raw
    head, body = raw.split(b"\r\n\r\n", 1)
    lines = head.decode("latin-1").split("\r\n")
    status_line = lines[0]
    parts = status_line.split(" ", 2)
    status = f"{parts[1]} {parts[2]}" if len(parts) > 2 else "500 Internal Server Error"
    headers = []
    for line in lines[1:]:
        if ":" in line:
            name, value = line.split(":", 1)
            headers.append((name.strip(), value.strip()))
    return status, headers, body


def application(environ, start_response):
    """WSGI entry point."""
    body = _build_environ_body(environ)
    raw = _raw_request(environ, body)

    handler = Handler.__new__(Handler)
    handler.rfile = io.BytesIO(raw)
    handler.wfile = io.BytesIO()
    handler.client_address = (environ.get("REMOTE_ADDR") or "127.0.0.1", 0)
    handler.server = _FakeServer()
    handler.close_connection = True
    handler.command = (environ.get("REQUEST_METHOD") or "GET").upper()
    handler.request_version = "HTTP/1.1"
    handler.requestline = ""
    handler.path = ""
    handler.headers = None

    try:
        handler.handle_one_request()
        status, headers, payload = _split_response(handler.wfile.getvalue())
    except Exception:  # never leak a stack trace to the client
        import traceback
        traceback.print_exc()
        status, headers, payload = (
            "500 Internal Server Error",
            [("Content-Type", "application/json"), ("Cache-Control", "no-store")],
            b'{"error": "Internal server error"}',
        )

    start_response(status, headers)
    return [payload]
