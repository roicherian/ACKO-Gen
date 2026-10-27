# ACKO Gen — Figma plugin

Generate a brand-compliant ACKO image from inside Figma and drop it straight
onto the canvas, instead of switching to the web app and re-uploading.

This is a real, standard Figma plugin (manifest + plugin-thread script + UI),
not the "quick generative plugin" tool — that one can't make authenticated
calls to ACKO Gen's backend at all, so it wasn't an option here.

## How it works

- `code.js` runs in Figma's plugin sandbox. It owns every `figma.*` call —
  reading/writing your saved token, and turning a generated image's bytes
  into a rectangle on the canvas.
- `ui.html` is the plugin's panel. It's the only part that calls
  `fetch()` — straight to `https://acko-gen.vercel.app/mcp`, the same
  endpoint the CLI/Claude Code MCP setup uses (see the main repo's
  `CLAUDE_MCP_SETUP.md`).
- Your personal access token is stored only in `figma.clientStorage` — local
  to your Figma account on this machine, never embedded in the plugin
  source, never shared with anyone else who opens the file.

## Install locally (Figma Desktop)

1. Open the Figma desktop app (this doesn't work in a browser tab).
2. Menu → **Plugins → Development → Import plugin from manifest…**
3. Select `figma-plugin/manifest.json` from this repo.
4. It now shows up under **Plugins → Development → ACKO Gen** in any file.

## Sign in (one-time per machine)

1. Run the plugin (**Plugins → Development → ACKO Gen**).
2. Enter your `@acko.tech` email and click **Sign in** — no password needed,
   the backend only checks the email domain.
3. The plugin signs you in and creates a personal access token for you
   automatically, then saves it locally. You won't need to do this again on
   this machine unless you switch accounts.

If you'd rather use a token you already generated yourself from the web
app's **API Tokens** panel, expand **Already have a token? Paste it
instead** and paste it there.

## Use it

1. Describe the scene. Click **Enhance** (top-right of the box) to replace it
   with the full built prompt — style, lighting, anatomy rules and all —
   which you can then edit freely; whatever's in the box at generate time is
   sent exactly as-is. Skip it and your plain scene gets built automatically.
2. Pick Ratio / Resolution / Moment / Product / Diversity axes, click
   **Generate image**.
3. Generation runs on Nano Banana 2 and typically takes 30–90 seconds — the
   status line counts up while it polls.
4. The finished image appears as a new rectangle near your current
   viewport, already selected.
5. To switch accounts or replace a token later, expand **Switch account or
   change token** at the bottom of the panel.
6. The sun/moon icon (top-right) switches between dark and light theme —
   your choice is remembered per machine.

## Why Nano Banana 2 only

The plugin generates exclusively via Nano Banana 2 (Magnific was dropped —
not needed for this workflow). Nano Banana 2's own API is job-based (submit,
get a task_id, poll for status), so the plugin starts the job and polls a
separate fast status check from the browser instead of holding one request
open — this is what lets a 30-90s generation work within Vercel's ~10s
function limit (see `start_acko_nano_banana_generation` /
`check_acko_nano_banana_generation` in `api/acko_mcp_server.py`).

## Publishing privately to the Acko org

This repo's copy is unpublished — each person installs it locally via
"Import plugin from manifest." To make it available to the whole team
without everyone doing that:

1. In Figma Desktop, with the plugin loaded: **Plugins → Development →
   ACKO Gen → Publish…** (needs a Figma account with publish rights in the
   Acko organization).
2. Figma will assign it a real plugin `id` and ask for an icon/description —
   fill those in through Figma's own publish flow, not by editing
   `manifest.json` by hand here.
3. Set visibility to **private to your organization** (not public to the
   Community) unless you specifically want to share it outside Acko.
