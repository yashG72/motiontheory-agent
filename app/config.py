"""Settings loaded from the .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# --- AI provider: "gemini" (free tier available) or "claude" ---
LLM_PROVIDER = _get("LLM_PROVIDER", "gemini").lower()

# --- Gemini (key from https://aistudio.google.com/apikey) ---
GEMINI_API_KEY = _get("GEMINI_API_KEY")
GEMINI_MODEL = _get("GEMINI_MODEL", "gemini-3.8-flash")

# --- Claude ---
CLAUDE_MODEL = _get("CLAUDE_MODEL", "claude-opus-5-5")
CLAUDE_EFFORT = _get("CLAUDE_EFFORT", "medium")  # low | medium | high

# --- Behaviour ---
# "draft": replies are saved for a human to approve before sending (safe default).
# "auto":  replies are sent immediately.
REPLY_MODE = _get("REPLY_MODE", "draft").lower()
BUSINESS_NAME = _get("BUSINESS_NAME", "MotionTheory")
BOOKING_LINK = _get("BOOKING_LINK", "")
ADMIN_TOKEN = _get("ADMIN_TOKEN", "change-me")
DB_PATH = Path(_get("DB_PATH", str(ROOT / "data" / "agent.db")))
KNOWLEDGE_DIR = ROOT / "knowledge"

# --- Instagram (Instagram API with Instagram Login) ---
IG_ACCESS_TOKEN = _get("IG_ACCESS_TOKEN")
IG_USER_ID = _get("IG_USER_ID")  # your professional account's IG user id
IG_APP_SECRET = _get("IG_APP_SECRET")
IG_VERIFY_TOKEN = _get("IG_VERIFY_TOKEN", "motiontheory-verify")
IG_GRAPH_VERSION = _get("IG_GRAPH_VERSION", "v23.0")

# --- Email (any IMAP/SMTP provider: Gmail, Outlook, Zoho, ...) ---
EMAIL_ADDRESS = _get("EMAIL_ADDRESS")
EMAIL_PASSWORD = _get("EMAIL_PASSWORD")  # use an app password, not your login password
IMAP_HOST = _get("IMAP_HOST", "imap.gmail.com")
IMAP_PORT = int(_get("IMAP_PORT", "993"))
SMTP_HOST = _get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(_get("SMTP_PORT", "465"))
EMAIL_POLL_SECONDS = int(_get("EMAIL_POLL_SECONDS", "60"))

# Where the agent sends "a human should take over" alerts (optional).
ALERT_EMAIL = _get("ALERT_EMAIL")


def instagram_enabled() -> bool:
    return bool(IG_ACCESS_TOKEN and IG_USER_ID)


def email_enabled() -> bool:
    return bool(EMAIL_ADDRESS and EMAIL_PASSWORD)
