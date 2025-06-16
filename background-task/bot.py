from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageReactionHandler
)
import os
import psycopg2
import uuid
import logging
from telegram.constants import ParseMode
import asyncio

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

NAME, AGE, CITY, PHONE = range(4)
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
DB_URL = os.getenv("DATABASE_URL")
APP_DOMAIN = os.getenv("APP_DOMAIN")

pending_accepts = {}
APPLICANTS_TOPIC_ID = None

def ensure_table():
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        logger.info("Creating/verifying database tables...")
        
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
        logger.info("✅ Applicants table verified")
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS topic_mappings (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT NOT NULL,
                thread_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT now()
            )
        """)
        logger.info("✅ Topic mappings table verified")
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS admin_tokens (
                id SERIAL PRIMARY KEY,
                token VARCHAR(255) NOT NULL,
                telegram_id BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        logger.info("✅ Admin tokens table verified")
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS message_log (
                id SERIAL PRIMARY KEY,
                admin_message_id BIGINT,
                user_message_id BIGINT,
                telegram_id BIGINT,
                thread_id INTEGER,
                message_type TEXT,
                created_at TIMESTAMP DEFAULT now()
            )
        """)
        logger.info("✅ Message log table verified")
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS message_reactions (
                id SERIAL PRIMARY KEY,
                message_id BIGINT NOT NULL,
                user_id BIGINT NOT NULL,
                reaction TEXT NOT NULL,
                is_admin BOOLEAN NOT NULL,
                created_at TIMESTAMP DEFAULT now()
            )
        """)
        logger.info("✅ Message reactions table verified")
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ All tables verified successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {str(e)}")
        raise

async def ensure_applicants_topic(context: ContextTypes.DEFAULT_TYPE):
    global APPLICANTS_TOPIC_ID
    try:
        # Check if topic already exists
        if APPLICANTS_TOPIC_ID is not None:
            return

        # Create the topic
        topic = await context.bot.create_forum_topic(
            chat_id=GROUP_ID,
            name="📋 Заявки"
        )
        APPLICANTS_TOPIC_ID = topic.message_thread_id
        logger.info(f"✅ Created applicants topic with ID: {APPLICANTS_TOPIC_ID}")
    except Exception as e:
        logger.error(f"❌ Failed to create applicants topic: {str(e)}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        telegram_id = update.message.from_user.id
        logger.info(f"🆕 New user started bot: {telegram_id}")
        
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM applicants WHERE telegram_id = %s", (telegram_id,))
        exists = cur.fetchone()
        cur.close()
        conn.close()

        if exists:
            logger.info(f"⚠️ User {telegram_id} already has an application")
            await update.message.reply_text("⚠️ Ви вже подали заявку. Очікуйте на відповідь від адміністратора.")
            return ConversationHandler.END

        logger.info(f"✅ Starting application process for user {telegram_id}")
        await update.message.reply_text("Привіт! Як тебе звати?")
        return NAME
    except Exception as e:
        logger.error(f"❌ Error in start command: {str(e)}")
        await update.message.reply_text("❌ Сталася помилка. Спробуйте пізніше.")
        return ConversationHandler.END

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['name'] = update.message.text
        logger.info(f"📝 User {update.message.from_user.id} provided name: {update.message.text}")
        await update.message.reply_text("Скільки тобі років?")
        return AGE
    except Exception as e:
        logger.error(f"❌ Error in get_name: {str(e)}")
        await update.message.reply_text("❌ Сталася помилка. Спробуйте ще раз.")
        return NAME

async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age = int(update.message.text)
        logger.info(f"📝 User {update.message.from_user.id} provided age: {age}")
        
        context.user_data['age'] = age

        if age < 16:
            logger.info(f"❌ User {update.message.from_user.id} rejected due to age: {age}")
            await update.message.reply_text(
                "Вибач, але ти не можеш приєднатися. Проте у нас є реферальна система — заробляй, запрошуючи інших!"
            )
            return ConversationHandler.END

        await update.message.reply_text("З якого ти міста?")
        return CITY
    except ValueError:
        logger.warning(f"⚠️ User {update.message.from_user.id} provided invalid age: {update.message.text}")
        await update.message.reply_text("Будь ласка, введи число.")
        return AGE
    except Exception as e:
        logger.error(f"❌ Error in get_age: {str(e)}")
        await update.message.reply_text("❌ Сталася помилка. Спробуйте ще раз.")
        return AGE

async def get_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data['city'] = update.message.text
        logger.info(f"📝 User {update.message.from_user.id} provided city: {update.message.text}")
        
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
    except Exception as e:
        logger.error(f"❌ Error in get_city: {str(e)}")
        await update.message.reply_text("❌ Сталася помилка. Спробуйте ще раз.")
        return CITY

async def get_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_data = context.user_data
        telegram_id = update.message.from_user.id
        username = update.message.from_user.username
        
        logger.info(f"📝 Processing phone for user {telegram_id}")
        
        # Get the phone number from contact or text
        phone = update.message.contact.phone_number if update.message.contact else update.message.text
        
        # Format the phone number only if it's manually entered (not shared through Telegram)
        if phone and not update.message.contact:
            # Remove any non-digit characters
            phone = ''.join(c for c in str(phone) if c.isdigit())
            
            # Handle different formats
            if len(phone) == 10:  # If the number starts with 0
                phone = '+380' + phone[1:]
            elif len(phone) == 11 and phone.startswith('8'):  # If the number starts with 8
                phone = '+380' + phone[1:]
            elif len(phone) == 12 and phone.startswith('380'):  # If the number starts with 380
                phone = '+' + phone
            elif not phone.startswith('+380'):  # If the number doesn't match any format
                logger.warning(f"⚠️ User {telegram_id} provided invalid phone format: {phone}")
                await update.message.reply_text(
                    "❌ Невірний формат номера. Введіть номер у форматі: +380XXXXXXXXX\n"
                    "Наприклад: +380931231919"
                )
                return PHONE

        name = user_data['name']
        age = user_data['age']
        city = user_data['city']

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM applicants WHERE telegram_id = %s", (telegram_id,))
        if cur.fetchone():
            logger.warning(f"⚠️ Duplicate application attempt from user {telegram_id}")
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
            f"👤 Ім'я: {name}\n"
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

        # Send to the applicants topic if it exists
        if APPLICANTS_TOPIC_ID is not None:
            await context.bot.send_message(
                chat_id=GROUP_ID,
                message_thread_id=APPLICANTS_TOPIC_ID,
                text=summary,
                reply_markup=keyboard
            )
            logger.info(f"✅ New application notification sent to applicants topic")
        else:
            # Fallback to regular group message if topic doesn't exist
            await context.bot.send_message(chat_id=GROUP_ID, text=summary, reply_markup=keyboard)
            logger.warning("⚠️ Applicants topic not found, sent notification to group")

        logger.info(f"✅ New application submitted by user {telegram_id}")
        await update.message.reply_text("📨 Твоя заявка відправлена. Очікуй відповідь від адміністратора.")
    except Exception as e:
        logger.error(f"❌ Error in get_phone: {str(e)}")
        await update.message.reply_text("❌ Сталася помилка при збереженні даних.")
    return ConversationHandler.END

async def send_admin_panel_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Check if the message is from the admin group
        if update.effective_chat.id != GROUP_ID:
            logger.warning(f"⚠️ Command used outside admin group: chat_id={update.effective_chat.id}")
            return

        # Check if the user is a member of the admin group
        try:
            chat_member = await context.bot.get_chat_member(
                chat_id=GROUP_ID,
                user_id=update.effective_user.id
            )
            if chat_member.status not in ['member', 'administrator', 'creator']:
                logger.warning(f"⚠️ Non-member tried to use command: user_id={update.effective_user.id}")
                return
        except Exception as e:
            logger.error(f"❌ Error checking group membership: {str(e)}")
            return

        token = uuid.uuid4().hex[:8]
        logger.info(f"🔑 Generated new admin token: {token}")
        
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO admin_tokens(token, telegram_id) VALUES (%s, %s)", (token, update.effective_chat.id))
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
            logger.info("📌 Admin panel message pinned")
        except Exception as e:
            logger.error(f"❌ Failed to pin admin panel message: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Error in send_admin_panel_link: {str(e)}")
        await update.message.reply_text("❌ Сталася помилка при створенні посилання.")

async def set_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()

        _, tg_id, new_status = query.data.split(":")
        logger.info(f"🔄 Setting status for user {tg_id} to {new_status}")

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        if new_status == "Accepted":
            pending_accepts[query.from_user.id] = tg_id
            await query.edit_message_reply_markup(None)
            await query.edit_message_text(
                "✅ Прийнято! Введіть місто та дату у форматі: `Київ:2025-07-01`",
                parse_mode=ParseMode.MARKDOWN
            )
            logger.info(f"⏳ Waiting for city and date input for user {tg_id}")
        else:
            cur.execute("UPDATE applicants SET status = %s WHERE telegram_id = %s", (new_status, tg_id))
            cur.execute("SELECT thread_id FROM topic_mappings WHERE telegram_id = %s", (tg_id,))
            topic = cur.fetchone()
            if topic:
                try:
                    await context.bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic[0])
                    logger.info(f"🗑️ Deleted forum topic for user {tg_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to delete forum topic: {str(e)}")
                cur.execute("DELETE FROM topic_mappings WHERE telegram_id = %s", (tg_id,))
            conn.commit()
            cur.close()
            conn.close()
            await query.edit_message_reply_markup(None)
            await query.edit_message_text(f"✅ Статус оновлено: {new_status}")
            logger.info(f"✅ Status updated for user {tg_id} to {new_status}")
    except Exception as e:
        logger.error(f"❌ Error in set_status_callback: {str(e)}")
        await query.answer("❌ Сталася помилка при оновленні статусу", show_alert=True)

async def start_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()

        data = query.data
        if not data.startswith("start_chat:"):
            return

        applicant_id = int(data.split(":")[1])
        logger.info(f"💬 Starting chat with user {applicant_id}")
        
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        # First, check if a chat already exists
        cur.execute("SELECT thread_id FROM topic_mappings WHERE telegram_id = %s", (applicant_id,))
        existing_topic = cur.fetchone()
        
        if existing_topic:
            # Chat already exists, show the link
            thread_id = existing_topic[0]
            logger.info(f"ℹ️ Chat already exists for user {applicant_id}")
            await query.edit_message_reply_markup(None)
            await query.edit_message_text(
                "💬 Чат вже існує. Натисніть кнопку нижче, щоб перейти до нього.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➡️ Перейти до чату", url=f"https://t.me/c/{str(GROUP_ID)[4:]}/{thread_id}")]
                ])
            )
            cur.close()
            conn.close()
            return

        # If no existing chat, create a new one
        cur.execute("SELECT name, username, age, city, phone, status FROM applicants WHERE telegram_id = %s", (applicant_id,))
        result = cur.fetchone()
        if not result:
            logger.error(f"❌ User {applicant_id} not found in database")
            await query.edit_message_text("❌ Користувача не знайдено.")
            return

        name, username, age, city, phone, status = result
        chat_title = f"{name} (@{username})" if username else name
        topic = await context.bot.create_forum_topic(
            chat_id=GROUP_ID,
            name=f"Чат: {chat_title}"
        )
        logger.info(f"✅ Created new forum topic for user {applicant_id}")

        thread_id = topic.message_thread_id
        cur.execute("INSERT INTO topic_mappings (telegram_id, thread_id) VALUES (%s, %s)", (applicant_id, thread_id))
        conn.commit()
        cur.close()
        conn.close()

        link = f"https://t.me/{username}" if username else "❓ Немає username"
        summary = (
            f"✅ Інформація про користувача:\n"
            f"👤 Ім'я: {name}\n"
            f"🎂 Вік: {age}\n"
            f"🏙️ Місто: {city}\n"
            f"📞 Телефон: {phone if phone else 'не надано'}\n"
            f"🔗 Username: @{username if username else 'немає'}\n"
            f"💬 Профіль: {link}\n"
            f"🆔 Telegram ID: {applicant_id}\n"
            f"📊 Статус: {status}"
        )

        await context.bot.send_message(
            chat_id=GROUP_ID,
            message_thread_id=thread_id,
            text=summary,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("➡️ Перейти до чату", url=f"https://t.me/c/{str(GROUP_ID)[4:]}/{thread_id}")]
            ])
        )
        logger.info(f"✅ Chat started successfully for user {applicant_id}")
    except Exception as e:
        logger.error(f"❌ Error in start_chat_callback: {str(e)}")
        await query.answer("❌ Сталася помилка при створенні чату", show_alert=True)

async def delete_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()

        # Check if the user is admin
        if query.from_user.id != ADMIN_ID:
            logger.warning(f"⚠️ Non-admin user {query.from_user.id} tried to delete an application")
            await query.edit_message_text("❌ Тільки адміністратор може видаляти заявки.")
            return

        data = query.data
        if not data.startswith("delete_user:"):
            return

        applicant_id = int(data.split(":")[1])
        logger.info(f"🗑️ Deleting application for user {applicant_id}")

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        cur.execute("SELECT thread_id FROM topic_mappings WHERE telegram_id = %s", (applicant_id,))
        topic = cur.fetchone()
        if topic:
            try:
                await context.bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic[0])
                logger.info(f"✅ Deleted forum topic for user {applicant_id}")
            except Exception as e:
                logger.error(f"❌ Failed to delete forum topic: {str(e)}")
            cur.execute("DELETE FROM topic_mappings WHERE telegram_id = %s", (applicant_id,))

        cur.execute("DELETE FROM applicants WHERE telegram_id = %s", (applicant_id,))
        conn.commit()
        cur.close()
        conn.close()

        await query.edit_message_text("🗑️ Заявку видалено.")
        logger.info(f"✅ Application deleted for user {applicant_id}")
    except Exception as e:
        logger.error(f"❌ Error in delete_user_callback: {str(e)}")
        await query.answer("❌ Сталася помилка при видаленні заявки", show_alert=True)

async def handle_admin_group_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.message
        if not msg or not msg.message_thread_id:
            return
            
        thread_id = msg.message_thread_id
        logger.info(f"📨 Processing admin message in thread {thread_id}")

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT telegram_id FROM topic_mappings WHERE thread_id = %s", (thread_id,))
        result = cur.fetchone()
        if not result:
            logger.warning(f"⚠️ No user mapping found for thread {thread_id}")
            return

        applicant_id = result[0]
        cur.execute("UPDATE applicants SET status = %s WHERE telegram_id = %s", ("In Progress", applicant_id))
        conn.commit()

        sent_message = None
        try:
            # Forward any type of message
            sent_message = await msg.copy(chat_id=applicant_id)
            
            if sent_message:
                # Add the delete button to the admin's message
                delete_button = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🗑️ Видалити", callback_data=f"delete_msg:{sent_message.message_id}:{applicant_id}")
                ]])
                await msg.edit_reply_markup(reply_markup=delete_button)
                
                cur.execute("""
                    INSERT INTO message_log (admin_message_id, user_message_id, telegram_id, thread_id, message_type)
                    VALUES (%s, %s, %s, %s, %s)
                """, (msg.message_id, sent_message.message_id, applicant_id, thread_id, 'message'))
                conn.commit()
                logger.info(f"✅ Message forwarded to user {applicant_id}")
        except Exception as e:
            logger.error(f"❌ Error forwarding message: {str(e)}")

        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Error in handle_admin_group_messages: {str(e)}")

async def forward_to_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message:
            return  # Not a message update, skip

        telegram_id = update.message.from_user.id
        logger.info(f"📨 Processing user message from {telegram_id}")

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT thread_id FROM topic_mappings WHERE telegram_id = %s", (telegram_id,))
        result = cur.fetchone()
        if not result:
            logger.warning(f"⚠️ No thread mapping found for user {telegram_id}")
            return

        thread_id = result[0]
        msg = update.message
        sent_message = None

        try:
            # Forward any type of message
            sent_message = await msg.copy(
                chat_id=GROUP_ID,
                message_thread_id=thread_id
            )
            
            if sent_message:
                cur.execute("""
                    INSERT INTO message_log (admin_message_id, user_message_id, telegram_id, thread_id, message_type)
                    VALUES (%s, %s, %s, %s, %s)
                """, (sent_message.message_id, msg.message_id, telegram_id, thread_id, 'message'))
                conn.commit()
                logger.info(f"✅ Message forwarded to admin group")
        except Exception as e:
            logger.error(f"❌ Error forwarding message: {str(e)}")

        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Error in forward_to_topic: {str(e)}")

async def handle_accept_extra_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        admin_id = update.effective_user.id
        if admin_id not in pending_accepts:
            return

        telegram_id = pending_accepts.pop(admin_id)
        logger.info(f"📝 Processing accept input for user {telegram_id}")

        try:
            city, date = update.message.text.strip().split(":")
        except ValueError:
            logger.warning(f"⚠️ Invalid format for accept input: {update.message.text}")
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
                logger.info(f"✅ Deleted forum topic for user {telegram_id}")
            except Exception as e:
                logger.error(f"❌ Failed to delete forum topic: {str(e)}")
            cur.execute("DELETE FROM topic_mappings WHERE telegram_id = %s", (telegram_id,))

        conn.commit()
        cur.close()
        conn.close()

        await update.message.reply_text("✅ Дані збережено та чат закрито.")
        logger.info(f"✅ Application accepted for user {telegram_id}")
    except Exception as e:
        logger.error(f"❌ Error in handle_accept_extra_input: {str(e)}")
        await update.message.reply_text("❌ Сталася помилка при збереженні даних.")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info(f"🚫 Conversation cancelled by user {update.message.from_user.id}")
        await update.message.reply_text("🚫 Розмову скасовано.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"❌ Error in cancel: {str(e)}")
        return ConversationHandler.END

async def delete_message_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()

        if not query.data.startswith("delete_msg:"):
            return

        _, message_id, user_id = query.data.split(":")
        message_id = int(message_id)
        user_id = int(user_id)
        logger.info(f"🗑️ Deleting message {message_id} for user {user_id}")

        try:
            # Delete message from user's chat
            await context.bot.delete_message(chat_id=user_id, message_id=message_id)
            logger.info(f"✅ Deleted message from user's chat")
            
            # Delete the admin's message if it exists and is accessible
            if query.message and query.message.is_accessible:
                try:
                    await context.bot.delete_message(
                        chat_id=query.message.chat.id,
                        message_id=query.message.message_id
                    )
                    logger.info(f"✅ Deleted message from admin's chat")
                except Exception as e:
                    logger.error(f"❌ Failed to delete admin message: {str(e)}")
            else:
                logger.warning("⚠️ Admin message not found or inaccessible for deletion")
            
            # Remove the delete button from the original message if it exists and is accessible
            if query.message and query.message.is_accessible:
                try:
                    await context.bot.edit_message_reply_markup(
                        chat_id=query.message.chat.id,
                        message_id=query.message.message_id,
                        reply_markup=None
                    )
                    logger.info(f"✅ Removed delete button from message")
                except Exception as e:
                    logger.error(f"❌ Failed to remove delete button: {str(e)}")

            # Delete from message_log
            conn = psycopg2.connect(DB_URL)
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM message_log 
                WHERE (admin_message_id = %s OR user_message_id = %s)
            """, (query.message.message_id if query.message and query.message.is_accessible else None, message_id))
            conn.commit()
            cur.close()
            conn.close()
            logger.info(f"✅ Removed message from message_log")
            
        except Exception as e:
            logger.error(f"❌ Error deleting message: {str(e)}")
            await query.answer("❌ Не вдалося видалити повідомлення", show_alert=True)
    except Exception as e:
        logger.error(f"❌ Error in delete_message_callback: {str(e)}")
        await query.answer("❌ Сталася помилка при видаленні повідомлення", show_alert=True)

async def handle_message_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("🔍 Edit handler triggered")
        logger.info(f"Has edited_message: {update.edited_message is not None}")
        
        if not update.edited_message:
            logger.info("❌ No edited message found, returning")
            return

        edited = update.edited_message
        message_id = edited.message_id
        thread_id = edited.message_thread_id  # Optional; only for admin messages in threads
        
        logger.info(f"📝 Processing edit for message_id: {message_id}")
        logger.info(f"📝 Thread ID: {thread_id}")
        logger.info(f"📝 Message type: {'text' if edited.text else 'caption' if edited.caption else 'other'}")
        if edited.text:
            logger.info(f"📝 New text: {edited.text[:50]}...")
        if edited.caption:
            logger.info(f"📝 New caption: {edited.caption[:50]}...")

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # Look up the message mapping
        cur.execute("""
            SELECT admin_message_id, user_message_id, telegram_id
            FROM message_log
            WHERE admin_message_id = %s OR user_message_id = %s
        """, (message_id, message_id))

        result = cur.fetchone()
        cur.close()
        conn.close()

        if not result:
            logger.warning("❌ No message mapping found in database")
            return  # No log match

        admin_msg_id, user_msg_id, telegram_id = result
        logger.info(f"✅ Found message mapping - admin_msg: {admin_msg_id}, user_msg: {user_msg_id}, user_id: {telegram_id}")

        try:
            if message_id == admin_msg_id:
                logger.info("🔄 Processing admin edit -> user")
                # Admin edited — update user
                if edited.text:
                    # Text message
                    await context.bot.edit_message_text(
                        chat_id=telegram_id,
                        message_id=user_msg_id,
                        text=edited.text
                    )
                    logger.info("✅ Updated user's text message")
                elif edited.caption:
                    # Media with caption
                    await context.bot.edit_message_caption(
                        chat_id=telegram_id,
                        message_id=user_msg_id,
                        caption=edited.caption
                    )
                    logger.info("✅ Updated user's message caption")

            elif message_id == user_msg_id:
                logger.info("🔄 Processing user edit -> admin")
                # User edited — update admin
                prefix = "👤 "
                if edited.text:
                    await context.bot.edit_message_text(
                        chat_id=GROUP_ID,
                        message_id=admin_msg_id,
                        message_thread_id=thread_id,
                        text=f"{prefix}{edited.text}"
                    )
                    logger.info("✅ Updated admin's text message")
                elif edited.caption:
                    await context.bot.edit_message_caption(
                        chat_id=GROUP_ID,
                        message_id=admin_msg_id,
                        message_thread_id=thread_id,
                        caption=f"{prefix}{edited.caption}"
                    )
                    logger.info("✅ Updated admin's message caption")

        except Exception as e:
            logger.error(f"❌ Edit sync failed: {str(e)}")
            logger.error(f"Error type: {type(e)}")
    except Exception as e:
        logger.error(f"❌ Error in handle_message_edit: {str(e)}")

async def handle_message_reaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message_reaction:
            return

        reaction = update.message_reaction
        message_id = reaction.message_id
        user_id = reaction.user.id
        
        logger.info(f"😀 Processing reaction change from user {user_id} on message {message_id}")

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # Look up the message mapping
        cur.execute("""
            SELECT admin_message_id, user_message_id, telegram_id
            FROM message_log
            WHERE admin_message_id = %s OR user_message_id = %s
        """, (message_id, message_id))

        result = cur.fetchone()
        if not result:
            logger.warning(f"❌ No message mapping found for reaction on message {message_id}")
            cur.close()
            conn.close()
            return

        admin_msg_id, user_msg_id, telegram_id = result
        logger.info(f"✅ Found message mapping - admin_msg: {admin_msg_id}, user_msg: {user_msg_id}, user_id: {telegram_id}")

        try:
            if message_id == admin_msg_id:
                logger.info("🔄 Processing admin reaction -> user")
                # Admin reacted — update user
                await context.bot.set_message_reaction(
                    chat_id=telegram_id,
                    message_id=user_msg_id,
                    reaction=reaction.new_reaction
                )
                logger.info("✅ Updated reaction on user's message")

            elif message_id == user_msg_id:
                logger.info("🔄 Processing user reaction -> admin")
                # User reacted — update admin
                await context.bot.set_message_reaction(
                    chat_id=GROUP_ID,
                    message_id=admin_msg_id,
                    reaction=reaction.new_reaction
                )
                logger.info("✅ Updated reaction on admin's message")

            # Update reaction in the database
            if reaction.old_reaction:
                # If there was an old reaction, update it
                cur.execute("""
                    UPDATE message_reactions 
                    SET reaction = %s 
                    WHERE message_id = %s AND user_id = %s
                """, (str(reaction.new_reaction[0].type) if reaction.new_reaction else '', message_id, user_id))
            else:
                # If there was no old reaction, insert new one
                cur.execute("""
                    INSERT INTO message_reactions (message_id, user_id, reaction, is_admin)
                    VALUES (%s, %s, %s, %s)
                """, (message_id, user_id, str(reaction.new_reaction[0].type) if reaction.new_reaction else '', message_id == admin_msg_id))
            
            conn.commit()
            logger.info("✅ Reaction updated in database")

        except Exception as e:
            logger.error(f"❌ Reaction sync failed: {str(e)}")

        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Error in handle_message_reaction: {str(e)}")

async def applicants_by_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Check if the message is from the admin group
        if update.effective_chat.id != GROUP_ID:
            logger.warning(f"⚠️ Command used outside admin group: chat_id={update.effective_chat.id}")
            return

        # Check if the user is a member of the admin group
        try:
            chat_member = await context.bot.get_chat_member(
                chat_id=GROUP_ID,
                user_id=update.effective_user.id
            )
            if chat_member.status not in ['member', 'administrator', 'creator']:
                logger.warning(f"⚠️ Non-member tried to use command: user_id={update.effective_user.id}")
                return
        except Exception as e:
            logger.error(f"❌ Error checking group membership: {str(e)}")
            return

        # Parse command arguments
        args = context.args
        if not args:
            await update.message.reply_text(
                "❌ Будь ласка, вкажіть статус.\n"
                "Доступні статуси: New, In Progress, Accepted, Declined\n"
                "Приклад: /applicants-by-status New"
            )
            return

        status = args[0]
        page = int(args[1]) if len(args) > 1 else 1
        per_page = 20

        if status not in ['New', 'In Progress', 'Accepted', 'Declined']:
            await update.message.reply_text(
                "❌ Невірний статус.\n"
                "Доступні статуси: New, In Progress, Accepted, Declined"
            )
            return

        logger.info(f"📋 Listing applicants with status {status}, page {page}")

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # Get total count
        cur.execute("SELECT COUNT(*) FROM applicants WHERE status = %s", (status,))
        total_count = cur.fetchone()[0]

        if total_count == 0:
            await update.message.reply_text(f"📭 Немає заявок зі статусом {status}")
            cur.close()
            conn.close()
            return

        # Calculate total pages
        total_pages = (total_count + per_page - 1) // per_page
        if page < 1 or page > total_pages:
            page = 1

        # Get applicants for current page
        offset = (page - 1) * per_page
        cur.execute("""
            SELECT name, age, city, phone, username, telegram_id, status, 
                   accepted_city, accepted_date::text
            FROM applicants 
            WHERE status = %s 
            ORDER BY id DESC 
            LIMIT %s OFFSET %s
        """, (status, per_page, offset))

        rows = cur.fetchall()
        cur.close()
        conn.close()

        # Create table header
        table = "📋 Заявки зі статусом " + status + f" (сторінка {page}/{total_pages}):\n\n"
        table += "👤 Ім'я | 🎂 Вік | 🏙️ Місто | 📞 Телефон | 🔗 Username | 📊 Статус\n"
        table += "─" * 80 + "\n"

        # Add rows
        for row in rows:
            name, age, city, phone, username, telegram_id, status, accepted_city, accepted_date = row
            username_str = f"@{username}" if username else "—"
            phone_str = phone if phone else "—"
            table += f"{name} | {age} | {city} | {phone_str} | {username_str} | {status}\n"
            if status == "Accepted" and accepted_city and accepted_date:
                table += f"   └─ Прийнято: {accepted_city}, {accepted_date}\n"

        # Add pagination controls
        table += "\n"
        if total_pages > 1:
            table += "📄 Навігація:\n"
            if page > 1:
                table += f"◀️ /applicants-by-status {status} {page-1}\n"
            if page < total_pages:
                table += f"▶️ /applicants-by-status {status} {page+1}\n"

        await update.message.reply_text(table)
        logger.info(f"✅ Listed {len(rows)} applicants with status {status} on page {page}")
    except Exception as e:
        logger.error(f"❌ Error in applicants_by_status: {str(e)}")
        await update.message.reply_text("❌ Сталася помилка при отриманні списку заявок.")

if __name__ == '__main__':
    ensure_table()
    app = ApplicationBuilder().token(TOKEN).build()

    # Create applicants topic on startup
    asyncio.run(ensure_applicants_topic(app))

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
    app.add_handler(CallbackQueryHandler(start_chat_callback, pattern="^start_chat:"))
    app.add_handler(CallbackQueryHandler(delete_user_callback, pattern="^delete_user:"))
    app.add_handler(CallbackQueryHandler(delete_message_callback, pattern="^delete_msg:"))
    app.add_handler(CommandHandler("admin-panel", send_admin_panel_link))
    app.add_handler(CommandHandler("applicants-by-status", applicants_by_status))
    app.add_handler(CallbackQueryHandler(set_status_callback, pattern="^set_status:"))
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.ALL, handle_admin_group_messages))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, forward_to_topic))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED, handle_message_edit))
    app.add_handler(MessageReactionHandler(callback=handle_message_reaction))
    app.run_polling()