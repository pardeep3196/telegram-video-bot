import logging, json, time, os, random
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")          # Render me set karna
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # Admin ka Telegram ID
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0"))  # Private channel id jahan videos upload hote hain
ADS_LINK_MAIN = os.getenv("ADS_LINK", "https://example.com")  # Shortlink

TOKEN_HOURS = 24
TOKEN_SECONDS = TOKEN_HOURS * 60 * 60

TOKENS_FILE = "/data/tokens.json"
VIDEOS_FILE = "/data/videos.json"
# ==========================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# ---------- JSON helpers ----------
def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return default
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f)

# ---------- Token System ----------
def has_valid_token(user_id: int) -> bool:
    tokens = load_json(TOKENS_FILE, {})
    exp = tokens.get(str(user_id))
    return bool(exp and exp > int(time.time()))

def refresh_token(user_id: int):
    tokens = load_json(TOKENS_FILE, {})
    tokens[str(user_id)] = int(time.time()) + TOKEN_SECONDS
    save_json(TOKENS_FILE, tokens)

def expire_token(user_id: int):
    tokens = load_json(TOKENS_FILE, {})
    if str(user_id) in tokens:
        del tokens[str(user_id)]
    save_json(TOKENS_FILE, tokens)

# ---------- Video Storage ----------
def add_video(file_id: str, title: str):
    db = load_json(VIDEOS_FILE, {"videos": []})
    if not any(v["file_id"] == file_id for v in db["videos"]):
        db["videos"].append({"file_id": file_id, "title": title, "ts": int(time.time())})
        save_json(VIDEOS_FILE, db)

def get_random_video():
    db = load_json(VIDEOS_FILE, {"videos": []})
    if not db["videos"]:
        return None
    return random.choice(db["videos"])

# ---------- UI ----------
def main_menu():
    return ReplyKeyboardMarkup(
        [["English", "Indian"], ["Desi Mix", "Pakistani"]],
        resize_keyboard=True
    )

async def send_video_with_next(user_id: int, context: ContextTypes.DEFAULT_TYPE):
    video = get_random_video()
    if not video:
        await context.bot.send_message(user_id, "📭 No videos available yet.")
        return

    keyboard = [[InlineKeyboardButton("⏭ NEXT", callback_data="next_video")]]
    when = datetime.utcfromtimestamp(video["ts"]).strftime("%Y-%m-%d %H:%M UTC")
    caption = f"🎬 {video['title']} • {when}"

    await context.bot.send_video(
        chat_id=user_id,
        video=video["file_id"],
        caption=caption,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args

    # User came back from ads
    if args and args[0].startswith("refresh"):
        refresh_token(user_id)
        await update.message.reply_text("✅ Token refreshed for 24 hours!", reply_markup=main_menu())
        await send_video_with_next(user_id, context)
        return

    if has_valid_token(user_id):
        await update.message.reply_text("🎉 Welcome back!", reply_markup=main_menu())
        await send_video_with_next(user_id, context)
    else:
        keyboard = [[InlineKeyboardButton("🔄 Refresh Token", url=ADS_LINK_MAIN)]]
        await update.message.reply_text(
            "⏳ Your ads token expired.\nWatch ad to refresh (valid 24h), then return to bot.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def next_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not has_valid_token(user_id):
        keyboard = [[InlineKeyboardButton("🔄 Refresh Token", url=ADS_LINK_MAIN)]]
        await query.edit_message_text(
            "⚠️ Token expired. Refresh to continue.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    await send_video_with_next(user_id, context)

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    choice = update.message.text

    if choice in ["English", "Indian", "Desi Mix", "Pakistani"]:
        if not has_valid_token(user_id):
            keyboard = [[InlineKeyboardButton("🔄 Refresh Token", url=ADS_LINK_MAIN)]]
            await update.message.reply_text("⚠️ Token expired.", reply_markup=InlineKeyboardMarkup(keyboard))
            return

        await update.message.reply_text(f"🎥 Category selected: {choice}")
        await send_video_with_next(user_id, context)

async def expire_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    expire_token(update.effective_user.id)
    await update.message.reply_text("⛔ Your token has expired. Use /start to refresh again.")

async def on_channel_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if msg and msg.video:
        title = msg.caption or f"Video {msg.message_id}"
        add_video(msg.video.file_id, title)
        logging.info(f"Saved channel video: {title}")

async def on_admin_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID and update.message.video:
        file_id = update.message.video.file_id
        title = update.message.caption or f"Admin Video {update.message.message_id}"
        add_video(file_id, title)
        await update.message.reply_text(f"✅ Saved video: {title}")

# ---------- Main ----------
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("expire", expire_command))
    app.add_handler(CallbackQueryHandler(next_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_handler(MessageHandler(filters.ChatType.CHANNEL & filters.VIDEO, on_channel_video))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.VIDEO, on_admin_video))

    print("🤖 Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
