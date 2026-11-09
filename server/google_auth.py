"""Google sign-in (OAuth 2.0 authorisation-code flow, standard library only).

Enabled when ``GOOGLE_CLIENT_ID`` and ``GOOGLE_CLIENT_SECRET`` are present. The
authorised redirect URI must be registered on the Google OAuth client and points at
``<site>/api/auth/google/callback``.
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

import auth

CLIENT_ID = (os.environ.get("GOOGLE_CLIENT_ID") or "").strip()
CLIENT_SECRET = (os.environ.get("GOOGLE_CLIENT_SECRET") or "").strip()
ENABLED = bool(CLIENT_ID and CLIENT_SECRET)
ADMIN_EMAILS = {e.strip().lower() for e in (os.environ.get("EXAMFLOW_GOOGLE_ADMIN_EMAILS") or "").split(",") if e.strip()}

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
STATE_TTL = 600


class GoogleAuthError(Exception):
    pass


def sign_state(redirect_uri):
    payload = {"n": secrets.token_urlsafe(10), "r": redirect_uri, "exp": int(time.time()) + STATE_TTL}
    body = auth._b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = auth._b64(hmac.new(auth.SECRET.encode(), body.encode(), hashlib.sha256).digest())
    return body + "." + signature


def read_state(state):
    try:
        body, signature = (state or "").split(".")
        expected = auth._b64(hmac.new(auth.SECRET.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(auth._unb64(body))
    except (ValueError, KeyError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


def authorize_url(redirect_uri, state):
    query = {
        "client_id": CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
        "include_granted_scopes": "true",
    }
    return AUTHORIZE_URL + "?" + urllib.parse.urlencode(query)


def _decode_id_token(id_token):
    try:
        segment = id_token.split(".")[1]
        padded = segment + "=" * (-len(segment) % 4)
        return json.loads(base64.urlsafe_b64decode(padded))
    except (IndexError, ValueError, json.JSONDecodeError):
        raise GoogleAuthError("Google returned an unreadable identity token.")


def exchange_code(code, redirect_uri):
    """Trade the authorisation code for tokens and return the verified profile."""
    if not ENABLED:
        raise GoogleAuthError("Google sign-in is not configured.")
    if not code:
        raise GoogleAuthError("Google did not return an authorisation code.")
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode()
    request = urllib.request.Request(TOKEN_URL, data=data, method="POST",
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            tokens = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise GoogleAuthError("Google rejected the sign-in (%s)." % detail)
    except urllib.error.URLError:
        raise GoogleAuthError("Could not reach Google to finish sign-in.")

    profile = _decode_id_token(tokens.get("id_token") or "")
    email = (profile.get("email") or "").strip().lower()
    if not email:
        raise GoogleAuthError("Google account has no email address.")
    if profile.get("email_verified") is False:
        raise GoogleAuthError("That Google email address is not verified.")
    return {"email": email,
            "name": profile.get("name") or email.split("@")[0],
            "picture": profile.get("picture"),
            "email_verified": bool(profile.get("email_verified", True))}


def role_for(email):
    return "Super Admin" if email in ADMIN_EMAILS else "Invigilator"
