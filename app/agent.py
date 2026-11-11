"""The AI sales assistant: reads a conversation and writes the next reply.

Two AI providers are supported, chosen with LLM_PROVIDER in .env:
  gemini  Google Gemini API (has a free tier)  - default
  claude  Anthropic Claude API (paid)
"""
import logging
import time

from . import config, db
from .tools import TOOLS, run_tool

log = logging.getLogger(__name__)

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


def system_prompt(channel: str) -> str:
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

{CHANNEL_STYLE.get(channel, CHANNEL_STYLE["test"])}

<company_knowledge>
{load_knowledge()}
</company_knowledge>"""


def _transcript(contact: dict, msgs: list[dict]) -> str:
    known = {k: contact.get(k) for k in sorted(db.LEAD_FIELDS) if contact.get(k) not in (None, "")}
    lines = [
        f"Channel: {contact['channel']}",
        f"What we already know about this lead: {known or 'nothing yet'}",
        "",
        "Conversation so far (oldest first):",
    ]
    for m in msgs:
        who = "CLIENT" if m["direction"] == "in" else config.BUSINESS_NAME.upper()
        lines.append(f"[{who}] {m['text']}")
    lines.append("")
    lines.append("Write our next reply to the client's latest message(s).")
    return "\n".join(lines)


def generate_reply(contact_id: int, max_steps: int = 6) -> str | None:
    """Run the agent on the contact's conversation. Returns the reply text, or None if no reply should go out."""
    contact = db.get_contact(contact_id)
    system = system_prompt(contact["channel"])
    user = _transcript(contact, db.history(contact_id))
    if config.LLM_PROVIDER == "claude":
        return _run_claude(system, user, contact_id, max_steps)
    return _run_gemini(system, user, contact_id, max_steps)


def _call_tool(name: str, args: dict, contact_id: int) -> tuple[str, bool]:
    try:
        return run_tool(name, args, contact_id), False
    except Exception as exc:  # report tool failures back to the model
        log.exception("Tool %s failed", name)
        return f"Error: {exc}", True


# ---------------------------------------------------------------- Gemini

_gemini_client = None


def _run_gemini(system: str, user: str, contact_id: int, max_steps: int) -> str | None:
    global _gemini_client
    from google import genai
    from google.genai import errors, types

    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=config.GEMINI_API_KEY)

    gen_config = types.GenerateContentConfig(
        system_instruction=system,
        tools=[types.Tool(function_declarations=[
            types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["input_schema"])
            for t in TOOLS
        ])],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=user)])]

    for _ in range(max_steps):
        response = None
        for attempt in range(4):  # the free tier has per-minute limits; wait and retry on 429
            try:
                response = _gemini_client.models.generate_content(
                    model=config.GEMINI_MODEL, contents=contents, config=gen_config
                )
                break
            except errors.APIError as exc:
                if exc.code in (429, 500, 503) and attempt < 3:
                    wait = 15 * (attempt + 1)
                    log.warning("Gemini returned %s, retrying in %ss", exc.code, wait)
                    time.sleep(wait)
                    continue
                raise

        if not response.candidates or response.candidates[0].content is None:
            log.warning("Gemini returned no answer for contact %s (blocked or empty)", contact_id)
            return None

        # Keep the model's turn as-is (it can carry thought signatures Gemini needs back).
        contents.append(response.candidates[0].content)

        calls = response.function_calls or []
        if calls:
            parts = []
            for call in calls:
                out, is_error = _call_tool(call.name, dict(call.args or {}), contact_id)
                parts.append(types.Part.from_function_response(
                    name=call.name, response={"error" if is_error else "result": out}
                ))
            contents.append(types.Content(role="user", parts=parts))
            continue

        text = (response.text or "").strip()
        return text or None

    log.warning("Agent hit max_steps for contact %s", contact_id)
    return None


# ---------------------------------------------------------------- Claude

_claude_client = None


def _run_claude(system: str, user: str, contact_id: int, max_steps: int) -> str | None:
    global _claude_client
    import anthropic

    if _claude_client is None:
        _claude_client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment

    messages = [{"role": "user", "content": user}]
    for _ in range(max_steps):
        response = _claude_client.beta.messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=16000,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
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
                out, is_error = _call_tool(block.name, block.input, contact_id)
                result = {"type": "tool_result", "tool_use_id": block.id, "content": out}
                if is_error:
                    result["is_error"] = True
                results.append(result)
            messages.append({"role": "user", "content": results})
            continue
        if response.stop_reason == "pause_turn":
            continue

        text = "\n".join(b.text for b in response.content if b.type == "text").strip()
        return text or None

    log.warning("Agent hit max_steps for contact %s", contact_id)
    return None
