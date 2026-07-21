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

import user_store

PORT = int(os.environ.get("PORT", 3458))
MAGNIFIC_BASE = "https://api.magnific.com"
HTML_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HTML_DIR, ".env")
# On a real host, point this at a persistent volume/disk (e.g. Render's mounted
# disk path) so the user DB and session secret survive restarts/redeploys.
# Defaults to living alongside the code, which is fine for local dev.
DATA_DIR = os.environ.get("DATA_DIR", HTML_DIR)
os.makedirs(DATA_DIR, exist_ok=True)


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

ALLOWED_EMAIL_DOMAIN = "acko.tech"
SESSION_TTL_SECONDS = 12 * 60 * 60  # 12 hours
SESSION_SECRET_FILE = os.path.join(DATA_DIR, ".session_secret")

user_store.init_db()
_bootstrap_admin_emails = [e for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()]
if _bootstrap_admin_emails:
    user_store.bootstrap_admins(_bootstrap_admin_emails)


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
    """Returns (True, email) if the session token is valid and unexpired, else (False, None).
    This only proves identity (a signed-in acko.tech email) — it says nothing about what
    that user is allowed to do. Permission level is looked up fresh, per gated action, via
    require_permission() below, never cached in or trusted from the token itself."""
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
    return True, email


def require_permission(email, allowed_levels):
    """Checks a signed-in user's current permission against a gated feature's allowed
    set. Returns (ok, error_response_dict_or_None). Marks the user pending (only from
    'No access', idempotently) when they're blocked for lack of any grant at all."""
    permission = user_store.get_permission(email)
    if permission in allowed_levels:
        return True, None
    if permission == "No access":
        user_store.mark_pending(email)
        return False, {"error": "Your request has been sent for admin approval.", "pending": True}
    return False, {"error": f"Your current access level ({permission}) doesn't include this feature."}


def require_admin(token):
    """Returns (True, email) if the token is valid AND that user is an Admin, else (False, None)."""
    ok, email = verify_session(token)
    if not ok:
        return False, None
    if user_store.get_permission(email) != "Admin":
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
        try:
            self._do_GET_inner()
        except Exception as e:
            # Last-resort safety net: whatever broke, make sure this request gets
            # SOME response instead of hanging (which is what made the proxy look
            # "unreachable" from the browser even though the process was alive).
            print(f"  ERROR handling GET {self.path}: {e}")
            try:
                self.send_response(500)
                self.end_headers()
            except Exception:
                pass

    def _do_GET_inner(self):
        # Serve generate.html directly. "/generate.html?x=y" (any query string) should
        # still match — strip it before comparing, otherwise a cache-busting query
        # param would silently 404 instead of serving the page.
        path_no_query = self.path.split("?", 1)[0]
        if path_no_query == "/" or path_no_query == "/generate.html":
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

        # Session check — lets the frontend confirm a stored session is still valid,
        # and always returns the user's current (live, never cached) permission level.
        if self.path == "/auth/session":
            ok, email = verify_session(self.headers.get("x-session-token", ""))
            permission = user_store.get_permission(email) if ok else None
            self.send_json(200, {"valid": ok, "email": email, "permission": permission})
            return

        # Admin-only: list users whose access request is awaiting a decision.
        if self.path == "/admin/pending":
            ok, _email = require_admin(self.headers.get("x-session-token", ""))
            if not ok:
                self.send_json(403, {"error": "Admin access required."})
                return
            self.send_json(200, {"pending": user_store.list_pending()})
            return

        # Admin-only: the full user list, for the permission-management table.
        if self.path == "/admin/users":
            ok, _email = require_admin(self.headers.get("x-session-token", ""))
            if not ok:
                self.send_json(403, {"error": "Admin access required."})
                return
            self.send_json(200, {"users": user_store.list_all_users()})
            return

        # Proxy GET (used for Magnific's async polling endpoint) — requires a valid
        # session AND a permission level allowed to use the image generator.
        if self.path.startswith("/api/"):
            ok, email = verify_session(self.headers.get("x-session-token", ""))
            if not ok:
                self.send_json(401, {"error": "Not signed in. Please sign in with your acko.tech email."})
                return
            perm_ok, perm_err = require_permission(email, user_store.IMAGE_GEN_ALLOWED)
            if not perm_ok:
                self.send_json(403, perm_err)
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
            except Exception as ex:
                # Network blip, DNS hiccup, timeout, etc. reaching Magnific —
                # tell the client cleanly instead of leaving the request hanging.
                self.send_json(502, {"error": f"Upstream request failed: {ex}"})
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        try:
            self._do_POST_inner()
        except Exception as e:
            print(f"  ERROR handling POST {self.path}: {e}")
            try:
                self.send_response(500)
                self.end_headers()
            except Exception:
                pass

    def _do_POST_inner(self):
        # Login — validates the email domain and issues a signed session token.
        # Login only proves identity now; it always succeeds for a valid acko.tech
        # address (creating a 'No access' user record on first sight). Whether that
        # user can actually do anything is decided per gated feature, not here.
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
            user = user_store.get_or_create_user(email)
            token = make_session(email)
            self.send_json(200, {
                "token": token, "email": email, "expiresIn": SESSION_TTL_SECONDS,
                "permission": user["permission"],
            })
            return

        # Admin-only: change a user's permission level.
        if self.path == "/admin/users/update":
            ok, admin_email = require_admin(self.headers.get("x-session-token", ""))
            if not ok:
                self.send_json(403, {"error": "Admin access required."})
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self.send_json(400, {"error": "Invalid request body."})
                return
            target_email = str(data.get("email", "")).strip().lower()
            new_permission = str(data.get("permission", "")).strip()
            try:
                updated = user_store.set_permission(target_email, new_permission, granted_by=admin_email)
            except ValueError as e:
                self.send_json(400, {"error": str(e)})
                return
            self.send_json(200, {"user": updated})
            return

        target, provider = route(self.path)
        if not target:
            self.send_response(404)
            self.end_headers()
            return

        ok, email = verify_session(self.headers.get("x-session-token", ""))
        if not ok:
            self.send_json(401, {"error": "Not signed in. Please sign in with your acko.tech email."})
            return
        perm_ok, perm_err = require_permission(email, user_store.IMAGE_GEN_ALLOWED)
        if not perm_ok:
            self.send_json(403, perm_err)
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
    # 0.0.0.0 so this works both locally and on a real host (Render etc. route
    # external traffic to whatever port the process binds, not just localhost).
    server = HTTPServer(("0.0.0.0", PORT), ProxyHandler)
    print(f"\n  ACKO Image Generator proxy running on port {PORT}")
    print(f"  Open in browser → http://localhost:{PORT}/generate.html\n")
    if not MAGNIFIC_KEY:
        print("  WARNING: MAGNIFIC_KEY is not set in .env — image generation will fail with a 401/403 until it is.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
