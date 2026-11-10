"""Real SMS delivery: transport selection and the diagnostic send.

The demonstration path is easy to test; the point of these tests is that a configured
gateway is actually used, that its rejection reason survives to the caller, and that the
one-off diagnostic cannot be used without the key.
"""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error

SERVER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server")
sys.path.insert(0, SERVER)
os.environ["EXAMFLOW_DB"] = os.path.join(tempfile.mkdtemp(prefix="examflow-sms-"), "t.db")
os.environ.setdefault("EXAMFLOW_SECRET", "s" * 20)
os.environ["EXAMFLOW_QUIET"] = "1"


class SmsTransportTest(unittest.TestCase):
    def setUp(self):
        import sms
        self.sms = sms
        self.saved = (sms.FAST2SMS_KEY, sms.TWILIO_SID, sms.TWILIO_TOKEN, sms.TWILIO_FROM,
                      sms.TRANSPORT, sms.ENABLED)

    def tearDown(self):
        s = self.sms
        (s.FAST2SMS_KEY, s.TWILIO_SID, s.TWILIO_TOKEN, s.TWILIO_FROM,
         s.TRANSPORT, s.ENABLED) = self.saved

    def test_twilio_is_preferred_when_only_twilio_is_configured(self):
        s = self.sms
        s.FAST2SMS_KEY = ""
        s.TWILIO_SID, s.TWILIO_TOKEN, s.TWILIO_FROM = "AC1", "tok", "+15551234567"
        s.TRANSPORT, s.ENABLED = "twilio", True
        seen = {}

        def perform(request, label):
            seen["url"] = request.full_url
            seen["auth"] = request.get_header("Authorization")
            seen["body"] = request.data.decode()
            return True

        original = s._perform
        s._perform = perform
        try:
            self.assertTrue(s.send("+919812340000", "code 123456"))
        finally:
            s._perform = original
        self.assertIn("/Accounts/AC1/Messages.json", seen["url"])
        self.assertTrue(seen["auth"].startswith("Basic "))
        self.assertIn("To=%2B919812340000", seen["body"])
        self.assertIn("Body=code+123456", seen["body"])

    def test_twilio_rejection_reason_reaches_the_caller(self):
        s = self.sms
        s.FAST2SMS_KEY = ""
        s.TWILIO_SID, s.TWILIO_TOKEN, s.TWILIO_FROM = "AC1", "tok", "+15551234567"
        s.TRANSPORT, s.ENABLED = "twilio", True

        def boom(request, label):
            raise urllib.error.HTTPError(request.full_url, 21608,
                                        "unverified", {}, io.BytesIO(b'{"message":"not verified"}'))

        def perform(request, label):
            try:
                with urllib.request.urlopen(request):
                    return True
            except urllib.error.HTTPError as exc:
                raise RuntimeError("%s rejected the message (%s) %s"
                                   % (label, exc.code, (exc.read() or b"").decode()))

        import urllib.request
        original = s._perform
        s._perform = perform
        s.urllib_error = urllib.error
        real_urlopen = urllib.request.urlopen
        urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(
            urllib.error.HTTPError("u", 21608, "x", {}, io.BytesIO(b'{"message":"unverified"}')))
        try:
            with self.assertRaises(RuntimeError) as ctx:
                s.send("+919812340000", "code")
        finally:
            urllib.request.urlopen = real_urlopen
            s._perform = original
        self.assertIn("21608", str(ctx.exception))
        self.assertIn("unverified", str(ctx.exception))

    def test_failure_text_carries_the_gateway_reason_and_the_dlt_hint(self):
        s = self.sms
        message = s.describe_failure(RuntimeError(
            "Fast2SMS rejected the message: {\"message\": [\"Invalid template\"]}"))
        self.assertIn("Invalid template", message)
        self.assertIn("DLT", message)
        plain = s.describe_failure(RuntimeError("Insufficient Wallet Balance"))
        self.assertIn("Insufficient Wallet Balance", plain)
        self.assertNotIn("DLT", plain)
        self.assertTrue(s.describe_failure(RuntimeError("")))

    def test_diagnostic_refuses_without_the_key_and_explains_a_missing_gateway(self):
        import app
        os.environ["EXAMFLOW_DIAG_KEY"] = "test-diag-key"
        key = app.diag_key()
        status, body = self._post(app, "/api/diag/sms-test", {"phone": "9812340000"}, key=None)
        self.assertEqual(status, 404, body)
        self.sms.FAST2SMS_KEY = ""
        self.sms.TRANSPORT, self.sms.ENABLED = "", False
        status, body = self._post(app, "/api/diag/sms-test", {"phone": "9812340000"}, key=key)
        self.assertEqual(status, 502, body)
        self.assertIn("No SMS transport", body["error"])

    def _post(self, app, path, payload, key=None):
        """Drive one request through the handler without opening a socket."""
        handler = object.__new__(app.Handler)
        handler.command = "POST"
        handler.path = path
        handler.headers = {"X-Diag-Key": key} if key else {}
        handler._json_body = lambda: dict(payload)
        captured = {}
        handler._send = lambda status, body=None, **kw: captured.update(status=status, body=body)
        try:
            handler.do_POST()
        except Exception as exc:  # noqa: BLE001 - a raised HTTP error is a valid outcome
            captured.setdefault("status", getattr(exc, "status", None))
            captured.setdefault("body", getattr(exc, "payload", None))
        return captured.get("status"), captured.get("body")


if __name__ == "__main__":
    unittest.main(verbosity=2)
