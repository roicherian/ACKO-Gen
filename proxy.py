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
import uuid
import urllib.request
import urllib.error
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
import os

import user_store

PORT = int(os.environ.get("PORT", 3458))
MAGNIFIC_BASE = "https://api.magnific.com"
REMOVE_BG_API = "https://api.remove.bg/v1.0/removebg"
HTML_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(HTML_DIR, ".env")
# On a real host, point this at a persistent volume/disk (e.g. Render's mounted
# disk path) so the user DB and session secret survive restarts/redeploys.
# Defaults to living alongside the code, which is fine for local dev.
DATA_DIR = os.environ.get("DATA_DIR", HTML_DIR)
os.makedirs(DATA_DIR, exist_ok=True)
# Local image store (S3 later). All generations / edits / cutouts land here.
GENERATED_DIR = os.path.join(DATA_DIR, "generated")
os.makedirs(GENERATED_DIR, exist_ok=True)


def _ext_for_mime(mime):
    mime = (mime or "").split(";")[0].strip().lower()
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime, ".png")


def save_generated_bytes(raw_bytes, mime="image/png", kind="generate", email=""):
    """
    Persist image bytes under ./generated for local durability.
    Returns metadata including a same-origin URL (/generated/<file>).
    """
    if not raw_bytes:
        raise ValueError("No image bytes to save.")
    safe_kind = "".join(c if c.isalnum() or c in "-_" else "-" for c in (kind or "generate"))[:40] or "generate"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    short = uuid.uuid4().hex[:10]
    filename = f"{stamp}_{safe_kind}_{short}{_ext_for_mime(mime)}"
    fpath = os.path.join(GENERATED_DIR, filename)
    with open(fpath, "wb") as f:
        f.write(raw_bytes)
    meta_path = fpath + ".json"
    try:
        with open(meta_path, "w", encoding="utf-8") as mf:
            json.dump(
                {
                    "filename": filename,
                    "mime": mime or "image/png",
                    "kind": kind or "generate",
                    "email": email or "",
                    "bytes": len(raw_bytes),
                    "ts": int(time.time() * 1000),
                },
                mf,
                indent=2,
            )
    except Exception:
        pass
    return {
        "id": short,
        "filename": filename,
        "path": os.path.join("generated", filename),
        "url": f"/generated/{filename}",
        "mime": mime or "image/png",
        "bytes": len(raw_bytes),
    }


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
# Same API the https://github.com/remove-bg/remove-bg-cli tool uses.
REMOVE_BG_API_KEY = os.environ.get("REMOVE_BG_API_KEY", "")


def encode_multipart(fields, files=None):
    """Build multipart/form-data body (stdlib only)."""
    boundary = "----AckoFormBoundary" + uuid.uuid4().hex
    body = bytearray()
    for name, value in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8")
        )
        if isinstance(value, bytes):
            body.extend(value)
        else:
            body.extend(str(value).encode("utf-8"))
        body.extend(b"\r\n")
    for name, (filename, content, content_type) in (files or {}).items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(
            (
                f'Content-Disposition: form-data; name="{name}"; '
                f'filename="{filename}"\r\n'
            ).encode("utf-8")
        )
        body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
        body.extend(content)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    return bytes(body), f"multipart/form-data; boundary={boundary}"


def remove_bg_cutout(image_url=None, image_bytes=None, filename="vehicle.png"):
    """
    Call remove.bg with car-tuned options (matches the official CLI example):
      type=car, semitransparency=true, shadow_type=car
    Returns (png_bytes, meta_dict).
    """
    if not REMOVE_BG_API_KEY:
        raise RuntimeError("REMOVE_BG_API_KEY is not configured.")

    fields = {
        "size": "auto",
        "format": "png",
        "type": "car",
        "semitransparency": "true",
        # Car contact shadow from remove.bg (replaces fragile client-side restore)
        "shadow_type": "car",
        "shadow_opacity": "60",
    }
    files = None
    if image_bytes:
        files = {
            "image_file": (filename, image_bytes, "image/png"),
        }
    elif image_url:
        fields["image_url"] = image_url
    else:
        raise ValueError("image_url or image_bytes is required.")

    body, content_type = encode_multipart(fields, files)
    req = urllib.request.Request(
        REMOVE_BG_API,
        data=body,
        headers={
            "X-Api-Key": REMOVE_BG_API_KEY,
            "Content-Type": content_type,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            png = r.read()
            meta = {
                "provider": "remove.bg",
                "shadow": "car",
                "credits_charged": r.headers.get("X-Credits-Charged"),
                "detected_type": r.headers.get("X-Type"),
            }
            return png, meta
    except urllib.error.HTTPError as e:
        err_body = e.read().decode(errors="replace")
        try:
            err_json = json.loads(err_body)
        except Exception:
            err_json = {"error": err_body[:400]}
        raise RuntimeError(json.dumps({"status": e.code, "body": err_json})) from e

# Universal vehicle base reference — kept server-side only (never shown in the
# prompt UI). Injected into Magnific requests when the client sends
# x-acko-vehicle-ref: 1.
VEHICLE_REF_PATH = os.path.join(
    HTML_DIR, "Vehicles-data", "vehicle_base_reference.png"
)
_vehicle_ref_cache = None  # (data_uri, mime, mtime)
GEN_DEBUG_LOG = os.path.join(DATA_DIR, "gen_debug.log")


def _log_gen_debug(message):
    try:
        with open(GEN_DEBUG_LOG, "a") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except OSError:
        pass


def get_vehicle_reference_image():
    """Load the universal vehicle base reference as a compact data URI for
    Magnific reference_images. Full PNG (~1MB) overloads Freepik when a second
    (user model) ref is also attached — so we serve a compressed JPEG (~100KB).
    Cached until the file on disk changes."""
    global _vehicle_ref_cache
    try:
        mtime = os.path.getmtime(VEHICLE_REF_PATH)
    except OSError:
        return None
    if _vehicle_ref_cache and _vehicle_ref_cache[2] == mtime:
        return _vehicle_ref_cache[0]
    try:
        from PIL import Image
        import io
        with Image.open(VEHICLE_REF_PATH) as im:
            rgb = im.convert("RGB")
            rgb.thumbnail((1024, 1024))
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=72, optimize=True)
            raw = buf.getvalue()
        mime = "image/jpeg"
        data_uri = "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")
    except Exception as ex:
        _log_gen_debug(f"vehicle ref jpeg compress failed ({ex}); using png")
        with open(VEHICLE_REF_PATH, "rb") as f:
            raw = f.read()
        mime = "image/png"
        data_uri = "data:image/png;base64," + base64.b64encode(raw).decode("ascii")
    _vehicle_ref_cache = (data_uri, mime, mtime)
    _log_gen_debug(f"vehicle base ref ready mime={mime} uri_chars={len(data_uri)}")
    return data_uri


def get_vehicle_reference_mime():
    if _vehicle_ref_cache:
        return _vehicle_ref_cache[1]
    get_vehicle_reference_image()
    if _vehicle_ref_cache:
        return _vehicle_ref_cache[1]
    return "image/jpeg"


# Magnific only accepts these for reference_images[].mime_type
_MAGNIFIC_REF_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})


def sanitize_magnific_ref_mime(mime, data_uri=""):
    """Normalize client mime aliases; infer from data URI when needed.
    Returns a Magnific-safe mime or None if unrecoverable."""
    m = (mime or "").split(";")[0].strip().lower()
    if m in ("image/jpg", "image/pjpeg", "image/x-jpeg"):
        m = "image/jpeg"
    elif m == "image/x-png":
        m = "image/png"
    if m in _MAGNIFIC_REF_MIMES:
        return m
    uri = data_uri or ""
    if uri.startswith("data:"):
        try:
            header = uri.split(",", 1)[0]  # data:image/jpeg;base64
            raw = header[5:]  # strip "data:"
            inferred = raw.split(";")[0].strip().lower()
            if inferred in ("image/jpg", "image/pjpeg", "image/x-jpeg"):
                inferred = "image/jpeg"
            elif inferred == "image/x-png":
                inferred = "image/png"
            if inferred in _MAGNIFIC_REF_MIMES:
                return inferred
        except Exception:
            pass
    return None


def sanitize_reference_images(refs):
    """Drop / fix reference_images entries so Freepik does not 400 on mime_type."""
    if not isinstance(refs, list):
        return []
    out = []
    for item in refs:
        if not isinstance(item, dict) or not item.get("image"):
            continue
        fixed = dict(item)
        safe = sanitize_magnific_ref_mime(fixed.get("mime_type"), fixed.get("image") or "")
        if not safe:
            _log_gen_debug(
                f"dropping ref with invalid mime_type={fixed.get('mime_type')!r}"
            )
            continue
        fixed["mime_type"] = safe
        out.append(fixed)
    return out


# Magnific/Freepik only accepts these for reference_images[].mime_type.
_ALLOWED_REF_MIMES = frozenset({"image/png", "image/jpeg", "image/webp"})


def sanitize_reference_mime(mime, data_uri=""):
    """Normalize aliases (image/jpg → image/jpeg) and infer from data URI when needed.

    Freepik returns HTTP 400 if mime_type is anything else (avif, heic, gif, empty…).
    """
    m = (mime or "").split(";")[0].strip().lower()
    if m in ("image/jpg", "image/pjpeg", "image/x-jpeg"):
        m = "image/jpeg"
    elif m == "image/x-png":
        m = "image/png"
    if m in _ALLOWED_REF_MIMES:
        return m
    # Infer from data: URI header when client sent a bad/empty mime_type.
    uri = data_uri or ""
    if uri.startswith("data:"):
        try:
            header = uri.split(",", 1)[0]  # data:image/jpeg;base64
            inferred = header[5:].split(";")[0].strip().lower()
            if inferred in ("image/jpg", "image/pjpeg", "image/x-jpeg"):
                inferred = "image/jpeg"
            elif inferred == "image/x-png":
                inferred = "image/png"
            if inferred in _ALLOWED_REF_MIMES:
                return inferred
        except Exception:
            pass
    return ""


def sanitize_reference_images(refs):
    """Drop / repair reference_images entries so Magnific validation cannot 400 on mime."""
    if not isinstance(refs, list):
        return []
    out = []
    for item in refs:
        if not isinstance(item, dict) or not item.get("image"):
            continue
        fixed = dict(item)
        mime = sanitize_reference_mime(fixed.get("mime_type"), fixed.get("image") or "")
        if not mime:
            _log_gen_debug(
                f"dropping ref with invalid mime={fixed.get('mime_type')!r} "
                f"uri_prefix={(str(fixed.get('image') or ''))[:40]!r}"
            )
            continue
        fixed["mime_type"] = mime
        out.append(fixed)
    return out


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
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type, x-session-token, x-acko-vehicle-ref, x-acko-vehicle-view",
        )

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

        # Vehicle catalog + exportable prompt lists.
        if path_no_query in ("/vehicle_catalog.json", "/vehicle_prompts.json", "/vehicle_prompts.txt"):
            fname = path_no_query.lstrip("/")
            try:
                with open(os.path.join(HTML_DIR, fname), "rb") as f:
                    body = f.read()
                ctype = "application/json" if fname.endswith(".json") else "text/plain; charset=utf-8"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", len(body))
                self.send_cors()
                self.end_headers()
                self.wfile.write(body)
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
            return

        # Local generated images (disk store; S3 later).
        if path_no_query.startswith("/generated/"):
            rel = path_no_query[len("/generated/"):]
            if ".." in rel or rel.startswith("/") or not rel or "/" in rel:
                self.send_response(400)
                self.end_headers()
                return
            fpath = os.path.join(GENERATED_DIR, rel)
            try:
                with open(fpath, "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                return
            lower = rel.lower()
            if lower.endswith(".png"):
                ctype = "image/png"
            elif lower.endswith(".jpg") or lower.endswith(".jpeg"):
                ctype = "image/jpeg"
            elif lower.endswith(".webp"):
                ctype = "image/webp"
            elif lower.endswith(".gif"):
                ctype = "image/gif"
            else:
                ctype = "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", len(body))
            self.send_header("Cache-Control", "private, max-age=86400")
            self.send_cors()
            self.end_headers()
            self.wfile.write(body)
            return

        # Design-system Skills (tokens, fonts) — read-only static assets.
        if path_no_query.startswith("/Skills/"):
            rel = path_no_query[len("/Skills/"):]
            if ".." in rel or rel.startswith("/"):
                self.send_response(400)
                self.end_headers()
                return
            fpath = os.path.join(HTML_DIR, "Skills", rel)
            try:
                with open(fpath, "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                return
            if rel.endswith(".css"):
                ctype = "text/css; charset=utf-8"
            elif rel.endswith(".woff2"):
                ctype = "font/woff2"
            elif rel.endswith(".woff"):
                ctype = "font/woff"
            elif rel.endswith(".mdc"):
                ctype = "text/plain; charset=utf-8"
            else:
                ctype = "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", len(body))
            self.send_header("Cache-Control", "public, max-age=3600")
            self.send_cors()
            self.end_headers()
            self.wfile.write(body)
            return

        # CoreUI Icons (npm) — only this package tree is exposed.
        if path_no_query.startswith("/node_modules/@coreui/icons/"):
            rel = path_no_query[len("/node_modules/@coreui/icons/"):]
            if ".." in rel or rel.startswith("/"):
                self.send_response(400)
                self.end_headers()
                return
            fpath = os.path.join(HTML_DIR, "node_modules", "@coreui", "icons", rel)
            try:
                with open(fpath, "rb") as f:
                    body = f.read()
            except FileNotFoundError:
                self.send_response(404)
                self.end_headers()
                return
            if rel.endswith(".css"):
                ctype = "text/css; charset=utf-8"
            elif rel.endswith(".woff2"):
                ctype = "font/woff2"
            elif rel.endswith(".woff"):
                ctype = "font/woff"
            elif rel.endswith(".ttf"):
                ctype = "font/ttf"
            elif rel.endswith(".svg"):
                ctype = "image/svg+xml"
            elif rel.endswith(".js"):
                ctype = "application/javascript; charset=utf-8"
            else:
                ctype = "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", len(body))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_cors()
            self.end_headers()
            self.wfile.write(body)
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

        # Fetch a remote generation URL server-side (avoids browser CORS) so the
        # UI can persist Magnific temp image links as durable data URLs.
        if path_no_query == "/api/fetch-image":
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            # <img src> cannot send custom headers — allow token via query too.
            token = self.headers.get("x-session-token", "") or (qs.get("token") or [""])[0]
            ok, email = verify_session(token)
            if not ok:
                self.send_json(401, {"error": "Not signed in. Please sign in with your acko.tech email."})
                return
            perm_ok, perm_err = require_permission(email, user_store.IMAGE_GEN_ALLOWED)
            if not perm_ok:
                self.send_json(403, perm_err)
                return
            remote = (qs.get("url") or [""])[0].strip()
            parsed = urllib.parse.urlparse(remote)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                self.send_json(400, {"error": "Invalid image URL."})
                return
            host = parsed.netloc.lower()
            allowed_hosts = (
                "magnific.com",
                "freepik.com",
                "freepik.es",
                "amazonaws.com",
                "cloudfront.net",
                "googleusercontent.com",
            )
            if not any(host == h or host.endswith("." + h) for h in allowed_hosts):
                self.send_json(400, {"error": "Host not allowed for image fetch."})
                return
            try:
                req = urllib.request.Request(
                    remote,
                    headers={"User-Agent": "ACKO-Gen-Proxy/1.0", "Accept": "image/*,*/*"},
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=60) as r:
                    body = r.read()
                    ctype = r.headers.get("Content-Type", "image/png")
                self.send_response(200)
                self.send_header("Content-Type", ctype.split(";")[0].strip() or "image/png")
                self.send_header("Content-Length", len(body))
                self.send_header("Cache-Control", "private, max-age=3600")
                self.send_cors()
                self.end_headers()
                self.wfile.write(body)
            except urllib.error.HTTPError as e:
                # Magnific/CDN temp URLs commonly expire as 403 — return a clear JSON error
                # so the browser Mirror/Edit path can surface a useful message.
                if e.code in (403, 404, 410):
                    self.send_json(
                        e.code,
                        {
                            "error": (
                                "Source image URL expired or is no longer accessible. "
                                "Re-generate the image, then try Mirror / Edit again while it is still open."
                            )
                        },
                    )
                    return
                err_body = e.read() if e.fp else b""
                self.send_response(e.code)
                self.send_cors()
                self.end_headers()
                self.wfile.write(err_body)
            except Exception as e:
                self.send_json(502, {"error": f"Failed to fetch image: {e}"})
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

        # Persist any generation / edit / cutout to ./generated (local disk; S3 later).
        if self.path == "/api/generated/save":
            ok, email = verify_session(self.headers.get("x-session-token", ""))
            if not ok:
                self.send_json(401, {"error": "Not signed in. Please sign in with your acko.tech email."})
                return
            perm_ok, perm_err = require_permission(email, user_store.IMAGE_GEN_ALLOWED)
            if not perm_ok:
                self.send_json(403, perm_err)
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self.send_json(400, {"error": "Invalid request body."})
                return
            kind = str(data.get("kind") or "generate").strip() or "generate"
            mime = str(data.get("mime") or "image/png").strip() or "image/png"
            image_b64 = str(data.get("image_b64") or "").strip()
            image_url = str(data.get("image_url") or "").strip()
            raw = None
            if image_b64.startswith("data:"):
                try:
                    header, image_b64 = image_b64.split(",", 1)
                    if ";base64" in header and ":" in header:
                        maybe_mime = header.split(":", 1)[1].split(";", 1)[0]
                        if maybe_mime.startswith("image/"):
                            mime = maybe_mime
                except ValueError:
                    image_b64 = ""
            if image_b64:
                try:
                    raw = base64.b64decode(image_b64, validate=False)
                except Exception:
                    self.send_json(400, {"error": "Invalid image_b64."})
                    return
            elif image_url.startswith("http://") or image_url.startswith("https://"):
                try:
                    req = urllib.request.Request(
                        image_url,
                        headers={"User-Agent": "ACKO-Gen-Proxy/1.0", "Accept": "image/*,*/*"},
                        method="GET",
                    )
                    with urllib.request.urlopen(req, timeout=60) as r:
                        raw = r.read()
                        ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
                        if ctype.startswith("image/"):
                            mime = ctype
                except Exception as ex:
                    self.send_json(502, {"error": f"Could not download image for local save: {ex}"})
                    return
            else:
                self.send_json(400, {"error": "Provide image_b64 or image_url."})
                return
            try:
                saved = save_generated_bytes(raw, mime=mime, kind=kind, email=email)
            except Exception as ex:
                self.send_json(500, {"error": f"Failed to save generated image: {ex}"})
                return
            self.send_json(200, saved)
            return

        # Vehicle / results: background removal via remove.bg (car mode).
        # Same API as https://github.com/remove-bg/remove-bg-cli
        if self.path == "/api/vehicle/remove-bg":
            ok, email = verify_session(self.headers.get("x-session-token", ""))
            if not ok:
                self.send_json(401, {"error": "Not signed in. Please sign in with your acko.tech email."})
                return
            perm_ok, perm_err = require_permission(email, user_store.IMAGE_GEN_ALLOWED)
            if not perm_ok:
                self.send_json(403, perm_err)
                return
            if not REMOVE_BG_API_KEY:
                self.send_json(500, {
                    "error": (
                        "REMOVE_BG_API_KEY is not configured. Add it to .env "
                        "(from https://www.remove.bg/dashboard#api-key)."
                    )
                })
                return
            length = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                self.send_json(400, {"error": "Invalid request body."})
                return

            image_url = str(data.get("image_url") or "").strip()
            image_b64 = str(data.get("image_b64") or "").strip()
            if image_b64.startswith("data:"):
                # data:image/png;base64,....
                try:
                    image_b64 = image_b64.split(",", 1)[1]
                except IndexError:
                    image_b64 = ""

            image_bytes = None
            if image_b64:
                try:
                    image_bytes = base64.b64decode(image_b64, validate=False)
                except Exception:
                    self.send_json(400, {"error": "Invalid image_b64."})
                    return
            elif image_url.startswith("http://") or image_url.startswith("https://"):
                pass
            else:
                self.send_json(400, {
                    "error": "Provide image_url or image_b64 for background removal."
                })
                return

            try:
                png_bytes, meta = remove_bg_cutout(
                    image_url=image_url if not image_bytes else None,
                    image_bytes=image_bytes,
                )
            except RuntimeError as ex:
                msg = str(ex)
                try:
                    parsed = json.loads(msg)
                    status = int(parsed.get("status") or 502)
                    body = parsed.get("body") or {"error": msg}
                    if isinstance(body, dict):
                        self.send_json(status, body)
                    else:
                        self.send_json(status, {"error": str(body)})
                except Exception:
                    self.send_json(502, {"error": f"remove.bg failed: {msg[:400]}"})
                return
            except Exception as ex:
                self.send_json(502, {"error": f"Background removal failed: {ex}"})
                return

            saved = None
            try:
                saved = save_generated_bytes(png_bytes, mime="image/png", kind="no-bg", email=email)
            except Exception as ex:
                _log_gen_debug(f"local save (no-bg) failed: {ex}")
            payload = {
                "b64": base64.b64encode(png_bytes).decode("ascii"),
                "mime": "image/png",
                "provider": meta.get("provider", "remove.bg"),
                "shadow": meta.get("shadow", "car"),
                "credits_charged": meta.get("credits_charged"),
                "detected_type": meta.get("detected_type"),
            }
            if saved:
                payload["local_url"] = saved["url"]
                payload["local_path"] = saved["path"]
                payload["local_filename"] = saved["filename"]
            self.send_json(200, payload)
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

        # Vehicle Image Gen: attach the universal base reference server-side so
        # the browser never sees or embeds the reference image in the prompt.
        if (
            provider == "magnific"
            and self.headers.get("x-acko-vehicle-ref", "").strip() == "1"
            and "nano-banana" in (self.path or "")
        ):
            ref_uri = get_vehicle_reference_image()
            if not ref_uri:
                self.send_json(500, {"error": "Vehicle base reference image is missing on the server."})
                return
            try:
                payload = json.loads(body_in or b"{}")
            except json.JSONDecodeError:
                self.send_json(400, {"error": "Invalid JSON body."})
                return
            payload.pop("use_vehicle_reference", None)
            # Always attach Baleno/base for camera/lighting. If the client also sent
            # reference_images (e.g. user model-identity / facelift photo), keep those
            # after the base ref (Magnific allows up to 3). Edit/mirror omit
            # x-acko-vehicle-ref so they are not rewritten here.
            view = (self.headers.get("x-acko-vehicle-view") or "driver").strip().lower()
            if view == "passenger":
                side_text = (
                    "PROMPT SIDE WINS: Indian RHD passenger-side front 3/4 — camera at the "
                    "front-LEFT corner, LEFT/passenger flank, ~35° yaw. Do NOT copy the "
                    "reference plate's left/right if it differs. Do NOT mirror incorrectly."
                )
            else:
                side_text = (
                    "PROMPT SIDE WINS: Indian RHD driver-side front 3/4 — camera at the "
                    "front-RIGHT corner, RIGHT/driver flank, steering wheel on the RIGHT, "
                    "~35° yaw. Do NOT copy the reference plate's left/right if it differs. "
                    "Do NOT mirror or flip to the opposite side."
                )
            base_ref = {
                "image": ref_uri,
                "mime_type": get_vehicle_reference_mime(),
                "text": (
                    "Baleno/base vehicle reference — lock ONLY: camera HEIGHT (~1.2 m / "
                    "headlight level), ~85 mm framing style, pitch/roll, distance/crop, "
                    "centering, soft studio lighting/highlights, straight tyre orientation, "
                    "and soft tyre contact shadow on true alpha (no checkerboard). "
                    + side_text
                    + " Do not reproduce checkerboard transparency; output true alpha PNG "
                    "with natural ground contact shadow only. "
                    "If an ADDITIONAL MODEL REFERENCE is also attached, that photo defines "
                    "the car’s grille, lamps, bumper, wheels/tyres, and body design — "
                    "this Baleno/base image remains camera and lighting only."
                ),
            }
            existing_refs = payload.get("reference_images")
            client_sent_refs = isinstance(existing_refs, list) and any(
                isinstance(x, dict) and x.get("image") for x in existing_refs
            )
            # Sanitize client model-identity refs (image/jpg → jpeg, etc.)
            # before merging with Baleno/base — Freepik 400s on bad mime_type.
            extra = sanitize_reference_images(existing_refs)
            if client_sent_refs and not extra:
                self.send_json(
                    400,
                    {
                        "error": (
                            "Model reference image has an unsupported mime_type "
                            "(use PNG, JPEG, or WebP). Re-add the reference photo and try again."
                        )
                    },
                )
                return
            # Model-identity refs first (car design), then Baleno/base (camera). Cap 3.
            payload["reference_images"] = (extra[:2] + [base_ref])[:3]
            body_in = json.dumps(payload).encode()
            mimes = [r.get("mime_type") for r in payload["reference_images"]]
            _log_gen_debug(
                f"vehicle create refs={len(payload['reference_images'])} "
                f"mimes={mimes} client_extra={len(extra)} "
                f"body_bytes={len(body_in)} path={self.path}"
            )

        req = urllib.request.Request(target, data=body_in, headers=upstream_headers(provider, self.headers), method="POST")

        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                body_out = r.read()
            self.send_response(r.status)
            self.send_header("Content-Type", "application/json")
            self.send_cors()
            self.end_headers()
            self.wfile.write(body_out)
            if "nano-banana" in (self.path or "") and self.command == "POST":
                _log_gen_debug(f"upstream OK status={r.status} path={self.path}")
        except urllib.error.HTTPError as e:
            body_out = e.read()
            _log_gen_debug(
                f"upstream HTTP {e.code} path={self.path} "
                f"req_bytes={len(body_in)} err={body_out[:240]!r}"
            )
            # Freepik/CDN often returns HTML 502/403 for oversized reference payloads —
            # convert to a clear JSON error the UI can show.
            ctype = (e.headers.get("Content-Type") or "").lower() if e.headers else ""
            if e.code in (413, 502, 503) or "text/html" in ctype:
                self.send_json(
                    e.code if e.code >= 400 else 502,
                    {
                        "error": (
                            "Image generation upstream rejected the request "
                            f"(HTTP {e.code}). If you attached a reference photo, try a "
                            "smaller image or remove it and generate again."
                        )
                    },
                )
                return
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_cors()
            self.end_headers()
            self.wfile.write(body_out)
        except Exception as ex:
            _log_gen_debug(f"upstream exception path={self.path}: {ex}")
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
    print(f"  Open in browser → http://localhost:{PORT}/generate.html")
    print(f"  Local image store → {GENERATED_DIR}\n")
    if not MAGNIFIC_KEY:
        print("  WARNING: MAGNIFIC_KEY is not set in .env — image generation will fail with a 401/403 until it is.\n")
    if not REMOVE_BG_API_KEY:
        print("  WARNING: REMOVE_BG_API_KEY is not set in .env — Vehicle Remove BG will fail until it is.\n")
    else:
        print("  remove.bg API key loaded — Vehicle Remove BG uses type=car + car shadow.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
