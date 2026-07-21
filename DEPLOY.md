# Deploying to Render

`proxy.py` is a plain stdlib Python 3 HTTP server — no external dependencies,
no build step. It serves `generate.html` and handles all `/api/*`, `/auth/*`,
and `/admin/*` routes itself.

## 1. Create the service

1. Push this repo to GitHub (already done if you're reading this from the repo).
2. In the Render dashboard: **New → Web Service** → connect this GitHub repo.
3. Settings:
   - **Runtime:** Python 3
   - **Build Command:** (leave blank — nothing to install)
   - **Start Command:** `python3 proxy.py`
   - **Instance Type:** the free tier works for ~30 low-traffic internal users,
     but see the persistent-storage note below before relying on it.

Render sets a `PORT` env var automatically; `proxy.py` already reads it
(`os.environ.get("PORT", 3458)`) and binds to `0.0.0.0`, so no changes needed.

## 2. Set environment variables

In the service's **Environment** tab, add:

| Key | Value |
|---|---|
| `MAGNIFIC_KEY` | your Magnific API key |
| `ADMIN_EMAILS` | comma-separated list, e.g. `roy.cherian@acko.tech,rahul.pramod@acko.tech,sreekanth.karthikeyan@acko.tech` |
| `DATA_DIR` | `/data` (see step 3 — only needed if you add a persistent disk) |

Don't upload `.env` itself — it's gitignored and shouldn't leave your machine.
These go into Render's own environment variable store instead.

## 3. Persistent storage — important

This app stores state in two local files: the user/permission SQLite database
(`acko_gen.db`) and a session-signing secret (`.session_secret`). Without a
persistent disk, **Render's free tier wipes the local filesystem on every
restart or redeploy** — meaning every user's permission level would reset to
"No access" and everyone would need to be re-approved, and all sessions would
invalidate.

To avoid that:

1. Upgrade to a paid instance type that supports **Disks**.
2. Add a Disk in the Render dashboard, mounted at e.g. `/data`.
3. Set `DATA_DIR=/data` in the environment variables above.

`proxy.py` and `user_store.py` both already read `DATA_DIR` (defaulting to
the app's own folder if unset) and will create/use the DB and secret file
there instead.

If you're fine with occasional resets (e.g. just testing this out), you can
skip the disk and leave `DATA_DIR` unset — it'll just use ephemeral storage.

## 4. First deploy

Once deployed, visit `https://<your-service>.onrender.com/generate.html`.
The emails listed in `ADMIN_EMAILS` are automatically promoted to Admin on
every startup — sign in with one of those to reach the User Management view
(`.../generate.html#admin` jumps straight there) and start approving others.
