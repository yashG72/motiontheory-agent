# MotionTheory lead agent

An AI assistant (powered by Claude) that replies to people who message MotionTheory on **Instagram DMs** and **email**, answers their questions from your company knowledge, qualifies them as leads, and sends good ones to a discovery call booking link. Anything it can't answer (custom quotes, negotiation, upset clients) is handed to a human.

## How it works

```
Instagram DM ──webhook──┐
                        ├─> agent (Claude) ──> reply ──> draft for approval  (REPLY_MODE=draft)
Email inbox ──IMAP poll─┘        │                  └──> sent straight away (REPLY_MODE=auto)
                                 ├─ update_lead       saves name, service, budget, timeline, score
                                 ├─ get_booking_link  shares your Calendly/Cal.com link
                                 └─ handoff_to_human  pauses the bot for that lead and alerts you
```

Every contact, message, lead score and draft is stored in `data/agent.db` (SQLite).

| File | What it does |
|---|---|
| `knowledge/company.md` | **Your company info. Fill this in first.** The agent only says what's here. |
| `app/agent.py` | The system prompt and the Claude tool-use loop |
| `app/tools.py` | The lead tools the agent can call |
| `app/channels/instagram.py` | Instagram webhook parsing and sending |
| `app/channels/email_channel.py` | Reads unread mail (IMAP), sends threaded replies (SMTP) |
| `app/main.py` | The web server: webhook, email poller, admin API |
| `scripts/chat.py` | Test the agent in your terminal, no Instagram/email needed |

## 1. Try it locally (10 minutes)

```powershell
cd C:\Users\goyal\OneDrive\Desktop\MotionTheory_Agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # then put your ANTHROPIC_API_KEY in .env
python scripts\chat.py      # pretend to be a client
```

Fill in `knowledge/company.md`, then chat again and see how the answers change.

## 2. Connect email

Use a Gmail/Google Workspace, Outlook or Zoho mailbox. Turn on 2-step verification and create an **app password** (Gmail: Google Account > Security > App passwords). Put the address and app password in `.env`. The server checks for unread mail every 60 seconds.

## 3. Connect Instagram

Needs an Instagram **Business or Creator** account.

1. Create an app at developers.facebook.com, add the **Instagram** product, and choose *API setup with Instagram login*.
2. Add your Instagram account, generate an access token, and copy it plus your Instagram user id into `.env` (`IG_ACCESS_TOKEN`, `IG_USER_ID`). Copy the app secret into `IG_APP_SECRET`.
3. Configure webhooks: callback URL `https://<your-server>/webhooks/instagram`, verify token = `IG_VERIFY_TOKEN`, and subscribe to the `messages` field.
4. Until Meta approves the `instagram_business_manage_messages` permission (App Review), only accounts added as testers on the app can DM the bot.

Your server must be reachable over HTTPS. For testing, run `uvicorn app.main:app --port 8000` and expose it with `ngrok http 8000`. For production, deploy to Render, Railway, Fly.io or a small VPS.

## 4. Run the server

```powershell
uvicorn app.main:app --port 8000
```

## 5. Review and send replies

Start with `REPLY_MODE=draft`: every reply waits for your approval. Send the header `X-Admin-Token: <ADMIN_TOKEN>`:

| Request | Purpose |
|---|---|
| `GET /drafts` | Replies waiting for approval |
| `POST /drafts/{id}/send` | Send it (optional body `{"text": "edited reply"}`) |
| `POST /drafts/{id}/reject` | Discard it |
| `GET /leads?status=qualified` | Your leads (`new`, `engaged`, `qualified`, `call_link_sent`, `not_a_fit`, `needs_human`) |
| `GET /leads/{id}/messages` | The full conversation |
| `POST /leads/{id}` `{"status": "engaged"}` | Let the bot resume after a human handoff |

Interactive docs for all of these are at `http://localhost:8000/docs`. Once you trust the replies, switch to `REPLY_MODE=auto`.

## Notes

- Model: `claude-opus-5-5` at `medium` effort. Change `CLAUDE_MODEL` / `CLAUDE_EFFORT` in `.env`; `claude-sonnet-5-5` is cheaper for high volume.
- If Claude's safety filter declines a message, the request automatically retries on a fallback model (`fallbacks="default"` in `app/agent.py`).
- Instagram only lets businesses reply within 24 hours of the client's last message.
