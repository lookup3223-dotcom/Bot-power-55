# =========================================================
#  PRODUCT SELLING TELEGRAM BOT  (Updated v3)
#  Library: python-telegram-bot v20+   (pip install python-telegram-bot)
#
#  What's new in this version:
#   - /start now supports MULTIPLE photos/videos (albums) — add as many
#     as you want (up to 30) with /addstartmedia (reply to each photo/video)
#   - ALL start photos/videos are sent as SPOILER (blurred until tapped)
#   - All bot messages are BOLD (thick text)
#   - Buttons decorated with colorful emojis
#     (Telegram does NOT allow real button colors — emojis are the only way)
#   - UNLIMITED custom commands: /addcmd, /delcmd, /cmdlist
#     (e.g. /addcmd help  -> users can type /help and get your saved reply)
#   - /panel shows every command including the new ones
#
#  Setup:
#   1) Put your @BotFather token in BOT_TOKEN
#   2) Put your Telegram numeric ID in OWNER_ID
#      (don't know it? start the bot and send /myid)
#   3) Run:  python product_bot.py
# =========================================================

import html
import json
import logging
import os
import re
from datetime import datetime

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================= PUT YOUR DETAILS HERE =================
BOT_TOKEN = "8948088783:AAF1ahSPgtx1Muu_XMV-JEyGovQpnHAkab4"
OWNER_ID = 8058735418  # your Telegram numeric ID (use /myid)
# =========================================================

CONFIG_FILE = "bot_config.json"
MAX_START_MEDIA = 30  # max photos/videos in the /start albums

logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)


# ---------------- CONFIG ----------------

def default_config():
    return {
        "start_message": "👋 Welcome!\n\nChoose a product from the buttons below to see details and buy.",
        "start_media": [],  # list of {"type": "photo"/"video", "file_id": "..."}
        "payment_text": (
            "💳 Payment Instructions\n\n"
            "1️⃣ Scan the QR code above and complete the payment.\n"
            "2️⃣ Take a screenshot of the successful payment.\n"
            "3️⃣ Send that screenshot here in this chat.\n\n"
            "✅ As soon as an admin verifies your payment, your product will be delivered automatically."
        ),
        "qr_file_id": None,
        "admins": [],
        "buttons": {
            str(i): {
                "title": f"Product {i}",
                "media_type": None,        # "photo" or "video"
                "media_file_id": None,
                "caption": f"Details for Product {i} have not been set yet.",
                "delivery_type": "text",   # text / photo / video / document
                "delivery_file_id": None,
                "delivery_text": "🎉 Your payment has been approved!\nThank you for your purchase.",
            }
            for i in range(1, 6)
        },
        "custom_cmds": {},  # command name -> {"type": ..., "file_id": ..., "text": ...}
        "pending": {},      # user_id -> product number (waiting for payment screenshot)
    }


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            base = default_config()
            base.update(cfg)
            # Migrate from the old single start photo/video format
            if not base.get("start_media") and cfg.get("start_media_file_id"):
                base["start_media"] = [{
                    "type": cfg.get("start_media_type") or "photo",
                    "file_id": cfg["start_media_file_id"],
                }]
            return base
        except Exception:
            pass
    return default_config()


def save_config():
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(CFG, f, ensure_ascii=False, indent=2)


CFG = load_config()


# ---------------- HELPERS ----------------

def B(text: str) -> str:
    """Make text BOLD (thick) and safe to send. Line breaks are preserved."""
    return f"<b>{html.escape(text)}</b>"


def is_admin(uid: int) -> bool:
    return uid == OWNER_ID or uid in CFG["admins"]


def all_admins():
    ids = [OWNER_ID]
    for a in CFG["admins"]:
        if a != OWNER_ID:
            ids.append(a)
    return ids


# Telegram does not allow changing button COLORS.
# Colorful emojis are the only way to make buttons look colorful.
BTN_EMOJIS = ["🔥", "💎", "⚡", "🎁", "🌟"]


def main_keyboard():
    rows = []
    for i in range(1, 6):
        e = BTN_EMOJIS[(i - 1) % len(BTN_EMOJIS)]
        title = CFG["buttons"][str(i)]["title"]
        rows.append([InlineKeyboardButton(f"{e} {title}", callback_data=f"prod_{i}")])
    return InlineKeyboardMarkup(rows)


def valid_slot(args):
    """Get product slot number (1-5) from the first command argument."""
    if not args:
        return None
    try:
        n = int(args[0])
        return n if 1 <= n <= 5 else None
    except ValueError:
        return None


def text_after_command(message):
    """Everything typed after the command, with ALL line breaks preserved."""
    if not message.text:
        return ""
    parts = message.text.split(None, 1)
    return parts[1] if len(parts) > 1 else ""


def text_after_slot(message):
    """Everything typed after '/command <n>', line breaks preserved."""
    if not message.text:
        return ""
    parts = message.text.split(None, 2)
    return parts[2] if len(parts) > 2 else ""


async def send_start(bot, chat_id):
    """Send the start message: ALL photos/videos as SPOILER albums + bold text + buttons."""
    text = B(CFG["start_message"])
    kb = main_keyboard()
    media = CFG["start_media"]

    if len(media) == 1:
        m = media[0]
        try:
            if m["type"] == "photo":
                await bot.send_photo(chat_id, m["file_id"], caption=text,
                                     parse_mode="HTML", reply_markup=kb, has_spoiler=True)
            else:
                await bot.send_video(chat_id, m["file_id"], caption=text,
                                     parse_mode="HTML", reply_markup=kb, has_spoiler=True)
            return
        except Exception as e:
            logging.warning(f"Start media failed: {e}")

    elif len(media) > 1:
        # Telegram allows max 10 items per album -> send in groups of 10
        for i in range(0, len(media), 10):
            chunk = media[i:i + 10]
            group = []
            for m in chunk:
                if m["type"] == "photo":
                    group.append(InputMediaPhoto(m["file_id"], has_spoiler=True))
                else:
                    group.append(InputMediaVideo(m["file_id"], has_spoiler=True))
            try:
                if len(group) == 1:
                    m = chunk[0]
                    if m["type"] == "photo":
                        await bot.send_photo(chat_id, m["file_id"], has_spoiler=True)
                    else:
                        await bot.send_video(chat_id, m["file_id"], has_spoiler=True)
                else:
                    await bot.send_media_group(chat_id, group)
            except Exception as e:
                logging.warning(f"Start album failed: {e}")

    await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=kb)


async def send_delivery(bot, uid: int, p: dict):
    """Send the product delivery (text/link/photo/video/file) to the user."""
    header = f"✅ Payment Approved!\n📦 Product: {p['title']}\n\nHere is your order:"
    await bot.send_message(uid, B(header), parse_mode="HTML")
    cap = B(p["delivery_text"]) if p["delivery_text"] else None
    if p["delivery_type"] == "photo" and p["delivery_file_id"]:
        await bot.send_photo(uid, p["delivery_file_id"], caption=cap, parse_mode="HTML")
    elif p["delivery_type"] == "video" and p["delivery_file_id"]:
        await bot.send_video(uid, p["delivery_file_id"], caption=cap, parse_mode="HTML")
    elif p["delivery_type"] == "document" and p["delivery_file_id"]:
        await bot.send_document(uid, p["delivery_file_id"], caption=cap, parse_mode="HTML")
    else:
        await bot.send_message(uid, cap or B("Done!"), parse_mode="HTML",
                               disable_web_page_preview=False)


# ---------------- USER SIDE ----------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_start(context.bot, update.effective_chat.id)


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        B(f"🆔 Your Telegram ID: {update.effective_user.id}"), parse_mode="HTML"
    )


async def on_product_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    n = q.data.split("_")[1]
    p = CFG["buttons"][n]

    buy_btn = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🛒💰 Buy Now", callback_data=f"buy_{n}")],
         [InlineKeyboardButton("⬅️🏠 Back to Menu", callback_data="back_home")]]
    )

    chat_id = q.message.chat_id
    cap = B(p["caption"])
    if p["media_type"] == "photo" and p["media_file_id"]:
        await context.bot.send_photo(chat_id, p["media_file_id"], caption=cap,
                                     parse_mode="HTML", reply_markup=buy_btn)
    elif p["media_type"] == "video" and p["media_file_id"]:
        await context.bot.send_video(chat_id, p["media_file_id"], caption=cap,
                                     parse_mode="HTML", reply_markup=buy_btn)
    else:
        await context.bot.send_message(chat_id, cap, parse_mode="HTML", reply_markup=buy_btn)


async def on_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await send_start(context.bot, q.message.chat_id)


async def on_buy_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    n = q.data.split("_")[1]
    uid = q.from_user.id
    chat_id = q.message.chat_id
    p = CFG["buttons"][n]

    CFG["pending"][str(uid)] = n
    save_config()

    order_note = f"🧾 Order placed: {p['title']}\n\n"
    full = B(order_note + CFG["payment_text"])
    if CFG["qr_file_id"]:
        await context.bot.send_photo(chat_id, CFG["qr_file_id"], caption=full, parse_mode="HTML")
    else:
        await context.bot.send_message(chat_id, full, parse_mode="HTML")
    await context.bot.send_message(
        chat_id,
        B("📸 Please send your payment screenshot here once you have paid."),
        parse_mode="HTML",
    )


async def on_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User sends a payment screenshot -> forwarded to all admins with Approve/Reject buttons."""
    uid = update.effective_user.id

    if str(uid) not in CFG["pending"]:
        # Admins often send photos while configuring products — stay silent for them.
        if not is_admin(uid):
            await update.message.reply_text(
                B("ℹ️ You don't have any pending order.\n"
                  "Please choose a product first and tap 🛒 Buy Now, then send your payment screenshot."),
                parse_mode="HTML",
            )
        return

    n = CFG["pending"][str(uid)]
    p = CFG["buttons"][n]
    user = update.effective_user
    uname = f"@{user.username}" if user.username else user.full_name
    when = datetime.now().strftime("%d %b %Y, %I:%M %p")

    kb = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Approve", callback_data=f"ap_{uid}_{n}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"rj_{uid}_{n}"),
        ]]
    )
    info = (
        "🧾 NEW PAYMENT SCREENSHOT\n"
        f"👤 User: {uname}\n"
        f"🆔 ID: {uid}\n"
        f"📦 Product: {p['title']}\n"
        f"🕒 Time: {when}\n\n"
        "Tap a button below to approve or reject this payment."
    )

    sent = False
    for admin_id in all_admins():
        try:
            # Screenshot + order info + buttons, all in ONE message
            await update.message.copy(chat_id=admin_id, caption=B(info),
                                      parse_mode="HTML", reply_markup=kb)
            sent = True
        except Exception as e:
            logging.warning(f"Could not notify admin {admin_id}: {e}")

    if sent:
        await update.message.reply_text(
            B("✅ Screenshot received!\n"
              "⏳ An admin is verifying your payment. You will get your product here as soon as it is approved."),
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text(
            B("⚠️ Could not reach an admin right now. Please try again in a few minutes."),
            parse_mode="HTML",
        )


async def on_approve_reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(q.from_user.id):
        await q.answer("This action is for admins only!", show_alert=True)
        return
    await q.answer()

    action, uid, n = q.data.split("_")
    uid = int(uid)
    p = CFG["buttons"][n]
    done_note = None

    if action == "ap":
        try:
            await send_delivery(context.bot, uid, p)
            done_note = f"✅ APPROVED — product delivered to user {uid} ({p['title']})."
        except Exception as e:
            done_note = f"⚠️ Approved, but delivery to user {uid} failed: {e}"
    else:
        try:
            await context.bot.send_message(
                uid,
                B("❌ Your payment was rejected.\n\n"
                  "If you sent a wrong or unclear screenshot, please send the correct one.\n"
                  "If you think this is a mistake, contact the admin."),
                parse_mode="HTML",
            )
        except Exception:
            pass
        done_note = f"❌ REJECTED — user {uid} has been informed."

    # Works whether the admin message is a photo (caption) or plain text
    try:
        if q.message.photo or q.message.video or q.message.document:
            await q.edit_message_caption(caption=B(done_note), parse_mode="HTML")
        else:
            await q.edit_message_text(B(done_note), parse_mode="HTML")
    except Exception:
        await context.bot.send_message(q.message.chat_id, B(done_note), parse_mode="HTML")

    CFG["pending"].pop(str(uid), None)
    save_config()


# ---------------- ADMIN COMMANDS ----------------

async def admin_only(update: Update) -> bool:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(B("⛔ This command is for admins only."), parse_mode="HTML")
        return False
    return True


async def cmd_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    text = (
        "🛠 ADMIN PANEL — All Commands\n\n"
        "━━━ START MESSAGE ━━━\n"
        "/setstart <text> — set the /start welcome text (line breaks are kept)\n"
        "• Or reply to a TEXT message with /setstart — its exact formatting is kept\n"
        "• Or reply to a PHOTO/VIDEO with /setstart — that becomes the FIRST start media (caption = text)\n"
        "/addstartmedia — REPLY to a photo/video to ADD it to /start\n"
        f"   (repeat for each one — up to {MAX_START_MEDIA}; all are sent together as SPOILER albums)\n"
        "/startmedialist — see how many photos/videos are set\n"
        "/delstartmedia — remove ALL start photos/videos (keep text only)\n\n"
        "━━━ PRODUCTS (1 to 5) ━━━\n"
        "/setbtn <n> <title> — set the button name\n"
        "/setproduct <n> — reply to a photo/video (its caption becomes the description)\n"
        "/setcaption <n> <text> — change only the description (line breaks kept)\n"
        "/setdelivery <n> — reply to any message (text/photo/video/file); the user receives exactly that after approval. For text only: /setdelivery <n> <text>\n\n"
        "━━━ PAYMENT ━━━\n"
        "/setqr — reply to the QR photo\n"
        "/setpaytext <text> — set the payment instructions (line breaks kept)\n\n"
        "━━━ CUSTOM COMMANDS (unlimited) ━━━\n"
        "/addcmd <name> <text> — create your own command, e.g. /addcmd help Contact @admin\n"
        "• Or reply to any text/photo/video/file with /addcmd <name>\n"
        "/delcmd <name> — delete a custom command\n"
        "/cmdlist — see all custom commands\n\n"
        "━━━ ADMINS ━━━\n"
        "/addadmin <user_id> — add an admin\n"
        "/deladmin <user_id> — remove an admin\n"
        "/adminlist — see all admins\n\n"
        "━━━ OTHER ━━━\n"
        "/myid — see your Telegram ID"
    )
    await update.message.reply_text(B(text), parse_mode="HTML")


async def cmd_setstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    r = update.message.reply_to_message
    text = text_after_command(update.message)

    if r and r.photo:
        CFG["start_media"] = [{"type": "photo", "file_id": r.photo[-1].file_id}]
        if r.caption:
            CFG["start_message"] = r.caption
        elif text:
            CFG["start_message"] = text
        save_config()
        await update.message.reply_text(
            B("✅ Start message set with PHOTO (spoiler)!\n"
              "Add more photos/videos with /addstartmedia. Send /start to preview."),
            parse_mode="HTML",
        )
        return
    if r and r.video:
        CFG["start_media"] = [{"type": "video", "file_id": r.video.file_id}]
        if r.caption:
            CFG["start_message"] = r.caption
        elif text:
            CFG["start_message"] = text
        save_config()
        await update.message.reply_text(
            B("✅ Start message set with VIDEO (spoiler)!\n"
              "Add more photos/videos with /addstartmedia. Send /start to preview."),
            parse_mode="HTML",
        )
        return
    if r and r.text:
        CFG["start_message"] = r.text
        save_config()
        await update.message.reply_text(
            B("✅ Start text set (formatting kept)! Send /start to preview."), parse_mode="HTML"
        )
        return
    if text:
        CFG["start_message"] = text
        save_config()
        await update.message.reply_text(B("✅ Start text set! Send /start to preview."), parse_mode="HTML")
        return

    await update.message.reply_text(
        B("How to use:\n"
          "• /setstart <your welcome text>\n"
          "• Or reply to a photo/video with /setstart (caption becomes the text)\n"
          "• Or reply to a text message with /setstart (exact formatting kept)\n"
          "• Add MORE photos/videos with /addstartmedia"),
        parse_mode="HTML",
    )


async def cmd_addstartmedia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    r = update.message.reply_to_message
    if not r or not (r.photo or r.video):
        await update.message.reply_text(
            B("How to use:\n"
              "1) Send (or forward) a photo/video to this chat\n"
              "2) REPLY to it with /addstartmedia\n"
              f"Repeat for every photo/video you want in /start (up to {MAX_START_MEDIA}).\n"
              "They will all be sent together as SPOILER albums."),
            parse_mode="HTML",
        )
        return
    if len(CFG["start_media"]) >= MAX_START_MEDIA:
        await update.message.reply_text(
            B(f"⚠️ Limit reached ({MAX_START_MEDIA}). Use /delstartmedia to clear and start again."),
            parse_mode="HTML",
        )
        return
    if r.photo:
        CFG["start_media"].append({"type": "photo", "file_id": r.photo[-1].file_id})
    else:
        CFG["start_media"].append({"type": "video", "file_id": r.video.file_id})
    save_config()
    await update.message.reply_text(
        B(f"✅ Added! /start now has {len(CFG['start_media'])} photo/video(s) — all spoiler.\n"
          "Send /start to preview."),
        parse_mode="HTML",
    )


async def cmd_startmedialist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    n_photo = sum(1 for m in CFG["start_media"] if m["type"] == "photo")
    n_video = sum(1 for m in CFG["start_media"] if m["type"] == "video")
    await update.message.reply_text(
        B(f"🖼 Start media: {len(CFG['start_media'])} total\n"
          f"• Photos: {n_photo}\n• Videos: {n_video}\n"
          "All are sent as SPOILER. /delstartmedia removes all."),
        parse_mode="HTML",
    )


async def cmd_delstartmedia(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    CFG["start_media"] = []
    save_config()
    await update.message.reply_text(
        B("✅ All start photos/videos removed. /start will show text only."), parse_mode="HTML"
    )


async def cmd_setbtn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    n = valid_slot(context.args)
    if n is None or len(context.args) < 2:
        await update.message.reply_text(B("How to use: /setbtn 1 Netflix Premium  (number 1-5)"), parse_mode="HTML")
        return
    CFG["buttons"][str(n)]["title"] = " ".join(context.args[1:])
    save_config()
    await update.message.reply_text(
        B(f"✅ Button {n} title set: {CFG['buttons'][str(n)]['title']}"), parse_mode="HTML"
    )


async def cmd_setproduct(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    n = valid_slot(context.args)
    r = update.message.reply_to_message
    if n is None or r is None:
        await update.message.reply_text(
            B("First send the product photo/video, then REPLY to that message with: /setproduct 1"),
            parse_mode="HTML",
        )
        return
    p = CFG["buttons"][str(n)]
    if r.photo:
        p["media_type"] = "photo"
        p["media_file_id"] = r.photo[-1].file_id
        p["caption"] = r.caption or p["caption"]
    elif r.video:
        p["media_type"] = "video"
        p["media_file_id"] = r.video.file_id
        p["caption"] = r.caption or p["caption"]
    elif r.text:
        p["media_type"] = None
        p["media_file_id"] = None
        p["caption"] = r.text
    else:
        await update.message.reply_text(B("⚠️ Please reply to a photo, video, or text message."), parse_mode="HTML")
        return
    save_config()
    await update.message.reply_text(B(f"✅ Product {n} is set!"), parse_mode="HTML")


async def cmd_setcaption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    n = valid_slot(context.args)
    r = update.message.reply_to_message
    if n is not None and r and r.text:
        CFG["buttons"][str(n)]["caption"] = r.text
        save_config()
        await update.message.reply_text(B(f"✅ Product {n} description set (formatting kept)!"), parse_mode="HTML")
        return
    text = text_after_slot(update.message)
    if n is None or not text:
        await update.message.reply_text(
            B("How to use: /setcaption 1 <description>\n"
              "Or reply to a text message with /setcaption 1 to keep its exact formatting."),
            parse_mode="HTML",
        )
        return
    CFG["buttons"][str(n)]["caption"] = text
    save_config()
    await update.message.reply_text(B(f"✅ Product {n} description set!"), parse_mode="HTML")


async def cmd_setdelivery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    n = valid_slot(context.args)
    if n is None:
        await update.message.reply_text(
            B("How to use:\n"
              "• /setdelivery 1 <text>\n"
              "• Or reply to a photo/video/file/text with /setdelivery 1\n"
              "The user receives exactly this after approval."),
            parse_mode="HTML",
        )
        return
    p = CFG["buttons"][str(n)]
    r = update.message.reply_to_message
    if r:
        if r.photo:
            p["delivery_type"], p["delivery_file_id"] = "photo", r.photo[-1].file_id
        elif r.video:
            p["delivery_type"], p["delivery_file_id"] = "video", r.video.file_id
        elif r.document:
            p["delivery_type"], p["delivery_file_id"] = "document", r.document.file_id
        elif r.text:
            p["delivery_type"], p["delivery_file_id"] = "text", None
            p["delivery_text"] = r.text
            save_config()
            await update.message.reply_text(
                B(f"✅ Delivery for Product {n} is set! (formatting kept)"), parse_mode="HTML"
            )
            return
        p["delivery_text"] = r.caption or p["delivery_text"]
    else:
        text = text_after_slot(update.message)
        if text:
            p["delivery_type"], p["delivery_file_id"] = "text", None
            p["delivery_text"] = text
        else:
            await update.message.reply_text(B("⚠️ Provide the text, or reply to a message."), parse_mode="HTML")
            return
    save_config()
    await update.message.reply_text(
        B(f"✅ Delivery for Product {n} is set! The user will receive it right after approval."),
        parse_mode="HTML",
    )


async def cmd_setqr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    r = update.message.reply_to_message
    if not r or not r.photo:
        await update.message.reply_text(B("Send the QR photo first, then REPLY to it with /setqr."), parse_mode="HTML")
        return
    CFG["qr_file_id"] = r.photo[-1].file_id
    save_config()
    await update.message.reply_text(B("✅ Payment QR is set!"), parse_mode="HTML")


async def cmd_setpaytext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    r = update.message.reply_to_message
    if r and r.text:
        CFG["payment_text"] = r.text
        save_config()
        await update.message.reply_text(B("✅ Payment instructions set (formatting kept)!"), parse_mode="HTML")
        return
    text = text_after_command(update.message)
    if not text:
        await update.message.reply_text(
            B("How to use: /setpaytext <payment instructions>\n"
              "Or reply to a text message with /setpaytext to keep its exact formatting."),
            parse_mode="HTML",
        )
        return
    CFG["payment_text"] = text
    save_config()
    await update.message.reply_text(B("✅ Payment instructions set!"), parse_mode="HTML")


# ---------------- CUSTOM COMMANDS (unlimited) ----------------

RESERVED_CMDS = {
    "start", "myid", "panel", "setstart", "addstartmedia", "startmedialist",
    "delstartmedia", "setbtn", "setproduct", "setcaption", "setdelivery",
    "setqr", "setpaytext", "addadmin", "deladmin", "adminlist",
    "addcmd", "delcmd", "cmdlist",
}


async def cmd_addcmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text(
            B("How to use:\n"
              "• /addcmd help Contact @YourAdmin for support\n"
              "• Or reply to any text/photo/video/file with: /addcmd <name>\n\n"
              "Then anyone can type /<name> and get that reply.\n"
              "There is NO limit — add as many commands as you want."),
            parse_mode="HTML",
        )
        return

    name = context.args[0].lstrip("/").lower()
    if not re.fullmatch(r"[a-z0-9_]{1,32}", name):
        await update.message.reply_text(
            B("⚠️ Command name can only use letters a-z, numbers and _ (max 32 chars).\n"
              "Example: /addcmd help ..."),
            parse_mode="HTML",
        )
        return
    if name in RESERVED_CMDS:
        await update.message.reply_text(
            B(f"⚠️ /{name} is a built-in command. Pick another name."), parse_mode="HTML"
        )
        return

    r = update.message.reply_to_message
    entry = {"type": "text", "file_id": None, "text": ""}
    if r:
        if r.photo:
            entry = {"type": "photo", "file_id": r.photo[-1].file_id, "text": r.caption or ""}
        elif r.video:
            entry = {"type": "video", "file_id": r.video.file_id, "text": r.caption or ""}
        elif r.document:
            entry = {"type": "document", "file_id": r.document.file_id, "text": r.caption or ""}
        elif r.text:
            entry["text"] = r.text
        else:
            await update.message.reply_text(
                B("⚠️ Reply to a text, photo, video or file message."), parse_mode="HTML"
            )
            return
    else:
        text = text_after_slot(update.message)  # everything after "/addcmd <name>"
        if not text:
            await update.message.reply_text(
                B("⚠️ Type the reply text after the name, or reply to a message.\n"
                  "Example: /addcmd help Contact @YourAdmin"),
                parse_mode="HTML",
            )
            return
        entry["text"] = text

    CFG["custom_cmds"][name] = entry
    save_config()
    await update.message.reply_text(
        B(f"✅ Custom command /{name} is set! ({len(CFG['custom_cmds'])} custom commands total)\n"
          f"Anyone can now type /{name}."),
        parse_mode="HTML",
    )


async def cmd_delcmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not context.args:
        await update.message.reply_text(B("How to use: /delcmd <name>"), parse_mode="HTML")
        return
    name = context.args[0].lstrip("/").lower()
    if name in CFG["custom_cmds"]:
        del CFG["custom_cmds"][name]
        save_config()
        await update.message.reply_text(B(f"✅ /{name} deleted."), parse_mode="HTML")
    else:
        await update.message.reply_text(B(f"⚠️ /{name} does not exist. See /cmdlist."), parse_mode="HTML")


async def cmd_cmdlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not CFG["custom_cmds"]:
        await update.message.reply_text(
            B("No custom commands yet. Create one with /addcmd — there is no limit."),
            parse_mode="HTML",
        )
        return
    lines = [f"📋 Custom commands ({len(CFG['custom_cmds'])}):"]
    for name, c in CFG["custom_cmds"].items():
        lines.append(f"/{name} — {c['type']}")
    await update.message.reply_text(B("\n".join(lines)), parse_mode="HTML")


async def on_custom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles every /command that is not built-in -> replies if a custom command matches."""
    msg = update.message
    if not msg or not msg.text or not msg.text.startswith("/"):
        return
    name = msg.text.split()[0][1:].split("@")[0].lower()
    c = CFG["custom_cmds"].get(name)
    if not c:
        return
    cap = B(c["text"]) if c["text"] else None
    if c["type"] == "photo" and c["file_id"]:
        await msg.reply_photo(c["file_id"], caption=cap, parse_mode="HTML", has_spoiler=True)
    elif c["type"] == "video" and c["file_id"]:
        await msg.reply_video(c["file_id"], caption=cap, parse_mode="HTML", has_spoiler=True)
    elif c["type"] == "document" and c["file_id"]:
        await msg.reply_document(c["file_id"], caption=cap, parse_mode="HTML")
    else:
        await msg.reply_text(cap or B("..."), parse_mode="HTML")


# ---------------- ADMINS ----------------

async def cmd_addadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text(
            B("How to use: /addadmin <user_id>\n(The user can get their ID with /myid)"), parse_mode="HTML"
        )
        return
    uid = int(context.args[0])
    if uid in CFG["admins"] or uid == OWNER_ID:
        await update.message.reply_text(B("This user is already an admin."), parse_mode="HTML")
        return
    CFG["admins"].append(uid)
    save_config()
    await update.message.reply_text(
        B(f"✅ {uid} is now an admin and will also receive payment screenshots."), parse_mode="HTML"
    )


async def cmd_deladmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text(B("How to use: /deladmin <user_id>"), parse_mode="HTML")
        return
    uid = int(context.args[0])
    if uid in CFG["admins"]:
        CFG["admins"].remove(uid)
        save_config()
        await update.message.reply_text(B(f"✅ {uid} is no longer an admin."), parse_mode="HTML")
    else:
        await update.message.reply_text(B("This user is not in the admin list."), parse_mode="HTML")


async def cmd_adminlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update):
        return
    lines = [f"👑 Owner: {OWNER_ID}"] + [f"🛡 Admin: {a}" for a in CFG["admins"]]
    await update.message.reply_text(B("\n".join(lines)), parse_mode="HTML")


# ---------------- MAIN ----------------

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # user
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CallbackQueryHandler(on_product_click, pattern=r"^prod_[1-5]$"))
    app.add_handler(CallbackQueryHandler(on_buy_click, pattern=r"^buy_[1-5]$"))
    app.add_handler(CallbackQueryHandler(on_back, pattern=r"^back_home$"))
    app.add_handler(CallbackQueryHandler(on_approve_reject, pattern=r"^(ap|rj)_\d+_[1-5]$"))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.IMAGE, on_screenshot))

    # admin
    app.add_handler(CommandHandler("panel", cmd_panel))
    app.add_handler(CommandHandler("setstart", cmd_setstart))
    app.add_handler(CommandHandler("addstartmedia", cmd_addstartmedia))
    app.add_handler(CommandHandler("startmedialist", cmd_startmedialist))
    app.add_handler(CommandHandler("delstartmedia", cmd_delstartmedia))
    app.add_handler(CommandHandler("setbtn", cmd_setbtn))
    app.add_handler(CommandHandler("setproduct", cmd_setproduct))
    app.add_handler(CommandHandler("setcaption", cmd_setcaption))
    app.add_handler(CommandHandler("setdelivery", cmd_setdelivery))
    app.add_handler(CommandHandler("setqr", cmd_setqr))
    app.add_handler(CommandHandler("setpaytext", cmd_setpaytext))
    app.add_handler(CommandHandler("addcmd", cmd_addcmd))
    app.add_handler(CommandHandler("delcmd", cmd_delcmd))
    app.add_handler(CommandHandler("cmdlist", cmd_cmdlist))
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    app.add_handler(CommandHandler("deladmin", cmd_deladmin))
    app.add_handler(CommandHandler("adminlist", cmd_adminlist))

    # custom commands (must be LAST so built-in commands run first)
    app.add_handler(MessageHandler(filters.COMMAND, on_custom_cmd))

    print("Bot is running... (press Ctrl+C to stop)")
    app.run_polling()


if __name__ == "__main__":
    main()
