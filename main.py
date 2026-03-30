import os
import asyncio
import logging
import tempfile
from pathlib import Path
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import googleapiclient.discovery
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
API_ID         = int(os.environ["TELEGRAM_API_ID"])
API_HASH       = os.environ["TELEGRAM_API_HASH"]
BOT_TOKEN      = os.environ["TELEGRAM_BOT_TOKEN"]
SESSION_STRING = os.environ["PYROGRAM_SESSION_STRING"]
OWNER_ID       = int(os.environ["OWNER_TELEGRAM_ID"])
PRIVACY        = "private"

YT_CLIENT_ID     = os.environ["YT_CLIENT_ID"]
YT_CLIENT_SECRET = os.environ["YT_CLIENT_SECRET"]
YT_REFRESH_TOKEN = os.environ["YT_REFRESH_TOKEN"]

pending: dict = {}


# ── Title generator ───────────────────────────────────────────────────────────

def generate_title(message: Message) -> str:
    for attr in (message.video, message.document):
        if attr and getattr(attr, "file_name", None):
            stem = Path(attr.file_name).stem
            if stem:
                return _clean(stem)
    if message.caption:
        first_line = message.caption.strip().splitlines()[0]
        if first_line:
            return _clean(first_line[:100])
    ts = datetime.now().strftime("%Y-%m-%d %H-%M")
    return f"Video {ts}"


def _clean(name: str) -> str:
    return name.replace("_", " ").replace("-", " ").strip()


# ── YouTube helpers ───────────────────────────────────────────────────────────

def get_youtube_client():
    creds = Credentials(
        token=None,
        refresh_token=YT_REFRESH_TOKEN,
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
    )
    creds.refresh(Request())
    return googleapiclient.discovery.build("youtube", "v3", credentials=creds)


def upload_to_youtube(file_path: str, title: str, description: str = "") -> str:
    youtube = get_youtube_client()
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": PRIVACY,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(
        file_path,
        mimetype="video/*",
        resumable=True,
        chunksize=10 * 1024 * 1024,
    )
    insert_request = youtube.videos().insert(
        part="snippet,status", body=body, media_body=media
    )
    response = None
    while response is None:
        status, response = insert_request.next_chunk()
        if status:
            logger.info(f"YT upload progress: {int(status.progress() * 100)}%")
    return f"https://youtu.be/{response['id']}"


# ── Pyrogram clients ──────────────────────────────────────────────────────────

userbot = Client(
    "userbot",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

bot = Client(
    "ytbot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
)


def _confirm_keyboard(msg_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Upload", callback_data=f"upload:{msg_id}"),
            InlineKeyboardButton("✏️ Edit title", callback_data=f"edit:{msg_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel:{msg_id}"),
        ]
    ])


# ── Bot handlers ──────────────────────────────────────────────────────────────

@bot.on_message(
    (filters.video | filters.document) & filters.user(OWNER_ID)
)
async def handle_video(client: Client, message: Message):
    title = generate_title(message)
    status_msg = await message.reply(
        f"📹 **Video detected!**\n\n"
        f"🏷 Auto-title: `{title}`\n"
        f"🔒 Privacy: `private`\n\n"
        f"Tap **Upload** to proceed, **Edit title** to rename, or **Cancel**.",
        reply_markup=_confirm_keyboard(message.id),
    )
    pending[message.id] = {
        "path": None,
        "title": title,
        "original_msg": message,
        "status_msg_id": status_msg.id,
        "awaiting_title": False,
    }


@bot.on_callback_query(filters.user(OWNER_ID))
async def handle_callback(client: Client, query: CallbackQuery):
    action, raw_id = query.data.split(":", 1)
    msg_id = int(raw_id)

    if msg_id not in pending:
        await query.answer("Session expired. Forward the video again.", show_alert=True)
        return

    info = pending[msg_id]

    if action == "cancel":
        pending.pop(msg_id)
        await query.message.edit("❌ Upload cancelled.")
        await query.answer()

    elif action == "edit":
        info["awaiting_title"] = True
        await query.message.edit(
            f"✏️ Current title: `{info['title']}`\n\n"
            "Reply to this message with the new title:"
        )
        await query.answer()

    elif action == "upload":
        await query.answer("Starting download…")
        await _do_download_and_upload(client, query.message, msg_id)


@bot.on_message(filters.text & filters.user(OWNER_ID) & filters.reply)
async def handle_title_edit(client: Client, message: Message):
    target_id = None
    for orig_id, info in pending.items():
        if info["status_msg_id"] == message.reply_to_message_id and info.get("awaiting_title"):
            target_id = orig_id
            break
    if target_id is None:
        return

    info = pending[target_id]
    new_title = message.text.strip().splitlines()[0][:100]
    info["title"] = new_title
    info["awaiting_title"] = False

    await message.reply(
        f"✅ Title updated to: `{new_title}`\n"
        f"🔒 Privacy: `private`",
        reply_markup=_confirm_keyboard(target_id),
    )


async def _do_download_and_upload(client: Client, status_msg: Message, msg_id: int):
    info = pending.get(msg_id)
    if not info:
        return

    original_msg = info["original_msg"]
    title = info["title"]

    await status_msg.edit(f"⬇️ Downloading `{title}` via userbot (no size limit)…")

    try:
        tmp_dir = tempfile.mkdtemp()
        file_path = await userbot.download_media(
            original_msg,
            file_name=os.path.join(tmp_dir, "video.mp4"),
        )
        logger.info(f"Downloaded to {file_path}")
    except Exception as e:
        await status_msg.edit(f"❌ Download failed:\n`{e}`")
        pending.pop(msg_id, None)
        return

    info["path"] = file_path
    await status_msg.edit(f"✅ Downloaded!\n🚀 Uploading **{title}** to YouTube (private)…")

    try:
        loop = asyncio.get_event_loop()
        url = await loop.run_in_executor(
            None, upload_to_youtube, file_path, title, ""
        )
        await status_msg.edit(
            f"✅ **Upload complete!**\n\n"
            f"🎬 `{title}`\n"
            f"🔒 Private\n"
            f"🔗 {url}"
        )
    except Exception as e:
        logger.exception("YouTube upload failed")
        await status_msg.edit(f"❌ YouTube upload failed:\n`{e}`")
    finally:
        pending.pop(msg_id, None)
        try:
            Path(file_path).unlink(missing_ok=True)
            Path(file_path).parent.rmdir()
        except Exception:
            pass


@bot.on_message(filters.command("start") & filters.user(OWNER_ID))
async def cmd_start(client: Client, message: Message):
    await message.reply(
        "👋 **YouTube Uploader Bot**\n\n"
        "Forward any video — title is auto-generated from filename or date, "
        "uploaded as **private** to your YouTube channel.\n\n"
        "Commands:\n"
        "`/start` – this message\n"
        "`/cancel` – clear all pending uploads\n"
        "`/pending` – list pending uploads"
    )


@bot.on_message(filters.command("cancel") & filters.user(OWNER_ID))
async def cmd_cancel(client: Client, message: Message):
    count = len(pending)
    pending.clear()
    await message.reply(f"🗑️ Cleared {count} pending upload(s).")


@bot.on_message(filters.command("pending") & filters.user(OWNER_ID))
async def cmd_pending(client: Client, message: Message):
    if not pending:
        await message.reply("✅ No pending uploads.")
        return
    lines = [f"• `{info['title']}`" for info in pending.values()]
    await message.reply("⏳ **Pending uploads:**\n" + "\n".join(lines))


# ── Entry point ───────────────────────────────────────────────────────────────

async def main():
    await userbot.start()
    logger.info("Userbot started")
    await bot.start()
    logger.info("Bot started – waiting for videos…")
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
```

---

## `requirements.txt`
```
pyrogram==2.0.106
tgcrypto==1.2.5
google-api-python-client==2.118.0
google-auth==2.28.0
google-auth-httplib2==0.2.0
google-auth-oauthlib==1.2.0
httplib2==0.22.0
