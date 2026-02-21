# pip install requests python-dotenv
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(env_path)

phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
meta_token = os.getenv("meta_token")

url = f"https://graph.facebook.com/v22.0/{phone_number_id}/messages"
headers = {
    "Authorization": f"Bearer {meta_token}",
    "Content-Type": "application/json",
}
payload = {
    # Template required for first contact — plain text only works after recipient replies (24h window rule)
    "messaging_product": "whatsapp",
    "to": "+5548991552841",
    "type": "template",
    "template": {
        "name": "hello_world",
        "language": {"code": "en_US"},
    },
}

response = requests.post(url, headers=headers, json=payload)
print(response.status_code)
print(response.json())
