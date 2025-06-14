
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)
import os
import psycopg2

# Stages
NAME, AGE, CITY, PHONE = range(4)

# Env vars
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_URL = os.getenv("DATABASE_URL")

def ensure_table():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS applicants (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            city TEXT NOT NULL,
            telegram_id BIGINT NOT NULL,
            username TEXT,
            phone TEXT,
            status TEXT DEFAULT 'New'
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Привіт! Як тебе звати?")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("Скільки тобі років?")
    return AGE

async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Будь ласка, введи число.")
        return AGE

    context.user_data['age'] = age

    if age < 16:
        await update.message.reply_text(
            "Вибач, але ти не можеш приєднатися. Проте у нас є реферальна система — заробляй, запрошуючи інших!"
        )
        return ConversationHandler.END

    await update.message.reply_text("З якого ти міста?")
    return CITY

async def get_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['city'] = update.message.text
    keyboard = [[{"text": "📱 Поділитися телефоном", "request_contact": True}]]
    await update.message.reply_text("📱 Хочеш поділитися номером? Натисни кнопку або введи вручну.")
    return PHONE

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    telegram_id = update.message.from_user.id
    username = update.message.from_user.username
    phone = None

    if update.message.contact:
        phone = update.message.contact.phone_number
    else:
        phone = update.message.text

    name = user_data['name']
    age = user_data['age']
    city = user_data['city']

    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO applicants (name, age, city, telegram_id, username, phone) VALUES (%s, %s, %s, %s, %s, %s)",
            (name, age, city, telegram_id, username, phone)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        await update.message.reply_text("Сталася помилка при збереженні даних.")
        return ConversationHandler.END

    link = f"https://t.me/{username}" if username else "❌ Немає username"
    summary = (
        f"✅ Новий користувач:\n"
        f"👤 Ім'я: {name}\n"
        f"🎂 Вік: {age}\n"
        f"🏙️ Місто: {city}\n"
        f"📞 Телефон: {phone if phone else 'не надано'}\n"
        f"🔗 Username: @{username if username else 'немає'}\n"
        f"💬 Профіль: {link}\n"
        f"🆔 Telegram ID: {telegram_id}"
    )

    await context.bot.send_message(chat_id=ADMIN_ID, text=summary)
    await update.message.reply_text("📨 Твоя заявка відправлена. Очікуй відповідь від адміністратора.")
    return ConversationHandler.END

async def forward_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        lines = update.message.reply_to_message.text.splitlines()
        for line in lines:
            if "Telegram ID:" in line:
                user_id = int(line.split(":")[1].strip())

                # Update status to In Progress
                try:
                    conn = psycopg2.connect(DB_URL)
                    cur = conn.cursor()
                    cur.execute("UPDATE applicants SET status = %s WHERE telegram_id = %s", ("In Progress", user_id))
                    conn.commit()
                    cur.close()
                    conn.close()
                except Exception:
                    pass

                if update.message.voice:
                    await context.bot.send_voice(chat_id=user_id, voice=update.message.voice.file_id)
                elif update.message.text:
                    await context.bot.send_message(chat_id=user_id, text=update.message.text)

                await update.message.reply_text("✅ Повідомлення надіслано користувачу. Статус: In Progress.")
                return
    await update.message.reply_text("❌ Неможливо визначити, кому відповісти.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Розмову скасовано.")
    return ConversationHandler.END

if __name__ == '__main__':
    ensure_table()
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_city)],
            PHONE: [MessageHandler(filters.ALL & ~filters.COMMAND, get_phone)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.REPLY & filters.ChatType.GROUPS, forward_reply))

    app.run_polling()
