#!/usr/bin/env python3
"""
ACKO Image Generator — MCP Server
Runs as a local tool server for Claude Code.
Pure stdlib, Python 3.9+. No external packages required.

Protocol: JSON-RPC 2.0 over stdin/stdout (MCP spec 2024-11-05)
"""
import sys
import os
import json
import urllib.request
import urllib.error
import time
import base64

# ── CONFIG ────────────────────────────────────────────────────────────────────
# Only used when this file is run standalone (see ACKO_MCP_TOKEN relay mode at
# the bottom) — the deployed /mcp endpoint in main.py always passes its own
# already-.env-loaded key explicitly instead of relying on this module-level read.
MAGNIFIC_KEY      = os.environ.get("MAGNIFIC_KEY", "")
MAGNIFIC_URL      = "https://api.magnific.com/v1/ai/text-to-image"
NANO_BANANA_URL   = "https://api.magnific.com/v1/ai/text-to-image/nano-banana-pro-flash"
POLL_INTERVAL     = 2        # seconds between polls for Nano Banana
POLL_MAX          = 60       # max polls (~2 min)

# ── PROMPT BUILDER ────────────────────────────────────────────────────────────
MOOD_MAP = {
    "pre-purchase":   "calm and quietly focused, slightly weighing something — natural, unforced expression",
    "active-life":    "easy and self-sufficient, going about their day — a small natural smile",
    "care":           "composed and engaged, attentive to the person across from them — warm and trusting",
    "reassurance":    "settled and gently relieved — composed look of someone whose problem is already sorted",
    "internal-brand": "warm and professionally confident, at ease in their environment",
}

# Mirrors generate.html's SETTINGS object exactly (the web app's version was
# already fixed to avoid forcing an unrelated backdrop into every scene, e.g.
# a "health" product tag no longer forces a hospital ward onto a scene that's
# actually set on a football turf — see PROPS_RULE/BACKGROUND_RULE below).
# Kept in sync: any change to one setting's scene/propsHint/light should be
# mirrored in the other file's copy of the same entry.
SETTING_MAP = {
    "motor": {
        "scene": "a clean, uncluttered modern Indian car service area — one plain wall, a single tidy tool rack, minimal and calm",
        "props": "if the scene involves a vehicle or mechanic, a plain dark navy work uniform and a single compact Indian hatchback with a state number plate are appropriate",
        "light": "bright even daylight from a large open shutter — soft natural fill, clean neutral whites",
    },
    "health": {
        "scene": "a clean, modern Indian clinic — a plain beige wall and minimal furnishings, a single small green plant",
        "props": "if the scene involves a doctor or consultation, a white coat and stethoscope are appropriate",
        "light": "soft diffused window light with gentle neutral overhead fill — bright and clean",
    },
    "travel": {
        "scene": "a calm, modern Indian airport interior — clean floor and large windows, minimal and uncrowded",
        "props": "if the scene involves travel, a single cabin suitcase or boarding pass is appropriate",
        "light": "soft afternoon daylight through large windows — bright, airy, mostly neutral tone",
    },
    "home": {
        "scene": "a warm, tidy Indian family home — a wooden table and a single small potted plant, uncluttered",
        "props": "if the scene calls for it, a cup of chai or a tablet is appropriate",
        "light": "soft diffused window light — bright, mostly neutral domestic fill",
    },
    "general": {
        "scene": "a real, contemporary Indian setting — a clean, uncluttered home, office or quiet street corner",
        "props": "",
        "light": "bright clean natural light — mostly neutral, not dramatic",
    },
}

# Same discipline rules as generate.html's BACKGROUND_RULE/PROPS_RULE — without
# these, a product tag's setting/props get force-injected regardless of what
# the scene text actually describes (the original bug: tagging a football-turf
# scene as product="health" appended a full hospital-ward-and-doctor backdrop
# on top of the user's own setting instead of deferring to it).
BACKGROUND_RULE = (
    "Keep the background minimal, clean and uncluttered — softly blurred, with only the few "
    "elements the context genuinely needs. No crowds, no rush, no busy scenery, no extra "
    "people, props or activity competing for attention."
)
PROPS_RULE = (
    "Only include props, accessories or objects that the scene description explicitly calls "
    "for. Do not add a phone, bag, tablet, or any other item by default — empty hands are "
    "correct whenever the scene does not need an object."
)

NEGATIVE_PROMPT = (
    "posed, stiff, looking at camera, stock photo smile, "
    "plastic skin, airbrushed complexion, heavy makeup, "
    "melted hands, wrong finger count, distorted face, "
    "Western setting, left-hand drive car, foreign architecture, "
    "dark moody tones, hard shadows, neon colours, oversaturated HDR, "
    "mascot, cartoon, 3D render, CGI, illustration, "
    "visible brand logos, competitor names, text overlay on scene, "
    "fear, panic, blood, gore, distress, plain white background, nsfw"
)

MAGNIFIC_SIZES = {
    "16:9": "widescreen_16_9", "4:5": "social_post_4_5", "9:16": "social_story_9_16",
    "1:1": "square_1_1", "4:3": "classic_4_3", "3:4": "traditional_3_4", "3:2": "standard_3_2",
}


def build_prompt(scene, moment, product, skin_tone="", region="", age="", life_stage=""):
    mood    = MOOD_MAP.get(moment, MOOD_MAP["care"])
    s       = SETTING_MAP.get(product, SETTING_MAP["general"])
    subject = " ".join(filter(None, [
        skin_tone + "," if skin_tone else "",
        region or "Indian",
        "person",
        f", {age}" if age else "",
        f", {life_stage}" if life_stage else "",
    ]))
    return " ".join([
        "Cinematic photorealistic lifestyle photograph, 16:9 widescreen, "
        "shot on 50mm prime lens at f/2.8 to f/4, shallow depth of field.",
        f"A {subject} — {scene}.",
        f"Setting: {s['scene']}.",
        BACKGROUND_RULE,
        PROPS_RULE + (f" ({s['props']}.)" if s["props"] else ""),
        f"{s['light']}. Warm whites, natural skin tones with slight imperfections "
        "— premium Indian commercial photography style, NOT dark or moody.",
        f"Expression: {mood}. One clear subject with room to breathe.",
        "Candid documentary feel, not posed. Realistic skin texture, no heavy makeup. "
        "Middle-class Indian aesthetic, modern but understated. "
        "Slight warm colour grade, gently desaturated, subtle film grain.",
    ])


# ── HTTP HELPERS ──────────────────────────────────────────────────────────────
def http_post(url, payload, headers):
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def http_get(url, headers):
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def fetch_image_as_base64(url):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return base64.b64encode(r.read()).decode()


# ── MAGNIFIC (sync, returns base64) ───────────────────────────────────────────
def generate_magnific(prompt, ratio, guidance=1.2, seed=None, api_key=None):
    body = {
        "prompt":          prompt,
        "negative_prompt": NEGATIVE_PROMPT,
        "guidance_scale":  guidance,
        "num_images":      1,
        "filter_nsfw":     True,
        "image":           {"size": MAGNIFIC_SIZES.get(ratio, "widescreen_16_9")},
    }
    if seed is not None:
        body["seed"] = seed

    headers = {
        "Content-Type":        "application/json",
        "x-magnific-api-key":  api_key or MAGNIFIC_KEY,
    }
    data = http_post(MAGNIFIC_URL, body, headers)
    images = data.get("data") or []
    if not images:
        raise RuntimeError("No image returned from Magnific.")
    return images[0]["base64"], data.get("meta", {})


# ── NANO BANANA 2 via Magnific (async, returns URL) ───────────────────────────
def generate_nano_banana(prompt, ratio, resolution="2K", api_key=None):
    headers = {
        "Content-Type":       "application/json",
        "x-magnific-api-key": api_key or MAGNIFIC_KEY,
    }
    body = {
        "prompt":                 prompt,
        "aspect_ratio":           ratio,
        "resolution":             resolution,
        "use_google_search_tool": False,
    }
    created = http_post(NANO_BANANA_URL, body, headers)
    task_id = (created.get("data") or {}).get("task_id")
    if not task_id:
        raise RuntimeError("No task_id returned from Nano Banana.")

    poll_url = f"{NANO_BANANA_URL}/{task_id}"
    for _ in range(POLL_MAX):
        time.sleep(POLL_INTERVAL)
        result = http_get(poll_url, headers)
        status = (result.get("data") or {}).get("status")
        if status == "COMPLETED":
            urls = (result.get("data") or {}).get("generated") or []
            if not urls:
                raise RuntimeError("Completed but no image URLs returned.")
            b64 = fetch_image_as_base64(urls[0])
            return b64, {}
        if status == "FAILED":
            raise RuntimeError("Nano Banana generation failed.")
    raise RuntimeError("Timed out waiting for Nano Banana 2.")

# NOTE: generate_nano_banana() blocks inline for up to ~2 minutes (job creation
# + polling) when called from /mcp's tools/call. This is safe from freezing the
# whole app (main.py runs a ThreadingHTTPServer, so this only ties up one
# request's thread), but a calling MCP client with a shorter tool-call timeout
# than the job takes may see the call fail even though generation still
# succeeds server-side. Accepted tradeoff — a job-id/poll-tool pair would avoid
# that but is real additional infrastructure, not built here.


# ── TOOL DEFINITION ───────────────────────────────────────────────────────────
TOOL = {
    "name":        "generate_acko_image",
    "description": (
        "Generate an ACKO brand-compliant image via Magnific. "
        "Automatically builds the correct ACKO prompt style (Indian commercial photography, "
        "warm light, candid, real settings) from a plain-language scene description. "
        "Use this whenever a user asks to generate, create, or produce an image for ACKO. "
        "nano_banana_2 takes roughly 30-90 seconds — say so before calling it."
    ),
    "inputSchema": {
        "type":     "object",
        "required": ["scene"],
        "properties": {
            "scene": {
                "type":        "string",
                "description": "Plain-language description of the scene to generate. "
                               "E.g. 'A woman photographing the dent on her car on a residential street'",
            },
            "model": {
                "type":        "string",
                "enum":        ["magnific", "nano_banana_2"],
                "default":     "magnific",
                "description": "magnific = fast (few seconds), high-fidelity. "
                               "nano_banana_2 = Google Gemini Flash, slower (~30-90s), call it knowing it will block for a while.",
            },
            "resolution": {
                "type":        "string",
                "enum":        ["1K", "2K", "4K"],
                "default":     "2K",
                "description": "nano_banana_2 only — output resolution.",
            },
            "moment": {
                "type":        "string",
                "enum":        ["pre-purchase", "active-life", "care", "reassurance", "internal-brand"],
                "default":     "care",
                "description": "Insurance moment — sets mood and expression",
            },
            "product": {
                "type":        "string",
                "enum":        ["motor", "health", "travel", "home", "general"],
                "default":     "general",
                "description": (
                    "Which ACKO insurance vertical's standard backdrop to use. "
                    "IMPORTANT: this REPLACES the location/setting with that vertical's fixed "
                    "backdrop (e.g. 'health' sets the scene in a clinic, 'motor' a car service "
                    "area, 'travel' an airport, 'home' a family dining table) — even though "
                    "matching props (a doctor's coat, a mechanic's uniform, a suitcase) are only "
                    "added when the scene text itself calls for them, the location itself still "
                    "changes. Only choose a specific vertical when the scene is actually set "
                    "there (e.g. a hospital visit, a car service). Do NOT choose 'health' just "
                    "because the scene mentions an injury/wound/illness — a kid checking a "
                    "scraped knee on a football turf is NOT a hospital scene. If the scene "
                    "already fully describes its own setting (a turf, a street, an office, "
                    "anywhere not matching one of these four verticals), use 'general' so that "
                    "setting is respected instead of overridden."
                ),
            },
            "ratio": {
                "type":        "string",
                "enum":        ["16:9", "4:5", "9:16", "1:1", "4:3", "3:4", "3:2"],
                "default":     "16:9",
                "description": "Output aspect ratio",
            },
            "skin_tone": {
                "type":        "string",
                "enum":        ["", "fair-skinned", "wheatish-skinned", "medium brown-skinned", "dark brown-skinned"],
                "default":     "",
                "description": "Skin tone specification for diversity",
            },
            "region": {
                "type":        "string",
                "enum":        ["", "North Indian", "South Indian", "East Indian", "West Indian", "Northeast Indian"],
                "default":     "",
                "description": "Regional background for diversity",
            },
            "age": {
                "type":        "string",
                "enum":        ["", "mid-twenties", "early thirties", "mid-forties", "late fifties", "elderly, sixties+"],
                "default":     "",
                "description": "Age range",
            },
            "guidance": {
                "type":        "number",
                "default":     1.2,
                "description": "Guidance scale 0.8–1.5",
            },
        },
    },
}


# ── LOCAL RELAY MODE ──────────────────────────────────────────────────────────
# Running this file directly no longer talks to Magnific in-process and holds no
# API key. It forwards every JSON-RPC request byte-for-byte to the real, deployed
# /mcp endpoint, authenticated with your own personal access token (generate one
# from the ACKO Image Generator web app's "API Tokens" panel). This exists purely
# as a fallback for Claude clients that can't register a remote HTTP MCP server
# with a custom bearer header — it cannot bypass permissions or the rate limit,
# unlike the old (pre-fix) version of this file.
ACKO_MCP_URL   = os.environ.get("ACKO_MCP_URL", "https://web-production-af07c.up.railway.app/mcp")
ACKO_MCP_TOKEN = os.environ.get("ACKO_MCP_TOKEN", "")


def respond(id_, result):
    msg = json.dumps({"jsonrpc": "2.0", "id": id_, "result": result})
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def error(id_, code, message):
    msg = json.dumps({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def relay_to_remote(raw_line):
    req = urllib.request.Request(
        ACKO_MCP_URL,
        data=raw_line.encode(),
        method="POST",
        headers={
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {ACKO_MCP_TOKEN}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def main():
    if not ACKO_MCP_TOKEN:
        sys.stderr.write(
            "ACKO_MCP_TOKEN is not set. Generate a personal access token from the "
            "ACKO Image Generator web app's API Tokens panel and set it as an env "
            "var before running this relay — every request will otherwise be "
            "rejected by the remote server as unauthenticated.\n"
        )
        sys.stderr.flush()

    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue

        id_ = req.get("id")

        # Notifications have no id and need no response — still forward them
        # (fire-and-forget) so the remote server's own state stays in sync.
        if id_ is None:
            try:
                relay_to_remote(raw)
            except Exception:
                pass
            continue

        try:
            body = relay_to_remote(raw)
            sys.stdout.write(body.decode() + "\n")
            sys.stdout.flush()
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:200]
            error(id_, -32000, f"Remote /mcp request failed: HTTP {e.code} {detail}")
        except Exception as e:
            error(id_, -32000, f"Could not reach remote /mcp endpoint at {ACKO_MCP_URL}: {e}")


if __name__ == "__main__":
    main()
