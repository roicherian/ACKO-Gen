# Deploying to Vercel

`api/main.py` is the same plain stdlib Python 3 HTTP server used on Render —
no framework, no build step, no code rewritten. It lives under `api/`
specifically because that's the only place Vercel's Python runtime
recognizes the `handler`-class convention (a `BaseHTTPRequestHandler`
subclass exposed as a module-level `handler` variable). `vercel.json` routes
every incoming path to it, so the file's own `self.path`-based dispatch still
decides what each request actually does — identical behavior to Render.

Persistent state (users, characters, shared history, generated images) is
**already** external — Neon Postgres and Supabase Storage, not local disk —
so **there is nothing to migrate**. Point Vercel at the exact same Neon
database and Supabase bucket already used on Render, and every character,
history row, and account carries over with zero extra steps.

## 1. Import the project

1. In the Vercel dashboard: **Add New → Project** → import the
   `roicherian/ACKO-Gen` GitHub repo.
2. Pick the **`vercel-migration-v2`** branch (not `main` — `main` is ~30
   commits behind and missing most of this app's current features).
3. Application Preset: **Python** (auto-detected from `requirements.txt` at
   the project root — no build command needed).

## 2. Set environment variables

Copy these **verbatim from Render's Environment tab** — same Neon database,
same Supabase bucket, same secret:

| Key | Value |
|---|---|
| `DATABASE_URL` | same Neon connection string used on Render |
| `SUPABASE_PROJECT_URL` | same as Render |
| `SUPABASE_S3_ENDPOINT` | same as Render |
| `SUPABASE_S3_REGION` | same as Render |
| `SUPABASE_ACCESS_KEY_ID` | same as Render |
| `SUPABASE_SECRET_ACCESS_KEY` | same as Render |
| `SUPABASE_BUCKET_NAME` | same as Render |
| `SESSION_SECRET` | **the exact same value used on Render** — reusing it means existing logged-in sessions keep working; a different value silently logs everyone out |
| `MAGNIFIC_KEY` | same as Render |
| `OPENAI_API_KEY` | same as Render |
| `REMOVE_BG_API_KEY` | same as Render |
| `ADMIN_EMAILS` | same as Render |
| `MCP_RATE_LIMIT_PER_HOUR` | same as Render (optional, defaults to `20`) |

Don't upload `.env` itself — it's gitignored and shouldn't leave your
machine. Add these directly in Vercel's **Settings → Environment Variables**.

## 3. Deploy

Click **Deploy**. Vercel builds `api/main.py` as a single serverless
function and routes every path to it via the `rewrites` rule in
`vercel.json`.

## 4. Known limitation: Hobby's 10-second function timeout

Nano Banana 2 generations are async in the web UI — it creates a job, then
polls it with short, separate requests, each well under 10 seconds — so the
web app works fine on the free Hobby plan.

The **MCP tool's `nano_banana_2` option is the one exception**: it blocks
synchronously for up to ~2 minutes inside a single request (`api/main.py`,
the `nano_banana_2` branch of the MCP `tools/call` handler), which *will*
time out on Hobby's 10s cap. MCP callers should default to the fast
`magnific` model instead; Vercel Pro (300s function timeout) is required to
make `nano_banana_2` work over MCP.

## 5. Cut over

Once the Vercel URL is verified working end-to-end (sign in, generate an
image, History, Characters), update any bookmarks/links to point at it, then
decommission the Render service. Nothing to migrate at that point — both
deployments were reading and writing the same Neon/Supabase backend the
whole time.

## Local development

Unchanged: run `python3 api/main.py` from the project root. You'll need
`DATABASE_URL` and the `SUPABASE_*` variables set locally, same as before.
