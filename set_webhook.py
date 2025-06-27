from telegram import Bot
import os
import asyncio
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

async def main():
    bot = Bot(token=BOT_TOKEN)
    success = await bot.set_webhook(WEBHOOK_URL)
    print("Webhook set:", success)

if __name__ == "__main__":
    asyncio.run(main())
