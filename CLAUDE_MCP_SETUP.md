# Using ACKO Image Generator in Claude Code

This lets you generate ACKO brand-compliant images directly from a Claude
conversation — no need to open the web app to generate images. It calls the
same Magnific-backed generator as the web app, through a remote MCP server.

## Step 1: Get access to the app (one-time, skip if you already have an account)

1. Go to `https://acko-gen.onrender.com` in a browser.
2. Enter your acko.tech email and sign in.
3. If you're new, you'll see a "request access" screen — submit it.
4. An Admin needs to approve your request before you can generate images.

## Step 2: Generate your personal access token

1. Once signed in, click **API Tokens** in the left sidebar.
2. Type a label for this token (e.g. "My laptop").
3. Click **Generate token**.
4. Copy the token (starts with `acko_pat_...`) immediately — it's only shown
   once. If you lose it, just generate a new one.

## Step 3: Register it

This is a *remote* MCP server — you don't need to clone this repo. Pick
(or create) any folder you'll open in Claude Code, and create a file named
exactly `.mcp.json` in it:

```bash
cat > .mcp.json << 'EOF'
{
  "mcpServers": {
    "acko-image-gen": {
      "type": "http",
      "url": "https://acko-gen.onrender.com/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_TOKEN_HERE"
      }
    }
  }
}
EOF
```

Replace `YOUR_TOKEN_HERE` with your real token before running this. If this
repo happens to be that folder, it's already gitignored, so your token stays
local and is never committed.

<details>
<summary>Alternative: one-line command (only if you have the standalone Claude Code CLI installed)</summary>

Most people only have the Claude desktop app, not the separate `claude` CLI
binary — check first by running `claude --version`. If that works, you can
register the server globally (works in every project, no per-folder file
needed) instead of creating `.mcp.json`:

```bash
claude mcp add acko-image-gen --transport http https://acko-gen.onrender.com/mcp --header "Authorization: Bearer YOUR_TOKEN_HERE" --scope user
```

If you instead see `command not found: claude`, use the `.mcp.json` method
above.
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
