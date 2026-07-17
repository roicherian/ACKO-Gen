#!/usr/bin/env python3
"""
ACKO Image Generator — MCP Server
Runs as a local tool server for Claude Code.
Pure stdlib, Python 3.9+. No external packages required.

Protocol: JSON-RPC 2.0 over stdin/stdout (MCP spec 2024-11-05)
"""
import sys
import json
import urllib.request
import urllib.error
import time
import base64

# ── CONFIG ────────────────────────────────────────────────────────────────────
MAGNIFIC_KEY      = "MS37c8268acced4d76966a212c97d658de"
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

SETTING_MAP = {
    "motor": {
        "scene": "a clean well-lit Indian car service workshop — pegboard tool wall, cars on lifts in background",
        "props": 'mechanic in dark navy "Car Care Service" uniform; compact silver Maruti or Tata hatchback with Indian state number plate',
        "light": "bright even workshop lighting from large open shutter windows — soft natural daylight fill, warm whites",
    },
    "health": {
        "scene": "a modern Indian hospital ward or clinic — clean beige walls, hospital bed, IV drip stand",
        "props": 'doctor in white coat with "Dr. [Name]" name badge and stethoscope — friendly, approachable',
        "light": "soft diffused overhead lighting mixed with warm window light — bright and clinically warm",
    },
    "travel": {
        "scene": "an Indian airport terminal — polished tile floor, yellow-on-black departure boards with Hindi and English signage",
        "props": "ground staff in dark navy uniform; suitcase and boarding pass as props",
        "light": "warm golden afternoon light flooding through large terminal windows — bright and airy",
    },
    "home": {
        "scene": "a warm Indian family home — wooden dining table, steel water bottle, small potted plant",
        "props": "everyday Indian household details: tablet, cup of chai, cotton furnishings",
        "light": "soft diffused window light — warm afternoon domestic fill",
    },
    "general": {
        "scene": "a real contemporary Indian setting — office, street, or home that feels lived-in",
        "props": "authentic everyday Indian props — phone, bag, notebook",
        "light": "bright clean natural light — warm but not dramatic",
    },
}

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
        f"Setting: {s['scene']}. {s['props']}.",
        f"{s['light']}. Warm whites, natural skin tones with slight imperfections "
        "— premium Indian commercial photography style, NOT dark or moody.",
        f"Expression: {mood}. Background softly blurred real Indian people — busy but not chaotic.",
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
def generate_magnific(prompt, ratio, guidance=1.2, seed=None):
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
        "x-magnific-api-key":  MAGNIFIC_KEY,
    }
    data = http_post(MAGNIFIC_URL, body, headers)
    images = data.get("data") or []
    if not images:
        raise RuntimeError("No image returned from Magnific.")
    return images[0]["base64"], data.get("meta", {})


# ── NANO BANANA 2 via Magnific (async, returns URL) ───────────────────────────
def generate_nano_banana(prompt, ratio, resolution="2K"):
    headers = {
        "Content-Type":       "application/json",
        "x-magnific-api-key": MAGNIFIC_KEY,
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


# ── TOOL DEFINITION ───────────────────────────────────────────────────────────
TOOL = {
    "name":        "generate_acko_image",
    "description": (
        "Generate an ACKO brand-compliant image using Magnific or Google Nano Banana 2. "
        "Automatically builds the correct ACKO prompt style (Indian commercial photography, "
        "warm light, candid, real settings) from a plain-language scene description. "
        "Use this whenever a user asks to generate, create, or produce an image for ACKO."
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
                "description": "magnific = high-fidelity, slower. nano_banana_2 = Google Gemini Flash, faster.",
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
                "description": "ACKO product line — sets setting, props, and lighting",
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
                "description": "Magnific only: guidance scale 0.8–1.5",
            },
            "resolution": {
                "type":        "string",
                "enum":        ["1K", "2K", "4K"],
                "default":     "2K",
                "description": "Nano Banana only: output resolution",
            },
        },
    },
}


# ── TOOL HANDLER ──────────────────────────────────────────────────────────────
def call_tool(args):
    scene      = args.get("scene", "")
    model      = args.get("model", "magnific")
    moment     = args.get("moment", "care")
    product    = args.get("product", "general")
    ratio      = args.get("ratio", "16:9")
    skin_tone  = args.get("skin_tone", "")
    region     = args.get("region", "")
    age        = args.get("age", "")
    life_stage = args.get("life_stage", "")
    guidance   = float(args.get("guidance", 1.2))
    resolution = args.get("resolution", "2K")

    prompt = build_prompt(scene, moment, product, skin_tone, region, age, life_stage)

    try:
        if model == "nano_banana_2":
            b64, meta = generate_nano_banana(prompt, ratio, resolution)
            model_label = "Google Nano Banana 2"
        else:
            seed = args.get("seed")
            b64, meta = generate_magnific(prompt, ratio, guidance, seed)
            model_label = "Magnific"
    except Exception as e:
        return {
            "content": [{"type": "text", "text": f"Generation failed: {e}"}],
            "isError": True,
        }

    info_lines = [
        f"**ACKO Image Generated** · {model_label}",
        f"Scene: {scene}",
        f"Moment: {moment} | Product: {product} | Format: {ratio}",
        f"Prompt used: {prompt[:200]}…" if len(prompt) > 200 else f"Prompt: {prompt}",
    ]
    if meta.get("seed"):
        info_lines.append(f"Seed: {meta['seed']}")

    return {
        "content": [
            {"type": "text",  "text": "\n".join(info_lines)},
            {"type": "image", "data": b64, "mimeType": "image/png"},
        ],
    }


# ── MCP JSON-RPC LOOP ─────────────────────────────────────────────────────────
def respond(id_, result):
    msg = json.dumps({"jsonrpc": "2.0", "id": id_, "result": result})
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def error(id_, code, message):
    msg = json.dumps({"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}})
    sys.stdout.write(msg + "\n")
    sys.stdout.flush()


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            continue

        method = req.get("method", "")
        id_    = req.get("id")
        params = req.get("params", {})

        # Notifications have no id and need no response
        if id_ is None:
            continue

        if method == "initialize":
            respond(id_, {
                "protocolVersion": "2024-11-05",
                "capabilities":    {"tools": {}},
                "serverInfo":      {"name": "acko-image-generator", "version": "1.0"},
            })

        elif method == "tools/list":
            respond(id_, {"tools": [TOOL]})

        elif method == "tools/call":
            name = params.get("name")
            if name != "generate_acko_image":
                error(id_, -32601, f"Unknown tool: {name}")
                continue
            result = call_tool(params.get("arguments", {}))
            respond(id_, result)

        else:
            error(id_, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
