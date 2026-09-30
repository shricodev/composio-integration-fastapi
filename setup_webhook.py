"""One-time setup: register this app's webhook URL with Composio.

Run once per project (and again whenever the public URL changes):
    python setup_webhook.py https://your-app.example.com
"""

import json
import sys

from composio import Composio
from dotenv import load_dotenv

load_dotenv()
composio = Composio()

if len(sys.argv) != 2:
    sys.exit("usage: python setup_webhook.py <public-base-url>")

subscription = composio.triggers.set_webhook_subscription(
    webhook_url=f"{sys.argv[1].rstrip('/')}/webhooks/composio",
    enabled_events=[
        "composio.trigger.message",
        "composio.connected_account.expired",
    ],
)
print(f"Webhook URL: {subscription['webhook_url']}")
print(f"Add this to .env -> COMPOSIO_WEBHOOK_SECRET={subscription['secret']}")

# Print the trigger's config schema so you can check the field names
trigger_type = composio.triggers.get_type("GMAIL_NEW_GMAIL_MESSAGE")
print("\nGMAIL_NEW_GMAIL_MESSAGE config schema:")
print(json.dumps(trigger_type.config, indent=2))
