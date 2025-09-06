import os, json, time, random, logging, requests
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN missing. Railway → Variables me BOT_TOKEN add karo.")

BOT_USERNAME = os.getenv("BOT_USERNAME", "EagleEyeSignals_bot")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))

# GPLinks API Token
GPLINKS_API = os.getenv("GPLINKS_API", "")

TOKEN_HOURS = 24
TOKEN_SECONDS = TOKEN_HOURS * 60 * 60

DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
TOKENS_FILE = DATA_DIR / "tokens.json"
VIDEOS_FILE = DATA_DIR / "videos.json"

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger("bot")

# Track last sent message for auto-delete
ACTIVE_MESSAGES: Dict[int, int] = {}

# ============== STORAGE HELPERS ==============
def ensure_storage():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not TOKENS_FILE.exists():
        TOKENS_FILE.write_text(json.dumps({}, ensure_ascii=False))
    if not VIDEOS_FILE.exists():
        VIDEOS_FILE.write_text(json.dumps({"videos": []}, ensure_ascii=False))

def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default

def write_json(path: Path, data: Any):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(path)

# ============== TOKEN SYSTEM ==============
def _now() -> int:
    return int(time.time())

def has_valid_token(user_id: int) -> bool:
    db: Dict[str, int] = read_json(TOKENS_FILE, {})
    exp = db.get(str(user_id))
    return bool(exp and exp > _now())

def refresh_token(user_id: int):
    db: Dict[str, int] = read_json(TOKENS_FILE, {})
    db[str(user_id)] = _now() + TOKEN_SECONDS
    write_json(TOKENS_FILE, db)

def expire_token(user_id: int):
    db: Dict[str, int] = read_json(TOKENS_FILE, {})
    if str(user_id) in db:
        del db[str(user_id)]
        write_json(TOKENS_FILE, db)

# ============== VIDEO STORAGE ==============
def add_video(file_id: str, title: str, duration: int = 0):
    db = read_json(VIDEOS_FILE, {"videos": []})
    videos = db.get("videos", [])
    if not any(v.get("file_id") == file_id for v in videos):
        videos.append({"file_id": file_id, "title": title, "ts": _now(), "duration": duration})
        db["videos"] = videos
        write_json(VIDEOS_FILE, db)

def get_random_video(category: Optional[str] = None) -> Optional[Dict[str, Any]]:
    db = read_json(VIDEOS_FILE, {"videos": []})
    vids = db.get("videos", [])
    if not vids:
        return None
    if category:
        vids = [v for v in vids if f"#{category.lower()}" in v["title"].lower()]
    if not vids:
        return None
    return random.choice(vids)

# ============== UI HELPERS ==============
CATEGORIES = ["Instagram Viral", "Viral Memes", "Desi Leaked", "18+"]

def main_menu() -> ReplyKeyboardMarkup:
    rows = [CATEGORIES[:2], CATEGORIES[2:]]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def make_gplink(url: str) -> str:
    if not GPLINKS_API:
        return url
    try:
        api_url = f"https://api.gplinks.com/api?api={GPLINKS_API}&url={url}&format=text"
        r = requests.get(api_url, timeout=10)
        if r.status_code == 200 and r.text.strip():
            return r.text.strip()
    except Exception as e:
        log.warning(f"GPLinks failed: {e}")
    return url

def refresh_button_url() -> str:
    target = f"https://t.me/{BOT_USERNAME}?start=refresh"
    return make_gplink(target)

def see_more_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("▶️ See More", callback_data="next_video")]])

async def auto_delete_message(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    user_id, msg_id = job.data

    try:
        await context.bot.delete_message(chat_id=user_id, message_id=msg_id)
        await context.bot.send_animation(
            chat_id=user_id,
            animation="https://media.giphy.com/media/j5QcmXoFWl4Q0/giphy.gif",  # Example GIF
            caption="⏳ This video was auto-deleted after expiry.\n\n👉 To continue watching, click below.",
            reply_markup=see_more_kb()
        )
    except Exception as e:
        log.warning(f"Auto-delete failed: {e}")

# ============== SEND VIDEO ==============
async def send_video_with_next(user_id: int, context: ContextTypes.DEFAULT_TYPE, category: Optional[str] = None):
    video = get_random_video(category)
    if not video:
        await context.bot.send_message(
            chat_id=user_id,
            text="📭 No videos available yet. Ask admin to add some."
        )
        return

    if user_id in ACTIVE_MESSAGES:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=ACTIVE_MESSAGES[user_id])
        except:
            pass

    when = datetime.utcfromtimestamp(video["ts"]).strftime("%Y-%m-%d %H:%M UTC")
    caption = f"🎬 {video['title']} • {when}"
    keyboard = [[InlineKeyboardButton("⏭ NEXT", callback_data="next_video")]]

    msg = await context.bot.send_video(
        chat_id=user_id,
        video=video["file_id"],
        caption=caption,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    ACTIVE_MESSAGES[user_id] = msg.message_id

    duration = video.get("duration", 0) or 0
    delete_after = (duration + 300) if duration > 0 else 600
    context.job_queue.run_once(
        auto_delete_message,
        when=delete_after,
        data=(user_id, msg.message_id),
        name=f"del_{user_id}_{msg.message_id}"
    )

# ============== HANDLERS ==============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_storage()
    user_id = update.effective_user.id
    args = context.args

    if args and len(args) > 0 and args[0].lower().startswith("refresh"):
        refresh_token(user_id)
        await update.message.reply_text("✅ Token refreshed for 24 hours!", reply_markup=main_menu())
        await send_video_with_next(user_id, context)
        return

    if has_valid_token(user_id):
        await update.message.reply_text("🎉 Welcome back!", reply_markup=main_menu())
        await send_video_with_next(user_id, context)
        return

    btn_url = refresh_button_url()
    await update.message.reply_text(
        "⏳ Your token expired.\nTap below, watch the ad, then return to bot.",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh Token", url=btn_url)]])
    )

async def on_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not has_valid_token(user_id):
        btn_url = refresh_button_url()
        await query.edit_message_text(
            "⚠️ Token expired. Refresh to continue.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh Token", url=btn_url)]])
        )
        return

    await send_video_with_next(user_id, context)

async def on_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_storage()
    user_id = update.effective_user.id
    choice = (update.message.text or "").strip()

    if choice in CATEGORIES:
        if not has_valid_token(user_id):
            btn_url = refresh_button_url()
            await update.message.reply_text(
                "⚠️ Token expired.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Refresh Token", url=btn_url)]])
            )
            return
        await update.message.reply_text(f"🎥 Category selected: {choice}")
        await send_video_with_next(user_id, context, category=choice)
    else:
        await update.message.reply_text("Use the menu below or /start.", reply_markup=main_menu())

async def expire_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    expire_token(user_id)
    await update.message.reply_text("⛔ Your token has expired. Use /start after watching ads to refresh.")

async def on_channel_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_storage()
    msg = update.channel_post
    if not msg or not msg.video:
        return
    if CHANNEL_ID and msg.chat and msg.chat.id != CHANNEL_ID:
        return
    title = (msg.caption or "").strip() or f"Video {msg.message_id}"
    duration = msg.video.duration or 0
    add_video(msg.video.file_id, title, duration)
    log.info("Saved channel video: %s", title)

async def on_admin_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_storage()
    msg = update.message
    if not msg or not msg.video:
        return
    if ADMIN_ID > 0 and update.effective_user.id != ADMIN_ID:
        await msg.reply_text("🚫 Only admin can add videos.")
        return
    title = (msg.caption or "").strip() or f"Admin Video {msg.message_id}"
    duration = msg.video.duration or 0
    add_video(msg.video.file_id, title, duration)
    await msg.reply_text(f"✅ Saved video: {title}")

# ============== MAIN ==============
def main():
    ensure_storage()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("expire", expire_cmd))
    app.add_handler(CallbackQueryHandler(on_next, pattern=r"^next_video$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_category))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL & filters.VIDEO, on_channel_video))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.VIDEO, on_admin_video))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
