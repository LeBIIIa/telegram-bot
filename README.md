# Unified Telegram Bot + Admin Panel (Ukrainian)

## What This Does
- Telegram bot that collects name, age, city
- Saves applicants to PostgreSQL
- Web admin panel to view and reply

## Setup

1. Create PostgreSQL DB and run `schema.sql`
2. Set environment variables:
```bash
export BOT_TOKEN=your_bot_token
export ADMIN_ID=your_telegram_id
export DATABASE_URL=your_postgres_url
```
3. Install Python deps:
```bash
pip install -r requirements.txt
```
4. Run bot and web panel:
```bash
# Option 1: Run both in separate processes
python bot.py  # background process
python app.py  # foreground for admin panel

# Option 2: Use Railway to run one as a web service and one as a worker
```
