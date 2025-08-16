# -*- coding: utf-8 -*-
import telebot
import sqlite3
from telebot import types
import json
import random
import datetime
import os
import threading
import datetime
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
ADMIN_IDS = [6322816106,1401881769,6072785933]
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
        with open(filename, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def send_main_menu(user_id, text="Asosiy menyu:"):
    """Send appropriate menu based on user role"""
    markup = main_menu(user_id)
    bot.send_message(user_id, text, reply_markup=markup)

def main_menu(user_id):
    """Generate menu based on user role"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    
    # Common buttons for all users
    row1 = ["📨 Referal havola", "📊 Referal reyting"]
    row2 = ["💰 UC balans", "💸 UC yechish"]
    
    # Add admin button if needed
    if user_id in ADMIN_IDS:
        row2.insert(1, "🎁 Konkurslar")  # Insert after UC balans
    
    markup.row(*row1)
    markup.row(*row2)
    
    return markup

def save_json(filename, data):
    with open(filename, 'w') as f:
        json.dump(data, f, indent=4)

# Initialize JSON files if they don't exist
for file in ["users.json", "competitions.json", "devices.json"]:
    if not os.path.exists(file):
        save_json(file, {})

# --- SUBSCRIPTION CHECK ---
def check_subscription(user_id):
    try:
        channel = bot.get_chat_member(CHANNEL_ID, user_id)
        group = bot.get_chat_member(GROUP_ID, user_id)
        return channel.status in ["member", "administrator", "creator"] and group.status in ["member", "administrator", "creator"]
    except Exception as e:
        print(f"Subscription check error: {e}")
        return False

def send_subscription_prompt(user_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📢 Kanalga obuna bo'lish", url=f"https://t.me/{CHANNEL_ID[1:]}"))
    markup.add(types.InlineKeyboardButton("👥 Guruhga obuna bo'lish", url=f"https://t.me/{GROUP_ID[1:]}"))
    markup.add(types.InlineKeyboardButton("📺 YouTube kanalga obuna bo'lish", url=YOUTUBE_LINK))
    markup.add(types.InlineKeyboardButton("✅ Obuna bo'ldim", callback_data="check_sub"))
    
    text = (
        "🔒 Botdan foydalanish uchun quyidagilarga obuna bo'ling:\n\n"
        f"{CHANNEL_ID} - Telegram kanal\n"
        f"{GROUP_ID} - Telegram guruh\n"
        f"{YOUTUBE_LINK} - YouTube kanal\n\n"
        "Obuna bo'lgach, '✅ Obuna bo'ldim' tugmasini bosing."
    )
    bot.send_message(user_id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "check_sub")
def check_sub_callback(call):
    if check_subscription(call.from_user.id):
        bot.send_message(call.from_user.id, "✅ Obuna tasdiqlandi!")
        send_main_menu(call.from_user.id) 
    else:
        bot.send_message(call.from_user.id, "❌ Obuna aniqlanmadi. Iltimos, tekshirib qayta urinib ko'ring.")

# --- MAIN MENU ---
def main_menu(user_id):
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
        buttons.insert(3, "🎁 Konkurslar")  # Insert at position 3
    
    # Add buttons in rows
    markup.row(buttons[0], buttons[1])  # First row
    markup.row(buttons[2], buttons[3])  # Second row
    
    # Add third row only if needed
    if len(buttons) > 4:
        markup.row(buttons[4])  # Third row for admin
        
    return markup

# --- REFERRAL SYSTEM ---
def add_user(user_id, ref_id=None):
    users = load_json("users.json")
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
        save_json("users.json", users)

# --- REFERRAL LINK ---
@bot.message_handler(func=lambda msg: msg.text == "📨 Referal havola")
def send_ref_link(message):
    link = f"https://t.me/{bot.get_me().username}?start={message.from_user.id}"
    bot.send_message(message.chat.id, f"🔗 Referal havolangiz:\n{link}")

# --- UC BALANCE ---
@bot.message_handler(func=lambda msg: msg.text == "💰 UC balans")
def send_uc(message):
    users = load_json("users.json")
    uc = users.get(str(message.from_user.id), {}).get("uc", 0)
    bot.send_message(message.chat.id, f"💰 Sizning balansingiz: {uc} UC")

# --- REFERRAL RATING SYSTEM ---
@bot.message_handler(func=lambda m: m.text == "📊 Referal reyting")
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
def last_7_days_rating(message):
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=7)
    show_referral_rating(message.chat.id, start_date, end_date)

@bot.message_handler(func=lambda m: m.text == "📅 Boshqa davr")
def ask_custom_dates(message):
    msg = bot.send_message(
        message.chat.id,
        "Boshlanish sanasini yuboring (YYYY-MM-DD):\nMasalan: 2023-12-01"
    )
    bot.register_next_step_handler(msg, process_start_date)

def process_start_date(message):
    if message.text == "🔙 Ortga":
        return send_main_menu(message.chat.id)
    
    try:
        start_date = datetime.datetime.strptime(message.text, "%Y-%m-%d").date()
        msg = bot.send_message(
            message.chat.id,
            "Tugash sanasini yuboring (YYYY-MM-DD):\nMasalan: 2023-12-31"
        )
        bot.register_next_step_handler(msg, process_end_date, start_date)
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
            username = f"@{user_chat.username}" if user_chat.username else f"ID:{user_id}"
        except:
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
                         "\n".join([f"{idx}. {username}: {ref_count} do'st" 
                                   for idx, (_, ref_count, _) in enumerate(rating[:10], 1)]))


def check_expired_competitions():
    competitions = load_json("competitions.json")
    now = datetime.datetime.now()
    
    for comp_id, comp in list(competitions.items()):
        try:
            deadline = datetime.datetime.fromisoformat(comp["deadline"])
            if now >= deadline and "winners_announced" not in comp:
                finish_competition(comp_id)
        except Exception as e:
            print(f"Error processing competition {comp_id}: {e}")

def finish_competition(comp_id):
    competitions = load_json("competitions.json")
    comp = competitions[comp_id]
    
    if "winners_announced" in comp and comp["winners_announced"]:
        return  # Already processed
    
    participants = comp.get("participants", [])
    winners_count = comp.get("winners", 1)
    
    if not participants:
        # No participants case
        announcement = f"⚠️ #{comp_id} konkursi yakunlandi. Ishtirokchilar bo'lmadi."
        try:
            bot.send_message(GROUP_ID, announcement)
            bot.send_message(CHANNEL_ID, announcement)
        except Exception as e:
            print(f"Error announcing no participants: {e}")
        
        # Mark as completed
        comp["winners_announced"] = True
        competitions[comp_id] = comp
        save_json("competitions.json", competitions)
        return
    
    # Select winners
    winners_count = min(winners_count, len(participants))
    winners = random.sample(participants, winners_count)
    
    # Prepare announcement
    winner_mentions = []
    for winner_id in winners:
        try:
            user = bot.get_chat(int(winner_id))
            mention = f"@{user.username}" if user.username else f"[{user.first_name}](tg://user?id={user.id})"
            winner_mentions.append(mention)
            
            # Notify winner privately
            bot.send_message(
                winner_id,
                f"🎉 Tabriklaymiz! Siz #{comp_id} konkurs g'oliblaridan birisiz!\n\n"
                f"Tez orada adminlar siz bilan bog'lanishadi."
            )
        except Exception as e:
            print(f"Could not process winner {winner_id}: {e}")
            winner_mentions.append(f"ID:{winner_id}")
    
    # Create announcement message
    winners_text = "\n".join([f"🏆 {i+1}. {winner}" for i, winner in enumerate(winner_mentions)])
    announcement = (
        f"🎊 *Konkurs #{comp_id} yakunlandi!* 🎊\n\n"
        f"G'oliblar ({len(winners)} ta):\n{winners_text}\n\n"
        "Tabriklaymiz! 🎉 Adminlar tez orada siz bilan bog'lanishadi."
    )
    
    # Send to both group and channel
    try:
        # Send to group
        bot.send_message(
            GROUP_ID,
            announcement,
            parse_mode="Markdown"
        )
        
        # Send to channel
        bot.send_message(
            CHANNEL_ID,
            announcement,
            parse_mode="Markdown"
        )
        
        print(f"Winners announced for competition {comp_id}")
    except Exception as e:
        print(f"Error announcing winners: {e}")
        # Fallback - try without Markdown
        try:
            winners_text = "\n".join([f"{i+1}. {winner}" for i, winner in enumerate(winner_mentions)])
            announcement = (
                f"Konkurs #{comp_id} g'oliblari ({len(winners)} ta):\n{winners_text}"
            )
            bot.send_message(GROUP_ID, announcement)
            bot.send_message(CHANNEL_ID, announcement)
        except Exception as e2:
            print(f"Fallback announcement failed: {e2}")
    
    # Update competition status
    comp["winners"] = winners
    comp["winners_announced"] = True
    competitions[comp_id] = comp
    save_json("competitions.json", competitions)
    
    # Notify admins
    for admin_id in ADMIN_IDS:
        try:
            bot.send_message(
                admin_id,
                f"🏆 #{comp_id} konkurs yakunlandi. G'oliblar:\n" +
                "\n".join([f"- {winner}" for winner in winners])
            )
        except Exception as e:
            print(f"Could not notify admin {admin_id}: {e}")

def process_comp_winners_count(message, file_id, deadline):
    try:
        winners = int(message.text)
        if winners <= 0:
            raise ValueError
        
        competitions = load_json("competitions.json")
        comp_id = str(len(competitions) + 1)
        
        # Store deadline as ISO format with timezone
        deadline_iso = deadline.isoformat()
        
        competitions[comp_id] = {
            "file_id": file_id,
            "deadline": deadline_iso,
            "winners": winners,
            "participants": []
        }
        
        save_json("competitions.json", competitions)
        bot.send_message(message.chat.id, f"Konkurs №{comp_id} yaratildi. Endi e'lon qilinadi.")
        post_competition(comp_id)
        
    except ValueError:
        bot.send_message(message.chat.id, "Iltimos, 0 dan katta butun son kiriting:")

def competition_checker():
    while True:
        try:
            check_expired_competitions()
            time.sleep(60)  # Check every minute
        except Exception as e:
            print(f"Error in competition checker: {e}")
            time.sleep(60)  # Wait 1 minute before retrying

# --- UC WITHDRAWAL ---
@bot.message_handler(func=lambda msg: msg.text == "💸 UC yechish")
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
def handle_withdraw(call):
    amount = int(call.data.split("_")[1])
    msg = bot.send_message(call.from_user.id, f"🔢 PUBG ID raqamingizni yuboring:")
    bot.register_next_step_handler(msg, confirm_withdraw, amount)

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
        bot.send_message(admin, f"📥 @{message.from_user.username} ({user_id})\n💸 {amount} UC so'radi.\n🔢 PUBG ID: {pubg_id}")
    
    bot.send_message(user_id, f"✅ So'rovingiz qabul qilindi. Tez orada UC yuboriladi.")


@bot.message_handler(func=lambda m: m.text == "🔙 Ortga")
def handle_back(message):
    """Handle back button for all users"""
    if message.from_user.id in ADMIN_IDS:
        # For admin, show admin menu if coming from admin section
        if hasattr(message, 'coming_from_admin') and message.coming_from_admin:
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.row("🆕 Yangi konkurs yaratish")
            markup.row("🔙 Asosiy menyu")
            bot.send_message(message.chat.id, "Admin menyusi:", reply_markup=markup)
            return
    # For all users, return to main menu
    send_main_menu(message.chat.id)

# --- COMPETITIONS ---
@bot.message_handler(func=lambda m: m.text == "🎁 Konkurslar" and m.from_user.id in ADMIN_IDS)
def handle_competitions_menu(message):
    """Admin-only competitions menu"""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🆕 Yangi konkurs yaratish")
    markup.row("🔙 Asosiy menyu")
    msg = bot.send_message(
        message.chat.id, 
        "Admin: konkurslar boshqaruvi",
        reply_markup=markup
    )
    # Mark this message as coming from admin section
    msg.coming_from_admin = True

@bot.message_handler(func=lambda m: m.text == "🆕 Yangi konkurs yaratish" and m.from_user.id in ADMIN_IDS)
def ask_competition_image(message):
    """Start competition creation process"""
    msg = bot.send_message(
        message.chat.id, 
        "Konkurs uchun rasm yuboring:",
        reply_markup=types.ReplyKeyboardRemove()
    )
    msg.coming_from_admin = True
    bot.register_next_step_handler(msg, process_comp_image)

@bot.message_handler(func=lambda m: m.text == "🔙 Asosiy menyu" and m.from_user.id in ADMIN_IDS)
def admin_back_to_main(message):
    """Special back button for admin menu"""
    send_main_menu(message.chat.id)

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
        return bot.send_message(message.chat.id, "Formati noto'g'ri. YYYY-MM-DD HH:MM tarzda yozing:")
    
    msg = bot.send_message(message.chat.id, "G'oliblar sonini kiriting:")
    bot.register_next_step_handler(msg, process_comp_winners_count, file_id, deadline)

def post_competition(comp_id):
    competitions = load_json("competitions.json")
    comp = competitions[comp_id]
    
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("✅ Qatnashish", callback_data=f"join_{comp_id}"))
    
    caption = (
        f"🎉 *Yangi konkurs #{comp_id}!* 🎉\n\n"
        f"⏳ Tugash vaqti: {comp['deadline']}\n"
        f"🏆 G'oliblar soni: {comp['winners']}\n\n"
        "Ishtirok etish uchun quyidagi tugmani bosing!"
    )
    
    # Post in both channel and group
    try:
        bot.send_photo(CHANNEL_ID, comp["file_id"], caption, reply_markup=keyboard, parse_mode="Markdown")
        bot.send_photo(GROUP_ID, comp["file_id"], caption, reply_markup=keyboard, parse_mode="Markdown")
    except Exception as e:
        print(f"Error posting competition: {e}")

@bot.callback_query_handler(func=lambda c: c.data.startswith("join_"))
def join_competition(call):
    comp_id = call.data.split("_")[1]
    competitions = load_json("competitions.json")
    comp = competitions[comp_id]
    uid = str(call.from_user.id)
    
    if uid in comp["participants"]:
        return bot.answer_callback_query(call.id, "Siz allaqachon qatnashgansiz.")
    
    if not check_subscription(call.from_user.id):
        bot.answer_callback_query(call.id, "❗ Obuna bo'ling", show_alert=True)
        send_subscription_prompt(call.from_user.id)
        return
    
    comp["participants"].append(uid)
    competitions[comp_id] = comp
    save_json("competitions.json", competitions)
    bot.answer_callback_query(call.id, "✅ Siz tanlov ishtirokchisiga aylandingiz!")

# --- START COMMAND ---
@bot.message_handler(commands=["start"])
def start(message):
    user_id = message.from_user.id
    ref_id = None
    
    if len(message.text.split()) > 1:
        ref_id = message.text.split()[1]
    
    add_user(user_id, ref_id)
    
    if not check_subscription(user_id):
        send_subscription_prompt(user_id)
    else:
        send_main_menu(user_id, "🎮 Botga xush kelibsiz!")

if __name__ == "__main__":
    try:
        init_db()
        print("Database initialized")
        
        # Start competition checker thread
        def competition_checker():
            while True:
                try:
                    check_expired_competitions()
                    time.sleep(60)  # Check every minute
                except Exception as e:
                    print(f"Error in competition checker: {e}")
                    time.sleep(60)  # Wait before retrying
        
        checker_thread = threading.Thread(target=competition_checker)
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
        else:
            flask_thread = threading.Thread(target=run_server)
        
        flask_thread.daemon = True
        flask_thread.start()
        print("Health check server started")
        
        print("Starting bot polling...")
        bot.infinity_polling()
        
    except Exception as e:
        print(f"Bot crashed: {e}")
        for admin in ADMIN_IDS:
            try:
                bot.send_message(admin, f"Bot crashed: {e}")
            except:
                pass
