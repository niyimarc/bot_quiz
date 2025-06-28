import requests
import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

resp = requests.post(
    f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
    data={"url": WEBHOOK_URL}
)

print(resp.json())
