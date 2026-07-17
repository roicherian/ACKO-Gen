#!/usr/bin/env python3
"""
Local CORS proxy for ACKO Image Generator.
Relays browser requests → api.magnific.com / api.openai.com, adding CORS headers.
Run: python3 proxy.py
Then open generate.html in any browser.
"""
import json
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
import os

PORT = 3458
MAGNIFIC_BASE = "https://api.magnific.com"
MAGNIFIC_KEY  = "MS37c8268acced4d76966a212c97d658de"
OPENAI_BASE   = "https://api.openai.com"
HTML_DIR = os.path.dirname(os.path.abspath(__file__))


def route(path):
    """Map /api/<provider>/... to (upstream_url, provider)."""
    if path.startswith("/api/magnific/"):
        return MAGNIFIC_BASE + path[len("/api/magnific"):], "magnific"
    if path.startswith("/api/openai/"):
        return OPENAI_BASE + path[len("/api/openai"):], "openai"
    return None, None


def upstream_headers(provider, incoming_headers):
    # Preserve the client's Content-Type (e.g. multipart/form-data; boundary=... for
    # image edit uploads) instead of forcing JSON, so multipart bodies parse correctly upstream.
    content_type = incoming_headers.get("Content-Type", "application/json")
    if provider == "magnific":
        key = incoming_headers.get("x-magnific-api-key", "") or MAGNIFIC_KEY
        return {"Content-Type": content_type, "x-magnific-api-key": key}
    if provider == "openai":
        key = incoming_headers.get("x-openai-api-key", "")
        return {"Content-Type": content_type, "Authorization": f"Bearer {key}"}
    return {"Content-Type": "application/json"}


class ProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"  {args[0]} {args[1]}")

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, x-magnific-api-key, x-openai-api-key")

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

        # Proxy GET (used for Magnific's async polling endpoint)
        if self.path.startswith("/api/"):
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
        target, provider = route(self.path)
        if not target:
            self.send_response(404)
            self.end_headers()
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
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.")
