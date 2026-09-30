# Gmail integration in 30 minutes (FastAPI + Composio)

Read, send, and react to Gmail from your app without creating a Google Cloud
OAuth app, passing Google verification, or doing a CASA assessment yourself.
Users consent through Composio's managed Gmail OAuth app.

## Setup

```bash
uv venv && source .venv/bin/activate    # or: python -m venv .venv
uv pip install -r requirements.txt      # or: pip install -r requirements.txt
cp .env.example .env                    # add COMPOSIO_API_KEY from platform.composio.dev
uvicorn main:app --reload
```

## Try it

```bash
# 1. Connect Gmail: open the returned redirect_url in a browser
curl -X POST "localhost:8000/connect?user_id=user_123"
curl "localhost:8000/status?user_id=user_123"

# 2. Read the inbox
curl "localhost:8000/emails?user_id=user_123&q=is:unread&limit=5"

# 3. Save a draft (set draft_only to false to actually send)
curl -X POST "localhost:8000/send?user_id=user_123" \
  -H "content-type: application/json" \
  -d '{"to":"you@example.com","subject":"Hello from FastAPI","body":"It works.","draft_only":true}'

# 4. Get new-email events
python setup_webhook.py https://your-public-url   # prints COMPOSIO_WEBHOOK_SECRET for .env
curl -X POST "localhost:8000/triggers/enable?user_id=user_123"

# Local dev without a tunnel: forward signed events to your app
# (dev init must pick the same project your COMPOSIO_API_KEY belongs to)
composio login && composio dev init
set -a; source .env; set +a
composio dev listen --toolkits gmail --forward http://localhost:8000/webhooks/composio
```

Interactive API docs: http://localhost:8000/docs

## Trade-offs of managed auth

- Google's consent screen says "Composio", not your app's name.
- Google API quota is shared with other Composio users.
- Triggers are polling-based (2-minute default). New-email events took ~40–75s in testing, so they're not instant.
- Scopes are fixed. For custom scopes, your own branding, or dedicated quota,
  bring your own OAuth app, and Google verification and CASA become your job again.
