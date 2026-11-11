"""The Claude-powered sales assistant: reads a conversation and writes the next reply."""
import logging

import anthropic

from . import config, db
from .tools import TOOLS, run_tool

log = logging.getLogger(__name__)
client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

CHANNEL_STYLE = {
    "instagram": (
        "You are replying in an Instagram DM. Keep it short and conversational: 1-3 short sentences, "
        "no headings or bullet lists, at most one emoji, no email-style sign-off."
    ),
    "email": (
        "You are replying by email. Write a warm, professional email body (no subject line): a greeting "
        "using their name if known, 2-4 short paragraphs, and a sign-off from "
        f"'The {config.BUSINESS_NAME} Team'."
    ),
    "test": "You are replying in a chat. Keep it short and conversational.",
}


def load_knowledge() -> str:
    parts = []
    for path in sorted(config.KNOWLEDGE_DIR.glob("*.md")):
        parts.append(f"<document name=\"{path.name}\">\n{path.read_text(encoding='utf-8')}\n</document>")
    return "\n\n".join(parts)


def system_prompt() -> str:
    return f"""You are the client-facing assistant for {config.BUSINESS_NAME}. You answer people who message \
the business on Instagram and email, help them, and turn genuine prospects into booked discovery calls.

How to work:
- Answer questions using only the company knowledge below. If something isn't covered (exact pricing for a \
custom project, availability, anything you are not sure about), don't invent it: say the team will confirm \
and use handoff_to_human.
- Be helpful first. Learn naturally, one or two questions at a time, what they need, their timeline and \
budget range, and how to reach them. Never interrogate or dump a form on them.
- Save every useful detail with update_lead as soon as you learn it, and keep the score current.
- When someone is a good fit and interested, suggest a short discovery call and share the link from \
get_booking_link.
- Spam, job applications, collaboration pitches and vendors: reply politely and briefly, and mark them \
not_a_fit.
- You represent a real business. Never promise discounts, deadlines or deliverables that the knowledge \
does not state. Never claim to be a human; if asked, say you are {config.BUSINESS_NAME}'s assistant and \
a person can join.
- Reply in the language the client writes in.
- Your final message is sent to the client exactly as written, so it must contain only the reply.

<company_knowledge>
{load_knowledge()}
</company_knowledge>"""


def _transcript(contact: dict, msgs: list[dict]) -> str:
    known = {k: contact.get(k) for k in sorted(db.LEAD_FIELDS) if contact.get(k) not in (None, "")}
    lines = [f"Channel: {contact['channel']}", f"What we already know about this lead: {known or 'nothing yet'}", "", "Conversation so far (oldest first):"]
    for m in msgs:
        who = "CLIENT" if m["direction"] == "in" else config.BUSINESS_NAME.upper()
        lines.append(f"[{who}] {m['text']}")
    lines.append("")
    lines.append("Write our next reply to the client's latest message(s).")
    return "\n".join(lines)


def generate_reply(contact_id: int, max_steps: int = 6) -> str | None:
    """Run the agent on the contact's conversation. Returns the reply text, or None if no reply should go out."""
    contact = db.get_contact(contact_id)
    msgs = db.history(contact_id)
    system = [
        {"type": "text", "text": system_prompt(), "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": CHANNEL_STYLE.get(contact["channel"], CHANNEL_STYLE["test"])},
    ]
    messages = [{"role": "user", "content": _transcript(contact, msgs)}]

    for _ in range(max_steps):
        response = client.beta.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=16000,
            system=system,
            tools=TOOLS,
            messages=messages,
            output_config={"effort": config.CLAUDE_EFFORT},
            # If a request is declined by a safety classifier, retry it on a fallback model automatically.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

        if response.stop_reason == "refusal":
            log.warning("Model declined to answer contact %s", contact_id)
            return None

        # Pass the full assistant content (including thinking blocks) back unchanged.
        messages.append({"role": "assistant", "content": response.content})

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason == "tool_use" and tool_uses:
            results = []
            for block in tool_uses:
                try:
                    out = run_tool(block.name, block.input, contact_id)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
                except Exception as exc:  # report tool failures back to the model
                    log.exception("Tool %s failed", block.name)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {exc}", "is_error": True})
            messages.append({"role": "user", "content": results})
            continue

        if response.stop_reason == "pause_turn":
            continue

        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        return text or None

    log.warning("Agent hit max_steps for contact %s", contact_id)
    return None
