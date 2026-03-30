import os
import asyncio
import logging
from pyrogram import Client, filters, idle
from pyrogram.types import Message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_ID    = int(os.environ["TELEGRAM_API_ID"])
API_HASH  = os.environ["TELEGRAM_API_HASH"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# NO userbot — just the bot alone
bot = Client(
    "solobot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)

@bot.on_message()
async def catch_all(client, message: Message):
    logger.info(f"MESSAGE RECEIVED from {message.from_user.id}: {message.text}")
    await message.reply(f"✅ Hello! Your ID: `{message.from_user.id}`")

async def main():
    await bot.start()
    logger.info("Solo bot started — send me anything!")
    await idle()

asyncio.run(main())
