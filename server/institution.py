"""Identity of the university this deployment serves.

The scheduling engine is generic; everything a visitor reads on the sign-in screen and
the shell comes from here, so one deployment can be handed to a university without
touching the code. Values are environment-overridable, and ``public()`` is what the
browser is allowed to see.
"""
import os


def _env(key, default):
    return (os.environ.get(key) or "").strip() or default


PRODUCT = _env("EXAMFLOW_PRODUCT", "ExamFlow AI")
NAME = _env("EXAMFLOW_INSTITUTION", "Lovely Professional University")
SHORT = _env("EXAMFLOW_INSTITUTION_SHORT", "LPU")
OFFICE = _env("EXAMFLOW_EXAM_OFFICE", "Division of Examination")
ADDRESS = _env("EXAMFLOW_INSTITUTION_ADDRESS",
               "Jalandhar - Delhi G.T. Road, Phagwara, Punjab 144411")
PHONE = _env("EXAMFLOW_INSTITUTION_PHONE", "+91 1824 404404")
EMAIL = _env("EXAMFLOW_INSTITUTION_EMAIL", "examination.office@lpu.co.in")
TERM = _env("EXAMFLOW_TERM_NAME", "Term End Examination")
SESSION = _env("EXAMFLOW_SESSION", "2026-27")
THEME = _env("EXAMFLOW_THEME", "lpu")


def public():
    """The branding the browser may show. No secrets, no contact lists."""
    return {"product": PRODUCT, "name": NAME, "short": SHORT, "office": OFFICE,
            "address": ADDRESS, "phone": PHONE, "email": EMAIL, "term": TERM,
            "session": SESSION, "theme": THEME}


def title(suffix=""):
    """A document title in the university's terms, e.g. ``Examinations · LPU``."""
    head = ("%s · %s" % (suffix, SHORT)) if suffix else ("%s · %s" % (PRODUCT, SHORT))
    return head
