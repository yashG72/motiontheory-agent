"""Instagram DMs via the Instagram API with Instagram Login (Meta webhooks + Send API)."""
import hashlib
import hmac
import logging

import httpx

from .. import config

log = logging.getLogger(__name__)


def verify_signature(body: bytes, header: str | None) -> bool:
    """Check Meta's X-Hub-Signature-256 header. Skipped if no app secret is configured."""
    if not config.IG_APP_SECRET:
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(config.IG_APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


def parse_webhook(payload: dict) -> list[dict]:
    """Extract incoming text DMs: [{"sender_id": ..., "text": ..., "mid": ...}]."""
    out = []
    for entry in payload.get("entry", []):
        for event in entry.get("messaging", []):
            msg = event.get("message") or {}
            if msg.get("is_echo") or not msg.get("text"):
                continue  # skip our own outgoing messages and non-text (stickers, reactions, ...)
            sender = event.get("sender", {}).get("id")
            if sender and sender != config.IG_USER_ID:
                out.append({"sender_id": sender, "text": msg["text"], "mid": msg.get("mid")})
    return out


def get_username(user_id: str) -> str | None:
    try:
        r = httpx.get(
            f"https://graph.instagram.com/{config.IG_GRAPH_VERSION}/{user_id}",
            params={"fields": "username,name", "access_token": config.IG_ACCESS_TOKEN},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("name") or data.get("username")
    except Exception:
        return None


def send_message(recipient_id: str, text: str) -> None:
    # Instagram caps a DM at 1000 characters; split longer replies.
    chunks = [text[i : i + 1000] for i in range(0, len(text), 1000)] or [text]
    for chunk in chunks:
        r = httpx.post(
            f"https://graph.instagram.com/{config.IG_GRAPH_VERSION}/{config.IG_USER_ID}/messages",
            headers={"Authorization": f"Bearer {config.IG_ACCESS_TOKEN}"},
            json={"recipient": {"id": recipient_id}, "message": {"text": chunk}},
            timeout=15,
        )
        if r.status_code >= 400:
            log.error("Instagram send failed: %s %s", r.status_code, r.text)
            r.raise_for_status()
