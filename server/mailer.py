"""Outbound email for sign-in codes.

Two transports, in order of preference:
  * RESEND_API_KEY  -> Resend HTTPS API (works on serverless hosts)
  * SMTP_HOST/USER/PASSWORD/FROM -> plain SMTP (e.g. a Gmail app password)

When neither is configured the app stays usable: request-code reports that
delivery is unavailable instead of pretending a code was sent.
"""

import json
import os
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage

RESEND_KEY = (os.environ.get("RESEND_API_KEY") or "").strip()
SMTP_HOST = (os.environ.get("SMTP_HOST") or "").strip()
if not SMTP_HOST and (os.environ.get("SMTP_USER") or "").lower().endswith(("@gmail.com", "@googlemail.com")):
    SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = int(os.environ.get("SMTP_PORT") or 587)
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASSWORD = (os.environ.get("SMTP_PASSWORD") or "").strip()
MAIL_FROM = (os.environ.get("EXAMFLOW_MAIL_FROM") or SMTP_USER or "ExamFlow AI <onboarding@resend.dev>").strip()

ENABLED = bool(RESEND_KEY or (SMTP_HOST and SMTP_USER and SMTP_PASSWORD))
TRANSPORT = "resend" if RESEND_KEY else ("smtp" if SMTP_HOST else "")


def send(to_address, subject, text, html=None):
    """Deliver one message. Raises RuntimeError when no transport is configured."""
    if not ENABLED:
        raise RuntimeError("No mail transport configured")
    if TRANSPORT == "resend":
        payload = {"from": MAIL_FROM, "to": [to_address], "subject": subject, "text": text}
        if html:
            payload["html"] = html
        request = urllib.request.Request(
            "https://api.resend.com/emails",
            data=json.dumps(payload).encode(),
            headers={"Authorization": "Bearer " + RESEND_KEY, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            response.read()
        return True

    message = EmailMessage()
    message["From"] = MAIL_FROM
    message["To"] = to_address
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    context = ssl.create_default_context()
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=25) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=25) as server:
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    return True
