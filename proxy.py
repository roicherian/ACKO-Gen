#!/usr/bin/env python3
"""
Local CORS proxy for ACKO Image Generator.
Relays browser requests → api.magnific.com, adding CORS headers.
Also gates access behind a simple @acko.tech email login.
Run: python3 proxy.py
Then open generate.html in any browser.
"""
import json
import time
import hmac
import base64
import hashlib
import secrets
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
import os

PORT = 3458
MAGNIFIC_BASE = "https://api.magnific.com"
HTML_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HTML_DIR, ".env")


def load_env_file(path):
    """Minimal .env parser (stdlib only) — sets os.environ from KEY=VALUE lines,
    without overriding anything already set in the real environment."""
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key, value = key.strip(), value.strip()
                if key and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass


load_env_file(ENV_FILE)
MAGNIFIC_KEY = os.environ.get("MAGNIFIC_KEY", "")

# sheets_store reads GOOGLE_* env vars at import time, so it must be imported only
# after .env has been loaded into os.environ above.
import sheets_store

ALLOWED_EMAIL_DOMAIN = "acko.tech"
SESSION_TTL_SECONDS = 12 * 60 * 60  # 12 hours
SESSION_SECRET_FILE = os.path.join(HTML_DIR, ".session_secret")

# Permission checks are delegated to sheets_store, which talks to the Google Sheet
# directly via a service account and keeps its own refreshed in-process cache.
get_permissions = sheets_store.get_permissions
record_pending_request = sheets_store.record_pending_request


def get_allowed_emails():
    """Back-compat helper — just the approved set."""
    approved, _denied = get_permissions()
    return approved


def get_session_secret():
    """Load a persistent random secret for signing sessions, creating it on first run."""
    try:
        with open(SESSION_SECRET_FILE, "r") as f:
            secret = f.read().strip()
            if secret:
                return secret
    except FileNotFoundError:
        pass
    secret = secrets.token_hex(32)
    with open(SESSION_SECRET_FILE, "w") as f:
        f.write(secret)
    return secret


SESSION_SECRET = get_session_secret()


def make_session(email):
    payload = json.dumps({"email": email, "exp": int(time.time()) + SESSION_TTL_SECONDS}).encode()
    payload_b64 = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    sig = hmac.new(SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{sig}"


def verify_session(token):
    """Returns (True, email) if the session token is valid and unexpired, else (False, None)."""
    if not token or "." not in token:
        return False, None
    payload_b64, sig = token.rsplit(".", 1)
    expected_sig = hmac.new(SESSION_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return False, None
    try:
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except Exception:
        return False, None
    if payload.get("exp", 0) < time.time():
        return False, None
    email = payload.get("email", "").lower()
    if not email.endswith("@" + ALLOWED_EMAIL_DOMAIN):
        return False, None
    if email not in get_allowed_emails():
        return False, None
    return True, email


def route(path):
    """Map /api/<provider>/... to (upstream_url, provider)."""
    if path.startswith("/api/magnific/"):
        return MAGNIFIC_BASE + path[len("/api/magnific"):], "magnific"
    return None, None


def upstream_headers(provider, incoming_headers):
    # Preserve the client's Content-Type (e.g. multipart/form-data; boundary=... for
    # image edit uploads) instead of forcing JSON, so multipart bodies parse correctly upstream.
    content_type = incoming_headers.get("Content-Type", "application/json")
    if provider == "magnific":
        # The real key lives only here, loaded from .env — the browser never sees it and
        # any client-supplied x-magnific-api-key header is ignored, not trusted.
        return {"Content-Type": content_type, "x-magnific-api-key": MAGNIFIC_KEY}
    return {"Content-Type": "application/json"}


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {args[0]} {args[1]}")

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-session-token")

    def send_json(self, status, obj):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors()
        self.end_headers()

    def do_GET(self):
        # Serve generate.html directly
        if self.path == "/" or self.path == "/generate.html":
            try:
                with open(os.path.join(HTML_DIR, "generate.html"), "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", len(body))
                self.send_cors()
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
            return

        # Session check — lets the frontend confirm a stored session is still valid
        if self.path == "/auth/session":
            ok, email = verify_session(self.headers.get("x-session-token", ""))
            self.send_json(200, {"valid": ok, "email": email})
            return

        # Proxy GET (used for Magnific's async polling endpoint) — requires a valid session
        if self.path.startswith("/api/"):
            ok, _email = verify_session(self.headers.get("x-session-token", ""))
            if not ok:
                self.send_json(401, {"error": "Not signed in. Please sign in with your acko.tech email."})
                return
            target, provider = route(self.path)
            if not target:
                self.send_response(404)
                self.end_headers()
                return
            req = urllib.request.Request(target, headers=upstream_headers(provider, self.headers), method="GET")
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    body = r.read()
                self.send_response(r.status)
                self.send_header("Content-Type", "application/json")
                self.send_cors()
                self.end_headers()
                self.wfile.write(body)
            except urllib.error.HTTPError as e:
                body = e.read()
                self.send_response(e.code)
                self.send_header("Content-Type", "application/json")
                self.send_cors()
                self.end_headers()
                self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        # Login — validates the email domain and issues a signed session token
        if self.path == "/auth/login":
            length = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self.send_json(400, {"error": "Invalid request body."})
                return
            email = str(data.get("email", "")).strip().lower()
            if "@" not in email or not email.endswith("@" + ALLOWED_EMAIL_DOMAIN):
                self.send_json(403, {"error": f"Access is limited to @{ALLOWED_EMAIL_DOMAIN} email addresses."})
                return
            approved, denied = get_permissions()
            if email in denied:
                self.send_json(403, {
                    "error": "Your access request was declined by Roy Cherian.",
                    "denied": True,
                })
                return
            if email not in approved:
                record_pending_request(email)
                self.send_json(403, {
                    "error": "Your request has been sent to Roy Cherian for approval.",
                    "pending": True,
                })
                return
            token = make_session(email)
            self.send_json(200, {"token": token, "email": email, "expiresIn": SESSION_TTL_SECONDS})
            return

        target, provider = route(self.path)
        if not target:
            self.send_response(404)
            self.end_headers()
            return

        ok, _email = verify_session(self.headers.get("x-session-token", ""))
        if not ok:
            self.send_json(401, {"error": "Not signed in. Please sign in with your acko.tech email."})
            return

        length = int(self.headers.get("Content-Length", 0))
        body_in = self.rfile.read(length)

        req = urllib.request.Request(target, data=body_in, headers=upstream_headers(provider, self.headers), method="POST")

        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                body_out = r.read()
            self.send_response(r.status)
            self.send_header("Content-Type", "application/json")
            self.send_cors()
            self.end_headers()
            self.wfile.write(body_out)
        except urllib.error.HTTPError as e:
            body_out = e.read()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_cors()
            self.end_headers()
            self.wfile.write(body_out)
        except Exception as ex:
            msg = json.dumps({"error": str(ex)}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_cors()
            self.end_headers()
            self.wfile.write(msg)


if __name__ == "__main__":
    server = HTTPServer(("localhost", PORT), ProxyHandler)
    print(f"\n  ACKO Image Generator proxy running")
    print(f"  Open in browser → http://localhost:{PORT}/generate.html\n")
    if not MAGNIFIC_KEY:
        print("  WARNING: MAGNIFIC_KEY is not set in .env — image generation will fail with a 401/403 until it is.\n")
    sheets_store.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
