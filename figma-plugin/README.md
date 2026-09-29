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

## Get a personal access token (one-time)

1. Go to `https://acko-gen.vercel.app` and sign in with your `@acko.tech`
   email.
2. Click **API Tokens** in the sidebar → give it a label → **Generate
   token**.
3. Copy the token (starts with `acko_pat_...`) — it's only shown once.

## Use it

1. Run the plugin (**Plugins → Development → ACKO Gen**).
2. Paste your token, click **Save token** (one-time per machine).
3. Describe the scene, pick Model / Ratio / Moment / Product, click
   **Generate image**.
4. The finished image appears as a new rectangle near your current
   viewport, already selected.

## Known limitation

**Nano Banana 2** can take 30–90 seconds per generation and may time out on
Vercel's free Hobby plan (10-second function limit) — the same documented
limitation as the MCP/Claude Code setup. **Magnific** (the default) is fast
and reliable; only switch models if you're specifically testing Nano Banana
and expect it might fail.

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
