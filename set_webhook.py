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

# async def clear_webhook():
#     bot = Bot(token=BOT_TOKEN)
#     await bot.delete_webhook(drop_pending_updates=True)
#     await bot.set_webhook(WEBHOOK_URL)


if __name__ == "__main__":
    asyncio.run(main())
