"""SQLite storage for contacts (leads), conversation history and reply drafts."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS contacts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    channel       TEXT NOT NULL,            -- instagram | email | test
    external_id   TEXT NOT NULL,            -- IG-scoped user id or email address
    name          TEXT,
    email         TEXT,
    phone         TEXT,
    company       TEXT,
    service       TEXT,                     -- what they want from us
    budget        TEXT,
    timeline      TEXT,
    notes         TEXT,
    status        TEXT NOT NULL DEFAULT 'new',  -- new|engaged|qualified|call_link_sent|not_a_fit|needs_human
    score         INTEGER,                  -- 0-100 lead score from the agent
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE(channel, external_id)
);
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id  INTEGER NOT NULL REFERENCES contacts(id),
    direction   TEXT NOT NULL,              -- in | out
    text        TEXT NOT NULL,
    meta        TEXT,                       -- JSON (email subject, message-id, ...)
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id  INTEGER NOT NULL REFERENCES contacts(id),
    text        TEXT NOT NULL,
    meta        TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | sent | rejected
    created_at  TEXT NOT NULL
);
"""

LEAD_FIELDS = {"name", "email", "phone", "company", "service", "budget", "timeline", "notes", "status", "score"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init() -> None:
    with connect() as c:
        c.executescript(SCHEMA)


def get_or_create_contact(channel: str, external_id: str, **fields) -> dict:
    with connect() as c:
        row = c.execute(
            "SELECT * FROM contacts WHERE channel=? AND external_id=?", (channel, external_id)
        ).fetchone()
        if row:
            return dict(row)
        ts = now()
        c.execute(
            "INSERT INTO contacts (channel, external_id, name, email, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (channel, external_id, fields.get("name"), fields.get("email"), ts, ts),
        )
        return dict(c.execute("SELECT * FROM contacts WHERE id=last_insert_rowid()").fetchone())


def get_contact(contact_id: int) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM contacts WHERE id=?", (contact_id,)).fetchone()
        return dict(row) if row else None


def update_contact(contact_id: int, **fields) -> dict:
    fields = {k: v for k, v in fields.items() if k in LEAD_FIELDS and v not in (None, "")}
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        with connect() as c:
            c.execute(
                f"UPDATE contacts SET {sets}, updated_at=? WHERE id=?",
                (*fields.values(), now(), contact_id),
            )
    return get_contact(contact_id)


def list_contacts(status: str | None = None) -> list[dict]:
    with connect() as c:
        if status:
            rows = c.execute("SELECT * FROM contacts WHERE status=? ORDER BY updated_at DESC", (status,))
        else:
            rows = c.execute("SELECT * FROM contacts ORDER BY updated_at DESC")
        return [dict(r) for r in rows]


def add_message(contact_id: int, direction: str, text: str, meta: dict | None = None) -> None:
    with connect() as c:
        c.execute(
            "INSERT INTO messages (contact_id, direction, text, meta, created_at) VALUES (?,?,?,?,?)",
            (contact_id, direction, text, json.dumps(meta or {}), now()),
        )
        c.execute("UPDATE contacts SET updated_at=? WHERE id=?", (now(), contact_id))


def history(contact_id: int, limit: int = 40) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT * FROM messages WHERE contact_id=? ORDER BY id DESC LIMIT ?", (contact_id, limit)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def add_draft(contact_id: int, text: str, meta: dict | None = None) -> int:
    with connect() as c:
        c.execute(
            "INSERT INTO drafts (contact_id, text, meta, created_at) VALUES (?,?,?,?)",
            (contact_id, text, json.dumps(meta or {}), now()),
        )
        return c.execute("SELECT last_insert_rowid()").fetchone()[0]


def list_drafts(status: str = "pending") -> list[dict]:
    with connect() as c:
        rows = c.execute(
            """SELECT d.*, c.channel, c.external_id, c.name FROM drafts d
               JOIN contacts c ON c.id = d.contact_id WHERE d.status=? ORDER BY d.id""",
            (status,),
        )
        return [dict(r) for r in rows]


def get_draft(draft_id: int) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM drafts WHERE id=?", (draft_id,)).fetchone()
        return dict(row) if row else None


def set_draft_status(draft_id: int, status: str, text: str | None = None) -> None:
    with connect() as c:
        if text is not None:
            c.execute("UPDATE drafts SET status=?, text=? WHERE id=?", (status, text, draft_id))
        else:
            c.execute("UPDATE drafts SET status=? WHERE id=?", (status, draft_id))
