from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler
)
import os
import psycopg2
import uuid
from telegram.constants import ParseMode

NAME, AGE, CITY, PHONE = range(4)
TOKEN = os.getenv("BOT_TOKEN")
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
DB_URL = os.getenv("DATABASE_URL")
APP_DOMAIN = os.getenv("APP_DOMAIN", "https://yourdomain.com")

pending_accepts = {}

def ensure_table():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS applicants (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            age INTEGER NOT NULL,
            city TEXT NOT NULL,
            telegram_id BIGINT NOT NULL UNIQUE,
            username TEXT,
            phone TEXT,
            status TEXT DEFAULT 'New',
            accepted_city TEXT,
            accepted_date DATE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS topic_mappings (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT NOT NULL,
            thread_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT now()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS admin_tokens (
            token TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT now()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_id = update.message.from_user.id
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM applicants WHERE telegram_id = %s", (telegram_id,))
    exists = cur.fetchone()
    cur.close()
    conn.close()

    if exists:
        await update.message.reply_text("⚠️ Ви вже подали заявку. Очікуйте на відповідь від адміністратора.")
        return ConversationHandler.END

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
    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton(text="📱 Поділитися телефоном", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True
    )
    await update.message.reply_text(
        "📱 Хочеш поділитися номером? Натисни кнопку або введи вручну.",
        reply_markup=keyboard
    )
    return PHONE


async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_data = context.user_data
    telegram_id = update.message.from_user.id
    username = update.message.from_user.username
    phone = update.message.contact.phone_number if update.message.contact else update.message.text

    name = user_data['name']
    age = user_data['age']
    city = user_data['city']

    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM applicants WHERE telegram_id = %s", (telegram_id,))
        if cur.fetchone():
            await update.message.reply_text("⚠️ Ви вже подали заявку.")
            cur.close()
            conn.close()
            return ConversationHandler.END

        cur.execute(
            "INSERT INTO applicants (name, age, city, telegram_id, username, phone) VALUES (%s, %s, %s, %s, %s, %s)",
            (name, age, city, telegram_id, username, phone)
        )
        conn.commit()
        cur.close()

        link = f"https://t.me/{username}" if username else "❓ Немає username"
        summary = (
            f"✅ Новий користувач:\n"
            f"👤 Ім’я: {name}\n"
            f"🎂 Вік: {age}\n"
            f"🏙️ Місто: {city}\n"
            f"📞 Телефон: {phone if phone else 'не надано'}\n"
            f"🔗 Username: @{username if username else 'немає'}\n"
            f"💬 Профіль: {link}\n"
            f"🆔 Telegram ID: {telegram_id}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("💬 Почати чат", callback_data=f"start_chat:{telegram_id}"),
                InlineKeyboardButton("🗑️ Видалити", callback_data=f"delete_user:{telegram_id}")
            ],
            [
                InlineKeyboardButton("✅ Прийняти", callback_data=f"set_status:{telegram_id}:Accepted"),
                InlineKeyboardButton("❌ Відхилити", callback_data=f"set_status:{telegram_id}:Declined")
            ]
        ])

        await context.bot.send_message(chat_id=GROUP_ID, text=summary, reply_markup=keyboard)
        await update.message.reply_text("📨 Твоя заявка відправлена. Очікуй відповідь від адміністратора.")
    except Exception:
        await update.message.reply_text("❌ Сталася помилка при збереженні даних.")
    return ConversationHandler.END


async def send_admin_panel_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != GROUP_ID:
        await update.message.reply_text("⚠️ Ця команда доступна лише у адмін-групі.")
        return

    token = uuid.uuid4().hex[:8]
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("INSERT INTO admin_tokens(token) VALUES (%s)", (token,))
    conn.commit()
    cur.close()
    conn.close()

    base_link = f"{APP_DOMAIN}/admin?token={token}"
    buttons = [
        [InlineKeyboardButton("📋 Всі", url=base_link)],
        [InlineKeyboardButton("🆕 Нові", url=f"{base_link}&status=New")],
        [InlineKeyboardButton("🔵 В процесі", url=f"{base_link}&status=In%20Progress")],
        [InlineKeyboardButton("✅ Прийняті", url=f"{base_link}&status=Accepted")],
        [InlineKeyboardButton("❌ Відхилені", url=f"{base_link}&status=Declined")]
    ]

    message = await update.message.reply_text(
        "🔐 Панель адміністратора доступна нижче (посилання дійсне 10 хвилин):",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

    try:
        await context.bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id)
    except:
        pass


async def set_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, tg_id, new_status = query.data.split(":")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    if new_status == "Accepted":
        pending_accepts[query.from_user.id] = tg_id
        await query.edit_message_reply_markup(None)
        await query.edit_message_text(
            "✅ Прийнято! Введіть місто та дату у форматі: `Київ:2025-07-01`",
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        cur.execute("UPDATE applicants SET status = %s WHERE telegram_id = %s", (new_status, tg_id))
        cur.execute("SELECT thread_id FROM topic_mappings WHERE telegram_id = %s", (tg_id,))
        topic = cur.fetchone()
        if topic:
            try:
                await context.bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic[0])
            except:
                pass
            cur.execute("DELETE FROM topic_mappings WHERE telegram_id = %s", (tg_id,))
        conn.commit()
        cur.close()
        conn.close()
        await query.edit_message_reply_markup(None)
        await query.edit_message_text(f"✅ Статус оновлено: {new_status}")


async def handle_accept_extra_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if admin_id not in pending_accepts:
        return

    telegram_id = pending_accepts.pop(admin_id)
    try:
        city, date = update.message.text.strip().split(":")
    except ValueError:
        await update.message.reply_text("❌ Невірний формат. Введіть як: `Київ:2025-07-01`", parse_mode=ParseMode.MARKDOWN)
        return

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("""
        UPDATE applicants
        SET accepted_city = %s, accepted_date = %s, status = 'Accepted'
        WHERE telegram_id = %s
    """, (city.strip(), date.strip(), telegram_id))

    cur.execute("SELECT thread_id FROM topic_mappings WHERE telegram_id = %s", (telegram_id,))
    topic = cur.fetchone()
    if topic:
        try:
            await context.bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic[0])
        except:
            pass
        cur.execute("DELETE FROM topic_mappings WHERE telegram_id = %s", (telegram_id,))

    conn.commit()
    cur.close()
    conn.close()

    await update.message.reply_text("✅ Дані збережено та чат закрито.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Розмову скасовано.")
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
    app.add_handler(CommandHandler("adminpanel", send_admin_panel_link))
    app.add_handler(CallbackQueryHandler(set_status_callback, pattern="^set_status:"))
    app.add_handler(MessageHandler(filters.TEXT & filters.Chat(GROUP_ID), handle_accept_extra_input))
    app.run_polling()