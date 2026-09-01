# Deploying to Vercel

`api/main.py` is a plain stdlib Python 3 HTTP server (a `BaseHTTPRequestHandler`
subclass exposed as `handler`) — no framework, no build step. It serves
`generate.html` and handles all `/api/*`, `/auth/*`, `/admin/*`, and `/mcp`
routes itself. It lives under `api/` specifically because that's the only
place Vercel's Python runtime recognizes the `handler`-class convention; a
`vercel.json` rewrite routes every incoming path to it, so the file's own
`self.path`-based dispatch still decides what each request actually does.

Persistent state (users, characters, shared history, generated images) lives
in **Vercel Postgres** and **Vercel Blob**, not local disk — serverless
functions have no durable writable filesystem.

## 1. Create the project

1. Push this repo to GitHub (already done if you're reading this from the repo).
2. In the Vercel dashboard: **Add New → Project** → import this GitHub repo.
3. Vercel auto-detects the Python runtime from `requirements.txt` — no build
   command needed.

## 2. Provision Postgres and Blob storage

In the project's **Storage** tab:

1. **Create Database → Postgres** → attach it to this project. This sets
   `DATABASE_URL` (and a few Postgres-prefixed variants) automatically.
2. **Create Database → Blob** → set access to **Public** → attach it to this
   project. This sets `BLOB_READ_WRITE_TOKEN` automatically.

Both are added directly as project environment variables — nothing to copy
by hand for these two.

## 3. Set the remaining environment variables

In the project's **Settings → Environment Variables**, add:

| Key | Value |
|---|---|
| `SESSION_SECRET` | a fixed random value — generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"`. **Critical**: without this, the app raises an error at startup rather than silently signing every session with a different secret per cold start. |
| `MAGNIFIC_KEY` | your Magnific API key |
| `OPENAI_API_KEY` | your OpenAI API key (GPT Image 1 model) |
| `REMOVE_BG_API_KEY` | your remove.bg API key (Vehicle Remove BG — same API as the [remove.bg CLI](https://github.com/remove-bg/remove-bg-cli)) |
| `ADMIN_EMAILS` | comma-separated list, e.g. `roy.cherian@acko.tech,rahul.pramod@acko.tech,sreekanth.karthikeyan@acko.tech` |
| `MCP_RATE_LIMIT_PER_HOUR` | optional, defaults to `20` |

Don't upload `.env` itself — it's gitignored and shouldn't leave your machine.
These go into Vercel's own environment variable store instead.

## 4. Known limitation: Vercel Hobby's 10-second function timeout

Nano Banana 2 and Flux 2 Pro generations are async — the web UI creates a job
then polls it with short, separate requests, each well under 10 seconds, so
this works fine even on the free Hobby plan.

The **MCP tool's `nano_banana_2` option is the one exception** — it blocks
synchronously for up to ~2 minutes inside a single request, which *will* time
out on Hobby. MCP callers should default to the fast `magnific` model; Vercel
Pro (300s function timeout) is required to make `nano_banana_2` work over MCP.

## 5. Migrating existing data from Railway

If you're moving from an existing Railway deployment, run
`migrate_railway_to_vercel.py` once (from the project root, with
`DATABASE_URL`/`BLOB_READ_WRITE_TOKEN` set in your shell — e.g. via
`vercel env pull` then sourcing the result) **before** decommissioning
Railway, since its data can be wiped at any time. See the script's own
docstring for details — note that raw API token values can't be recovered
(they're hashed at rest); every user with an existing token needs to
regenerate one from the **API Tokens** panel once the app is live on Vercel.

## 6. First deploy

Once deployed, visit `https://<your-project>.vercel.app`. The emails listed in
`ADMIN_EMAILS` are automatically promoted to Admin on every cold start — sign
in with one of those to reach the User Management view and start approving
others.

## Local development

Run `python3 api/main.py` from the project root (not `cd api && python3
main.py` — it resolves `generate.html`, `Skills/`, etc. relative to the
project root, one level up from its own file). You'll need `DATABASE_URL` and
`BLOB_READ_WRITE_TOKEN` set locally too now (e.g. pulled from the same Vercel
Postgres/Blob store via `vercel env pull`), since local dev no longer falls
back to SQLite/local disk.
