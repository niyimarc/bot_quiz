# check_webhook.py
import asyncio
from telegram import Bot
import os
from dotenv import load_dotenv

load_dotenv()
bot = Bot(token=os.getenv("BOT_TOKEN"))

async def check():
    info = await bot.get_webhook_info()
    print(info)

asyncio.run(check())
