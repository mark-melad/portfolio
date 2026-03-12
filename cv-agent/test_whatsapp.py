import os, sys
import requests
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
import tools

TOKEN    = os.getenv("WHATSAPP_TOKEN")
PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")

# ── 1. Check phone number details registered on this Phone ID ──
print("\n-- Phone Number Info --")
r = requests.get(
    f"https://graph.facebook.com/v19.0/{PHONE_ID}",
    headers={"Authorization": f"Bearer {TOKEN}"},
    params={"fields": "display_phone_number,verified_name,quality_rating,status,platform_type"}
)
print(f"  Status: {r.status_code}")
print(f"  Body  : {r.json()}")

# ── 2. Send a fresh message and print raw Meta response ──
print("\n-- Sending WhatsApp message (raw response) --")
url     = f"https://graph.facebook.com/v19.0/{PHONE_ID}/messages"
headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
payload = {
    "messaging_product": "whatsapp",
    "recipient_type":    "individual",
    "to":                "201204781311",
    "type":              "text",
    "text":              {"preview_url": False, "body": "Test message from CV Intake Agent"},
}
r2 = requests.post(url, headers=headers, json=payload, timeout=15)
print(f"  Status: {r2.status_code}")
print(f"  Body  : {r2.json()}")
