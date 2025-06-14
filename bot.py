
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler
)
import os

# Stages
NAME, AGE, CITY = range(3)

# Replace with your actual Telegram user ID
ADMIN_ID = 123456789

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Welcome! What's your name?")
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['name'] = update.message.text
    await update.message.reply_text("How old are you?")
    return AGE

async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return AGE

    context.user_data['age'] = age

    if age < 16:
        await update.message.reply_text(
            "Sorry, you can't join us but we have a referral system where you can earn money by inviting people."
        )
        return ConversationHandler.END

    await update.message.reply_text("Great! What city do you live in?")
    return CITY

async def get_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['city'] = update.message.text
    user_data = context.user_data

    summary = f"""✅ New User Joined:
Name: {user_data['name']}
Age: {user_data['age']}
City: {user_data['city']}
Telegram ID: {update.message.from_user.id}"""

    await context.bot.send_message(chat_id=ADMIN_ID, text=summary)
    await update.message.reply_text("Thanks! Your data has been submitted.")
    return ConversationHandler.END

async def admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.reply_to_message:
        lines = update.message.reply_to_message.text.splitlines()
        for line in lines:
            if "Telegram ID:" in line:
                user_id = int(line.split(":")[1].strip())
                await context.bot.send_message(chat_id=user_id, text=update.message.text)
                await update.message.reply_text("✅ Reply sent to the user.")
                return
    await update.message.reply_text("❌ No valid user ID found in replied message.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Conversation cancelled.")
    return ConversationHandler.END

if __name__ == '__main__':
    TOKEN = os.getenv("BOT_TOKEN")
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
