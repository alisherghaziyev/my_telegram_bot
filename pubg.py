# -*- coding: utf-8 -*-
import telebot
import sqlite3
import json
import random
import datetime
import os
import threading
import time
import functools
from telebot import types

# Try to import Flask (optional for health checks)
try:
    from flask import Flask
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# Simple HTTP server fallback
from http.server import BaseHTTPRequestHandler, HTTPServer

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"PUBG UC Bot is running")

def run_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    server.serve_forever()

# Bot Configuration
BOT_TOKEN = os.environ.get("BOT_TOKEN")
CHANNEL_ID = "@swKoMBaT"
GROUP_ID = "@swKoMBaT1"
YOUTUBE_LINK = "https://youtube.com/@swkombat?si=5vVIGfj_NYx-yJLK"
ADMIN_IDS = [6322816106, 6072785933]
DB_NAME = "bot.db"

bot = telebot.TeleBot(BOT_TOKEN)

# --- DATABASE INIT ---
def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    ''')
    conn.commit()
    conn.close()

# --- JSON FILES HANDLING ---
def load_json(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_json(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# Initialize JSON files if they don't exist
for file in ["users.json", "competitions.json", "devices.json"]:
    if not os.path.exists(file):
        save_json(file, {})

# --- SUBSCRIPTION CHECK ---
def check_subscription(user_id):
    """
    Return True only if user is member of both CHANNEL_ID and GROUP_ID.
    """
    try:
        channel = bot.get_chat_member(CHANNEL_ID, user_id)
        group = bot.get_chat_member(GROUP_ID, user_id)
        return (channel.status in ["member", "administrator", "creator"]) and \
               (group.status in ["member", "administrator", "creator"])
    except Exception as e:
        # If any problem occurs, treat as not subscribed (safe)
        print(f"Subscription check error for {user_id}: {e}")
        return False

def send_subscription_prompt(user_id):
    """
    Send inline keyboard prompting user to subscribe to channel, group and YouTube.
    The "✅ Obuna bo'ldim" button triggers "check_sub" callback which re-checks subscription.
    """
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📢 Kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_ID.lstrip('@')}"))
    markup.add(types.InlineKeyboardButton("👥 Guruhga obuna bo'lish", url=f"https://t.me/{GROUP_ID.lstrip('@')}"))
    markup.add(types.InlineKeyboardButton("📺 YouTube kanalga obuna bo'lish", url=YOUTUBE_LINK))
    markup.add(types.InlineKeyboardButton("✅ Obuna bo'ldim", callback_data="check_sub"))

    text = (
        "🔒 Botdan foydalanish uchun quyidagilarga obuna bo'ling:\n\n"
        f"{CHANNEL_ID} - Telegram kanal\n"
        f"{GROUP_ID} - Telegram guruh\n"
        f"{YOUTUBE_LINK} - YouTube kanal\n\n"
        "Obuna bo'lgach, '✅ Obuna bo'ldim' tugmasini bosing."
    )
    try:
        bot.send_message(user_id, text, reply_markup=markup)
    except Exception as e:
        print(f"Failed to send subscription prompt to {user_id}: {e}")

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def check_sub_callback(call):
    if check_subscription(call.from_user.id):
        bot.send_message(call.from_user.id, "✅ Obuna tasdiqlandi!")
        send_main_menu(call.from_user.id)
    else:
        bot.send_message(call.from_user.id, "❌ Obuna aniqlanmadi. Iltimos, tekshirib qayta urinib ko'ring.")
        send_subscription_prompt(call.from_user.id)

# --- DECORATORS & SAFE NEXT-STEP ---
def subscription_guard_message(handler_func):
    """
    Decorator for message handlers:
    - Blocks the handler if user is not subscribed to both channel and group.
    - Sends subscription prompt instead.
    - /start is allowed through (so new users can get added).
    """
    @functools.wraps(handler_func)
    def wrapper(message, *args, **kwargs):
        try:
            user_id = message.from_user.id
        except Exception:
            return  # safety: if no from_user, ignore

        # Allow /start to be handled without guard so new user can be registered.
        if getattr(message, "text", "") and message.text.startswith("/start"):
            return handler_func(message, *args, **kwargs)

        if not check_subscription(user_id):
            send_subscription_prompt(user_id)
            return
        return handler_func(message, *args, **kwargs)
    return wrapper

def subscription_guard_callback(handler_func):
    """
    Decorator for callback_query handlers:
    - Blocks the callback action if user is not subscribed, notifies, and sends subscription prompt.
    - Allows 'check_sub' callback to function.
    """
    @functools.wraps(handler_func)
    def wrapper(call, *args, **kwargs):
        try:
            user_id = call.from_user.id
        except Exception:
            return

        if call.data == "check_sub":
            return handler_func(call, *args, **kwargs)

        if not check_subscription(user_id):
            try:
                bot.answer_callback_query(call.id, "❗ Obuna bo'ling", show_alert=True)
            except Exception:
                pass
            send_subscription_prompt(user_id)
            return
        return handler_func(call, *args, **kwargs)
    return wrapper

def safe_register_next_step_handler(msg, callback, *args, **kwargs):
    """
    Use instead of bot.register_next_step_handler so the callback is also wrapped with subscription guard.
    """
    wrapped = subscription_guard_message(callback)
    return bot.register_next_step_handler(msg, wrapped, *args, **kwargs)

# --- MAIN MENU ---
def main_menu(user_id):
    """Generate menu based on user role"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    # Common buttons for all users
    buttons = [
        "📨 Referal havola",
        "📊 Referal reyting",
        "💰 UC balans",
        "💸 UC yechish"
    ]

    # Add admin-only button if user is admin
    if user_id in ADMIN_IDS:
        buttons.insert(3, "🎁 Konkurslar")  # Insert before UC yechish

    # Add buttons in rows
    markup.row(buttons[0], buttons[1])  # First row
    markup.row(buttons[2], buttons[3])  # Second row

    # Add third row only if needed (admin)
    if len(buttons) > 4:
        # place admin button on its own row
        markup.row(buttons[4])

    return markup

def send_main_menu(user_id, text="Asosiy menyu:"):
    """Send main menu keyboard to a user"""
    try:
        markup = main_menu(user_id)
        bot.send_message(user_id, text, reply_markup=markup)
    except Exception as e:
        print(f"Failed to send main menu to {user_id}: {e}")

# --- REFERRAL SYSTEM ---
def add_user(user_id, ref_id=None):
    users = load_json("users.json")
    uid = str(user_id)
    if uid not in users:
        users[uid] = {
            "uc": 0,
            "ref": str(ref_id) if ref_id else None,
            "refs": [],
            "joined": str(datetime.date.today())
        }
        if ref_id and str(ref_id) in users:
            users[str(ref_id)]["refs"].append(uid)
            users[str(ref_id)]["uc"] += 3
        save_json("users.json", users)

# --- REFERRAL LINK ---
@bot.message_handler(func=lambda msg: msg.text == "📨 Referal havola")
@subscription_guard_message
def send_ref_link(message):
    try:
        me = bot.get_me()
        username = me.username if me and getattr(me, 'username', None) else ""
        link = f"https://t.me/{username}?start={message.from_user.id}" if username else f"/start {message.from_user.id}"
    except Exception:
        link = f"/start {message.from_user.id}"
    bot.send_message(message.chat.id, f"🔗 Referal havolangiz:\n{link}")

# --- UC BALANCE ---
@bot.message_handler(func=lambda msg: msg.text == "💰 UC balans")
@subscription_guard_message
def send_uc(message):
    users = load_json("users.json")
    uc = users.get(str(message.from_user.id), {}).get("uc", 0)
    bot.send_message(message.chat.id, f"💰 Sizning balansingiz: {uc} UC")

# --- REFERRAL RATING SYSTEM ---
@bot.message_handler(func=lambda m: m.text == "📊 Referal reyting")
@subscription_guard_message
def handle_referral_rating(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("🔄 Oxirgi 7 kun", "📅 Boshqa davr")
    markup.add("🔙 Ortga")
    bot.send_message(
        message.chat.id,
        "Referal reyting uchun davrni tanlang:",
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: m.text == "🔄 Oxirgi 7 kun")
@subscription_guard_message
def last_7_days_rating(message):
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=7)
    show_referral_rating(message.chat.id, start_date, end_date)

@bot.message_handler(func=lambda m: m.text == "📅 Boshqa davr")
@subscription_guard_message
def ask_custom_dates(message):
    msg = bot.send_message(
        message.chat.id,
        "Boshlanish sanasini yuboring (YYYY-MM-DD):\nMasalan: 2023-12-01"
    )
    safe_register_next_step_handler(msg, process_start_date)

def process_start_date(message):
    if message.text == "🔙 Ortga":
        return send_main_menu(message.chat.id)

    try:
        start_date = datetime.datetime.strptime(message.text, "%Y-%m-%d").date()
        msg = bot.send_message(
            message.chat.id,
            "Tugash sanasini yuboring (YYYY-MM-DD):\nMasalan: 2023-12-31"
        )
        safe_register_next_step_handler(msg, process_end_date, start_date)
    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ Noto'g'ri format. Iltimos quyidagi formatda yuboring: YYYY-MM-DD"
        )
        ask_custom_dates(message)

def process_end_date(message, start_date):
    if message.text == "🔙 Ortga":
        return send_main_menu(message.chat.id)

    try:
        end_date = datetime.datetime.strptime(message.text, "%Y-%m-%d").date()
        if end_date < start_date:
            bot.send_message(
                message.chat.id,
                "❌ Tugash sanasi boshlanish sanasidan oldin bo'lishi mumkin emas."
            )
            ask_custom_dates(message)
        else:
            show_referral_rating(message.chat.id, start_date, end_date)
    except ValueError:
        bot.send_message(
            message.chat.id,
            "❌ Noto'g'ri format. Iltimos quyidagi formatda yuboring: YYYY-MM-DD"
        )
        ask_custom_dates(message)

def show_referral_rating(chat_id, start_date, end_date):
    users = load_json("users.json")
    rating = []

    for user_id, user_data in users.items():
        try:
            join_date = datetime.datetime.strptime(
                user_data.get("joined", "2000-01-01"),
                "%Y-%m-%d"
            ).date()

            if start_date <= join_date <= end_date:
                ref_count = len(user_data.get("refs", []))
                uc_balance = user_data.get("uc", 0)
                rating.append((int(user_id), ref_count, uc_balance))
        except Exception as e:
            print(f"Error processing user {user_id}: {e}")

    if not rating:
        bot.send_message(
            chat_id,
            f"⚠️ {start_date} dan {end_date} gacha bo'lgan davrda hech qanday referal topilmadi."
        )
        return

    rating.sort(key=lambda x: x[1], reverse=True)

    # Build message without Markdown formatting
    message = f"🏆 Referal reyting ({start_date} - {end_date}):\n\n"
    message += "┌──────────┬──────────────────────┬──────────┬───────┐\n"
    message += "│ Reyting  │ Foydalanuvchi        │ Do'stlar │ UC    │\n"
    message += "├──────────┼──────────────────────┼──────────┼───────┤\n"

    for idx, (user_id, ref_count, uc_balance) in enumerate(rating[:10], 1):
        try:
            user_chat = bot.get_chat(user_id)
            username = f"@{user_chat.username}" if getattr(user_chat, 'username', None) else f"ID:{user_id}"
        except Exception:
            username = f"ID:{user_id}"

        # Remove any Markdown special characters
        username = username.replace("*", "").replace("_", "").replace("`", "").replace("[", "").replace("]", "")

        message += f"│ #{idx:<7} │ {username[:20]:<20} │ {ref_count:<7} │ {uc_balance:<5} │\n"

    message += "└──────────┴──────────────────────┴─────────┴───────┘\n\n"
    message += f"📊 Jami referallar: {sum([x[1] for x in rating])}"

    # Send as plain text without Markdown
    try:
        bot.send_message(chat_id, message)
    except Exception as e:
        print(f"Failed to send rating message: {e}")
        # Fallback to simpler message if still failing
        bot.send_message(chat_id, f"Referal reyting ({start_date} - {end_date})\n" +
                         "\n".join([f"{idx}. ID:{uid} - {ref_count} do'st"
                                   for idx, (uid, ref_count, _) in enumerate(rating[:10], 1)]))

# --- UC WITHDRAWAL ---
@bot.message_handler(func=lambda msg: msg.text == "💸 UC yechish")
@subscription_guard_message
def request_uc_withdraw(message):
    users = load_json("users.json")
    uc = users.get(str(message.from_user.id), {}).get("uc", 0)
    if uc < 60:
        bot.send_message(message.chat.id, "❌ UC yechish uchun kamida 60 UC kerak.")
        return

    markup = types.InlineKeyboardMarkup()
    for amount in [60, 120, 180, 325]:
        if uc >= amount:
            markup.add(types.InlineKeyboardButton(f"{amount} UC", callback_data=f"withdraw_{amount}"))
    bot.send_message(message.chat.id, "💳 Yechmoqchi bo'lgan UC miqdorini tanlang:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("withdraw_"))
@subscription_guard_callback
def handle_withdraw(call):
    amount = int(call.data.split("_")[1])
    try:
        msg = bot.send_message(call.from_user.id, f"🔢 PUBG ID raqamingizni yuboring:")
        safe_register_next_step_handler(msg, confirm_withdraw, amount)
    except Exception as e:
        print(f"Error initiating withdraw flow for {call.from_user.id}: {e}")
        bot.answer_callback_query(call.id, "❌ Xatolik yuz berdi", show_alert=True)

def confirm_withdraw(message, amount):
    pubg_id = message.text.strip()
    user_id = message.from_user.id
    users = load_json("users.json")

    if users.get(str(user_id), {}).get("uc", 0) < amount:
        bot.send_message(user_id, "❌ Sizda yetarli UC mavjud emas.")
        return

    users[str(user_id)]["uc"] -= amount
    save_json("users.json", users)

    for admin in ADMIN_IDS:
        try:
            bot.send_message(admin, f"📥 @{message.from_user.username} ({user_id})\n💸 {amount} UC so'radi.\n🔢 PUBG ID: {pubg_id}")
        except Exception as e:
            print(f"Could not notify admin {admin}: {e}")

    bot.send_message(user_id, f"✅ So'rovingiz qabul qilindi. Tez orada UC yuboriladi.")

# --- BACK BUTTON ---
@bot.message_handler(func=lambda m: m.text == "🔙 Ortga")
@subscription_guard_message
def handle_back(message):
    """Handle back button for all users"""
    # For all users, return to main menu
    send_main_menu(message.chat.id)

# --- Helper: update competition posts (caption + keyboard) ---
def build_competition_caption(comp_id, comp):
    caption = comp.get("caption", "")
    caption_full = f"🎉 *Konkurs #{comp_id}!* 🎉\n\n"
    if caption:
        caption_full += f"{caption}\n\n"
    caption_full += f"⏳ Tugash vaqti: {comp['deadline']}\n"
    caption_full += f"🏆 G'oliblar soni: {comp['winners']}\n\nIshtirok etish uchun quyidagi tugmani bosing!"
    return caption_full

def build_join_keyboard(comp_id, participants_count):
    keyboard = types.InlineKeyboardMarkup()
    button_text = f"✅ Qatnashish ({participants_count})"
    keyboard.add(types.InlineKeyboardButton(button_text, callback_data=f"join_{comp_id}"))
    # Admin quick-edit button visible in public posts might be undesirable; keep admin edits via admin menu.
    return keyboard

def update_competition_posts(comp_id):
    competitions = load_json("competitions.json")
    comp = competitions.get(comp_id)
    if not comp:
        return
    participants_count = len(comp.get("participants", []))
    caption_full = build_competition_caption(comp_id, comp)
    keyboard = build_join_keyboard(comp_id, participants_count)

    # Update stored message ids if exist
    msg_info = comp.get("message_info", {})  # expected {"channel": {"chat_id":..., "message_id":...}, "group": {...}}
    # Try edit caption and keyboard in both places
    for place in ("channel", "group"):
        info = msg_info.get(place)
        if not info:
            continue
        chat_id = info.get("chat_id")
        msg_id = info.get("message_id")
        try:
            bot.edit_message_caption(caption=caption_full, chat_id=chat_id, message_id=msg_id, parse_mode="Markdown", reply_markup=keyboard)
        except Exception as e:
            # maybe caption too long or parse error, try edit reply_markup only
            try:
                bot.edit_message_reply_markup(chat_id=chat_id, message_id=msg_id, reply_markup=keyboard)
            except Exception as e2:
                print(f"Failed to update post {comp_id} in {place}: {e} / {e2}")

# --- COMPETITIONS MANAGEMENT (create/post/join/edit/delete) ---
@bot.message_handler(func=lambda m: m.text == "🎁 Konkurslar" and m.from_user.id in ADMIN_IDS)
@subscription_guard_message
def handle_competitions_menu(message):
    """Admin-only competitions menu"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🆕 Yangi konkurs yaratish")
    markup.row("📋 Konkurslarni ko'rish/tahrirlash")
    markup.row("🔙 Asosiy menyu")
    bot.send_message(
        message.chat.id,
        "Admin: konkurslar boshqaruvi",
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: m.text == "🆕 Yangi konkurs yaratish" and m.from_user.id in ADMIN_IDS)
@subscription_guard_message
def ask_competition_image(message):
    """Start competition creation process - ask admin for an image first"""
    msg = bot.send_message(
        message.chat.id,
        "Konkurs uchun rasm yuboring:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    # Next step expects a message with photo
    safe_register_next_step_handler(msg, process_comp_image)

@bot.message_handler(func=lambda m: m.text == "📋 Konkurslarni ko'rish/tahrirlash" and m.from_user.id in ADMIN_IDS)
@subscription_guard_message
def list_competitions_for_admin(message):
    competitions = load_json("competitions.json")
    if not competitions:
        bot.send_message(message.chat.id, "Hozircha konkurslar mavjud emas.")
        return
    for comp_id, comp in competitions.items():
        participants_count = len(comp.get("participants", []))
        caption_preview = comp.get("caption", "")[:200]
        text = f"Konkurs #{comp_id}\nG'oliblar: {comp.get('winners')} | Ishtirokchilar: {participants_count}\n{caption_preview}"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("✏️ Tahrirlash", callback_data=f"admin_edit_{comp_id}"),
               types.InlineKeyboardButton("🗑️ O'chirish", callback_data=f"admin_delete_{comp_id}"))
        kb.add(types.InlineKeyboardButton("📣 Qayta e'lon qilish", callback_data=f"admin_repost_{comp_id}"))
        bot.send_message(message.chat.id, text, reply_markup=kb)

@bot.message_handler(func=lambda m: m.text == "🔙 Asosiy menyu" and m.from_user.id in ADMIN_IDS)
@subscription_guard_message
def admin_back_to_main(message):
    """Special back button for admin menu"""
    send_main_menu(message.chat.id)

def process_comp_image(message):
    if not message.photo:
        msg = bot.send_message(message.chat.id, "Iltimos, rasm yuboring:")
        safe_register_next_step_handler(msg, process_comp_image)
        return

    file_id = message.photo[-1].file_id
    msg = bot.send_message(message.chat.id, "Konkurs uchun sarlavha/izoh yuboring (caption). Agar bo'sh qoldirmoqchi bo'lsangiz, '-' yuboring:")
    safe_register_next_step_handler(msg, process_comp_caption, file_id)

def process_comp_caption(message, file_id):
    caption = message.text.strip()
    if caption == "-":
        caption = ""
    # Ask for deadline
    msg = bot.send_message(message.chat.id, "Konkurs tugash vaqtini yuboring (YYYY-MM-DD HH:MM) - server vaqtida:")
    # Pass file_id and caption forward
    safe_register_next_step_handler(msg, process_comp_deadline, file_id, caption)

def process_comp_deadline(message, file_id, caption):
    try:
        deadline = datetime.datetime.strptime(message.text.strip(), "%Y-%m-%d %H:%M")
    except Exception:
        msg = bot.send_message(message.chat.id, "Formati noto'g'ri. YYYY-MM-DD HH:MM tarzda yozing:")
        safe_register_next_step_handler(msg, process_comp_deadline, file_id, caption)
        return

    msg = bot.send_message(message.chat.id, "G'oliblar sonini kiriting (butun son):")
    safe_register_next_step_handler(msg, process_comp_winners_count, file_id, caption, deadline)

def process_comp_winners_count(message, file_id, caption, deadline):
    try:
        winners = int(message.text.strip())
        if winners <= 0:
            raise ValueError
    except ValueError:
        bot.send_message(message.chat.id, "Iltimos, 0 dan katta butun son kiriting:")
        return

    competitions = load_json("competitions.json")
    comp_id = str(len(competitions) + 1)

    # Store deadline as ISO format
    deadline_iso = deadline.isoformat()

    competitions[comp_id] = {
        "file_id": file_id,
        "deadline": deadline_iso,
        "winners": winners,
        "participants": [],  # list of {"id": "123", "comment": "..." }
        "caption": caption,
        "winners_announced": False,
        "message_info": {}  # will store posted message ids: {"channel": {"chat_id":..., "message_id":...}, "group": {...}}
    }

    save_json("competitions.json", competitions)
    bot.send_message(message.chat.id, f"Konkurs №{comp_id} yaratildi va e'lon qilinadi.")
    post_competition(comp_id)

def post_competition(comp_id):
    """
    Post competition photo with inline 'Join' button to both channel and group.
    Store message ids for later editing (to update participant counts).
    """
    competitions = load_json("competitions.json")
    comp = competitions.get(comp_id)
    if not comp:
        print(f"post_competition: competition {comp_id} not found")
        return

    participants_count = len(comp.get("participants", []))
    keyboard = build_join_keyboard(comp_id, participants_count)
    caption_full = build_competition_caption(comp_id, comp)

    message_info = comp.get("message_info", {})

    # Post in channel
    try:
        msg_channel = bot.send_photo(CHANNEL_ID, comp["file_id"], caption=caption_full, reply_markup=keyboard, parse_mode="Markdown")
        message_info["channel"] = {"chat_id": CHANNEL_ID, "message_id": msg_channel.message_id}
    except Exception as e:
        print(f"Error posting competition {comp_id} to channel: {e}")
        message_info["channel"] = {}

    # Post in group
    try:
        msg_group = bot.send_photo(GROUP_ID, comp["file_id"], caption=caption_full, reply_markup=keyboard, parse_mode="Markdown")
        message_info["group"] = {"chat_id": GROUP_ID, "message_id": msg_group.message_id}
    except Exception as e:
        print(f"Error posting competition {comp_id} to group: {e}")
        message_info["group"] = {}

    comp["message_info"] = message_info
    competitions[comp_id] = comp
    save_json("competitions.json", competitions)

@bot.callback_query_handler(func=lambda c: c.data.startswith("join_"))
@subscription_guard_callback
def join_competition(call):
    comp_id = call.data.split("_", 1)[1]
    competitions = load_json("competitions.json")
    comp = competitions.get(comp_id)
    if not comp:
        return bot.answer_callback_query(call.id, "Konkurs topilmadi", show_alert=True)

    uid = str(call.from_user.id)

    # Check if already participating
    if any(p.get("id") == uid for p in comp.get("participants", [])):
        return bot.answer_callback_query(call.id, "Siz allaqachon qatnashgansiz.")

    # Answer callback, then DM user asking for an optional comment
    try:
        bot.answer_callback_query(call.id, "✅ Siz qatnashmoqchisiz. Shaxsiy xabarga izoh yuboring (ixtiyoriy).")
    except Exception:
        pass

    try:
        # Send private message asking for optional comment
        prompt = bot.send_message(call.from_user.id, "Konkursga qo'shish uchun izoh yuboring (masalan: 'ID:12345', yoki - bo'sh qoldirish uchun '-').")
        # Next step must save comment and add participant
        safe_register_next_step_handler(prompt, save_comment_and_join, comp_id)
    except Exception as e:
        print(f"Could not DM user {uid} for comment: {e}")
        # As fallback, directly add participant with empty comment and notify
        comp["participants"].append({"id": uid, "comment": ""})
        competitions[comp_id] = comp
        save_json("competitions.json", competitions)
        bot.send_message(call.from_user.id, "Siz muvaffaqiyatli konkursga qo'shildingiz (izoh yo'q).")
        update_competition_posts(comp_id)

def save_comment_and_join(message, comp_id):
    comment = message.text.strip() if message.text else ""
    if comment == "-":
        comment = ""
    competitions = load_json("competitions.json")
    comp = competitions.get(comp_id)
    if not comp:
        bot.send_message(message.from_user.id, "Konkurs topilmadi.")
        return

    uid = str(message.from_user.id)

    # Double-check not already in participants
    if any(p.get("id") == uid for p in comp.get("participants", [])):
        bot.send_message(message.from_user.id, "Siz allaqachon qatnashgansiz.")
        return

    comp["participants"].append({"id": uid, "comment": comment})
    competitions[comp_id] = comp
    save_json("competitions.json", competitions)

    bot.send_message(message.from_user.id, "✅ Siz muvaffaqiyatli konkursga qo'shildingiz! Omad tilaymiz 🎉")
    # Update posted messages to reflect new participant count
    update_competition_posts(comp_id)

# Admin callback handlers for edit/delete/repost
@bot.callback_query_handler(func=lambda c: c.data.startswith("admin_edit_") or c.data.startswith("admin_delete_") or c.data.startswith("admin_repost_"))
@subscription_guard_callback
def admin_comp_actions(call):
    data = call.data
    if not any(admin == call.from_user.id for admin in ADMIN_IDS):
        return bot.answer_callback_query(call.id, "Bu faqat adminlarga!", show_alert=True)

    if data.startswith("admin_edit_"):
        comp_id = data.split("_", 2)[2]
        # Present editing options
        kb = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        kb.row("🔁 Rasmni o'zgartirish", "✍️ Izohni tahrirlash")
        kb.row("⏰ Muddatni tahrirlash", "🏆 G'oliblar sonini o'zgartirish")
        kb.row("📌 Ishtirokchilar ro'yxati", "📣 Hozir e'lon qilish")
        kb.row("🔙 Ortga")
        msg = bot.send_message(call.from_user.id, f"Konkurs #{comp_id} - tahrirlash menyusi. Qaysi maydonni tahrirlaysiz?", reply_markup=kb)
        # Store context via a simple mapping file or pass comp_id by next step handler
        safe_register_next_step_handler(msg, process_admin_edit_choice, comp_id)
        bot.answer_callback_query(call.id)
        return

    if data.startswith("admin_delete_"):
        comp_id = data.split("_", 2)[2]
        competitions = load_json("competitions.json")
        if comp_id in competitions:
            del competitions[comp_id]
            save_json("competitions.json", competitions)
            bot.answer_callback_query(call.id, f"Konkurs #{comp_id} o'chirildi.", show_alert=True)
            bot.send_message(call.from_user.id, f"Konkurs #{comp_id} muvaffaqiyatli o'chirildi.")
        else:
            bot.answer_callback_query(call.id, "Konkurs topilmadi.", show_alert=True)
        return

    if data.startswith("admin_repost_"):
        comp_id = data.split("_", 2)[2]
        # Repost (edit messages with same content) to refresh
        update_competition_posts(comp_id)
        bot.answer_callback_query(call.id, f"Konkurs #{comp_id} postlari yangilandi.", show_alert=True)
        bot.send_message(call.from_user.id, f"Konkurs #{comp_id} postlari yangilanishga harakat qilindi.")
        return

def process_admin_edit_choice(message, comp_id):
    text = message.text
    competitions = load_json("competitions.json")
    comp = competitions.get(comp_id)
    if not comp:
        bot.send_message(message.chat.id, "Konkurs topilmadi.")
        return

    if text == "🔁 Rasmni o'zgartirish":
        msg = bot.send_message(message.chat.id, "Yangi rasm yuboring:")
        safe_register_next_step_handler(msg, admin_update_image, comp_id)
    elif text == "✍️ Izohni tahrirlash":
        msg = bot.send_message(message.chat.id, "Yangi izohni yuboring (yoki '-' bo'sh qoldirish):")
        safe_register_next_step_handler(msg, admin_update_caption, comp_id)
    elif text == "⏰ Muddatni tahrirlash":
        msg = bot.send_message(message.chat.id, "Yangi muddatni yuboring (YYYY-MM-DD HH:MM):")
        safe_register_next_step_handler(msg, admin_update_deadline, comp_id)
    elif text == "🏆 G'oliblar sonini o'zgartirish":
        msg = bot.send_message(message.chat.id, "Yangi g'oliblar sonini yuboring (butun son):")
        safe_register_next_step_handler(msg, admin_update_winners_count, comp_id)
    elif text == "📌 Ishtirokchilar ro'yxati":
        participants = comp.get("participants", [])
        if not participants:
            bot.send_message(message.chat.id, "Ishtirokchilar mavjud emas.")
        else:
            txt = "Ishtirokchilar:\n" + "\n".join([f"- {p['id']} | {p.get('comment','')}" for p in participants])
            bot.send_message(message.chat.id, txt)
    elif text == "📣 Hozir e'lon qilish":
        # Trigger immediate finish or repost? We'll repost/update posts
        update_competition_posts(comp_id)
        bot.send_message(message.chat.id, f"Konkurs #{comp_id} postlari yangilandi.")
    elif text == "🔙 Ortga":
        handle_competitions_menu(message)
    else:
        bot.send_message(message.chat.id, "Noma'lum tanlov. Admin menyusiga qaytildi.")
        handle_competitions_menu(message)

def admin_update_image(message, comp_id):
    if not message.photo:
        msg = bot.send_message(message.chat.id, "Iltimos, rasm yuboring:")
        safe_register_next_step_handler(msg, admin_update_image, comp_id)
        return
    file_id = message.photo[-1].file_id
    competitions = load_json("competitions.json")
    comp = competitions.get(comp_id)
    if not comp:
        bot.send_message(message.chat.id, "Konkurs topilmadi.")
        return
    comp["file_id"] = file_id
    competitions[comp_id] = comp
    save_json("competitions.json", competitions)
    # Try to edit the posted media in both chats
    msg_info = comp.get("message_info", {})
    for place in ("channel", "group"):
        info = msg_info.get(place)
        if not info:
            continue
        chat_id = info.get("chat_id")
        message_id = info.get("message_id")
        try:
            media = types.InputMediaPhoto(media=file_id, caption=build_competition_caption(comp_id, comp))
            bot.edit_message_media(media=media, chat_id=chat_id, message_id=message_id, reply_markup=build_join_keyboard(comp_id, len(comp.get("participants", []))))
        except Exception as e:
            print(f"Failed to edit media for comp {comp_id} in {place}: {e}")
    bot.send_message(message.chat.id, f"Konkurs #{comp_id} rasmi yangilandi va postlar yangilanishi urinildi.")

def admin_update_caption(message, comp_id):
    caption = message.text.strip()
    if caption == "-":
        caption = ""
    competitions = load_json("competitions.json")
    comp = competitions.get(comp_id)
    if not comp:
        bot.send_message(message.chat.id, "Konkurs topilmadi.")
        return
    comp["caption"] = caption
    competitions[comp_id] = comp
    save_json("competitions.json", competitions)
    update_competition_posts(comp_id)
    bot.send_message(message.chat.id, f"Konkurs #{comp_id} izohi yangilandi.")

def admin_update_deadline(message, comp_id):
    try:
        deadline = datetime.datetime.strptime(message.text.strip(), "%Y-%m-%d %H:%M")
    except Exception:
        msg = bot.send_message(message.chat.id, "Formati noto'g'ri. YYYY-MM-DD HH:MM tarzda yozing:")
        safe_register_next_step_handler(msg, admin_update_deadline, comp_id)
        return
    competitions = load_json("competitions.json")
    comp = competitions.get(comp_id)
    if not comp:
        bot.send_message(message.chat.id, "Konkurs topilmadi.")
        return
    comp["deadline"] = deadline.isoformat()
    competitions[comp_id] = comp
    save_json("competitions.json", competitions)
    update_competition_posts(comp_id)
    bot.send_message(message.chat.id, f"Konkurs #{comp_id} muddatini yangilandi: {comp['deadline']}")

def admin_update_winners_count(message, comp_id):
    try:
        winners = int(message.text.strip())
        if winners <= 0:
            raise ValueError
    except Exception:
        msg = bot.send_message(message.chat.id, "Iltimos, 0 dan katta butun son kiriting:")
        safe_register_next_step_handler(msg, admin_update_winners_count, comp_id)
        return
    competitions = load_json("competitions.json")
    comp = competitions.get(comp_id)
    if not comp:
        bot.send_message(message.chat.id, "Konkurs topilmadi.")
        return
    comp["winners"] = winners
    competitions[comp_id] = comp
    save_json("competitions.json", competitions)
    update_competition_posts(comp_id)
    bot.send_message(message.chat.id, f"Konkurs #{comp_id} g'oliblar soni yangilandi: {winners}")

# --- Expiration and finishing logic ---
def check_expired_competitions():
    competitions = load_json("competitions.json")
    now = datetime.datetime.now()
    for comp_id, comp in list(competitions.items()):
        try:
            deadline = datetime.datetime.fromisoformat(comp["deadline"])
            if now >= deadline and not comp.get("winners_announced", False):
                finish_competition(comp_id)
        except Exception as e:
            print(f"Error processing competition {comp_id}: {e}")

def finish_competition(comp_id):
    competitions = load_json("competitions.json")
    comp = competitions.get(comp_id)
    if not comp:
        print(f"finish_competition: comp {comp_id} not found")
        return

    if comp.get("winners_announced", False):
        return  # already processed

    participants = comp.get("participants", [])
    winners_count = comp.get("winners", 1)

    if not participants:
        announcement = f"⚠️ #{comp_id} konkursi yakunlandi. Ishtirokchilar bo'lmadi."
        try:
            bot.send_message(GROUP_ID, announcement)
            bot.send_message(CHANNEL_ID, announcement)
        except Exception as e:
            print(f"Error announcing no participants for comp {comp_id}: {e}")

        comp["winners_announced"] = True
        competitions[comp_id] = comp
        save_json("competitions.json", competitions)
        return

    # Choose winners randomly from participants list
    winners_count = min(winners_count, len(participants))
    winners_sample = random.sample(participants, winners_count)
    winners_ids = [p["id"] for p in winners_sample]

    # Prepare winner mentions and notify winners privately
    winner_mentions = []
    for wid in winners_ids:
        try:
            user = bot.get_chat(int(wid))
            if getattr(user, 'username', None):
                mention = f"@{user.username}"
            else:
                # Use markdown mention by id
                name = getattr(user, 'first_name', 'Ism')
                mention = f"[{name}](tg://user?id={user.id})"
        except Exception:
            mention = f"ID:{wid}"
        winner_mentions.append((wid, mention))

    # Announce in group and channel
    winners_text = "\n".join([f"🏆 {i+1}. {m[1]}" for i, m in enumerate(winner_mentions)])
    caption = comp.get("caption", "")
    announcement = (
        f"🎊 *Konkurs #{comp_id} yakunlandi!* 🎊\n\n"
        f"{('' if not caption else caption + '\\n\\n')}"
        f"G'oliblar ({len(winner_mentions)} ta):\n"
        f"{winners_text}\n\n"
        "Tabriklaymiz! 🎉 Adminlar tez orada siz bilan bog'lanishadi."
    )

    # Send to both group and channel with Markdown safe mentions (we used inline tg://user links)
    try:
        bot.send_message(GROUP_ID, announcement, parse_mode="Markdown")
        bot.send_message(CHANNEL_ID, announcement, parse_mode="Markdown")
    except Exception as e:
        print(f"Error announcing winners for comp {comp_id}: {e}")
        # Fallback without parse_mode
        try:
            fallback = f"Konkurs #{comp_id} g'oliblari ({len(winner_mentions)}):\n" + "\n".join([f"{i+1}. {m[1]}" for i, m in enumerate(winner_mentions)])
            bot.send_message(GROUP_ID, fallback)
            bot.send_message(CHANNEL_ID, fallback)
        except Exception as e2:
            print(f"Fallback announcement failed: {e2}")

    # DM winners individually with congratulations and their prize notification
    for wid, mention in winner_mentions:
        try:
            bot.send_message(int(wid),
                             f"🎉 Tabriklaymiz! Siz #{comp_id} konkurs g'oliblaridan birisiz!\n{mention}\nTez orada adminlar siz bilan bog'lanadi.")
        except Exception as e:
            print(f"Could not DM winner {wid}: {e}")

    # Update competition status
    comp["winners"] = winners_ids
    comp["winners_announced"] = True
    competitions[comp_id] = comp
    save_json("competitions.json", competitions)

    # Notify admins
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(admin_id, f"🏆 #{comp_id} konkurs yakunlandi. G'oliblar:\n" + "\n".join([f"- {m[1]}" for m in winner_mentions]))
        except Exception as e:
            print(f"Could not notify admin {admin_id}: {e}")

# --- START COMMAND ---
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    ref_id = None

    parts = message.text.split()
    if len(parts) > 1:
        # start may be like: /start 12345
        ref_id = parts[1]

    add_user(user_id, ref_id)

    if not check_subscription(user_id):
        send_subscription_prompt(user_id)
    else:
        send_main_menu(user_id, "🎮 Botga xush kelibsiz!")

# --- COMPETITION CHECKER THREAD ---
def competition_checker_thread():
    while True:
        try:
            check_expired_competitions()
            time.sleep(30)  # check every 30 seconds
        except Exception as e:
            print(f"Error in competition checker: {e}")
            time.sleep(30)

# --- HEALTH CHECK SERVER & STARTUP ---
if __name__ == "__main__":
    try:
        init_db()
        print("Database initialized")

        # Start competition checker thread
        checker_thread = threading.Thread(target=competition_checker_thread)
        checker_thread.daemon = True
        checker_thread.start()
        print("Competition checker started")

        # Start health check server
        if FLASK_AVAILABLE:
            app = Flask(__name__)
            @app.route('/')
            def health_check():
                return "PUBG UC Bot is running", 200

            flask_thread = threading.Thread(target=lambda: app.run(
                host='0.0.0.0',
                port=int(os.environ.get("PORT", 10000)),
                debug=False,
                use_reloader=False
            ))
            flask_thread.daemon = True
            flask_thread.start()
            print("Flask health check started")
        else:
            flask_thread = threading.Thread(target=run_server)
            flask_thread.daemon = True
            flask_thread.start()
            print("Simple HTTP health check server started")

        print("Starting bot polling...")
        bot.infinity_polling(timeout=60, long_polling_timeout=60)

    except Exception as e:
        print(f"Bot crashed: {e}")
        for admin in ADMIN_IDS:
            try:
                bot.send_message(admin, f"Bot crashed: {e}")
            except Exception:
                pass
