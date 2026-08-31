# Using ACKO Image Generator in Claude Code

This lets you generate ACKO brand-compliant images directly from a Claude
conversation — no need to open the web app to generate images. It calls the
same Magnific-backed generator as the web app, through a remote MCP server.

## Step 1: Get access to the app (one-time, skip if you already have an account)

1. Go to `https://web-production-af07c.up.railway.app` in a browser.
2. Enter your acko.tech email and sign in.
3. If you're new, you'll see a "request access" screen — submit it.
4. An Admin needs to approve your request before you can generate images.

## Step 2: Generate your personal access token

1. Once signed in, click **API Tokens** in the left sidebar.
2. Type a label for this token (e.g. "My laptop").
3. Click **Generate token**.
4. Copy the token (starts with `acko_pat_...`) immediately — it's only shown
   once. If you lose it, just generate a new one.

## Step 3: Register it with one command

This is a *remote* MCP server — you don't need to clone this repo or create
any files by hand. Just run this once in a terminal, with your real token
swapped in:

```bash
claude mcp add acko-image-gen --transport http https://web-production-af07c.up.railway.app/mcp --header "Authorization: Bearer YOUR_TOKEN_HERE" --scope user
```

`--scope user` registers it globally for your account, so it works in every
Claude Code project you open from now on — no per-project setup needed.

<details>
<summary>Alternative: project-level <code>.mcp.json</code> (if you'd rather scope it to one folder)</summary>

Create a file named exactly `.mcp.json` in whichever folder you're working
in:

```bash
cat > .mcp.json << 'EOF'
{
  "mcpServers": {
    "acko-image-gen": {
      "type": "http",
      "url": "https://web-production-af07c.up.railway.app/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
EOF
```

If this repo happens to be that folder, it's already gitignored, so your
token stays local and is never committed.
</details>

## Step 4: Restart Claude Code

MCP servers only load on startup — fully quit and reopen Claude Code (or
start a new session).

## Step 5: Use it

Start a new conversation and just ask in plain language, e.g.:

> Generate an ACKO image of a woman checking her phone at a bus stop

Claude calls the tool automatically and the image appears right in the chat.

## A few things to know

- Each person's token is tied to their own account — never share tokens.
- Default rate limit: 20 image generations per hour.
- Every image generated this way also appears in the shared **History**
  gallery in the web app, tagged with your name.
- Revoke a token anytime from the **API Tokens** panel — it takes effect
  immediately.
