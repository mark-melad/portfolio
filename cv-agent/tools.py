import os
import json
import base64
import logging
import sqlite3
import smtplib
import uuid
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, formatdate
from datetime import datetime

import openai
import requests as http_requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "candidates.db")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

# ─────────────────────────────────────────────
# SECTION 1 — Database
# ─────────────────────────────────────────────

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                name                TEXT,
                email               TEXT,
                phone               TEXT,
                title               TEXT,
                summary             TEXT,
                source_file         TEXT,
                source_email_id     TEXT,
                email_sent          INTEGER DEFAULT 0,
                whatsapp_sent       INTEGER DEFAULT 0,
                whatsapp_msg_id     TEXT,
                whatsapp_status     TEXT,
                error               TEXT,
                created_at          TEXT DEFAULT (datetime('now'))
            )
        """)
        # Add WhatsApp columns to existing databases that predate this migration
        for col, definition in [
            ("whatsapp_sent",   "INTEGER DEFAULT 0"),
            ("whatsapp_msg_id", "TEXT"),
            ("whatsapp_status", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE candidates ADD COLUMN {col} {definition}")
            except Exception:
                pass  # column already exists
        conn.commit()
    log.info("Database initialised.")


def save_candidate(data: dict):
    """INSERT OR IGNORE on (source_email_id, source_file); update error/email_sent if row exists."""
    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM candidates WHERE source_email_id=? AND source_file=?",
            (data.get("source_email_id"), data.get("source_file")),
        ).fetchone()

        if existing:
            conn.execute(
                "UPDATE candidates SET error=?, email_sent=? WHERE id=?",
                (data.get("error"), data.get("email_sent", 0), existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO candidates
                   (name, email, phone, title, summary, source_file, source_email_id, email_sent, error)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    data.get("name"),
                    data.get("email"),
                    data.get("phone"),
                    data.get("title"),
                    data.get("summary"),
                    data.get("source_file"),
                    data.get("source_email_id"),
                    data.get("email_sent", 0),
                    data.get("error"),
                ),
            )
        conn.commit()


def _update_candidate(source_email_id: str, source_file: str, **fields):
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [source_email_id, source_file]
    with _get_conn() as conn:
        conn.execute(
            f"UPDATE candidates SET {set_clause} WHERE source_email_id=? AND source_file=?",
            values,
        )
        conn.commit()


def get_all_candidates() -> list:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM candidates ORDER BY id DESC"
        ).fetchall()
    return [dict(row) for row in rows]


def get_stats() -> dict:
    with _get_conn() as conn:
        total   = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
        emailed = conn.execute("SELECT COUNT(*) FROM candidates WHERE email_sent=1").fetchone()[0]
        errors  = conn.execute("SELECT COUNT(*) FROM candidates WHERE error IS NOT NULL").fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM candidates WHERE email_sent=0 AND error IS NULL"
        ).fetchone()[0]
    return {"total": total, "emailed": emailed, "pending": pending, "errors": errors}


# ─────────────────────────────────────────────
# SECTION 2 — Gmail Client
# ─────────────────────────────────────────────

def get_gmail_service():
    creds = None
    token_path = os.path.join(os.path.dirname(__file__), "token.json")
    creds_path = os.getenv("GMAIL_CREDENTIALS_PATH", "./credentials.json")

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def poll_inbox() -> list:
    """Return list of {message_id, attachments:[{filename, data:bytes}]}."""
    service = get_gmail_service()
    query = "is:unread (from:linkedin.com OR from:jobs.linkedin.com OR subject:application)"

    result = service.users().messages().list(userId="me", q=query).execute()
    messages = result.get("messages", [])

    emails = []
    for msg_ref in messages:
        msg_id = msg_ref["id"]
        msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        attachments = _extract_attachments(service, msg_id, msg)
        if not attachments:
            continue
        emails.append({"message_id": msg_id, "attachments": attachments})

    log.info("Polled inbox — %d emails with attachments found.", len(emails))
    return emails


def _extract_attachments(service, msg_id: str, msg: dict) -> list:
    attachments = []
    parts = msg.get("payload", {}).get("parts", [])

    def walk(parts):
        for part in parts:
            if part.get("parts"):
                walk(part["parts"])
            filename = part.get("filename", "")
            body = part.get("body", {})
            if filename:
                att_id = body.get("attachmentId")
                if att_id:
                    att = service.users().messages().attachments().get(
                        userId="me", messageId=msg_id, id=att_id
                    ).execute()
                    raw = base64.urlsafe_b64decode(att["data"])
                else:
                    raw = base64.urlsafe_b64decode(body.get("data", ""))
                attachments.append({"filename": filename, "data": raw})

    walk(parts)
    return attachments


def _get_or_create_label(service, label_name: str) -> str:
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for lbl in labels:
        if lbl["name"] == label_name:
            return lbl["id"]
    new_label = service.users().labels().create(
        userId="me", body={"name": label_name, "labelListVisibility": "labelShow",
                           "messageListVisibility": "show"}
    ).execute()
    return new_label["id"]


def mark_as_read(message_id: str):
    service = get_gmail_service()
    label_id = _get_or_create_label(service, "cv-processed")
    service.users().messages().modify(
        userId="me",
        id=message_id,
        body={"removeLabelIds": ["UNREAD"], "addLabelIds": [label_id]},
    ).execute()
    log.info("Marked message %s as read and labelled cv-processed.", message_id)


# ─────────────────────────────────────────────
# SECTION 3 — CV Parser
# ─────────────────────────────────────────────

def parse_cv(filename: str, file_bytes: bytes) -> str:
    ext = os.path.splitext(filename.lower())[1]

    try:
        if ext == ".pdf":
            from pypdf import PdfReader
            import io
            reader = PdfReader(io.BytesIO(file_bytes))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            if len(text.strip()) < 100:
                return "PDF appears to be image-based or empty."
            return text

        elif ext == ".docx":
            import docx
            import io
            doc = docx.Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs)

        elif ext == ".doc":
            import mammoth
            import io
            result = mammoth.extract_raw_text(io.BytesIO(file_bytes))
            return result.value

        elif ext == ".txt":
            return file_bytes.decode("utf-8", errors="replace")

        elif ext == ".rtf":
            from striprtf.striprtf import rtf_to_text
            return rtf_to_text(file_bytes.decode("utf-8", errors="replace"))

        elif ext == ".odt":
            from odf.opendocument import load as odf_load
            from odf.text import P
            import io
            doc = odf_load(io.BytesIO(file_bytes))
            paragraphs = doc.getElementsByType(P)
            return "\n".join(
                "".join(
                    node.data for node in p.childNodes
                    if hasattr(node, "data")
                )
                for p in paragraphs
            )

        elif ext in (".png", ".jpg", ".jpeg"):
            encoded = base64.b64encode(file_bytes).decode()
            return "IMAGE_CV:" + encoded

        else:
            try:
                return file_bytes.decode("utf-8")
            except Exception:
                return "UNREADABLE"

    except Exception as exc:
        log.warning("parse_cv failed for %s: %s", filename, exc)
        return f"PARSE_ERROR: {exc}"


# ─────────────────────────────────────────────
# SECTION 4 — AI Extraction (Groq via openai SDK)
# ─────────────────────────────────────────────

def extract_contact(cv_text: str) -> dict:
    client = openai.OpenAI(
        api_key=os.getenv("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1",
    )

    null_result = {"name": None, "email": None, "phone": None, "title": None, "summary": None}

    if cv_text.startswith("IMAGE_CV:"):
        system_msg = (
            "You are a CV parser. The provided file is an image-based CV, "
            "but this model is text-only and cannot process images. "
            "Return ONLY a raw JSON object with all fields set to null. "
            "Keys: name, email, phone, title, summary."
        )
        user_msg = "Image CV — cannot extract text. Return nulls."
    else:
        system_msg = (
            "You are a CV parser. Return ONLY a raw JSON object. No markdown. "
            "No explanation. Keys: name, email, phone, title, summary. "
            "Use null for missing fields."
        )
        user_msg = cv_text[:6000]

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        parsed = json.loads(raw)
        # Ensure all expected keys are present
        for key in null_result:
            parsed.setdefault(key, None)
        return parsed

    except json.JSONDecodeError as exc:
        log.warning("extract_contact JSON parse error: %s", exc)
        return {**null_result, "summary": "parse_error"}
    except Exception as exc:
        log.error("extract_contact error: %s", exc)
        return {**null_result, "summary": f"extraction_error: {exc}"}


# ─────────────────────────────────────────────
# SECTION 5 — Email Sender
# ─────────────────────────────────────────────

def send_welcome_email(to_name: str, to_email: str, title: str) -> bool:
    sender = os.getenv("SENDER_EMAIL", "")
    password = os.getenv("SMTP_PASSWORD", "")
    welcome_msg = os.getenv("WELCOME_MESSAGE", "Thank you for applying. We will be in touch shortly.")
    sender_domain = sender.split("@")[-1] if "@" in sender else "mail"

    plain_body = (
        f"Hi {to_name or 'Candidate'},\n\n"
        f"{welcome_msg}\n\n"
        f"Role detected: {title or 'N/A'}\n\n"
        "Best regards,\n"
        "The Hiring Team"
    )

    html_body = f"""<html><body style="font-family:Arial,sans-serif;font-size:15px;color:#222;max-width:560px;margin:0 auto;padding:32px 24px;">
  <p>Hi <strong>{to_name or 'Candidate'}</strong>,</p>
  <p>{welcome_msg}</p>
  <p><strong>Role detected:</strong> {title or 'N/A'}</p>
  <br>
  <p>Best regards,<br><strong>The Hiring Team</strong></p>
</body></html>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"]    = "We received your application!"
    msg["From"]       = formataddr(("The Hiring Team", sender))
    msg["To"]         = formataddr((to_name or "", to_email))
    msg["Date"]       = formatdate(localtime=True)
    msg["Message-ID"] = f"<{uuid.uuid4().hex}@{sender_domain}>"
    msg["Reply-To"]   = sender
    msg["X-Mailer"]   = "CV-Intake-Agent/1.0"

    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body,  "html",  "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, password)
            server.sendmail(sender, to_email, msg.as_string())
        log.info("Welcome email sent to %s.", to_email)
        return True
    except Exception as exc:
        log.error("send_welcome_email failed for %s: %s", to_email, exc)
        return False


# ─────────────────────────────────────────────
# SECTION 5b — WhatsApp Sender
# ─────────────────────────────────────────────

def _normalize_phone(phone: str) -> str:
    """Strip spaces, dashes, parentheses. Ensure leading + is kept."""
    import re
    digits = re.sub(r"[\s\-().]+", "", phone)
    # Remove leading + for the API (Meta expects E.164 without +)
    return digits.lstrip("+")


def send_whatsapp_message(to_name: str, to_phone: str, title: str) -> tuple[bool, str | None]:
    """
    Send a WhatsApp text message via Meta Cloud API.
    Returns (success: bool, whatsapp_message_id: str | None)
    """
    token    = os.getenv("WHATSAPP_TOKEN", "")
    phone_id = os.getenv("WHATSAPP_PHONE_ID", "")
    welcome  = os.getenv("WELCOME_MESSAGE", "Thank you for applying. We will be in touch shortly.")

    if not token or not phone_id:
        log.warning("WhatsApp credentials not set — skipping WhatsApp message.")
        return False, None

    phone  = _normalize_phone(to_phone)
    body   = (
        f"Hi {to_name or 'Candidate'},\n\n"
        f"{welcome}\n\n"
        f"Role detected: {title or 'N/A'}\n\n"
        "Best regards,\nThe Hiring Team"
    )

    url     = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type":    "individual",
        "to":                phone,
        "type":              "text",
        "text":              {"preview_url": False, "body": body},
    }

    try:
        resp = http_requests.post(url, headers=headers, json=payload, timeout=15)
        resp.raise_for_status()
        data   = resp.json()
        msg_id = data.get("messages", [{}])[0].get("id")
        log.info("WhatsApp message sent to %s (msg_id=%s)", to_phone, msg_id)
        return True, msg_id
    except Exception as exc:
        log.error("send_whatsapp_message failed for %s: %s", to_phone, exc)
        return False, None


def handle_whatsapp_status(whatsapp_msg_id: str, status: str, recipient: str):
    """Update candidate record when Meta sends a status callback."""
    if not whatsapp_msg_id:
        return
    with _get_conn() as conn:
        conn.execute(
            "UPDATE candidates SET whatsapp_status=? WHERE whatsapp_msg_id=?",
            (status, whatsapp_msg_id),
        )
        conn.commit()
    log.info("WhatsApp status updated: %s → %s", whatsapp_msg_id, status)


# ─────────────────────────────────────────────
# SECTION 6 — Main Scan Orchestrator
# ─────────────────────────────────────────────

def run_scan():
    log.info("=== Starting CV scan ===")
    try:
        emails = poll_inbox()
    except Exception as exc:
        log.error("poll_inbox failed: %s", exc)
        return

    for email_obj in emails:
        msg_id = email_obj["message_id"]
        attachments = email_obj["attachments"]

        for att in attachments:
            filename  = att["filename"]
            file_bytes = att["data"]
            try:
                # a) Parse CV
                cv_text = parse_cv(filename, file_bytes)

                # b) Extract contact info
                contact = extract_contact(cv_text)

                # c) Save to DB
                save_candidate({
                    "name":            contact.get("name"),
                    "email":           contact.get("email"),
                    "phone":           contact.get("phone"),
                    "title":           contact.get("title"),
                    "summary":         contact.get("summary"),
                    "source_file":     filename,
                    "source_email_id": msg_id,
                    "email_sent":      0,
                    "error":           None,
                })

                # d) Send welcome email if we have an address
                candidate_email = contact.get("email")
                if candidate_email:
                    success = send_welcome_email(
                        contact.get("name"), candidate_email, contact.get("title")
                    )
                    if success:
                        _update_candidate(msg_id, filename, email_sent=1)
                    else:
                        _update_candidate(msg_id, filename, error="email send failed")
                else:
                    # e) No email found
                    _update_candidate(msg_id, filename, error="no email found in CV")

                # f) Send WhatsApp message if phone number is available
                candidate_phone = contact.get("phone")
                if candidate_phone:
                    wa_success, wa_msg_id = send_whatsapp_message(
                        contact.get("name"), candidate_phone, contact.get("title")
                    )
                    if wa_success:
                        _update_candidate(msg_id, filename,
                                          whatsapp_sent=1, whatsapp_msg_id=wa_msg_id,
                                          whatsapp_status="sent")
                    else:
                        _update_candidate(msg_id, filename, whatsapp_status="failed")

            except Exception as exc:
                log.error("Error processing attachment %s in message %s: %s", filename, msg_id, exc)
                try:
                    save_candidate({
                        "source_file":     filename,
                        "source_email_id": msg_id,
                        "email_sent":      0,
                        "error":           str(exc),
                    })
                except Exception:
                    pass

        # f) Mark the whole email as read after all attachments are processed
        try:
            mark_as_read(msg_id)
        except Exception as exc:
            log.error("mark_as_read failed for %s: %s", msg_id, exc)

    log.info("=== CV scan complete — %d email(s) processed ===", len(emails))
