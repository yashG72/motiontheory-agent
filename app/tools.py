"""Tools the agent can call while talking to a client."""
import json

from . import config, db, notify

TOOLS = [
    {
        "name": "update_lead",
        "description": (
            "Save or update what you have learned about this person as a sales lead. "
            "Call it whenever the client shares a detail (name, email, phone, company, what service "
            "they need, budget, timeline). Also set a 0-100 score for how likely they are to become "
            "a paying client, and the status: 'engaged' once they show real interest, 'qualified' "
            "once you know the service they need plus at least budget or timeline, 'not_a_fit' for "
            "spam, job seekers, vendors pitching us, or requests we don't serve."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "company": {"type": "string"},
                "service": {"type": "string", "description": "What they want us to make or do."},
                "budget": {"type": "string"},
                "timeline": {"type": "string"},
                "notes": {"type": "string", "description": "Short summary of the opportunity."},
                "status": {"type": "string", "enum": ["engaged", "qualified", "not_a_fit"]},
                "score": {"type": "integer", "minimum": 0, "maximum": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_booking_link",
        "description": (
            "Get the link where a qualified client can book a discovery call with the team. "
            "Use it when the client is ready to talk, then include the link in your reply."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "handoff_to_human",
        "description": (
            "Flag this conversation for a person on the team. Use it when the client asks for a "
            "custom quote, negotiates price, is angry or upset, asks something the knowledge base "
            "does not answer, or explicitly asks for a human. After calling it, tell the client "
            "someone from the team will follow up shortly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
            "additionalProperties": False,
        },
    },
]


def run_tool(name: str, args: dict, contact_id: int) -> str:
    if name == "update_lead":
        contact = db.update_contact(contact_id, **args)
        return json.dumps({"saved": True, "lead": {k: contact[k] for k in db.LEAD_FIELDS}})
    if name == "get_booking_link":
        if not config.BOOKING_LINK:
            return "No booking link is configured. Ask for their preferred time and say the team will confirm."
        db.update_contact(contact_id, status="call_link_sent")
        return config.BOOKING_LINK
    if name == "handoff_to_human":
        db.update_contact(contact_id, status="needs_human")
        notify.alert_team(contact_id, args.get("reason", ""))
        return "The team has been notified."
    raise ValueError(f"Unknown tool: {name}")
