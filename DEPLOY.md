# Deploying to Vercel

`api/main.py` is a plain stdlib Python 3 HTTP server — no framework, no build
step. It lives under `api/` because Vercel's Python runtime only recognizes
its `BaseHTTPRequestHandler`-based entrypoint convention for files there: the
class itself is named `handler` (Vercel statically scans for a literal
`class handler(BaseHTTPRequestHandler):` definition — a `handler = SomeClass`
alias assignment is not recognized). No `vercel.json` rewrite is needed —
Vercel auto-detects this single-file backend and routes every request to it
while preserving the real request path, so the file's own `self.path`-based
dispatch decides what each request does, same as it always has.

Persistent state (users, characters, shared history, generated images) lives
in **Neon Postgres** and **Supabase Storage**, not local disk — nothing here
depends on any particular host's filesystem.

## 1. Import the project

1. In the Vercel dashboard: **Add New → Project** → import the
   `roicherian/ACKO-Gen` GitHub repo, branch **`main`**.
2. Application Preset: **Python** (auto-detected from `requirements.txt` at
   the project root — no build command needed).

## 2. Set environment variables

In the project's **Settings → Environment Variables**:

| Key | Value |
|---|---|
| `DATABASE_URL` | your Neon Postgres connection string |
| `SUPABASE_PROJECT_URL` | `https://<project-ref>.supabase.co` |
| `SUPABASE_S3_ENDPOINT` | from Supabase Project Settings → Storage → S3 Connection |
| `SUPABASE_S3_REGION` | from the same S3 Connection panel |
| `SUPABASE_ACCESS_KEY_ID` | from a Supabase S3 access key |
| `SUPABASE_SECRET_ACCESS_KEY` | from the same S3 access key |
| `SUPABASE_BUCKET_NAME` | your Supabase Storage bucket name |
| `SESSION_SECRET` | a fixed random value — generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`. **Critical**: without this, every cold start would sign sessions with a different secret and silently invalidate every login. |
| `MAGNIFIC_KEY` | your Magnific API key |
| `OPENAI_API_KEY` | your OpenAI API key (GPT Image 1 model) |
| `REMOVE_BG_API_KEY` | your remove.bg API key (Vehicle Remove BG) |
| `ADMIN_EMAILS` | comma-separated list, e.g. `roy.cherian@acko.tech,rahul.pramod@acko.tech` |
| `MCP_RATE_LIMIT_PER_HOUR` | optional, defaults to `20` |

Don't upload `.env` itself — it's gitignored and shouldn't leave your
machine. Add these directly in Vercel's own environment variable store.

## 3. Deploy

Click **Deploy**. Vercel builds `api/main.py` as a single serverless function
and routes every path to it automatically.

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

## Local development

Run `python3 api/main.py` from the project root. You'll need `DATABASE_URL`
and the `SUPABASE_*` variables set locally (pointing at the same resources,
or your own separate dev ones).
