import os, json, time, random, logging
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

# ===================== CONFIG =====================
# Railway/Local: env se le lo; defaults diye hue hain taaki locally bhi run ho jaye.
BOT_TOKEN = os.getenv("BOT_TOKEN")  # <-- Railway me zaroor set karein
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN missing. Railway → Variables me BOT_TOKEN add karo.")

BOT_USERNAME = os.getenv("BOT_USERNAME", "YourBotUsernameWithoutAt")  # without @
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))           # Optional: sirf is ID ko admin upload allow (0 = allow all)
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))       # Optional: agar channel handler chahiye

# Ads shortlink (Recommended):
ADS_LINK = os.getenv("ADS_LINK", "")  # agar blank hua to deep-link fallback use hoga
# ==================================================

# ================ TOKEN SETTINGS ==================
TOKEN_HOURS = 24
TOKEN_SECONDS = TOKEN_HOURS * 60 * 60
# ==================================================

# ================ STORAGE PATHS ===================
DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
TOKENS_FILE = DATA_DIR / "tokens.json"
VIDEOS_FILE = DATA_DIR / "videos.json"
# ==================================================

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger("bot")

# ----------------- Utils & Storage ----------------
def ensure_storage():
    """Create data dir & files if missing."""
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

# ----------------- Token System -------------------
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

# --------------- Video Storage --------------------
def add_video(file_id: str, title: str):
    db = read_json(VIDEOS_FILE, {"videos": []})
    videos = db.get("videos", [])
    if not any(v.get("file_id") == file_id for v in videos):
        videos.append({"file_id": file_id, "title": title, "ts": _now()})
        db["videos"] = videos
        write_json(VIDEOS_FILE, db)

def get_random_video() -> Optional[Dict[str, Any]]:
    db = read_json(VIDEOS_FILE, {"videos": []})
    vids = db.get("videos", [])
    if not vids:
        return None
    # Random from all saved (can be biased to latest if you want)
    return random.choice(vids)

# --------------- UI Helpers -----------------------
CATEGORIES = ["English", "Indian", "Desi Mix", "Pakistani"]

def main_menu() -> ReplyKeyboardMarkup:
    rows = [CATEGORIES[:2], CATEGORIES[2:]]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def refresh_button_url() -> str:
    """Prefer ADS_LINK; otherwise deep-link back to bot with ?start=refresh."""
    if ADS_LINK.strip():
        return ADS_LINK.strip()
    return f"https://t.me/{BOT_USERNAME}?start=refresh"

async def send_video_with_next(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    video = get_random_video()
    if not video:
        await context.bot.send_message(
            chat_id=user_id,
            text="📭 No videos available yet. Ask admin to add some."
        )
        return

    when = datetime.utcfromtimestamp(video["ts"]).strftime("%Y-%m-%d %H:%M UTC")
    caption = f"🎬 {video['title']} • {when}"
    keyboard = [[InlineKeyboardButton("⏭ NEXT", callback_data="next_video")]]

    await context.bot.send_video(
        chat_id=user_id,
        video=video["file_id"],
        caption=caption,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ------------------- Handlers ---------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_storage()

    user = update.effective_user
    user_id = user.id if user else 0
    args = context.args

    log.info("START from %s args=%s", user_id, args)

    # 2) Refresh token via deep-link: /start refresh...
    if args and len(args) > 0 and args[0].lower().startswith("refresh"):
        refresh_token(user_id)
        await update.message.reply_text(
            "✅ Token refreshed for 24 hours!",
            reply_markup=main_menu()
        )
        await send_video_with_next(user_id, context)
        return

    # 1) If token valid → send a random video + menu
    if has_valid_token(user_id):
        await update.message.reply_text("🎉 Welcome back!", reply_markup=main_menu())
        await send_video_with_next(user_id, context)
        return

    # If token expired → show Refresh button (shortlink or deep-link)
    btn_url = refresh_button_url()
    await update.message.reply_text(
        "⏳ Your ads token expired.\nWatch the ad to refresh (valid 24h), then return to the bot.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔄 Refresh Token", url=btn_url)]]
        )
    )

async def on_next(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not has_valid_token(user_id):
        btn_url = refresh_button_url()
        await query.edit_message_text(
            "⚠️ Token expired. Refresh to continue.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔄 Refresh Token", url=btn_url)]]
            )
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
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("🔄 Refresh Token", url=btn_url)]]
                )
            )
            return

        await update.message.reply_text(f"🎥 Category selected: {choice}")
        await send_video_with_next(user_id, context)
    else:
        # Ignore random text / or guide
        await update.message.reply_text(
            "Use the menu below or /start.",
            reply_markup=main_menu()
        )

async def expire_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_storage()
    user_id = update.effective_user.id
    expire_token(user_id)
    await update.message.reply_text(
        "⛔ Your token has expired. Use /start after watching ads to refresh."
    )

async def on_channel_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save videos posted in the configured private channel."""
    ensure_storage()
    msg = update.channel_post
    if not msg or not msg.video:
        return

    if CHANNEL_ID and msg.chat and msg.chat.id != CHANNEL_ID:
        # Ignore other channels if CHANNEL_ID is set
        return

    title = (msg.caption or "").strip() or f"Video {msg.message_id}"
    add_video(msg.video.file_id, title)
    log.info("Saved channel video: %s", title)

async def on_admin_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin can DM a video to the bot to save it."""
    ensure_storage()
    msg = update.message
    if not msg or not msg.video:
        return

    # If ADMIN_ID is set (>0), restrict; else allow any sender.
    if ADMIN_ID > 0 and update.effective_user.id != ADMIN_ID:
        await msg.reply_text("🚫 Only admin can add videos.")
        return

    title = (msg.caption or "").strip() or f"Admin Video {msg.message_id}"
    add_video(msg.video.file_id, title)
    await msg.reply_text(f"✅ Saved video: {title}")

# ------------------- Main ------------------------
def main():
    ensure_storage()
    app = Application.builder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("expire", expire_cmd))

    # Buttons
    app.add_handler(CallbackQueryHandler(on_next, pattern=r"^next_video$"))

    # Text (bottom menu)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_category))

    # Channel: auto-save videos
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL & filters.VIDEO, on_channel_video))

    # Admin DM: save video
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.VIDEO, on_admin_video))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
