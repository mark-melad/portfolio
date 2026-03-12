import os
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from apscheduler.schedulers.background import BackgroundScheduler

import tools

app = FastAPI(title="CV Intake Agent")
scheduler = BackgroundScheduler()


@app.on_event("startup")
def startup_event():
    tools.init_db()

    interval = int(os.getenv("SCAN_INTERVAL_SECONDS", "60"))
    scheduler.add_job(tools.run_scan, "interval", seconds=interval, id="cv_scan")
    scheduler.start()


@app.on_event("shutdown")
def shutdown_event():
    scheduler.shutdown(wait=False)


@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    html_path = Path(__file__).parent / "frontend" / "index.html"
    return HTMLResponse(content=html_path.read_text(encoding="utf-8"))


@app.get("/candidates")
def list_candidates():
    return JSONResponse(content=tools.get_all_candidates())


@app.post("/scan-now")
def scan_now():
    tools.run_scan()
    return {"status": "ok"}


@app.get("/stats")
def stats():
    return JSONResponse(content=tools.get_stats())


# ── WhatsApp Webhook ──────────────────────────────────────────────────────────

@app.get("/webhook/whatsapp")
def whatsapp_verify(request: Request):
    """Meta webhook verification handshake."""
    params        = request.query_params
    mode          = params.get("hub.mode")
    token         = params.get("hub.verify_token")
    challenge     = params.get("hub.challenge")
    verify_token  = os.getenv("WHATSAPP_VERIFY_TOKEN", "cv-agent-verify")

    if mode == "subscribe" and token == verify_token:
        return PlainTextResponse(content=challenge)
    return JSONResponse(status_code=403, content={"error": "Forbidden"})


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request):
    """Receive message status updates from Meta."""
    try:
        body = await request.json()
        for entry in body.get("entry", []):
            for change in entry.get("changes", []):
                value    = change.get("value", {})
                statuses = value.get("statuses", [])
                for status in statuses:
                    msg_id    = status.get("id")
                    state     = status.get("status")   # sent | delivered | read | failed
                    recipient = status.get("recipient_id")
                    tools.log.info(
                        "WhatsApp status update — msg_id=%s state=%s recipient=%s",
                        msg_id, state, recipient
                    )
                    tools.handle_whatsapp_status(msg_id, state, recipient)
    except Exception as exc:
        tools.log.error("WhatsApp webhook error: %s", exc)
    return JSONResponse(content={"status": "ok"})
