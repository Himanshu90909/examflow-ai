"""Outbound SMS for phone-number sign-in codes.

Two transports, in order of preference:

  * FAST2SMS_API_KEY -> Fast2SMS bulk/quick route (India, DLT-registered sender)
  * TWILIO_ACCOUNT_SID + TWILIO_AUTH_TOKEN + TWILIO_FROM -> Twilio Messages API

``EXAMFLOW_SMS_DEMO=1`` runs a demonstration without any gateway: the requested
code is handed back to the sign-in page so a reviewer can finish the flow. It is
off unless that variable is set, and it must never be set on a real deployment.

Numbers are stored in E.164 form (``+919000000001``). ``EXAMFLOW_PHONE_COUNTRY``
sets the country code assumed for bare national numbers (default ``91``).
"""

import base64
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

FAST2SMS_KEY = (os.environ.get("FAST2SMS_API_KEY") or "").strip()
FAST2SMS_ROUTE = (os.environ.get("EXAMFLOW_FAST2SMS_ROUTE") or "q").strip()

TWILIO_SID = (os.environ.get("TWILIO_ACCOUNT_SID") or "").strip()
TWILIO_TOKEN = (os.environ.get("TWILIO_AUTH_TOKEN") or "").strip()
TWILIO_FROM = (os.environ.get("TWILIO_FROM") or "").strip()

COUNTRY_CODE = re.sub(r"\D", "", os.environ.get("EXAMFLOW_PHONE_COUNTRY") or "91") or "91"

DEMO = (os.environ.get("EXAMFLOW_SMS_DEMO") or "").strip().lower() in ("1", "true", "yes", "on")

TRANSPORT = "fast2sms" if FAST2SMS_KEY else ("twilio" if (TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM) else "")
ENABLED = bool(TRANSPORT)


def available():
    """True when phone sign-in can complete: a gateway is wired up or the demo is on."""
    return ENABLED or DEMO


def normalize(value):
    """Return ``+<country code><national number>`` for the entered value.

    Accepts ``+91 90000 00001``, ``0919000000001``, ``919000000001`` and a bare
    national number such as ``9000000001``. Raises ValueError for anything that
    cannot be a real number.
    """
    raw = (value or "").strip()
    if raw.startswith("00"):
        raw = raw[2:]
    digits = re.sub(r"\D", "", raw)
    if not digits:
        raise ValueError("Enter your phone number with the country code.")
    if len(digits) <= 11 and COUNTRY_CODE and not digits.startswith(COUNTRY_CODE):
        if digits.startswith("0"):
            digits = digits[1:]
        digits = COUNTRY_CODE + digits
    elif digits.startswith("0") and len(digits) > 10:
        digits = digits[1:]
    if not 8 <= len(digits) <= 15:
        raise ValueError("That does not look like a phone number.")
    return "+" + digits


def display(number):
    """Group a stored E.164 number for reading: +91 90000 00001."""
    digits = re.sub(r"\D", "", number or "")
    if digits.startswith(COUNTRY_CODE) and len(digits) == len(COUNTRY_CODE) + 10:
        national = digits[len(COUNTRY_CODE):]
        return "+%s %s %s" % (COUNTRY_CODE, national[:5], national[5:])
    return "+" + digits if digits else ""


def send(number, text):
    """Deliver one SMS. Raises RuntimeError when no transport is configured or the
    gateway rejects the message."""
    if TRANSPORT == "fast2sms":
        return _fast2sms(number, text)
    if TRANSPORT == "twilio":
        return _twilio(number, text)
    raise RuntimeError("No SMS transport configured")


def _fast2sms(number, text):
    payload = {"route": FAST2SMS_ROUTE, "message": text[:900],
               "numbers": re.sub(r"\D", "", number), "flash": 0}
    request = urllib.request.Request(
        "https://www.fast2sms.com/dev/bulkV2",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"authorization": FAST2SMS_KEY, "Content-Type": "application/json",
                 "User-Agent": "ExamFlowAI"})
    return _perform(request, "Fast2SMS")


def _twilio(number, text):
    body = urllib.parse.urlencode({"To": number, "From": TWILIO_FROM, "Body": text[:900]}).encode()
    credentials = base64.b64encode(("%s:%s" % (TWILIO_SID, TWILIO_TOKEN)).encode()).decode()
    request = urllib.request.Request(
        "https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json" % TWILIO_SID,
        data=body, method="POST",
        headers={"Authorization": "Basic " + credentials,
                 "Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": "ExamFlowAI"})
    return _perform(request, "Twilio")


def _perform(request, label):
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", "replace")[:300]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError("%s rejected the message (%s) %s" % (label, exc.code, detail))
    except (urllib.error.URLError, ValueError) as exc:
        raise RuntimeError("%s could not be reached: %s" % (label, exc))
    if payload.get("return") is False or payload.get("status") == "failure" or payload.get("error"):
        raise RuntimeError("%s rejected the message: %s" % (label, json.dumps(payload)[:300]))
    return True
