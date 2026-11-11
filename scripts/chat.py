"""Talk to the agent in your terminal, as if you were a client. No Instagram or email setup needed.

    python scripts/chat.py            # chat as an Instagram client
    python scripts/chat.py email      # chat as an email client
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import agent, db  # noqa: E402

channel = sys.argv[1] if len(sys.argv) > 1 else "instagram"
db.init()
contact = db.get_or_create_contact(channel, f"test-{uuid.uuid4().hex[:8]}")
print(f"Chatting as a {channel} client (lead #{contact['id']}). Ctrl+C to quit.\n")

while True:
    try:
        text = input("You: ").strip()
    except (KeyboardInterrupt, EOFError):
        break
    if not text:
        continue
    db.add_message(contact["id"], "in", text)
    reply = agent.generate_reply(contact["id"])
    if reply:
        db.add_message(contact["id"], "out", reply)
        print(f"\nAgent: {reply}\n")
    else:
        print("\n(Agent chose not to reply)\n")

lead = db.get_contact(contact["id"])
print("\nLead record:", {k: lead[k] for k in sorted(db.LEAD_FIELDS) if lead[k] is not None})
