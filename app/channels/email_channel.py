"""Email via IMAP (read new mail) and SMTP (send replies). Works with Gmail, Outlook, Zoho, etc."""
import email
import imaplib
import logging
import re
import smtplib
from email.message import EmailMessage
from email.utils import make_msgid, parseaddr

from .. import config

log = logging.getLogger(__name__)

SKIP_SENDERS = re.compile(r"(no-?reply|mailer-daemon|postmaster|notifications?@|bounce)", re.I)


def _body_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition")):
                return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                return re.sub(r"<[^>]+>", " ", html)
        return ""
    return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "replace")


def _strip_quoted(text: str) -> str:
    """Drop the quoted earlier thread so the agent sees only the new message."""
    lines = []
    for line in text.splitlines():
        if line.startswith(">") or re.match(r"^On .+ wrote:$", line.strip()):
            break
        lines.append(line)
    return "\n".join(lines).strip()


def fetch_unread() -> list[dict]:
    """Return unread emails and mark them as read."""
    results = []
    with imaplib.IMAP4_SSL(config.IMAP_HOST, config.IMAP_PORT) as imap:
        imap.login(config.EMAIL_ADDRESS, config.EMAIL_PASSWORD)
        imap.select("INBOX")
        _, data = imap.search(None, "UNSEEN")
        for num in data[0].split():
            _, msg_data = imap.fetch(num, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])
            name, addr = parseaddr(msg.get("From", ""))
            if not addr or addr.lower() == config.EMAIL_ADDRESS.lower() or SKIP_SENDERS.search(addr):
                continue
            if msg.get("Auto-Submitted", "no") != "no" or msg.get("Precedence", "").lower() in ("bulk", "list", "junk"):
                continue  # newsletters, auto-replies
            results.append(
                {
                    "from_name": name,
                    "from_addr": addr.lower(),
                    "subject": msg.get("Subject", ""),
                    "message_id": msg.get("Message-ID"),
                    "references": msg.get("References", ""),
                    "text": _strip_quoted(_body_text(msg))[:8000],
                }
            )
    return results


def send_reply(to_addr: str, subject: str, body: str, in_reply_to: str | None = None, references: str = "") -> None:
    msg = EmailMessage()
    msg["From"] = config.EMAIL_ADDRESS
    msg["To"] = to_addr
    msg["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    msg["Message-ID"] = make_msgid()
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = f"{references} {in_reply_to}".strip()
    msg.set_content(body)
    with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT) as s:
        s.login(config.EMAIL_ADDRESS, config.EMAIL_PASSWORD)
        s.send_message(msg)
