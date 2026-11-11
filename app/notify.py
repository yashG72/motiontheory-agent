"""Alerts to the team when a conversation needs a human."""
import logging
import smtplib
from email.message import EmailMessage

from . import config, db

log = logging.getLogger(__name__)


def alert_team(contact_id: int, reason: str) -> None:
    contact = db.get_contact(contact_id)
    summary = (
        f"Lead #{contact_id} ({contact['channel']}: {contact.get('name') or contact['external_id']}) needs a human.\n"
        f"Reason: {reason}\n\nWhat we know: service={contact.get('service')}, budget={contact.get('budget')}, "
        f"timeline={contact.get('timeline')}, email={contact.get('email')}, phone={contact.get('phone')}\n"
        f"Notes: {contact.get('notes')}"
    )
    log.warning(summary)
    if not (config.ALERT_EMAIL and config.email_enabled()):
        return
    msg = EmailMessage()
    msg["From"] = config.EMAIL_ADDRESS
    msg["To"] = config.ALERT_EMAIL
    msg["Subject"] = f"[{config.BUSINESS_NAME} agent] Lead needs a human: {contact.get('name') or contact['external_id']}"
    msg.set_content(summary)
    try:
        with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT) as s:
            s.login(config.EMAIL_ADDRESS, config.EMAIL_PASSWORD)
            s.send_message(msg)
    except Exception:
        log.exception("Could not send alert email")
