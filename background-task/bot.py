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
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bot_settings (
                id SERIAL PRIMARY KEY,
                key TEXT NOT NULL UNIQUE,
                value TEXT,
                updated_at TIMESTAMP DEFAULT now()
            )
        """)
        logger.info("✅ Bot settings table verified")
        
        conn.commit()
        cur.close()
        conn.close()
        logger.info("✅ All tables verified successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization failed: {str(e)}")
        raise

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

        # Create buttons for all users
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

        # Create buttons with callback data instead of direct URLs
        buttons = [
            [InlineKeyboardButton("📋 Всі", callback_data="admin_panel:all")],
            [InlineKeyboardButton("🆕 Нові", callback_data="admin_panel:New")],
            [InlineKeyboardButton("🔵 В процесі", callback_data="admin_panel:In Progress")],
            [InlineKeyboardButton("✅ Прийняті", callback_data="admin_panel:Accepted")],
            [InlineKeyboardButton("❌ Відхилені", callback_data="admin_panel:Declined")]
        ]

        message = await update.message.reply_text(
            "🔐 Виберіть категорію для перегляду в панелі адміністратора:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

        try:
            await context.bot.pin_chat_message(chat_id=GROUP_ID, message_id=message.message_id)
            logger.info("📌 Admin panel message pinned")
        except Exception as e:
            logger.error(f"❌ Failed to pin admin panel message: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Error in send_admin_panel_link: {str(e)}")
        await update.message.reply_text("❌ Сталася помилка при створенні панелі адміністратора.")

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        # Check if the user is a member of the admin group
        try:
            chat_member = await context.bot.get_chat_member(
                chat_id=GROUP_ID,
                user_id=query.from_user.id
            )
            if chat_member.status not in ['member', 'administrator', 'creator']:
                logger.warning(f"⚠️ Non-member tried to access admin panel: user_id={query.from_user.id}")
                await query.answer("❌ Ви не є учасником адмін групи", show_alert=True)
                return
        except Exception as e:
            logger.error(f"❌ Error checking group membership: {str(e)}")
            await query.answer("❌ Помилка перевірки членства в групі", show_alert=True)
            return

        # Generate token on demand
        token = uuid.uuid4().hex[:8]
        logger.info(f"🔑 Generated new admin token on demand: {token}")
        
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("INSERT INTO admin_tokens(token, telegram_id) VALUES (%s, %s)", (token, query.from_user.id))
        conn.commit()
        cur.close()
        conn.close()

        # Parse the callback data
        _, panel_type = query.data.split(":")
        
        # Create the appropriate URL based on panel type
        base_link = f"{APP_DOMAIN}/admin?token={token}"
        if panel_type != "all":
            url = f"{base_link}&status={panel_type.replace(' ', '%20')}"
        else:
            url = base_link
            
        # Answer the callback query with a notification
        await query.answer("🔑 Створено новий токен доступу", show_alert=True)
        
        # Send the link as a private message to the user
        try:
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=f"🔐 Ваше посилання на панель адміністратора (дійсне 10 хвилин):\n{url}",
                disable_web_page_preview=True
            )
            
            # Check if the message content is already the same
            current_text = query.message.text
            new_text = "🔐 Посилання відправлено вам в приватні повідомлення.\nПеревірте ваші особисті повідомлення з ботом."
            
            # Only edit if the content is different
            if current_text != new_text:
                # Also update the original message to confirm
                await query.edit_message_text(
                    new_text,
                    reply_markup=query.message.reply_markup
                )
            else:
                # Just answer the callback to acknowledge
                logger.info("Message content already matches, skipping edit")
        except Exception as e:
            logger.error(f"❌ Failed to send private message: {str(e)}")
            # If we can't send a private message, show the link in the group
            try:
                # Create a message with the URL
                new_text = (
                    f"🔐 Ваше посилання на панель адміністратора (дійсне 10 хвилин):\n{url}\n\n"
                    f"⚠️ Не вдалося відправити посилання в приватні повідомлення. "
                    f"Будь ласка, почніть приватний чат з ботом."
                )
                
                # Check if the content is already the same
                if query.message.text != new_text:
                    await query.edit_message_text(
                        new_text,
                        disable_web_page_preview=True
                    )
                else:
                    # Just log the issue
                    logger.info("Message content already matches, skipping edit")
            except Exception as edit_error:
                logger.error(f"❌ Failed to edit message: {str(edit_error)}")
                # If editing fails, try to send a new message
                try:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=f"🔐 Ваше посилання на панель адміністратора (дійсне 10 хвилин):\n{url}",
                        disable_web_page_preview=True
                    )
                except Exception as send_error:
                    logger.error(f"❌ Failed to send new message: {str(send_error)}")
            
    except Exception as e:
        logger.error(f"❌ Error in admin_panel_callback: {str(e)}")
        await query.answer("❌ Сталася помилка при створенні посилання", show_alert=True)

async def set_status_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        # Check if the user is admin
        #if query.from_user.id != ADMIN_ID:
        #    logger.warning(f"⚠️ Non-admin user {query.from_user.id} tried to change status")
        #    await query.answer("❌ Тільки адміністратор може змінювати статус.", show_alert=True)
        #    return

        _, tg_id, new_status = query.data.split(":")
        logger.info(f"🔄 Setting status for user {tg_id} to {new_status}")

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # First, verify the applicant exists
        cur.execute("SELECT 1 FROM applicants WHERE telegram_id = %s", (tg_id,))
        if not cur.fetchone():
            logger.warning(f"⚠️ Attempted to change status for non-existent applicant {tg_id}")
            await query.answer("❌ Заявку не знайдено.", show_alert=True)
            cur.close()
            conn.close()
            return

        if new_status == "Accepted":
            pending_accepts[query.from_user.id] = tg_id
            # Get user info to preserve it
            cur.execute("""
                SELECT name, age, city, phone, username, telegram_id, status
                FROM applicants WHERE telegram_id = %s
            """, (tg_id,))
            user_info = cur.fetchone()
            
            if user_info:
                name, age, city, phone, username, telegram_id, status = user_info
                username_str = f"@{username}" if username else "—"
                phone_str = phone if phone else "—"
                
                # Escape any potential Markdown characters in user-provided data
                name_escaped = name.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")
                city_escaped = city.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")
                username_str_escaped = username_str.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")
                phone_str_escaped = phone_str.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")
                
                user_summary = (
                    f"👤 Ім'я: {name_escaped}\n"
                    f"🎂 Вік: {age}\n"
                    f"🏙️ Місто: {city_escaped}\n"
                    f"📞 Телефон: {phone_str_escaped}\n"
                    f"🔗 Username: {username_str_escaped}\n"
                    f"🆔 Telegram ID: {telegram_id}\n"
                    f"📊 Статус: {status}\n\n"
                    f"✅ Прийнято! Введіть команду у форматі:\n"
                    f"`/accept {tg_id} Київ:2025-07-01`"
                )
                try:
                    await query.edit_message_text(
                        user_summary,
                        parse_mode=ParseMode.MARKDOWN
                    )
                except Exception as md_error:
                    logger.error(f"❌ Markdown formatting error: {str(md_error)}")
                    # Fallback to plain text if Markdown fails
                    await query.edit_message_text(user_summary)
            else:
                await query.edit_message_text(
                    "✅ Прийнято! Введіть команду у форматі:\n"
                    f"`/accept {tg_id} Київ:2025-07-01`",
                    parse_mode=ParseMode.MARKDOWN
                )
            # Answer the query with a visible popup
            await query.answer("✅ Статус змінено на 'Прийнято'", show_alert=True)
            logger.info(f"⏳ Waiting for accept command for user {tg_id}")
        else:
            try:
                cur.execute("UPDATE applicants SET status = %s WHERE telegram_id = %s", (new_status, tg_id))
                
                # Get topic info before deletion
                cur.execute("SELECT thread_id FROM topic_mappings WHERE telegram_id = %s", (tg_id,))
                topic = cur.fetchone()
                
                if topic:
                    try:
                        await context.bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic[0])
                        logger.info(f"🗑️ Deleted forum topic for user {tg_id}")
                    except Exception as e:
                        logger.error(f"❌ Failed to delete forum topic: {str(e)}")
                        # Continue with other operations even if topic deletion fails
                    cur.execute("DELETE FROM topic_mappings WHERE telegram_id = %s", (tg_id,))
                
                conn.commit()
                
                # Get user info to preserve it
                cur.execute("""
                    SELECT name, age, city, phone, username, telegram_id, status
                    FROM applicants WHERE telegram_id = %s
                """, (tg_id,))
                user_info = cur.fetchone()
                
                if user_info:
                    name, age, city, phone, username, telegram_id, status = user_info
                    username_str = f"@{username}" if username else "—"
                    phone_str = phone if phone else "—"
                    user_summary = (
                        f"👤 Ім'я: {name}\n"
                        f"🎂 Вік: {age}\n"
                        f"🏙️ Місто: {city}\n"
                        f"📞 Телефон: {phone_str}\n"
                        f"🔗 Username: {username_str}\n"
                        f"🆔 Telegram ID: {telegram_id}\n"
                        f"📊 Статус: {new_status}"
                    )
                    await query.edit_message_text(user_summary)
                else:
                    await query.edit_message_text(f"✅ Статус оновлено: {new_status}")
                
                # Answer the query with a visible popup
                await query.answer(f"✅ Статус змінено на '{new_status}'", show_alert=True)
                logger.info(f"✅ Status updated for user {tg_id} to {new_status}")
            except Exception as e:
                logger.error(f"❌ Error updating status: {str(e)}")
                conn.rollback()
                await query.answer("❌ Сталася помилка при оновленні статусу.", show_alert=True)
            finally:
                cur.close()
                conn.close()
    except Exception as e:
        logger.error(f"❌ Error in set_status_callback: {str(e)}")
        await query.answer("❌ Сталася помилка при оновленні статусу", show_alert=True)

async def accept_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Check if there are enough arguments
        if len(context.args) < 2:
            await update.message.reply_text(
                "❌ Невірний формат команди.\n"
                "Використання: `/accept <telegram_id> <місто:дата>`\n"
                "Приклад: `/accept 123456789 Київ:2025-07-01`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        telegram_id = int(context.args[0])
        city_date = context.args[1]

        try:
            city, date = city_date.split(":")
            # Validate date format
            from datetime import datetime
            datetime.strptime(date.strip(), "%Y-%m-%d")
        except ValueError:
            logger.warning(f"⚠️ Invalid format for accept command: {city_date}")
            await update.message.reply_text(
                "❌ Невірний формат дати. Введіть як: `Київ:2025-07-01`\n"
                "Дата повинна бути у форматі YYYY-MM-DD",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # First, verify the applicant exists
        cur.execute("SELECT 1 FROM applicants WHERE telegram_id = %s", (telegram_id,))
        if not cur.fetchone():
            logger.warning(f"⚠️ Attempted to accept non-existent applicant {telegram_id}")
            await update.message.reply_text("❌ Заявку не знайдено.")
            cur.close()
            conn.close()
            return

        try:
            cur.execute("""
                UPDATE applicants
                SET accepted_city = %s, accepted_date = %s, status = 'Accepted'
                WHERE telegram_id = %s
            """, (city.strip(), date.strip(), telegram_id))

            # Get topic info before deletion
            cur.execute("SELECT thread_id FROM topic_mappings WHERE telegram_id = %s", (telegram_id,))
            topic = cur.fetchone()
            
            if topic:
                try:
                    await context.bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic[0])
                    logger.info(f"✅ Deleted forum topic for user {telegram_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to delete forum topic: {str(e)}")
                    # Continue with other operations even if topic deletion fails
                cur.execute("DELETE FROM topic_mappings WHERE telegram_id = %s", (telegram_id,))

            conn.commit()

            # Get user info to show final status
            cur.execute("""
                SELECT name, age, city, phone, username, telegram_id, status, accepted_city, accepted_date::text
                FROM applicants WHERE telegram_id = %s
            """, (telegram_id,))
            user_info = cur.fetchone()
            
            if user_info:
                name, age, city, phone, username, telegram_id, status, accepted_city, accepted_date = user_info
                username_str = f"@{username}" if username else "—"
                phone_str = phone if phone else "—"
                user_summary = (
                    f"👤 Ім'я: {name}\n"
                    f"🎂 Вік: {age}\n"
                    f"🏙️ Місто: {city}\n"
                    f"📞 Телефон: {phone_str}\n"
                    f"🔗 Username: {username_str}\n"
                    f"🆔 Telegram ID: {telegram_id}\n"
                    f"📊 Статус: {status}\n"
                    f"✅ Прийнято: {accepted_city}, {accepted_date}"
                )
                await update.message.reply_text(user_summary)
            else:
                await update.message.reply_text("✅ Дані збережено та чат закрито.")
            logger.info(f"✅ Application accepted for user {telegram_id}")
        except Exception as e:
            logger.error(f"❌ Error during acceptance: {str(e)}")
            conn.rollback()
            await update.message.reply_text("❌ Сталася помилка при збереженні даних.")
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        logger.error(f"❌ Error in accept_command: {str(e)}")
        await update.message.reply_text("❌ Сталася помилка при збереженні даних.")

async def start_chat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
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
            # Chat already exists, update only the button
            thread_id = existing_topic[0]
            logger.info(f"ℹ️ Chat already exists for user {applicant_id}")
            
            # Create buttons for all users
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💬 Перейти до чату", url=f"https://t.me/c/{str(GROUP_ID)[4:]}/{thread_id}"),
                    InlineKeyboardButton("🗑️ Видалити", callback_data=f"delete_user:{applicant_id}")
                ],
                [
                    InlineKeyboardButton("✅ Прийняти", callback_data=f"set_status:{applicant_id}:Accepted"),
                    InlineKeyboardButton("❌ Відхилити", callback_data=f"set_status:{applicant_id}:Declined")
                ]
            ])
            
            await query.edit_message_reply_markup(
                reply_markup=keyboard
            )
            await query.answer("ℹ️ Чат вже існує", show_alert=True)
            cur.close()
            conn.close()
            return

        # If no existing chat, create a new one
        cur.execute("SELECT name, username, age, city, phone, status FROM applicants WHERE telegram_id = %s", (applicant_id,))
        result = cur.fetchone()
        if not result:
            logger.error(f"❌ User {applicant_id} not found in database")
            await query.answer("❌ Користувача не знайдено в базі даних", show_alert=True)
            cur.close()
            conn.close()
            return

        name, username, age, city, phone, status = result
        
        try:
            chat_title = f"{name} (@{username})" if username else name
            topic = await context.bot.create_forum_topic(
                chat_id=GROUP_ID,
                name=f"Чат: {chat_title}"
            )
            logger.info(f"✅ Created new forum topic for user {applicant_id}")

            thread_id = topic.message_thread_id
            cur.execute("INSERT INTO topic_mappings (telegram_id, thread_id) VALUES (%s, %s)", (applicant_id, thread_id))
            conn.commit()

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

            # Create buttons for all users
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("💬 Перейти до чату", url=f"https://t.me/c/{str(GROUP_ID)[4:]}/{thread_id}"),
                    InlineKeyboardButton("🗑️ Видалити", callback_data=f"delete_user:{applicant_id}")
                ],
                [
                    InlineKeyboardButton("✅ Прийняти", callback_data=f"set_status:{applicant_id}:Accepted"),
                    InlineKeyboardButton("❌ Відхилити", callback_data=f"set_status:{applicant_id}:Declined")
                ]
            ])

            # Update the original message with new buttons
            await query.edit_message_reply_markup(
                reply_markup=keyboard
            )

            # Send the summary to the new topic with the same buttons
            await context.bot.send_message(
                chat_id=GROUP_ID,
                message_thread_id=thread_id,
                text=summary,
                reply_markup=keyboard
            )
            
            # Show success message
            await query.answer("✅ Чат створено успішно", show_alert=True)
            logger.info(f"✅ Chat started successfully for user {applicant_id}")
        except Exception as e:
            logger.error(f"❌ Error creating forum topic: {str(e)}")
            conn.rollback()
            await query.answer(f"❌ Помилка при створенні чату: {str(e)[:50]}", show_alert=True)
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        logger.error(f"❌ Error in start_chat_callback: {str(e)}")
        await query.answer("❌ Сталася помилка при створенні чату", show_alert=True)

async def delete_user_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        # Check if the user is admin
        if query.from_user.id != ADMIN_ID:
            logger.warning(f"⚠️ Non-admin user {query.from_user.id} tried to delete an application")
            await query.answer("❌ Тільки адміністратор може видаляти заявки", show_alert=True)
            # Send a message to notify about the unauthorized attempt
            #await context.bot.send_message(
            #    chat_id=query.message.chat.id,
            #    message_thread_id=query.message.message_thread_id if query.message.is_topic_message else None,
            #    text=f"❌ Тільки адміністратор може видаляти заявки."
            #)
            return

        data = query.data
        if not data.startswith("delete_user:"):
            return

        applicant_id = int(data.split(":")[1])
        logger.info(f"🗑️ Deleting application for user {applicant_id}")

        # First, verify the applicant exists
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        
        cur.execute("SELECT 1 FROM applicants WHERE telegram_id = %s", (applicant_id,))
        if not cur.fetchone():
            logger.warning(f"⚠️ Attempted to delete non-existent applicant {applicant_id}")
            await query.answer("❌ Заявку не знайдено в базі даних", show_alert=True)
            # Send a message to notify about the error
            #await context.bot.send_message(
            #    chat_id=query.message.chat.id,
            #    message_thread_id=query.message.message_thread_id if query.message.is_topic_message else None,
            #    text=f"❌ Заявку не знайдено."
            #)
            cur.close()
            conn.close()
            return

        # Get topic info before deletion
        cur.execute("SELECT thread_id FROM topic_mappings WHERE telegram_id = %s", (applicant_id,))
        topic = cur.fetchone()

        try:
            # Delete the topic if it exists
            if topic:
                try:
                    await context.bot.delete_forum_topic(chat_id=GROUP_ID, message_thread_id=topic[0])
                    logger.info(f"✅ Deleted forum topic for user {applicant_id}")
                except Exception as e:
                    logger.error(f"❌ Failed to delete forum topic: {str(e)}")
                    # Continue with other deletions even if topic deletion fails
                cur.execute("DELETE FROM topic_mappings WHERE telegram_id = %s", (applicant_id,))

            # Delete the applicant data
            cur.execute("DELETE FROM applicants WHERE telegram_id = %s", (applicant_id,))
            conn.commit()
            
            # Only after successful deletion, update the message
            await query.edit_message_text("🗑️ Заявку видалено.")
            await query.answer("✅ Заявку успішно видалено", show_alert=True)
            logger.info(f"✅ Application deleted for user {applicant_id}")
        except Exception as e:
            logger.error(f"❌ Error during deletion: {str(e)}")
            conn.rollback()  # Rollback any partial changes
            await query.answer(f"❌ Помилка при видаленні заявки: {str(e)[:50]}", show_alert=True)
            # Send a message to notify about the error
            #await context.bot.send_message(
            #    chat_id=query.message.chat.id,
            #    message_thread_id=query.message.message_thread_id if query.message.is_topic_message else None,
            #    text=f"❌ Сталася помилка при видаленні заявки."
            #)
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        logger.error(f"❌ Error in delete_user_callback: {str(e)}")
        await query.answer(f"❌ Сталася помилка: {str(e)[:50]}", show_alert=True)
        # Send a message to notify about the error
        #try:
        #    await context.bot.send_message(
        #        chat_id=query.message.chat.id,
        #        message_thread_id=query.message.message_thread_id if query.message.is_topic_message else None,
        #        text=f"❌ Сталася помилка при видаленні заявки."
        #    )
        #except:
        #    pass  # If we can't send a message, just continue

async def handle_admin_group_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = update.message
        if not msg or not msg.message_thread_id:
            logger.info("❌ No message found, returning")
            return
        
        if update.edited_message:
            logger.info("❌ Edited message found, returning")
            return
            
        # Skip if message is from the bot itself
        if msg.from_user and msg.from_user.id == context.bot.id:
            logger.info("❌ Message is from bot, returning")
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
            logger.info("❌ No message found, returning")
            return
        
        if update.edited_message:
            logger.info("❌ Edited message found, returning")
            return

        # Skip if message is from the bot itself
        if update.message.from_user and update.message.from_user.id == context.bot.id:
            logger.info("❌ Message is from bot, returning")
            return

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

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info(f"🚫 Conversation cancelled by user {update.message.from_user.id}")
        await update.message.reply_text("🚫 Розмову скасовано.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"❌ Error in cancel: {str(e)}")
        return ConversationHandler.END

async def handle_message_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        logger.info("🔍 Edit handler triggered")
        
        if not update.edited_message:
            logger.info("❌ No edited message found, returning")
            return

        edited = update.edited_message
        message_id = edited.message_id
        thread_id = edited.message_thread_id
        
        logger.info(f"📝 Processing edit for message_id: {message_id}")
        logger.info(f"📝 Thread ID: {thread_id}")
        logger.info(f"📝 Message type: {'text' if edited.text else 'caption' if edited.caption else 'other'}")

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # Look up the message mapping
        cur.execute("""
            SELECT admin_message_id, user_message_id, telegram_id, thread_id
            FROM message_log
            WHERE admin_message_id = %s OR user_message_id = %s
        """, (message_id, message_id))

        result = cur.fetchone()
        cur.close()
        conn.close()

        if not result:
            logger.warning("❌ No message mapping found in database")
            return

        admin_msg_id, user_msg_id, telegram_id, stored_thread_id = result
        logger.info(f"✅ Found message mapping - admin_msg: {admin_msg_id}, user_msg: {user_msg_id}, user_id: {telegram_id}, thread_id: {stored_thread_id}")

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
                    # For forum topics, we need to use the full chat_id format and thread_id
                    await context.bot.edit_message_text(
                        chat_id=GROUP_ID,
                        message_id=admin_msg_id,
                        text=f"{prefix}{edited.text}"
                    )
                    logger.info("✅ Updated admin's text message")
                elif edited.caption:
                    await context.bot.edit_message_caption(
                        chat_id=GROUP_ID,
                        message_id=admin_msg_id,
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
        chat_id = reaction.chat.id
        
        logger.info(f"😀 Processing reaction change from user {user_id} on message {message_id} in chat {chat_id}")

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # Look up the message mapping
        cur.execute("""
            SELECT admin_message_id, user_message_id, telegram_id, thread_id
            FROM message_log
            WHERE admin_message_id = %s OR user_message_id = %s
        """, (message_id, message_id))

        result = cur.fetchone()
        if not result:
            logger.warning(f"❌ No message mapping found for reaction on message {message_id}")
            cur.close()
            conn.close()
            return

        admin_msg_id, user_msg_id, telegram_id, thread_id = result
        logger.info(f"✅ Found message mapping - admin_msg: {admin_msg_id}, user_msg: {user_msg_id}, user_id: {telegram_id}, thread_id: {thread_id}")

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
                # For forum topics, we need to use the full chat_id format
                chat_id = f"-100{str(GROUP_ID)[4:]}"
                await context.bot.set_message_reaction(
                    chat_id=chat_id,
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
            logger.error(f"Error type: {type(e)}")
            # Try to log more details about the error
            if hasattr(e, 'response'):
                logger.error(f"Response: {e.response}")

        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Error in handle_message_reaction: {str(e)}")
        logger.error(f"Error type: {type(e)}")
        if hasattr(e, 'response'):
            logger.error(f"Response: {e.response}")

async def applicants_by_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Get the message object, either from regular message or forum topic
    message = update.message or update.edited_message
    try:
        if not message and not update.callback_query:
            logger.warning("❌ No message or callback query found in update")
            return

        # Check if the message is from the admin group
        chat_id = message.chat.id if message else update.callback_query.message.chat.id
        if chat_id != GROUP_ID:
            logger.warning(f"⚠️ Command used outside admin group: chat_id={chat_id}")
            if update.callback_query:
                await update.callback_query.answer("❌ Команда доступна тільки в адмін групі", show_alert=True)
            return

        # Check if the user is a member of the admin group
        user_id = message.from_user.id if message else update.callback_query.from_user.id
        try:
            chat_member = await context.bot.get_chat_member(
                chat_id=GROUP_ID,
                user_id=user_id
            )
            if chat_member.status not in ['member', 'administrator', 'creator']:
                logger.warning(f"⚠️ Non-member tried to use command: user_id={user_id}")
                if update.callback_query:
                    await update.callback_query.answer("❌ Ви не є учасником адмін групи", show_alert=True)
                return
        except Exception as e:
            logger.error(f"❌ Error checking group membership: {str(e)}")
            if update.callback_query:
                await update.callback_query.answer("❌ Помилка перевірки членства в групі", show_alert=True)
            return

        # Parse command arguments
        args = context.args
        if not args:
            if message:
                await message.reply_text(
                    "❌ Будь ласка, вкажіть статус.\n"
                    "Доступні статуси: New, In Progress, Accepted, Declined\n"
                    "Приклад: /applicants_by_status New"
                )
            elif update.callback_query:
                await update.callback_query.answer("❌ Не вказано статус", show_alert=True)
            return

        status = args[0]
        page = int(args[1]) if len(args) > 1 else 1
        per_page = 20

        if status not in ['New', 'In Progress', 'Accepted', 'Declined']:
            if message:
                await message.reply_text(
                    "❌ Невірний статус.\n"
                    "Доступні статуси: New, In Progress, Accepted, Declined"
                )
            elif update.callback_query:
                await update.callback_query.answer("❌ Невірний статус", show_alert=True)
            return

        logger.info(f"📋 Listing applicants with status {status}, page {page}")

        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()

        # Get total count
        cur.execute("SELECT COUNT(*) FROM applicants WHERE status = %s", (status,))
        total_count = cur.fetchone()[0]

        if total_count == 0:
            if message:
                await message.reply_text(f"📭 Немає заявок зі статусом {status}")
            elif update.callback_query:
                await update.callback_query.answer(f"📭 Немає заявок зі статусом {status}", show_alert=True)
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

        # Create navigation buttons
        keyboard = []
        nav_row = []
        
        if page > 1:
            nav_row.append(InlineKeyboardButton("◀️", callback_data=f"nav:{status}:{page-1}"))
        nav_row.append(InlineKeyboardButton(f"{page}/{total_pages}", callback_data="ignore"))
        if page < total_pages:
            nav_row.append(InlineKeyboardButton("▶️", callback_data=f"nav:{status}:{page+1}"))
        
        if nav_row:
            keyboard.append(nav_row)

        # Add status filter buttons
        status_row = []
        for s in ['New', 'In Progress', 'Accepted', 'Declined']:
            status_row.append(InlineKeyboardButton(
                "✅" if s == status else s,
                callback_data=f"nav:{s}:1"
            ))
        keyboard.append(status_row)

        reply_markup = InlineKeyboardMarkup(keyboard)

        # If this is a callback query, edit the message
        if update.callback_query:
            try:
                # Check if the message content is already the same
                current_text = update.callback_query.message.text
                if current_text != table:
                    # Edit the message first
                    await update.callback_query.edit_message_text(
                        text=table,
                        reply_markup=reply_markup
                    )
                else:
                    # If content is the same, just update the reply markup
                    await update.callback_query.edit_message_reply_markup(
                        reply_markup=reply_markup
                    )
                # Then show the alert
                await update.callback_query.answer(f"Список заявок: {status}, сторінка {page}/{total_pages}", show_alert=True)
            except Exception as edit_error:
                logger.error(f"❌ Failed to edit message: {str(edit_error)}")
                # Just show the alert without modifying the message
                await update.callback_query.answer(f"Список заявок: {status}, сторінка {page}/{total_pages}", show_alert=True)
        else:
            # If this is a new command, send a new message
            await message.reply_text(
                text=table,
                reply_markup=reply_markup
            )

        logger.info(f"✅ Listed {len(rows)} applicants with status {status} on page {page}")
    except Exception as err:
        logger.error(f"❌ Error in applicants_by_status: {str(err)}")
        if update.callback_query:
            await update.callback_query.answer("❌ Сталася помилка при отриманні списку заявок", show_alert=True)
        elif message:
            await message.reply_text("❌ Сталася помилка при отриманні списку заявок.")

async def handle_navigation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        if not query or not query.data.startswith("nav:"):
            return

        # Ignore the "current page" button
        if query.data == "ignore":
            await query.answer("Поточна сторінка", show_alert=True)
            return

        # Parse the navigation data
        _, status, page = query.data.split(":")
        
        # Set the context args for applicants_by_status
        context.args = [status, page]
        
        # Call applicants_by_status with the new parameters
        await applicants_by_status(update, context)
    except ValueError as err:
        logger.error(f"❌ Invalid page number in navigation: {str(err)}")
        await query.answer("❌ Невірний номер сторінки", show_alert=True)
    except Exception as err:
        logger.error(f"❌ Error in handle_navigation_callback: {str(err)}")
        await query.answer(f"❌ Помилка: {str(err)[:50]}", show_alert=True)

async def create_applicants_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

        global APPLICANTS_TOPIC_ID
        
        # Check if topic already exists in database
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT value FROM bot_settings WHERE key = 'applicants_topic_id'")
        result = cur.fetchone()
        
        if result:
            APPLICANTS_TOPIC_ID = int(result[0])
            await update.message.reply_text(
                f"ℹ️ Тема для заявок вже існує (ID: {APPLICANTS_TOPIC_ID}).\n"
                "Використовуйте /delete_applicants_topic щоб видалити поточну тему."
            )
            cur.close()
            conn.close()
            return

        # Create the topic
        topic = await context.bot.create_forum_topic(
            chat_id=GROUP_ID,
            name="📋 Заявки"
        )
        APPLICANTS_TOPIC_ID = topic.message_thread_id

        # Store the topic ID in database
        cur.execute("""
            INSERT INTO bot_settings (key, value)
            VALUES ('applicants_topic_id', %s)
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = now()
        """, (str(APPLICANTS_TOPIC_ID),))
        conn.commit()

        # Close the topic
        await context.bot.close_forum_topic(
            chat_id=GROUP_ID,
            message_thread_id=APPLICANTS_TOPIC_ID
        )
        
        logger.info(f"✅ Created closed applicants topic with ID: {APPLICANTS_TOPIC_ID}")
        
        await update.message.reply_text(
            f"✅ Тема для заявок створена!\n"
            f"ID теми: {APPLICANTS_TOPIC_ID}\n"
            f"Всі нові заявки будуть надходити сюди.\n"
            f"🔒 Тема закрита - тільки бот може надсилати повідомлення."
        )
        
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Failed to create applicants topic: {str(e)}")
        await update.message.reply_text("❌ Сталася помилка при створенні теми.")

async def delete_applicants_topic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        # Check if the message is from the admin group
        if update.effective_chat.id != GROUP_ID:
            logger.warning(f"⚠️ Command used outside admin group: chat_id={update.effective_chat.id}")
            return

        # Check if the user is the admin
        if update.effective_user.id != ADMIN_ID:
            logger.warning(f"⚠️ Non-admin user {update.effective_user.id} tried to delete applicants topic")
            await update.message.reply_text("❌ Тільки адміністратор може видаляти тему заявок.")
            return

        global APPLICANTS_TOPIC_ID
        
        # Check if topic exists in database
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT value FROM bot_settings WHERE key = 'applicants_topic_id'")
        result = cur.fetchone()
        
        if not result:
            await update.message.reply_text("ℹ️ Тема для заявок ще не створена.")
            cur.close()
            conn.close()
            return

        APPLICANTS_TOPIC_ID = int(result[0])

        # Delete the topic
        await context.bot.delete_forum_topic(
            chat_id=GROUP_ID,
            message_thread_id=APPLICANTS_TOPIC_ID
        )
        
        # Remove from database
        cur.execute("DELETE FROM bot_settings WHERE key = 'applicants_topic_id'")
        conn.commit()
        
        # Clear the global variable
        APPLICANTS_TOPIC_ID = None
        
        logger.info(f"✅ Deleted applicants topic with ID: {APPLICANTS_TOPIC_ID}")
        
        await update.message.reply_text(
            "✅ Тема для заявок видалена.\n"
            "Використовуйте /create_applicants_topic щоб створити нову тему."
        )
        
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Failed to delete applicants topic: {str(e)}")
        await update.message.reply_text("❌ Сталася помилка при видаленні теми.")

if __name__ == '__main__':
    ensure_table()
    
    # Load applicants topic ID from database
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute("SELECT value FROM bot_settings WHERE key = 'applicants_topic_id'")
        result = cur.fetchone()
        if result:
            APPLICANTS_TOPIC_ID = int(result[0])
            logger.info(f"✅ Loaded applicants topic ID from database: {APPLICANTS_TOPIC_ID}")
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Failed to load applicants topic ID: {str(e)}")
    
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
    app.add_handler(CallbackQueryHandler(start_chat_callback, pattern="^start_chat:"))
    app.add_handler(CallbackQueryHandler(delete_user_callback, pattern="^delete_user:"))
    app.add_handler(CallbackQueryHandler(handle_navigation_callback, pattern="^nav:"))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern="^admin_panel:"))
    app.add_handler(CommandHandler("admin_panel", send_admin_panel_link))
    app.add_handler(CommandHandler("applicants_by_status", applicants_by_status))
    app.add_handler(CommandHandler("create_applicants_topic", create_applicants_topic))
    app.add_handler(CommandHandler("delete_applicants_topic", delete_applicants_topic))
    app.add_handler(CommandHandler("accept", accept_command))
    app.add_handler(CallbackQueryHandler(set_status_callback, pattern="^set_status:"))
    app.add_handler(MessageHandler(filters.UpdateType.EDITED, handle_message_edit))
    app.add_handler(MessageHandler(filters.Chat(GROUP_ID) & filters.ALL & ~filters.COMMAND, handle_admin_group_messages))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, forward_to_topic))
    app.add_handler(MessageReactionHandler(callback=handle_message_reaction))
    app.run_polling()