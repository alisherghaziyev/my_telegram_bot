# -*- coding: utf-8 -*-
"""
pubg.py - Complete Telegram bot for PUBG UC referrals, balance, withdrawals,
ratings and competitions (admin tools), ready for Heroku (webhook) deployment.

Key points:
- Uses Flask webhook endpoint so it works on Heroku/Railway/Render web dynos.
- Exposes `server` (Flask app) so `Procfile` can be:  web: gunicorn pubg:server
- Starts a background thread for periodic maintenance (unsubscribe cleanup,
  auto-finish expired competitions).
- Stores simple data in JSON files (users.json, competitions.json, devices.json).

Environment variables expected (Heroku Config Vars):
- BOT_TOKEN         : Telegram bot token (required)
- HEROKU_APP_NAME   : Your Heroku app name, e.g. "my-bot-app"  (optional if WEBHOOK_URL set)
- WEBHOOK_URL       : Full HTTPS webhook base URL, e.g. "https://my.domain.com" (optional)
- CHANNEL_ID        : e.g. "@swKoMBaT"
- GROUP_ID          : e.g. "@swKoMBaT1"
- YOUTUBE_LINK      : YouTube channel URL (optional)
- ADMIN_IDS         : Comma separated Telegram user IDs: "111,222" (optional)

Files created at runtime (JSON stores):
- users.json          : { user_id: {uc, ref, refs[], joined} }
- competitions.json   : { comp_id: {...} }
- devices.json        : misc small settings (e.g., UC image file_id)

Procfile example:
    web: gunicorn pubg:server

requirements.txt (minimal):
    pyTelegramBotAPI>=4.0.0
    Flask>=2.0
    gunicorn>=20.0.4
    python-dotenv>=0.21.0
"""

import os
import json
import time
import random
import threading
import functools
import urllib.parse
from typing import Optional, Dict, Any, List
from datetime import datetime, date, timedelta

import telebot
from telebot import types
from flask import Flask, request

# -----------------------
# Configuration
# -----------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")

CHANNEL_ID = os.environ.get("CHANNEL_ID", "@swKoMBaT")
GROUP_ID = os.environ.get("GROUP_ID", "@swKoMBaT1")
YOUTUBE_LINK = os.environ.get("YOUTUBE_LINK", "https://youtube.com/@swkombat?si=5vVIGfj_NYx-yJLK")

if os.environ.get("ADMIN_IDS"):
    try:
        ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS").split(",") if x.strip()]
    except Exception:
        ADMIN_IDS = []
else:
    ADMIN_IDS = [6322816106]  # put your admin IDs here if desired

# Optional explicit webhook URL (overrides HEROKU_APP_NAME)
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")  # e.g., https://mydomain.com
HEROKU_APP_NAME = os.environ.get("HEROKU_APP_NAME")  # e.g., my-bot-app

USERS_FILE = "users.json"
COMPS_FILE = "competitions.json"
DEVICES_FILE = "devices.json"

# Ensure data files exist
for fname in (USERS_FILE, COMPS_FILE, DEVICES_FILE):
    if not os.path.exists(fname):
        with open(fname, "w", encoding="utf-8") as f:
            json.dump({}, f, ensure_ascii=False, indent=2)

# Telegram bot
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# In-memory admin drafts and pending join contexts
comp_drafts: Dict[int, Dict[str, Any]] = {}
pending_joins: Dict[int, str] = {}  # user_id -> comp_id waiting for subscription confirm

# -----------------------
# JSON helpers
# -----------------------

def load_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_json(path: str, data: Dict[str, Any]):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# -----------------------
# Subscription check & prompt
# -----------------------

def check_subscription(user_id: int) -> bool:
    """
    Return True if user is member/administrator/creator in both CHANNEL_ID and GROUP_ID.
    Treat errors as not subscribed.
    """
    try:
        ch = bot.get_chat_member(CHANNEL_ID, user_id)
        gr = bot.get_chat_member(GROUP_ID, user_id)
        ok_ch = ch.status in ("member", "administrator", "creator")
        ok_gr = gr.status in ("member", "administrator", "creator")
        return ok_ch and ok_gr
    except Exception as e:
        print(f"[check_subscription] user={user_id} error: {e}")
        return False


def send_subscription_prompt(user_id: int, comp_id: Optional[str] = None) -> bool:
    """
    Send a DM to user with subscription instructions.
    If comp_id provided, confirm button will be 'confirm_sub_{comp_id}' so join flow is preserved.
    Returns True if DM sent, False otherwise.
    """
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📢 Kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"))
    kb.add(types.InlineKeyboardButton("👥 Guruhga obuna bo'lish", url=f"https://t.me/{GROUP_ID.lstrip('@')}"))
    kb.add(types.InlineKeyboardButton("📺 YouTube kanalga obuna bo'lish", url=YOUTUBE_LINK))
    if comp_id:
        kb.add(types.InlineKeyboardButton("✅ Obuna bo'ldim", callback_data=f"confirm_sub_{comp_id}"))
        text = (
            "🔒 Konkursga qo'shilish uchun quyidagi kanallarga obuna bo'ling:\n\n"
            f"{CHANNEL_ID}\n{GROUP_ID}\n\n"
            "Obuna bo'lgach, '✅ Obuna bo'ldim' tugmasini bosing. Bot obunangizni tekshiradi va sizni avtomatik qo'shadi."
        )
    else:
        kb.add(types.InlineKeyboardButton("✅ Obuna bo'ldim", callback_data="check_sub"))
        text = (
            "🔒 Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:\n\n"
            f"{CHANNEL_ID}\n{GROUP_ID}\n\n"
            "Obuna bo'lgach, '✅ Obuna bo'ldim' tugmasini bosing."
        )
    try:
        bot.send_message(user_id, text, reply_markup=kb)
        return True
    except Exception as e:
        print(f"[send_subscription_prompt] DM failed to {user_id}: {e}")
        return False


@bot.callback_query_handler(func=lambda c: c.data == "check_sub")
def callback_check_sub(call: types.CallbackQuery):
    uid = call.from_user.id
    if check_subscription(uid):
        try:
            bot.answer_callback_query(call.id, "✅ Obuna tasdiqlandi!", show_alert=False)
            bot.send_message(uid, "✅ Obuna tasdiqlandi. Endi bot menyusiga o'ting.", reply_markup=main_menu(uid))
        except Exception:
            pass
    else:
        try:
            bot.answer_callback_query(call.id, "❌ Obuna aniqlanmadi. Iltimos qayta tekshiring.", show_alert=True)
            send_subscription_prompt(uid)
        except Exception:
            pass


# -----------------------
# Decorators and safe next-step
# -----------------------

def subscription_guard_message(handler):
    @functools.wraps(handler)
    def wrapper(message, *args, **kwargs):
        try:
            uid = message.from_user.id
        except Exception:
            return
        # allow /start
        if getattr(message, "text", "") and message.text.startswith("/start"):
            return handler(message, *args, **kwargs)
        if not check_subscription(uid):
            sent = send_subscription_prompt(uid)
            if not sent:
                try:
                    bot.send_message(uid, f"Iltimos, botga yozing: https://t.me/{bot.get_me().username} va /start ni bosing.")
                except Exception:
                    pass
            return
        return handler(message, *args, **kwargs)

    return wrapper


def subscription_guard_callback(handler):
    @functools.wraps(handler)
    def wrapper(call: types.CallbackQuery, *args, **kwargs):
        try:
            uid = call.from_user.id
        except Exception:
            return
        if call.data == "check_sub":
            return handler(call, *args, **kwargs)
        if not check_subscription(uid):
            sent = send_subscription_prompt(uid)
            if sent:
                try:
                    bot.answer_callback_query(call.id, "❗ Obuna topilmadi. Sizga DM yubordim — obuna bo'ling.", show_alert=True)
                except Exception:
                    pass
            else:
                try:
                    bot.answer_callback_query(call.id, f"❗ Iltimos, botga yozing: https://t.me/{bot.get_me().username} va /start bosing.", show_alert=True)
                except Exception:
                    pass
            return
        return handler(call, *args, **kwargs)

    return wrapper


def safe_register_next_step_handler(msg, callback, *args, **kwargs):
    wrapped = subscription_guard_message(callback)
    return bot.register_next_step_handler(msg, wrapped, *args, **kwargs)


# -----------------------
# Main menu
# -----------------------

def main_menu(uid: int) -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    buttons = ["🪙 UC islash", "📊 Referal reyting", "💰 UC balans", "💸 UC yechish"]
    if uid in ADMIN_IDS:
        buttons.insert(3, "🎁 Konkurslar")
    kb.row(buttons[0], buttons[1])
    kb.row(buttons[2], buttons[3])
    if len(buttons) > 4:
        kb.row(buttons[4])
    return kb


# -----------------------
# Users & referrals
# -----------------------

def add_user(user_id: int, ref_id: Optional[str] = None):
    users = load_json(USERS_FILE)
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            "uc": 0,
            "ref": str(ref_id) if ref_id else None,
            "refs": [],
            "joined": str(date.today()),
        }
        # credit referrer if exists
        if ref_id and str(ref_id) in users:
            users[str(ref_id)].setdefault("refs", []).append(uid)
            users[str(ref_id)]["uc"] = users[str(ref_id)].get("uc", 0) + 3
        save_json(USERS_FILE, users)


# -----------------------
# UC islash & admin set image
# -----------------------

@bot.message_handler(func=lambda m: m.text == "🪙 UC islash")
@subscription_guard_message
def uc_ishlash(message: types.Message):
    uid = message.from_user.id
    try:
        me = bot.get_me()
        username = getattr(me, "username", None)
        if username:
            ref_link = f"https://t.me/{username}?start={uid}"
        else:
            ref_link = f"/start {uid}"
    except Exception:
        ref_link = f"/start {uid}"

    guidance = (
        "Ushbu bot orqali siz UC ishlashingiz mumkin.\n\n"
        "Menyudagi '🪙 UC islash' tugmasini bosish orqali sizga berilgan referal havolani do'stlaringizga ulashing.\n"
        "Har bir taklif uchun 3 UC to'lanadi.\n\n"
        f"Sizning referal havolangiz: {ref_link}"
    )

    devices = load_json(DEVICES_FILE)
    file_id = devices.get("uc_image", {}).get("file_id")

    share_text = urllib.parse.quote_plus(
        f"Men UC olish uchun bu kanalda qatnashaman! Siz ham qo'shiling: {ref_link}"
    )
    share_url = f"https://t.me/share/url?url={urllib.parse.quote_plus(ref_link)}&text={share_text}"

    inline = types.InlineKeyboardMarkup()
    inline.add(types.InlineKeyboardButton("🔗 Referal havolangizni ochish", url=ref_link))
    inline.add(types.InlineKeyboardButton("👥 Do'stlarni taklif qilish", url=share_url))

    reply = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    reply.row("🔙 Ortga")

    try:
        if file_id:
            bot.send_photo(uid, file_id, caption=guidance, reply_markup=inline)
        else:
            bot.send_message(uid, guidance, reply_markup=inline)
        bot.send_message(
            uid,
            "📤 Do'stlaringizga yuborish uchun 'Do'stlarni taklif qilish' tugmasidan foydalaning.",
            reply_markup=reply,
        )
    except Exception as e:
        print(f"[uc_ishlash] DM failed to {uid}: {e}")
        try:
            bot.send_message(
                message.chat.id,
                f"Iltimos botga yozing: https://t.me/{bot.get_me().username} va /start ni bosing.",
            )
        except Exception:
            pass


@bot.message_handler(commands=["set_uc_image"])
@subscription_guard_message
def cmd_set_uc_image(message: types.Message):
    if message.from_user.id not in ADMIN_IDS:
        bot.send_message(message.chat.id, "❌ Bu buyruq faqat adminlar uchun.")
        return
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("🔙 Ortga")
    msg = bot.send_message(message.chat.id, "Iltimos UC rasmi yuboring (yoki '🔙 Ortga'):", reply_markup=kb)
    safe_register_next_step_handler(msg, process_set_uc_image)


def process_set_uc_image(message: types.Message):
    if getattr(message, "text", "") and message.text == "🔙 Ortga":
        bot.send_message(message.chat.id, "✅ UC rasm sozlamalari bekor qilindi.")
        return
    if not message.photo:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.row("🔙 Ortga")
        msg = bot.send_message(message.chat.id, "Iltimos rasm yuboring (yoki '🔙 Ortga'):", reply_markup=kb)
        safe_register_next_step_handler(msg, process_set_uc_image)
        return
    file_id = message.photo[-1].file_id
    devices = load_json(DEVICES_FILE)
    devices.setdefault("uc_image", {})["file_id"] = file_id
    save_json(DEVICES_FILE, devices)
    bot.send_message(
        message.chat.id,
        "✅ UC rasmi saqlandi.",
        reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).row("🔙 Ortga"),
    )


# -----------------------
# Referral rating
# -----------------------

@bot.message_handler(func=lambda m: m.text == "📊 Referal reyting")
@subscription_guard_message
def referral_menu(message: types.Message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("🔄 Oxirgi 7 kun", "📅 Boshqa davr")
    kb.row("🔙 Ortga")
    bot.send_message(message.chat.id, "Referal reyting uchun davrni tanlang:", reply_markup=kb)


@bot.message_handler(func=lambda m: m.text == "🔄 Oxirgi 7 kun")
@subscription_guard_message
def last_7_days_rating(message: types.Message):
    end = date.today()
    start = end - timedelta(days=7)
    show_referral_rating(message.chat.id, start, end)


@bot.message_handler(func=lambda m: m.text == "📅 Boshqa davr")
@subscription_guard_message
def ask_custom_dates(message: types.Message):
    msg = bot.send_message(message.chat.id, "Boshlanish sanasini yuboring (YYYY-MM-DD):")
    safe_register_next_step_handler(msg, process_start_date)


def process_start_date(message: types.Message):
    if getattr(message, "text", "") and message.text == "🔙 Ortga":
        bot.send_message(message.chat.id, "Bosh menyu", reply_markup=main_menu(message.from_user.id))
        return
    try:
        start = datetime.strptime(message.text.strip(), "%Y-%m-%d").date()
    except Exception:
        bot.send_message(message.chat.id, "Noto'g'ri format. YYYY-MM-DD tarzida yuboring.")
        return
    msg = bot.send_message(message.chat.id, "Tugash sanasini yuboring (YYYY-MM-DD):")
    safe_register_next_step_handler(msg, process_end_date, start)


def process_end_date(message: types.Message, start_date: date):
    if getattr(message, "text", "") and message.text == "🔙 Ortga":
        bot.send_message(message.chat.id, "Bosh menyu", reply_markup=main_menu(message.from_user.id))
        return
    try:
        end = datetime.strptime(message.text.strip(), "%Y-%m-%d").date()
    except Exception:
        bot.send_message(message.chat.id, "Noto'g'ri format. YYYY-MM-DD tarzida yuboring.")
        return
    if end < start_date:
        bot.send_message(message.chat.id, "Tugash sanasi boshlanish sanasidan oldin bo'lishi mumkin emas.")
        return
    show_referral_rating(message.chat.id, start_date, end)


def show_referral_rating(chat_id: int, start_date: date, end_date: date):
    users = load_json(USERS_FILE)
    rating: List[tuple] = []
    for uid, data in users.items():
        try:
            joined = datetime.strptime(data.get("joined", "2000-01-01"), "%Y-%m-%d").date()
        except Exception:
            continue
        if start_date <= joined <= end_date:
            rating.append((int(uid), len(data.get("refs", []))))
    if not rating:
        bot.send_message(chat_id, f"⚠️ {start_date} dan {end_date} gacha davrda hech qanday referal topilmadi.")
        return
    rating.sort(key=lambda x: x[1], reverse=True)
    lines = [f"🏆 Referal reyting ({start_date} - {end_date}):"]
    for i, (uid, cnt) in enumerate(rating, 1):
        if i > 200:
            lines.append(f"... va yana {len(rating) - 200} ta foydalanuvchi")
            break
        try:
            u = bot.get_chat(uid)
            display = f"@{u.username}" if getattr(u, "username", None) else getattr(u, "first_name", f"ID:{uid}")
        except Exception:
            display = f"ID:{uid}"
        suffix = "taklif" if cnt == 1 else "takliflar"
        lines.append(f"{i}. {display} — {cnt} {suffix}")
    bot.send_message(chat_id, "\n".join(lines))


# -----------------------
# UC balance & withdraw
# -----------------------

@bot.message_handler(func=lambda m: m.text == "💰 UC balans")
@subscription_guard_message
def uc_balance(message: types.Message):
    users = load_json(USERS_FILE)
    uc = users.get(str(message.from_user.id), {}).get("uc", 0)
    bot.send_message(message.chat.id, f"💰 Sizning balansingiz: {uc} UC")


@bot.message_handler(func=lambda m: m.text == "💸 UC yechish")
@subscription_guard_message
def uc_withdraw(message: types.Message):
    users = load_json(USERS_FILE)
    uc = users.get(str(message.from_user.id), {}).get("uc", 0)
    if uc < 60:
        bot.send_message(message.chat.id, "❌ UC yechish uchun kamida 60 UC kerak.")
        return
    kb = types.InlineKeyboardMarkup()
    for amt in (60, 120, 180, 325):
        if uc >= amt:
            kb.add(types.InlineKeyboardButton(f"{amt} UC", callback_data=f"withdraw_{amt}"))
    bot.send_message(message.chat.id, "💳 Yechmoqchi bo'lgan UC miqdorini tanlang:", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("withdraw_"))
@subscription_guard_callback
def handle_withdraw(call: types.CallbackQuery):
    amount = int(call.data.split("_", 1)[1])
    try:
        msg = bot.send_message(call.from_user.id, "🔢 PUBG ID raqamingizni yuboring:")
        safe_register_next_step_handler(msg, confirm_withdraw, amount)
    except Exception as e:
        print(f"[handle_withdraw] {e}")
        bot.answer_callback_query(call.id, "Xatolik yuz berdi", show_alert=True)


def confirm_withdraw(message: types.Message, amount: int):
    users = load_json(USERS_FILE)
    uid = str(message.from_user.id)
    if users.get(uid, {}).get("uc", 0) < amount:
        bot.send_message(message.chat.id, "❌ Sizda yetarli UC mavjud emas.")
        return
    pubg_id = message.text.strip()
    users[uid]["uc"] -= amount
    save_json(USERS_FILE, users)
    for admin in ADMIN_IDS:
        try:
            bot.send_message(
                admin,
                f"📥 @{message.from_user.username} ({uid}) so'radi: {amount} UC\nPUBG ID: {pubg_id}",
            )
        except Exception:
            pass
    bot.send_message(message.chat.id, "✅ So'rovingiz qabul qilindi. Tez orada ko'rib chiqiladi.")


# -----------------------
# Competitions: admin creation and posting
# -----------------------

@bot.message_handler(func=lambda m: m.text == "🎁 Konkurslar" and m.from_user.id in ADMIN_IDS)
@subscription_guard_message
def competitions_menu(message: types.Message):
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("🆕 Yangi konkurs yaratish")
    kb.row("📋 Konkurslarni ko'rish/tahrirlash")
    kb.row("🔙 Asosiy menyu")
    bot.send_message(message.chat.id, "Admin: konkurslar boshqaruvi", reply_markup=kb)


@bot.message_handler(func=lambda m: m.text == "🆕 Yangi konkurs yaratish" and m.from_user.id in ADMIN_IDS)
@subscription_guard_message
def start_new_competition(message: types.Message):
    admin = message.from_user.id
    comp_drafts[admin] = {"mode": "creating", "step": "image"}
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("🔙 Ortga")
    msg = bot.send_message(admin, "Konkurs uchun rasm yuboring:", reply_markup=kb)
    safe_register_next_step_handler(msg, admin_process_comp_image)


def admin_process_comp_image(message: types.Message):
    admin = message.from_user.id
    if getattr(message, "text", "") and message.text == "🔙 Ortga":
        comp_drafts.pop(admin, None)
        competitions_menu(message)
        return
    if not message.photo:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.row("🔙 Ortga")
        msg = bot.send_message(admin, "Iltimos rasm yuboring:", reply_markup=kb)
        safe_register_next_step_handler(msg, admin_process_comp_image)
        return
    file_id = message.photo[-1].file_id
    draft = comp_drafts.get(admin, {})
    draft["file_id"] = file_id
    draft["step"] = "caption"
    comp_drafts[admin] = draft
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("🔙 Ortga")
    msg = bot.send_message(admin, "Konkurs uchun izoh/caption yuboring (yoki '-' bo'sh):", reply_markup=kb)
    safe_register_next_step_handler(msg, admin_process_comp_caption)


def admin_process_comp_caption(message: types.Message):
    admin = message.from_user.id
    if getattr(message, "text", "") and message.text == "🔙 Ortga":
        draft = comp_drafts.get(admin, {})
        draft["step"] = "image"
        comp_drafts[admin] = draft
        bot.send_message(
            admin,
            "Rasm yuboring (yoki yangisini yuboring):",
            reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).row("🔙 Ortga"),
        )
        return
    caption = (message.text or "").strip()
    if caption == "-":
        caption = ""
    draft = comp_drafts.get(admin, {})
    draft["caption"] = caption
    draft["step"] = "deadline"
    comp_drafts[admin] = draft
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("🔙 Ortga")
    msg = bot.send_message(admin, "Konkurs tugash vaqtini yuboring (YYYY-MM-DD HH:MM):", reply_markup=kb)
    safe_register_next_step_handler(msg, admin_process_comp_deadline)


def admin_process_comp_deadline(message: types.Message):
    admin = message.from_user.id
    if getattr(message, "text", "") and message.text == "🔙 Ortga":
        draft = comp_drafts.get(admin, {})
        draft["step"] = "caption"
        comp_drafts[admin] = draft
        bot.send_message(admin, "Izoh yuboring:", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).row("🔙 Ortga"))
        return
    try:
        deadline = datetime.strptime(message.text.strip(), "%Y-%m-%d %H:%M")
    except Exception:
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.row("🔙 Ortga")
        msg = bot.send_message(admin, "Formati noto'g'ri. YYYY-MM-DD HH:MM tarzida yuboring:", reply_markup=kb)
        safe_register_next_step_handler(msg, admin_process_comp_deadline)
        return
    draft = comp_drafts.get(admin, {})
    draft["deadline"] = deadline.isoformat()
    draft["step"] = "winners"
    comp_drafts[admin] = draft
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    kb.row("🔙 Ortga")
    msg = bot.send_message(admin, "G'oliblar sonini kiriting (butun son):", reply_markup=kb)
    safe_register_next_step_handler(msg, admin_process_comp_winners)


def admin_process_comp_winners(message: types.Message):
    admin = message.from_user.id
    if getattr(message, "text", "") and message.text == "🔙 Ortga":
        draft = comp_drafts.get(admin, {})
        draft["step"] = "deadline"
        comp_drafts[admin] = draft
        bot.send_message(admin, "Muddatni yuboring:", reply_markup=types.ReplyKeyboardMarkup(resize_keyboard=True).row("🔙 Ortga"))
        return
    try:
        winners = int(message.text.strip())
        if winners <= 0:
            raise ValueError
    except Exception:
        bot.send_message(admin, "Iltimos, musbat butun son kiriting.")
        return
    draft = comp_drafts.get(admin, {})
    draft["winners"] = winners
    comps = load_json(COMPS_FILE)
    comp_id = str(len(comps) + 1)
    comps[comp_id] = {
        "file_id": draft.get("file_id"),
        "caption": draft.get("caption", ""),
        "deadline": draft.get("deadline"),
        "winners": draft.get("winners"),
        "participants": [],
        "winners_announced": False,
        "message_info": {},
    }
    save_json(COMPS_FILE, comps)
    comp_drafts.pop(admin, None)
    bot.send_message(admin, f"Konkurs #{comp_id} yaratildi va avtomatik e'lon qilinadi.")
    # post to channel and group
    post_competition(comp_id)


def build_comp_caption(comp_id: str, comp: Dict[str, Any]) -> str:
    caption = comp.get("caption", "")
    text = f"🎉 *Konkurs #{comp_id}!* 🎉\n\n"
    if caption:
        text += caption + "\n\n"
    text += f"⏳ Tugash vaqti: {comp.get('deadline')}\n"
    text += f"🏆 G'oliblar soni: {comp.get('winners')}\n\n"
    text += "Ishtirok etish uchun pastdagi tugmani bosing!"
    return text


def build_comp_keyboard(comp_id: str, participants_count: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton(f"✅ Qatnashish ({participants_count})", callback_data=f"join_{comp_id}"))
    return kb


def post_competition(comp_id: str):
    comps = load_json(COMPS_FILE)
    comp = comps.get(comp_id)
    if not comp:
        print(f"[post_competition] {comp_id} not found")
        return
    caption = build_comp_caption(comp_id, comp)
    count = len(comp.get("participants", []))
    kb = build_comp_keyboard(comp_id, count)
    msg_info = comp.get("message_info", {})
    # Post to channel
    try:
        m_ch = bot.send_photo(CHANNEL_ID, comp["file_id"], caption=caption, reply_markup=kb, parse_mode="Markdown")
        msg_info["channel"] = {"chat_id": CHANNEL_ID, "message_id": m_ch.message_id}
    except Exception as e:
        print(f"[post_competition] channel post failed: {e}")
        msg_info["channel"] = {}
    # Post to group
    try:
        m_gr = bot.send_photo(GROUP_ID, comp["file_id"], caption=caption, reply_markup=kb, parse_mode="Markdown")
        msg_info["group"] = {"chat_id": GROUP_ID, "message_id": m_gr.message_id}
    except Exception as e:
        print(f"[post_competition] group post failed: {e}")
        msg_info["group"] = {}
    comp["message_info"] = msg_info
    comps[comp_id] = comp
    save_json(COMPS_FILE, comps)


# -----------------------
# Participant add/update helpers
# -----------------------

def add_participant(comp_id: str, user_id: int, comment: str = "") -> bool:
    comps = load_json(COMPS_FILE)
    comp = comps.get(comp_id)
    if not comp:
        return False
    uid = str(user_id)
    if any(p.get("id") == uid for p in comp.get("participants", [])):
        return False
    comp["participants"].append({"id": uid, "comment": comment})
    comps[comp_id] = comp
    save_json(COMPS_FILE, comps)
    update_competition_posts(comp_id)
    return True


def update_competition_posts(comp_id: str):
    comps = load_json(COMPS_FILE)
    comp = comps.get(comp_id)
    if not comp:
        return
    count = len(comp.get("participants", []))
    caption = build_comp_caption(comp_id, comp)
    kb = build_comp_keyboard(comp_id, count)
    msg_info = comp.get("message_info", {})
    for place in ("channel", "group"):
        info = msg_info.get(place)
        if not info or not info.get("message_id"):
            continue
        try:
            bot.edit_message_caption(
                chat_id=info["chat_id"],
                message_id=info["message_id"],
                caption=caption,
                parse_mode="Markdown",
                reply_markup=kb,
            )
        except Exception as e1:
            try:
                bot.edit_message_reply_markup(
                    chat_id=info["chat_id"], message_id=info["message_id"], reply_markup=kb
                )
            except Exception as e2:
                print(f"[update_competition_posts] failed to update {comp_id} in {place}: {e1} / {e2}")


# -----------------------
# Join flow: callback and confirmation
# -----------------------

@bot.callback_query_handler(func=lambda c: c.data.startswith("join_"))
def callback_join(call: types.CallbackQuery):
    comp_id = call.data.split("_", 1)[1]
    uid = call.from_user.id
    uid_s = str(uid)

    comps = load_json(COMPS_FILE)
    comp = comps.get(comp_id)
    if not comp:
        try:
            bot.answer_callback_query(call.id, "Konkurs topilmadi.", show_alert=True)
        except Exception:
            pass
        return

    # Already participating?
    if any(p.get("id") == uid_s for p in comp.get("participants", [])):
        try:
            bot.answer_callback_query(call.id, "Siz allaqachon qatnashgansiz.", show_alert=True)
        except Exception:
            pass
        try:
            bot.send_message(uid, "Siz allaqachon ushbu konkurs ishtirokchisiz.")
        except Exception:
            pass
        return

    # If subscribed -> add immediately
    if check_subscription(uid):
        added = add_participant(comp_id, uid, comment="")
        if added:
            try:
                bot.answer_callback_query(call.id, "✅ Siz konkursga qo'shildingiz.", show_alert=True)
            except Exception:
                pass
            try:
                bot.send_message(uid, "✅ Siz konkurs ishtirokchisiz! Omad tilaymiz 🎉")
                bot.send_message(
                    uid,
                    "Ushbu bot orqali siz UC ishlashingiz mumkin.\nMenyudagi '🪙 UC islash' tugmasini bosib referal havolani do'stlaringizga ulashing; har bir taklif uchun 3 UC beriladi.",
                )
            except Exception:
                try:
                    bot.answer_callback_query(
                        call.id,
                        f"✅ Siz konkursga qo'shildingiz. Iltimos botni oching: https://t.me/{bot.get_me().username}",
                        show_alert=True,
                    )
                except Exception:
                    pass
        else:
            try:
                bot.answer_callback_query(call.id, "Xatolik yoki allaqachon qatnashgansiz.", show_alert=True)
            except Exception:
                pass
        return

    # Not subscribed -> send DM with confirm_sub_{comp_id}
    sent = send_subscription_prompt(uid, comp_id=comp_id)
    if sent:
        pending_joins[uid] = comp_id
        try:
            bot.answer_callback_query(
                call.id,
                "❗ Sizga shaxsiy xabar yubordim — obuna bo'ling va '✅ Obuna bo'ldim' tugmasini bosing.",
                show_alert=True,
            )
        except Exception:
            pass
    else:
        # DM failed -> instruct to open bot and /start
        try:
            bot.answer_callback_query(
                call.id,
                f"Iltimos botga yozing: https://t.me/{bot.get_me().username} va /start bosing, keyin qaytadan tugmani bosing.",
                show_alert=True,
            )
        except Exception:
            pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("confirm_sub_"))
def callback_confirm_sub(call: types.CallbackQuery):
    uid = call.from_user.id
    comp_id = None
    try:
        comp_id = call.data.split("_", 2)[2]
    except Exception:
        pass
    if not comp_id:
        comp_id = pending_joins.pop(uid, None)
    if not comp_id:
        try:
            bot.answer_callback_query(call.id, "Kontekst topilmadi. Iltimos konkurs postidagi tugmani qayta bosing.", show_alert=True)
        except Exception:
            pass
        return
    if not check_subscription(uid):
        try:
            bot.answer_callback_query(call.id, "❌ Obuna aniqlanmadi. Iltimos kanallarga obuna bo'ling va qayta bosing.", show_alert=True)
            send_subscription_prompt(uid, comp_id=comp_id)
        except Exception:
            pass
        return
    added = add_participant(comp_id, uid, comment="")
    if added:
        try:
            bot.answer_callback_query(call.id, "✅ Obuna tekshirildi va siz konkursga qo'shildingiz!", show_alert=True)
        except Exception:
            pass
        try:
            bot.send_message(uid, "✅ Siz konkurs ishtirokchisiz! Omad tilaymiz 🎉")
            bot.send_message(
                uid,
                "Ushbu bot orqali siz UC ishlashingiz mumkin.\nMenyudagi '🪙 UC islash' tugmasini bosib referal havolani do'stlaringizga ulashing; har bir taklif uchun 3 UC beriladi.",
            )
        except Exception:
            pass
        update_competition_posts(comp_id)
    else:
        try:
            bot.answer_callback_query(call.id, "Siz allaqachon qatnashgansiz yoki xatolik yuz berdi.", show_alert=True)
        except Exception:
            pass


# -----------------------
# Remove unsubscribed participants & finishing competitions
# -----------------------

def remove_unsubscribed_participants():
    comps = load_json(COMPS_FILE)
    changed = False
    for comp_id, comp in comps.items():
        participants = comp.get("participants", [])
        remaining = []
        removed = []
        for p in participants:
            pid_str = p.get("id")
            try:
                pid = int(pid_str)
            except Exception:
                removed.append(p)
                continue
            if check_subscription(pid):
                remaining.append(p)
            else:
                removed.append(p)
        if removed:
            comp["participants"] = remaining
            comps[comp_id] = comp
            changed = True
            for p in removed:
                try:
                    bot.send_message(
                        int(p.get("id")),
                        f"❗ Siz Konkurs #{comp_id} dan chetlatildingiz — obuna bekor qilingan. Qaytadan qatnashish uchun obuna bo'ling va postdagi tugmani bosing.",
                    )
                except Exception:
                    pass
            try:
                update_competition_posts(comp_id)
            except Exception:
                pass
    if changed:
        save_json(COMPS_FILE, comps)


def check_expired_competitions():
    comps = load_json(COMPS_FILE)
    now = datetime.utcnow()
    for comp_id, comp in list(comps.items()):
        try:
            deadline = datetime.fromisoformat(comp.get("deadline"))
        except Exception:
            continue
        if now >= deadline and not comp.get("winners_announced", False):
            finish_competition(comp_id)


def finish_competition(comp_id: str):
    comps = load_json(COMPS_FILE)
    comp = comps.get(comp_id)
    if not comp:
        return
    participants = comp.get("participants", [])
    if not participants:
        msg = f"⚠️ #{comp_id} konkursi yakunlandi. Ishtirokchilar bo'lmadi."
        try:
            bot.send_message(GROUP_ID, msg)
            bot.send_message(CHANNEL_ID, msg)
        except Exception:
            pass
        comp["winners_announced"] = True
        comps[comp_id] = comp
        save_json(COMPS_FILE, comps)
        return
    winners_count = min(comp.get("winners", 1), len(participants))
    winners = random.sample(participants, winners_count)
    winners_ids = [w["id"] for w in winners]
    mentions = []
    for wid in winners_ids:
        try:
            u = bot.get_chat(int(wid))
            mention = f"@{u.username}" if getattr(u, "username", None) else getattr(u, "first_name", f"ID:{wid}")
        except Exception:
            mention = f"ID:{wid}"
        mentions.append(mention)
    announce = (
        f"🎊 Konkurs #{comp_id} yakunlandi! G'oliblar:\n"
        + "\n".join([f"{i+1}. {m}" for i, m in enumerate(mentions)])
        + "\n\nAdminlar siz bilan bog'lanadi."
    )
    try:
        bot.send_message(GROUP_ID, announce)
        bot.send_message(CHANNEL_ID, announce)
    except Exception:
        pass
    for wid in winners_ids:
        try:
            bot.send_message(int(wid), f"🎉 Tabriklaymiz! Siz Konkurs #{comp_id} g'olibisiz! Adminlar bilan bog'laning.")
        except Exception:
            pass
    comp["winners"] = winners_ids
    comp["winners_announced"] = True
    comps[comp_id] = comp
    save_json(COMPS_FILE, comps)
    for adm in ADMIN_IDS:
        try:
            bot.send_message(adm, f"Konkurs #{comp_id} yakunlandi. G'oliblar:\n" + "\n".join(mentions))
        except Exception:
            pass


# -----------------------
# Commands: /start and Back handler
# -----------------------

@bot.message_handler(commands=["start"])  # NOTE: works via webhook
def handler_start(message: types.Message):
    uid = message.from_user.id
    parts = message.text.split()
    ref = None
    if len(parts) > 1:
        ref = parts[1]
    add_user(uid, ref)
    if not check_subscription(uid):
        sent = send_subscription_prompt(uid)
        if not sent:
            try:
                bot.send_message(uid, f"Iltimos botga yozing: https://t.me/{bot.get_me().username} va /start bosing.")
            except Exception:
                pass
    else:
        try:
            bot.send_message(uid, "🎮 Botga xush kelibsiz!", reply_markup=main_menu(uid))
        except Exception:
            pass


@bot.message_handler(func=lambda m: m.text == "🔙 Ortga")
@subscription_guard_message
def handler_back(message: types.Message):
    uid = message.from_user.id
    draft = comp_drafts.get(uid)
    if draft and draft.get("mode") == "creating":
        comp_drafts.pop(uid, None)
        competitions_menu(message)
        return
    try:
        bot.send_message(message.chat.id, "Asosiy menyu:", reply_markup=main_menu(uid))
    except Exception:
        pass


# -----------------------
# Background maintenance worker
# -----------------------

_worker_started = False
_worker_lock = threading.Lock()


def _background_worker_loop():
    while True:
        try:
            remove_unsubscribed_participants()
            check_expired_competitions()
        except Exception as e:
            print(f"[background_worker] error: {e}")
        time.sleep(30)


def start_background_worker_once():
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(target=_background_worker_loop, daemon=True)
        t.start()
        _worker_started = True
        print("Background worker started")


# -----------------------
# Flask webhook app (exported as `server`)
# -----------------------

server = Flask(__name__)


@server.route(f"/{BOT_TOKEN}", methods=["POST"])
def telegram_webhook():
    try:
        update = telebot.types.Update.de_json(request.stream.read().decode("utf-8"))
        bot.process_new_updates([update])
    except Exception as e:
        print(f"[webhook] failed to process update: {e}")
    return "OK", 200


@server.route("/health", methods=["GET"])  # simple health check
@server.route("/", methods=["GET"])
def index():
    """Sets (or re-sets) the webhook and shows a tiny status page."""
    # Prefer explicit WEBHOOK_URL if provided, else build from HEROKU_APP_NAME
    if WEBHOOK_URL:
        base = WEBHOOK_URL.rstrip("/")
    elif HEROKU_APP_NAME:
        base = f"https://{HEROKU_APP_NAME}.herokuapp.com"
    else:
        return (
            "WEBHOOK_URL yoki HEROKU_APP_NAME Config Var o'rnatilmagan. Webhook sozlanmadi.",
            200,
        )

    # Ensure background worker is running (idempotent)
    start_background_worker_once()

    try:
        bot.remove_webhook()
        bot.set_webhook(url=f"{base}/{BOT_TOKEN}")
        status = f"Webhook set to {base}/{BOT_TOKEN}"
    except Exception as e:
        status = f"Webhook set failed: {e}"
    return status, 200


# -----------------------
# Local run (optional)
# -----------------------
if __name__ == "__main__":
    # For local testing you may use polling OR local flask run.
    # 1) Local Flask (simulate Heroku): visit http://localhost:5000 to set webhook to your public URL
    # 2) Or enable polling (NOT for Heroku): uncomment the polling block below.

    # start maintenance worker
    start_background_worker_once()

    port = int(os.environ.get("PORT", 5000))
    server.run(host="0.0.0.0", port=port)

    # --- If you want polling locally (not Heroku), comment out server.run above and uncomment below ---
    # try:
    #     print("Starting polling...")
    #     bot.infinity_polling(timeout=60, long_polling_timeout=60)
    # except KeyboardInterrupt:
    #     print("Bot stopped by user")
    # except Exception as e:
    #     print(f"Bot crashed: {e}")
