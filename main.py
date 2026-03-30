import os
import asyncio
import logging
from pyrogram import Client, filters, idle
from pyrogram.types import Message

logging.basicConfig(level=logging.DEBUG)  # DEBUG level to see everything
logger = logging.getLogger(__name__)

API_ID    = int(os.environ["TELEGRAM_API_ID"])
API_HASH  = os.environ["TELEGRAM_API_HASH"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

bot = Client("testbot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message()
async def catch_all(client, message: Message):
    logger.info(f"GOT MESSAGE from {message.from_user.id}: {message.text}")
    await message.reply("✅ I received your message!")

async def main():
    await bot.start()
    logger.info("Bot started")
    await idle()

asyncio.run(main())
