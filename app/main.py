"""Web server: Instagram webhook, email poller, and a small admin API for leads and drafts.

Run:  uvicorn app.main:app --port 8000
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from . import agent, config, db
from .channels import email_channel, instagram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("motiontheory")


# ---------- core flow ----------

def deliver(contact: dict, text: str, meta: dict) -> None:
    """Send a reply on the contact's channel and record it."""
    if contact["channel"] == "instagram":
        instagram.send_message(contact["external_id"], text)
    elif contact["channel"] == "email":
        email_channel.send_reply(
            contact["external_id"], meta.get("subject", ""), text, meta.get("message_id"), meta.get("references", "")
        )
    db.add_message(contact["id"], "out", text, meta)


def handle_incoming(channel: str, external_id: str, text: str, meta: dict, name: str | None = None) -> None:
    contact = db.get_or_create_contact(channel, external_id, name=name, email=external_id if channel == "email" else None)
    db.add_message(contact["id"], "in", text, meta)
    if contact["status"] == "needs_human":
        log.info("Contact %s is with a human; not auto-replying", contact["id"])
        return
    reply = agent.generate_reply(contact["id"])
    if not reply:
        return
    if config.REPLY_MODE == "auto":
        deliver(db.get_contact(contact["id"]), reply, meta)
        log.info("Sent reply to contact %s", contact["id"])
    else:
        draft_id = db.add_draft(contact["id"], reply, meta)
        log.info("Saved draft %s for contact %s (REPLY_MODE=draft)", draft_id, contact["id"])


async def email_loop() -> None:
    while True:
        try:
            for m in await asyncio.to_thread(email_channel.fetch_unread):
                if m["text"]:
                    await asyncio.to_thread(
                        handle_incoming, "email", m["from_addr"], m["text"],
                        {"subject": m["subject"], "message_id": m["message_id"], "references": m["references"]},
                        m["from_name"] or None,
                    )
        except Exception:
            log.exception("Email poll failed")
        await asyncio.sleep(config.EMAIL_POLL_SECONDS)


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    task = asyncio.create_task(email_loop()) if config.email_enabled() else None
    log.info("Started. reply_mode=%s instagram=%s email=%s", config.REPLY_MODE, config.instagram_enabled(), config.email_enabled())
    yield
    if task:
        task.cancel()


app = FastAPI(title=f"{config.BUSINESS_NAME} lead agent", lifespan=lifespan)


# ---------- Instagram webhook ----------

@app.get("/webhooks/instagram")
def instagram_verify(
    mode: str = Query(alias="hub.mode"),
    token: str = Query(alias="hub.verify_token"),
    challenge: str = Query(alias="hub.challenge"),
):
    if mode == "subscribe" and token == config.IG_VERIFY_TOKEN:
        return PlainTextResponse(challenge)
    raise HTTPException(403, "Verification failed")


@app.post("/webhooks/instagram")
async def instagram_webhook(request: Request, background: BackgroundTasks):
    body = await request.body()
    if not instagram.verify_signature(body, request.headers.get("X-Hub-Signature-256")):
        raise HTTPException(403, "Bad signature")
    for m in instagram.parse_webhook(json.loads(body or b"{}")):
        # Reply in the background so Meta gets a fast 200 response.
        background.add_task(_handle_ig, m)
    return {"ok": True}


def _handle_ig(m: dict) -> None:
    try:
        name = instagram.get_username(m["sender_id"])
        handle_incoming("instagram", m["sender_id"], m["text"], {"mid": m["mid"]}, name)
    except Exception:
        log.exception("Failed to handle Instagram message")


# ---------- admin API (send header: X-Admin-Token) ----------

def admin(x_admin_token: str = Header("")):
    if x_admin_token != config.ADMIN_TOKEN:
        raise HTTPException(401, "Bad admin token")


@app.get("/leads", dependencies=[Depends(admin)])
def leads(status: str | None = None):
    return db.list_contacts(status)


@app.get("/leads/{contact_id}/messages", dependencies=[Depends(admin)])
def lead_messages(contact_id: int):
    return db.history(contact_id, limit=500)


class LeadUpdate(BaseModel):
    status: str


@app.post("/leads/{contact_id}", dependencies=[Depends(admin)])
def set_lead_status(contact_id: int, body: LeadUpdate):
    """E.g. set status back to 'engaged' to let the agent resume after a human handoff."""
    return db.update_contact(contact_id, status=body.status)


@app.get("/drafts", dependencies=[Depends(admin)])
def drafts():
    return db.list_drafts()


class DraftAction(BaseModel):
    text: str | None = None  # optional edited text


@app.post("/drafts/{draft_id}/send", dependencies=[Depends(admin)])
def send_draft(draft_id: int, body: DraftAction | None = None):
    d = db.get_draft(draft_id)
    if not d or d["status"] != "pending":
        raise HTTPException(404, "No pending draft with that id")
    text = (body.text if body and body.text else d["text"])
    deliver(db.get_contact(d["contact_id"]), text, json.loads(d["meta"] or "{}"))
    db.set_draft_status(draft_id, "sent", text)
    return {"sent": True}


@app.post("/drafts/{draft_id}/reject", dependencies=[Depends(admin)])
def reject_draft(draft_id: int):
    db.set_draft_status(draft_id, "rejected")
    return {"rejected": True}


@app.get("/health")
def health():
    return {"ok": True, "reply_mode": config.REPLY_MODE, "instagram": config.instagram_enabled(), "email": config.email_enabled()}
