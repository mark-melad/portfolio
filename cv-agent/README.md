# CV Intake Agent

## Overview
Monitors Gmail for LinkedIn Easy Apply emails, extracts CV contact info using
Llama 3.3 70B (Groq), and sends welcome emails automatically.

## Prerequisites
- Python 3.10+
- A Gmail account
- Groq API key (console.groq.com)

## Setup

### 1. Groq API Key
Sign up at https://console.groq.com and create an API key.
Add it to `.env` as `GROQ_API_KEY`.

### 2. Gmail OAuth2 Credentials
1. Go to https://console.cloud.google.com
2. Create a new project
3. Enable the Gmail API
4. Go to **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
5. Application type: **Desktop App**
6. Download the JSON file and save it as `credentials.json` in the project root
7. Set `GMAIL_CREDENTIALS_PATH=./credentials.json` in `.env`

### 3. Gmail App Password (for sending emails)
1. Enable 2-Step Verification on your Google account
2. Go to **Google Account → Security → App Passwords**
3. Generate a password for "Mail"
4. Add it to `.env` as `SMTP_PASSWORD`

### 4. Configure .env
```bash
cp .env.example .env
# then open .env and fill in all values
```

| Key | Description |
|-----|-------------|
| `GROQ_API_KEY` | Groq API key from console.groq.com |
| `GMAIL_CREDENTIALS_PATH` | Path to your OAuth2 credentials JSON |
| `SENDER_EMAIL` | Gmail address used to send welcome emails |
| `SMTP_PASSWORD` | Gmail App Password (not your account password) |
| `SCAN_INTERVAL_SECONDS` | How often to poll inbox (default: 60) |
| `WELCOME_MESSAGE` | Body text inserted in welcome emails |

### 5. Virtual Environment & Dependencies
```bash
python -m venv venv

# macOS / Linux
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt
```

## Run
```bash
uvicorn main:app --reload --port 8000
```

On first run a browser window will open for Gmail OAuth consent.
After authorising, `token.json` is saved and future runs are headless.

Open **http://localhost:8000** to view the dashboard.

## Dashboard Features
- **Stats row** — total CVs processed, emails sent, pending, errors
- **Scan Now** button — trigger an immediate inbox scan
- **Live table** — all candidates with status pills (Sent / Pending / Error)
- **Auto-refresh** — table and stats update every 10 seconds

## File Reference

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app, routes, APScheduler background job |
| `tools.py` | DB helpers, Gmail client, CV parser, AI extraction, email sender, scan orchestrator |
| `frontend/index.html` | Single-file dark dashboard (no build tools) |
| `.env` | Secret config — **never commit** |
| `.env.example` | Template with empty values — safe to commit |
| `credentials.json` | Gmail OAuth client secrets — **never commit** |
| `token.json` | Saved OAuth token — **never commit** |
| `candidates.db` | SQLite database — auto-created on first run |
| `venv/` | Python virtual environment — **never commit** |

## Supported CV Formats

| Format | Parser |
|--------|--------|
| `.pdf` | pypdf |
| `.docx` | python-docx |
| `.doc` | mammoth |
| `.txt` | built-in |
| `.rtf` | striprtf |
| `.odt` | odfpy |
| `.png/.jpg/.jpeg` | base64 encoded, model returns nulls |
| other | UTF-8 decode attempt |
