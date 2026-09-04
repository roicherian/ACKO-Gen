# Deploying to Render

`main.py` is a plain stdlib Python 3 HTTP server — no framework, no build
step. It serves `generate.html` and handles all `/api/*`, `/auth/*`,
`/admin/*`, and `/mcp` routes itself, running as a normal long-running
process (Render supports this directly — no serverless entrypoint
restructuring needed).

Persistent state (users, characters, shared history, generated images) lives
in **Neon Postgres** and **Backblaze B2**, not local disk — Render's free
tier filesystem is wiped on every restart, redeploy, *and* sleep/wake cycle,
so nothing here writes anything that needs to survive to local disk.

## 1. Create the Neon database

1. Sign up at [neon.tech](https://neon.tech) (no credit card required) and
   create a project.
2. Copy its connection string — this is your `DATABASE_URL`.
3. The free plan (0.5 GB storage) auto-suspends compute after 5 minutes idle
   and wakes itself instantly on the next query — no manual intervention
   needed, unlike some other free Postgres providers.

## 2. Create the Backblaze B2 bucket

1. Sign up at [backblaze.com](https://www.backblaze.com/) (no credit card
   required for the free tier — 10 GB storage, unlike Cloudflare R2, which
   demands a payment method on file even at $0 usage).
2. **B2 Cloud Storage → Create a Bucket**. Name it (e.g. `acko-gen-images`),
   set **Files in Bucket** to **Private** (Public requires a card, same as
   R2), leave encryption/Object Lock disabled.
3. **Application Keys → Add a New Application Key** — do NOT use the
   account's Master Application Key (full account access; a leak of that
   is far worse than a leak of a bucket-scoped key). Name it, restrict
   **Allow access to Bucket(s)** to the bucket you just created, Type of
   Access: Read and Write. This gives you `B2_KEY_ID` and
   `B2_APPLICATION_KEY` (the `applicationKey` value — shown once).
4. On the bucket's detail page, note the **Endpoint** (e.g.
   `s3.us-east-005.backblazeb2.com`) — this is `B2_ENDPOINT`.
   `B2_BUCKET_NAME` is whatever you named the bucket.

Since the bucket is Private, there's no permanent public image URL —
`blob_store.py` generates a fresh presigned URL every time history or
characters are read back (see its module docstring).

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
| `B2_ENDPOINT` | from the bucket's detail page, e.g. `s3.us-east-005.backblazeb2.com` |
| `B2_KEY_ID` | from the scoped Application Key you created |
| `B2_APPLICATION_KEY` | from the scoped Application Key you created |
| `B2_BUCKET_NAME` | your bucket's name |
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
`DATABASE_URL` and the `B2_*` variables set locally too now (pointing at the
same Neon/B2 resources, or your own separate dev ones), since local dev no
longer falls back to SQLite/local disk.
