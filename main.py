import os

from composio import Composio
from composio.exceptions import (
    ValidationError,
    WebhookPayloadError,
    WebhookSignatureVerificationError,
)
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

load_dotenv()

# One client for the whole app. Reads COMPOSIO_API_KEY from the environment.
composio = Composio()
app = FastAPI(title="Gmail integration (Composio managed auth)")

BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")

# In-memory dedupe for webhook deliveries. Use Redis or your DB in production.
seen_event_ids: set[str] = set()


def gmail_session(user_id: str):
    # `user_id` is YOUR app's user ID, not a Gmail address.
    # manage_connections=False: we drive the connect flow ourselves via /connect.
    return composio.create(
        user_id=user_id, toolkits=["gmail"], manage_connections=False
    )


def run_tool(user_id: str, slug: str, arguments: dict):
    result = gmail_session(user_id).execute(slug, arguments=arguments)
    if result.error:
        raise HTTPException(502, f"{slug} failed: {result.error}")
    return result.data


# ---------- 1. Connect a Gmail account ----------


@app.post("/connect")
def connect(user_id: str):
    request = gmail_session(user_id).authorize(
        "gmail", callback_url=f"{BASE_URL}/callback?user_id={user_id}"
    )
    # Send the user here. They see Google's consent screen for Composio's OAuth app.
    return {"redirect_url": request.redirect_url}


@app.get("/callback")
def callback(
    user_id: str, status: str | None = None, connected_account_id: str | None = None
):
    # Query params are not proof of anything. Re-check the account server-side.
    if status != "success" or not connected_account_id:
        raise HTTPException(400, "Gmail connection failed or was cancelled")

    account = composio.connected_accounts.get(connected_account_id)
    if account.user_id != user_id:
        raise HTTPException(403, "Connected account does not belong to this user")
    if account.status != "ACTIVE":
        raise HTTPException(409, f"Connection is {account.status}")

    return {"connected": True, "connected_account_id": account.id}


@app.get("/status")
def connection_status(user_id: str):
    items = gmail_session(user_id).toolkits(toolkits=["gmail"]).items
    gmail = next((t for t in items if t.slug == "gmail"), None)
    return {"gmail_connected": bool(gmail and gmail.connection and gmail.connection.is_active)}


# ---------- 2. Read the inbox ----------


@app.get("/emails")
def list_emails(user_id: str, q: str = "in:inbox", limit: int = 5):
    data = run_tool(
        user_id,
        "GMAIL_FETCH_EMAILS",
        {
            "query": q,
            "max_results": limit,  # defaults to 1 if you leave it out
            "include_payload": False,
            "verbose": False,  # fast metadata-only fetch
        },
    )
    messages = data.get("messages") or []
    return {
        "count": len(messages),
        "next_page_token": data.get("nextPageToken"),
        "emails": [
            {
                "id": m.get("messageId"),
                "thread_id": m.get("threadId"),
                "from": m.get("sender"),
                "subject": m.get("subject"),
                "date": m.get("messageTimestamp"),
            }
            for m in messages
        ],
    }


# ---------- 3. Send an email (or save a draft) ----------


class EmailIn(BaseModel):
    to: str
    subject: str
    body: str
    is_html: bool = False
    draft_only: bool = False


@app.post("/send")
def send_email(user_id: str, email: EmailIn):
    slug = "GMAIL_CREATE_EMAIL_DRAFT" if email.draft_only else "GMAIL_SEND_EMAIL"
    data = run_tool(
        user_id,
        slug,
        {
            "recipient_email": email.to,
            "subject": email.subject,
            "body": email.body,
            "is_html": email.is_html,
        },
    )
    return {"action": "draft" if email.draft_only else "sent", "result": data}


# ---------- 4. React to new emails ----------


@app.post("/triggers/enable")
def enable_new_email_trigger(user_id: str):
    # Without connected_account_id, Composio uses this user's active Gmail connection.
    trigger = composio.triggers.create(
        "GMAIL_NEW_GMAIL_MESSAGE",
        user_id=user_id,
        trigger_config={"labelIds": "INBOX"},
    )
    return {"trigger_id": trigger.trigger_id}


@app.post("/webhooks/composio")
async def composio_webhook(request: Request):
    try:
        event = composio.triggers.parse(
            body=await request.body(),  # raw bytes, or the signature won't match
            headers=request.headers,
            verify_secret=os.environ["COMPOSIO_WEBHOOK_SECRET"],
        )
    except (ValidationError, WebhookPayloadError, WebhookSignatureVerificationError):
        raise HTTPException(401, "Invalid webhook")

    envelope = event["raw_payload"]

    # Delivery is at-least-once. Dedupe on the envelope ID.
    event_id = envelope.get("id")
    if event_id in seen_event_ids:
        return {"ok": True, "duplicate": True}
    seen_event_ids.add(event_id)

    event_type = envelope.get("type")

    if event_type == "composio.connected_account.expired":
        # Token revoked or expired. Send this user back through /connect.
        account = envelope["data"]
        print(f"[expired] {account['toolkit']['slug']} connection for user {account['user_id']}")
        return {"ok": True}

    if event_type == "composio.trigger.message":
        trigger = event["payload"]
        if trigger["trigger_slug"] == "GMAIL_NEW_GMAIL_MESSAGE":
            email = trigger["payload"] or {}
            print(
                f"[new email] user={trigger['user_id']} "
                f"from={email.get('sender')} subject={email.get('subject')!r}"
            )
            # Hand real work off to a queue and return 2xx fast.

    return {"ok": True}
