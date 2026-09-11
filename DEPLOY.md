# Deploying to Render

`main.py` is a plain stdlib Python 3 HTTP server — no framework, no build
step. It serves `generate.html` and handles all `/api/*`, `/auth/*`,
`/admin/*`, and `/mcp` routes itself, running as a normal long-running
process (Render supports this directly — no serverless entrypoint
restructuring needed).

Persistent state (users, characters, shared history, generated images) lives
in **Neon Postgres** and **Supabase Storage**, not local disk — Render's
free tier filesystem is wiped on every restart, redeploy, *and* sleep/wake
cycle, so nothing here writes anything that needs to survive to local disk.

## 1. Create the Neon database

1. Sign up at [neon.tech](https://neon.tech) (no credit card required) and
   create a project.
2. Copy its connection string — this is your `DATABASE_URL`.
3. The free plan (0.5 GB storage) auto-suspends compute after 5 minutes idle
   and wakes itself instantly on the next query — no manual intervention
   needed, unlike some other free Postgres providers.

## 2. Create the Supabase Storage bucket

1. Sign up at [supabase.com](https://supabase.com) (no credit card required)
   and create a project. Note the project ref from its URL
   (`https://<project-ref>.supabase.co`) — this is `SUPABASE_PROJECT_URL`
   (as `https://<project-ref>.supabase.co`).
2. **Storage → New bucket**. Name it (e.g. `acko-gen-images`), toggle
   **Public bucket** ON — unlike Cloudflare R2 or Backblaze B2, Supabase
   lets you do this for free, no payment method required. This also means
   uploaded images get a permanent public URL instead of needing a
   presigned URL re-generated on every read.
3. **Project Settings → Storage → S3 Connection**: note the **Endpoint**
   (`SUPABASE_S3_ENDPOINT`, looks like
   `https://<project-ref>.supabase.co/storage/v1/s3`) and **Region**
   (`SUPABASE_S3_REGION`, e.g. `ap-southeast-1`) shown there.
4. In that same section, create a new S3 access key (**New access key** →
   give it a description) — this gives you `SUPABASE_ACCESS_KEY_ID` and
   `SUPABASE_SECRET_ACCESS_KEY` (the secret is shown once).
   `SUPABASE_BUCKET_NAME` is whatever you named the bucket in step 2.

## 3. Create the Render web service

1. In the Render dashboard: **New → Web Service** → connect this GitHub repo.
2. Settings:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python3 main.py`
   - **Instance Type:** Free (512 MB RAM; sleeps after 15 min idle, ~30-60s
     cold start on the next request — acceptable for a low-traffic internal
     tool).

Render sets a `PORT` env var automatically; `main.py` already reads it
(`os.environ.get("PORT", 3458)`) and binds to `0.0.0.0`, so no changes needed.

## 4. Set environment variables

In the service's **Environment** tab, add:

| Key | Value |
|---|---|
| `DATABASE_URL` | your Neon connection string from step 1 |
| `SUPABASE_PROJECT_URL` | `https://<project-ref>.supabase.co` |
| `SUPABASE_S3_ENDPOINT` | from S3 Connection, e.g. `https://<project-ref>.supabase.co/storage/v1/s3` |
| `SUPABASE_S3_REGION` | from S3 Connection, e.g. `ap-southeast-1` |
| `SUPABASE_ACCESS_KEY_ID` | from the S3 access key you created |
| `SUPABASE_SECRET_ACCESS_KEY` | from the S3 access key you created |
| `SUPABASE_BUCKET_NAME` | your bucket's name |
| `SESSION_SECRET` | a fixed random value — generate with `python3 -c "import secrets; print(secrets.token_hex(32))"`. **Critical**: without this, the app raises an error at startup rather than silently signing every session with a different secret on every restart. |
| `MAGNIFIC_KEY` | your Magnific API key |
| `OPENAI_API_KEY` | your OpenAI API key (GPT Image 1 model) |
| `REMOVE_BG_API_KEY` | your remove.bg API key (Vehicle Remove BG — same API as the [remove.bg CLI](https://github.com/remove-bg/remove-bg-cli)) |
| `ADMIN_EMAILS` | comma-separated list, e.g. `roy.cherian@acko.tech,rahul.pramod@acko.tech,sreekanth.karthikeyan@acko.tech` |
| `MCP_RATE_LIMIT_PER_HOUR` | optional, defaults to `20` |

Don't upload `.env` itself — it's gitignored and shouldn't leave your machine.
These go into Render's own environment variable store instead.

## 5. Migrating existing data from Railway

If you're moving from an existing Railway deployment, run
`migrate_railway_to_render.py` once (from the project root, with the same
environment variables from step 4 set in your shell) **before**
decommissioning Railway, since its data can be wiped at any time. See the
script's own docstring for details — note that raw API token values can't be
recovered (they're hashed at rest); every user with an existing token needs
to regenerate one from the **API Tokens** panel once the app is live.

## 6. First deploy

Once deployed, visit `https://<your-service>.onrender.com`. The emails
listed in `ADMIN_EMAILS` are automatically promoted to Admin on every
startup — sign in with one of those to reach the User Management view and
start approving others.

## Local development

Run `python3 main.py` from the project root — same as always. You'll need
`DATABASE_URL` and the `SUPABASE_*` variables set locally too now (pointing
at the same Neon/Supabase resources, or your own separate dev ones), since
local dev no longer falls back to SQLite/local disk.
