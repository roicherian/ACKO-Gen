"""
Google Sheets-backed permission store for ACKO Image Generator.

Talks directly to the Sheets API using a service account (server-to-server,
no per-user Google login involved) instead of relying on an external sync
process. Keeps an in-process cache refreshed on a background timer so
request handling never blocks on a live network call to Google.

Env vars (loaded from .env by proxy.py before this module is used):
  GOOGLE_SERVICE_ACCOUNT_KEY   - path to the service account JSON key file
  GOOGLE_SHEET_ID              - the spreadsheet's file ID
  GOOGLE_SHEET_TAB             - optional; sheet/tab name (defaults to the first tab)
  GOOGLE_SHEET_REFRESH_SECONDS - optional; cache refresh interval, default 60

Sheet is expected to have a header row with columns named (case-insensitive):
  "Emails", "Permissions", "Request Pending"
Column order doesn't matter — they're located by name.
"""
import os
import json
import time
import threading
import urllib.request
import urllib.parse
import urllib.error

try:
    from google.oauth2 import service_account
    _GOOGLE_AUTH_AVAILABLE = True
except ImportError:
    _GOOGLE_AUTH_AVAILABLE = False


class _UrllibResponse:
    """Minimal stand-in for the response object google-auth's Credentials.refresh()
    expects: needs .status, .headers, .data."""
    def __init__(self, status, headers, data):
        self.status = status
        self.headers = headers
        self.data = data


class _UrllibRequest:
    """A stdlib-only transport for google-auth, so we don't need to install the
    (much heavier, and itself dependent on the third-party `requests` package)
    google.auth.transport.requests module just to refresh a service-account token."""
    def __call__(self, url, method="GET", body=None, headers=None, **kwargs):
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return _UrllibResponse(r.status, dict(r.getheaders()), r.read())
        except urllib.error.HTTPError as e:
            return _UrllibResponse(e.code, dict(e.headers or {}), e.read())


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
SHEETS_API_BASE = "https://sheets.googleapis.com/v4/spreadsheets"

KEY_PATH = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY", "")
SHEET_ID = os.environ.get("GOOGLE_SHEET_ID", "")
CONFIGURED_TAB = os.environ.get("GOOGLE_SHEET_TAB", "").strip()
REFRESH_SECONDS = int(os.environ.get("GOOGLE_SHEET_REFRESH_SECONDS", "") or "60")
STALE_AFTER_SECONDS = 30 * 60  # don't trust the cache for NEW approvals past this age

_lock = threading.Lock()
_state = {
    "approved": set(),
    "denied": set(),
    "row_by_email": {},            # email -> 1-based row number in the sheet
    "pending_cell_by_email": {},    # email -> current "Request Pending" cell text
    "last_success_at": 0,
    "sheet_title": None,
    "columns": {},                  # {"emails": 0, "permissions": 1, "request_pending": 2}
}
_credentials = None
_write_queue = set()  # emails waiting to be marked "Pending" in the sheet


def _log(msg):
    print(f"  [sheets_store] {msg}")


def _load_credentials():
    global _credentials
    if _credentials is not None:
        return _credentials
    if not _GOOGLE_AUTH_AVAILABLE:
        _log("google-auth is not installed — run: pip3 install -r requirements.txt")
        return None
    if not KEY_PATH or not SHEET_ID:
        _log("GOOGLE_SERVICE_ACCOUNT_KEY or GOOGLE_SHEET_ID is not set in .env")
        return None
    try:
        _credentials = service_account.Credentials.from_service_account_file(KEY_PATH, scopes=SCOPES)
        return _credentials
    except Exception as e:
        _log(f"failed to load service account key: {e}")
        return None


def _access_token():
    creds = _load_credentials()
    if creds is None:
        return None
    try:
        creds.refresh(_UrllibRequest())
        return creds.token
    except Exception as e:
        _log(f"failed to refresh access token: {e}")
        return None


def _api_get(path, params=None):
    token = _access_token()
    if not token:
        return None
    url = f"{SHEETS_API_BASE}/{SHEET_ID}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        _log(f"GET {path} failed: {e.code} {e.read()[:200]}")
        return None
    except Exception as e:
        _log(f"GET {path} failed: {e}")
        return None


def _api_put_values(range_a1, values_2d):
    token = _access_token()
    if not token:
        return False
    encoded_range = urllib.parse.quote(range_a1, safe="")
    url = f"{SHEETS_API_BASE}/{SHEET_ID}/values/{encoded_range}?valueInputOption=RAW"
    data = json.dumps({"values": values_2d}).encode()
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return True
    except urllib.error.HTTPError as e:
        _log(f"write {range_a1} failed: {e.code} {e.read()[:200]}")
        return False
    except Exception as e:
        _log(f"write {range_a1} failed: {e}")
        return False


def _resolve_sheet_title():
    if CONFIGURED_TAB:
        return CONFIGURED_TAB
    meta = _api_get("")
    if not meta:
        return None
    sheets = meta.get("sheets", [])
    if not sheets:
        return None
    return sheets[0]["properties"]["title"]


def _col_letter(idx):
    """0-based column index -> spreadsheet column letter (0->A, 25->Z, 26->AA, ...)."""
    letters = ""
    idx += 1
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def _refresh():
    """Pull the whole sheet, rebuild the cache. Returns True on success."""
    title = _resolve_sheet_title()
    if not title:
        return False

    encoded_range = urllib.parse.quote(f"{title}!A:Z", safe="")
    data = _api_get(f"/values/{encoded_range}")
    if not data:
        return False
    rows = data.get("values", [])
    if not rows:
        return False

    header = [h.strip().lower() for h in rows[0]]
    try:
        email_col = header.index("emails")
        perm_col = header.index("permissions")
        pending_col = header.index("request pending")
    except ValueError as e:
        _log(f"expected column missing from header row: {e}")
        return False

    approved, denied = set(), set()
    row_by_email, pending_by_email = {}, {}

    for i, row in enumerate(rows[1:], start=2):  # sheet rows are 1-based; row 1 is the header
        email = (row[email_col].strip().lower() if len(row) > email_col else "")
        if not email:
            continue
        perm = (row[perm_col].strip().lower() if len(row) > perm_col else "")
        pending_val = (row[pending_col].strip() if len(row) > pending_col else "")
        row_by_email[email] = i
        pending_by_email[email] = pending_val
        if perm == "yes":
            approved.add(email)
        elif perm == "no":
            denied.add(email)

    with _lock:
        _state["approved"] = approved
        _state["denied"] = denied
        _state["row_by_email"] = row_by_email
        _state["pending_cell_by_email"] = pending_by_email
        _state["sheet_title"] = title
        _state["columns"] = {"emails": email_col, "permissions": perm_col, "request_pending": pending_col}
        _state["last_success_at"] = time.time()
    _log(f"synced {len(approved)} approved, {len(denied)} denied, {len(row_by_email)} total rows")
    return True


def _flush_pending_writes():
    """Best-effort: write 'Pending' into the Request Pending cell for anyone queued."""
    with _lock:
        emails = list(_write_queue)
        title = _state["sheet_title"]
        pending_col = _state["columns"].get("request_pending")
        row_by_email = dict(_state["row_by_email"])
    if not emails or not title or pending_col is None:
        return
    for email in emails:
        row = row_by_email.get(email)
        if not row:
            continue  # not a row we recognise (e.g. not yet in the sheet at all) — skip
        cell = f"{title}!{_col_letter(pending_col)}{row}"
        if _api_put_values(cell, [["Pending"]]):
            with _lock:
                _write_queue.discard(email)
                _state["pending_cell_by_email"][email] = "Pending"


def _clear_decided_pending_cells():
    """If a row now has a Yes/No decision but its Request Pending cell still shows
    something, clear it — the request has been actioned."""
    with _lock:
        title = _state["sheet_title"]
        pending_col = _state["columns"].get("request_pending")
        row_by_email = dict(_state["row_by_email"])
        pending_cells = dict(_state["pending_cell_by_email"])
        approved = set(_state["approved"])
        denied = set(_state["denied"])
    if not title or pending_col is None:
        return
    for email, row in row_by_email.items():
        decided = email in approved or email in denied
        if decided and pending_cells.get(email, "").strip():
            cell = f"{title}!{_col_letter(pending_col)}{row}"
            if _api_put_values(cell, [[""]]):
                with _lock:
                    _state["pending_cell_by_email"][email] = ""


def _background_loop():
    while True:
        time.sleep(REFRESH_SECONDS)
        try:
            _refresh()
            _flush_pending_writes()
            _clear_decided_pending_cells()
        except Exception as e:
            _log(f"background refresh cycle crashed: {e}")


_started = False


def start():
    """Call once at proxy startup. Does an immediate synchronous first refresh so the
    proxy doesn't come up with an empty cache, then hands off to a background thread."""
    global _started
    if _started:
        return
    _started = True
    if not _GOOGLE_AUTH_AVAILABLE:
        _log("google-auth not installed — permission checks will fail safe (deny everyone) "
             "until you run: pip3 install -r requirements.txt")
        return
    if not KEY_PATH or not SHEET_ID:
        _log("GOOGLE_SERVICE_ACCOUNT_KEY / GOOGLE_SHEET_ID not set in .env — "
             "permission checks will fail safe (deny everyone) until configured")
        return
    ok = _refresh()
    if ok:
        _flush_pending_writes()
        _clear_decided_pending_cells()
    else:
        _log("initial sheet sync failed — starting with an empty cache (fails safe: nobody approved yet)")
    threading.Thread(target=_background_loop, daemon=True).start()


def get_permissions():
    """Returns (approved_set, denied_set). Fails safe: empty cache => nobody approved,
    nobody denied (they'll just show as pending)."""
    with _lock:
        return set(_state["approved"]), set(_state["denied"])


def record_pending_request(email):
    """Queue this email to be marked 'Pending' in the sheet. Fire-and-forget — the
    actual write happens on the next background flush, not on this call."""
    with _lock:
        already_marked = _state["pending_cell_by_email"].get(email, "").strip().lower() == "pending"
        if not already_marked:
            _write_queue.add(email)
