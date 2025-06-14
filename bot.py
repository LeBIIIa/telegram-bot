
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)
import os
import psycopg2

# Stages
NAME, AGE, CITY = range(3)

# Env vars
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_URL = os.getenv("DATABASE_URL")

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
    user_data = context.user_data
    telegram_id = update.message.from_user.id

    # Save to DB
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO applicants (name, age, city, telegram_id) VALUES (%s, %s, %s, %s)",
            (user_data['name'], user_data['age'], user_data['city'], telegram_id)
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        await update.message.reply_text("Сталася помилка при збереженні даних.")
        return ConversationHandler.END

    summary = f"""✅ Новий користувач:
Ім'я: {user_data['name']}
Вік: {user_data['age']}
Місто: {user_data['city']}
Telegram ID: {telegram_id}"""

    await context.bot.send_message(chat_id=ADMIN_ID, text=summary)
    await update.message.reply_text("📨 Твоя заявка відправлена. Очікуй відповідь від адміністратора.")
    return ConversationHandler.END

async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        lines = update.message.reply_to_message.text.splitlines()
        for line in lines:
            if "Telegram ID:" in line:
                user_id = int(line.split(":")[1].strip())
                await context.bot.send_message(chat_id=user_id, text=update.message.text)
                await update.message.reply_text("✅ Відповідь надіслано користувачу.")
                return
    await update.message.reply_text("❌ Не знайдено Telegram ID для відповіді.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Розмову скасовано.")
    return ConversationHandler.END

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            CITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_city)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.REPLY & filters.User(ADMIN_ID), admin_reply))

    app.run_polling()
