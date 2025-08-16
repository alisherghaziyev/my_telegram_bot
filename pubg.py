# -*- coding: utf-8 -*-
import telebot
import sqlite3
from telebot import types
import json
import random
import datetime
import os

BOT_TOKEN = "8113191674:AAEZs4N9NtKF5lSa3WLIIV9oO_t5b9tHVkg"
CHANNEL_ID = "@swKoMBaT"
GROUP_ID = "@swKoMBaT1"
YOUTUBE_LINK = "https://youtube.com/@swkombat?si=5vVIGfj_NYx-yJLK"
ADMIN_IDS = [6322816106]
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

# --- JSON FAYLLAR YARATIB OLING ---
for file in ["users.json", "competitions.json", "devices.json"]:
    try:
        open(file, "x").write("{}")
    except:
        pass

# --- OBUNA TEKSHIRISH ---
def check_subscription(user_id):
    try:
        channel = bot.get_chat_member(CHANNEL_ID, user_id)
        group = bot.get_chat_member(GROUP_ID, user_id)
        return channel.status in ["member", "administrator", "creator"] and group.status in ["member", "administrator", "creator"]
    except:
        return False

def send_subscription_prompt(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📢 Kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_ID[1:]}"))
    markup.add(types.InlineKeyboardButton("👥 Guruhga obuna bo'lish", url=f"https://t.me/{GROUP_ID[1:]}"))
    markup.add(types.InlineKeyboardButton("📺 YouTube kanalga obuna bo'lish", url=YOUTUBE_LINK))
    markup.add(types.InlineKeyboardButton("✅ Obuna bo‘ldim", callback_data="check_sub"))
    text = (
        "🔒 Botdan foydalanish uchun quyidagilarga obuna bo‘ling:\n\n"
        f"{CHANNEL_ID} - Telegram kanal\n"
        f"{GROUP_ID} - Telegram guruh\n"
        f"{YOUTUBE_LINK} - YouTube kanal\n\n"
        "Obuna bo‘lgach, '✅ Obuna bo‘ldim' tugmasini bosing."
    )
    bot.send_message(user_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def check_sub_callback(call):
    if check_subscription(call.from_user.id):
        bot.send_message(call.from_user.id, "✅ Obuna tasdiqlandi!")
        start(call.message)
    else:
        bot.send_message(call.from_user.id, "❌ Obuna aniqlanmadi. Iltimos, tekshirib qayta urinib ko‘ring.")

# --- ASOSIY MENYU ---
def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📨 Referal havola", "📊 Referal reyting")
    markup.row("🎁 Konkurslar", "💰 UC balans")
    markup.row("💸 UC yechish")
    return markup

# --- REFERAL TIZIMI ---
def load_users():
    with open("users.json", "r") as f:
        return json.load(f)

def save_users(users):
    with open("users.json", "w") as f:
        json.dump(users, f, indent=4)

def add_user(user_id, ref_id=None):
    users = load_users()
    if str(user_id) not in users:
        users[str(user_id)] = {
            "uc": 0,
            "ref": str(ref_id) if ref_id else None,
            "refs": [],
            "joined": str(datetime.date.today())
        }
        if ref_id and str(ref_id) in users:
            users[str(ref_id)]["refs"].append(str(user_id))
            users[str(ref_id)]["uc"] += 3
        save_users(users)

# --- REFERAL HAVOLA ---
@bot.message_handler(func=lambda msg: msg.text == "📨 Referal havola")
def send_ref_link(message):
    link = f"https://t.me/{bot.get_me().username}?start={message.from_user.id}"
    bot.send_message(message.chat.id, f"🔗 Referal havolangiz:\n{link}")

# --- UC BALANSI ---
@bot.message_handler(func=lambda msg: msg.text == "💰 UC balans")
def send_uc(message):
    users = load_users()
    uc = users.get(str(message.from_user.id), {}).get("uc", 0)
    bot.send_message(message.chat.id, f"💰 Sizning balansingiz: {uc} UC")

# --- UC YECHISH ---
@bot.message_handler(func=lambda msg: msg.text == "💸 UC yechish")
def request_uc_withdraw(message):
    users = load_users()
    uc = users.get(str(message.from_user.id), {}).get("uc", 0)
    if uc < 60:
        bot.send_message(message.chat.id, "❌ UC yechish uchun kamida 60 UC kerak.")
        return
    markup = types.InlineKeyboardMarkup()
    for amount in [60, 120, 180, 325]:
        if uc >= amount:
            markup.add(types.InlineKeyboardButton(f"{amount} UC", callback_data=f"withdraw_{amount}"))
    bot.send_message(message.chat.id, "💳 Yechmoqchi bo‘lgan UC miqdorini tanlang:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("withdraw_"))
def handle_withdraw(call):
    amount = int(call.data.split("_")[1])
    msg = bot.send_message(call.from_user.id, f"🔢 PUBG ID raqamingizni yuboring:")
    bot.register_next_step_handler(msg, confirm_withdraw, amount)

def confirm_withdraw(message, amount):
    pubg_id = message.text.strip()
    user_id = message.from_user.id
    users = load_users()
    if users[str(user_id)]["uc"] < amount:
        bot.send_message(user_id, "❌ Sizda yetarli UC mavjud emas.")
        return
    users[str(user_id)]["uc"] -= amount
    save_users(users)
    for admin in ADMIN_IDS:
        bot.send_message(admin, f"📥 @{message.from_user.username} ({user_id})\n💸 {amount} UC so‘radi.\n🔢 PUBG ID: {pubg_id}")
    bot.send_message(user_id, f"✅ So‘rovingiz qabul qilindi. Tez orada UC yuboriladi.")

# --- UC ISHLASH YO‘RIQNOMA ---
def send_uc_info(user_id):
    msg = (
        "🎮 *PUBG UC ishlash yo‘riqnoma:*\n\n"
        "1. @swKoMBaT kanaliga obuna bo‘ling.\n"
        "2. @swKoMBaT1 guruhiga obuna bo‘ling.\n"
        "3. Referal havolangizni tarqating.\n"
        "4. Har bir do‘st uchun 3 UC olasiz!\n"
        "5. 60 UC dan boshlab yechishingiz mumkin."
    )
    bot.send_message(user_id, msg, parse_mode="Markdown")

# --- ADMIN: KONKURSLAR ---
@bot.message_handler(func=lambda m: m.from_user.id in ADMIN_IDS and m.text == "🎁 Konkurslar")
def admin_competitions_menu(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🆕 Yangi konkurs yaratish")
    markup.row("🔙 Ortga")
    bot.send_message(message.chat.id, "Admin: nima qilamiz?", reply_markup=markup)

@bot.message_handler(func=lambda m: m.from_user.id in ADMIN_IDS and m.text == "🆕 Yangi konkurs yaratish")
def ask_competition_image(message):
    msg = bot.send_message(message.chat.id, "Konkurs rasm yuboring:")
    bot.register_next_step_handler(msg, process_comp_image)

@bot.message_handler(func=lambda m: m.from_user.id in ADMIN_IDS and m.text == "🔙 Ortga")
def admin_back_to_main_menu(message):
    markup = main_menu(message.from_user.id)
    bot.send_message(message.chat.id, "🎮 Asosiy menyu:", reply_markup=markup)



def process_comp_image(message):
    if not message.photo:
        return bot.send_message(message.chat.id, "Iltimos, rasm yuboring:")
    file_id = message.photo[-1].file_id
    msg = bot.send_message(message.chat.id, "Konkurs tugash vaqtini yuboring (YYYY-MM-DD HH:MM):")
    bot.register_next_step_handler(msg, process_comp_deadline, file_id)

def process_comp_deadline(message, file_id):
    try:
        deadline = datetime.datetime.strptime(message.text, "%Y-%m-%d %H:%M")
    except:
        return bot.send_message(message.chat.id, "Formati noto‘g‘ri. YYYY-MM-DD HH:MM tarzda yozing:")
    msg = bot.send_message(message.chat.id, "G‘oliblar sonini kiriting:")
    bot.register_next_step_handler(msg, process_comp_winners_count, file_id, deadline)

def process_comp_winners_count(message, file_id, deadline):
    try:
        winners = int(message.text)
    except:
        return bot.send_message(message.chat.id, "Iltimos, butun son kiriting:")
    comp = {
        "file_id": file_id,
        "deadline": deadline.isoformat(),
        "winners": winners,
        "participants": []
    }
    competitions = json.load(open("competitions.json"))
    comp_id = str(len(competitions) + 1)
    competitions[comp_id] = comp
    json.dump(competitions, open("competitions.json", "w"), indent=4)
    bot.send_message(message.chat.id, f"Konkurs №{comp_id} yaratildi. Endi e’lon qilinadi.")
    post_competition(comp_id)

def post_competition(comp_id):
    comp = json.load(open("competitions.json"))[comp_id]
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("✅ Qatnashish", callback_data=f"join_{comp_id}"))
    caption = f"📢 *Konkurs #{comp_id}!*⠀\n\nVaqti: {comp['deadline']}\n\nIshtirok etish uchun “Qatnashish” tugmasini bosing!"
    bot.send_photo(CHANNEL_ID, comp["file_id"], caption, reply_markup=keyboard, parse_mode="Markdown")
    bot.send_photo(GROUP_ID, comp["file_id"], caption, reply_markup=keyboard, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data and c.data.startswith("join_"))
def join_competition(call):
    comp_id = call.data.split("_")[1]
    competitions = json.load(open("competitions.json"))
    comp = competitions[comp_id]
    uid = str(call.from_user.id)
    if uid in comp["participants"]:
        return bot.answer_callback_query(call.id, "Siz allaqachon qatnashgansiz.")
    if not check_subscription(call.from_user.id):
        bot.answer_callback_query(call.id, "❗ Obuna bo‘ling", show_alert=True)
        send_subscription_prompt(call.from_user.id)
        return
    comp["participants"].append(uid)
    competitions[comp_id] = comp
    json.dump(competitions, open("competitions.json", "w"), indent=4)
    bot.answer_callback_query(call.id, "✅ Siz tanlov ishtirokchisiga aylandingiz!")

def finish_competition(comp_id):
    competitions = json.load(open("competitions.json"))
    comp = competitions[comp_id]
    participants = comp["participants"]
    if not participants:
        return
    winners = random.sample(participants, min(comp["winners"], len(participants)))
    comp["winners_list"] = winners
    competitions[comp_id] = comp
    json.dump(competitions, open("competitions.json", "w"), indent=4)
    for w in winners:
        bot.send_message(int(w), f"🎉 Tabriglar! Siz Konkurs #{comp_id} g‘olibsiz!")
    for admin in ADMIN_IDS:
        bot.send_message(admin, f"Konkurs #{comp_id} yakunlandi.\nG‘oliblar: {winners}")

# --- REFERAL REYTING (ANIQ DAVR ORQALI) ---

@bot.message_handler(func=lambda m: m.from_user.id in ADMIN_IDS and m.text == "📊 Referal reyting")
def ask_rating_start_date(message):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("🔙 Ortga")
    msg = bot.send_message(message.chat.id, "Davrni boshlanish sanasini kiriting (YYYY-MM-DD):", reply_markup=markup)
    bot.register_next_step_handler(msg, ask_rating_end_date)

def ask_rating_end_date(message):
    if message.text == "🔙 Ortga":
        send_main_menu(message.chat.id)
        return

    try:
        start_date = datetime.datetime.strptime(message.text.strip(), "%Y-%m-%d").date()
    except ValueError:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("🔙 Ortga")
        msg = bot.send_message(message.chat.id, "Sanani noto‘g‘ri kiritdingiz. Iltimos YYYY-MM-DD formatida kiriting:", reply_markup=markup)
        bot.register_next_step_handler(msg, ask_rating_end_date)
        return

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add("🔙 Ortga")
    msg = bot.send_message(message.chat.id, "Davrni tugash sanasini kiriting (YYYY-MM-DD):", reply_markup=markup)
    bot.register_next_step_handler(msg, show_rating_period, start_date)

def show_rating_period(message, start_date):
    if message.text == "🔙 Ortga":
        send_main_menu(message.chat.id)
        return

    try:
        end_date = datetime.datetime.strptime(message.text.strip(), "%Y-%m-%d").date()
    except ValueError:
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
        markup.add("🔙 Ortga")
        msg = bot.send_message(message.chat.id, "Sanani noto‘g‘ri kiritdingiz. Iltimos YYYY-MM-DD formatida kiriting:", reply_markup=markup)
        bot.register_next_step_handler(msg, show_rating_period, start_date)
        return

    users = load_users()
    filtered_users = []
    for uid, data in users.items():
        joined_date = datetime.datetime.fromisoformat(data["joined"]).date()
        if start_date <= joined_date <= end_date:
            filtered_users.append((uid, len(data.get("refs", [])), data.get("uc", 0)))

    filtered_users.sort(key=lambda x: x[1], reverse=True)

    if not filtered_users:
        bot.send_message(message.chat.id, "Ushbu davr uchun ma'lumot topilmadi.")
        send_main_menu(message.chat.id)
        return

    text = f"📊 Referal reyting {start_date} dan {end_date} gacha:\n\n"
    for i, (uid, refs_count, uc) in enumerate(filtered_users[:10], 1):
        # username olish uchun xavfsiz urinish
        try:
            user_info = bot.get_chat_member(int(uid), int(uid)).user
            username = "@" + user_info.username if user_info.username else f"ID:{uid}"
        except:
            username = f"ID:{uid}"
        text += f"{i}. {username} - Do‘stlar: {refs_count}, UC: {uc}\n"

    bot.send_message(message.chat.id, text)
    send_main_menu(message.chat.id)


# --- ASOSIY MENYU FUNKSIYASI ---
def main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("📨 Referal havola", "📊 Referal reyting")
    markup.row("🎁 Konkurslar", "💰 UC balans")
    markup.row("💸 UC yechish")
    return markup

def send_main_menu(user_id, text="🎮 Asosiy menyu:"):
    markup = main_menu(user_id)
    bot.send_message(user_id, text, reply_markup=markup)


# --- /start HANDLER ---
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    ref_id = None
    if message.text and len(message.text.split()) > 1:
        ref_id = message.text.split()[1]
    add_user(user_id, ref_id)
    if not check_subscription(user_id):
        send_subscription_prompt(user_id)
    else:
        bot.send_message(user_id, "🎮 Botga xush kelibsiz!", reply_markup=main_menu(user_id))

if __name__ == "__main__":
    init_db()
    bot.infinity_polling()

