# Telegram Bot with Admin Panel

## Features
- Collects name, age, city, and phone number (if shared)
- Sends admin notification with full applicant info
- Admin can:
  - Reply via Telegram group to start conversation (status auto-updates)
  - Change applicant status (New, In Progress, Accepted, Declined) in web panel

## Deploy on Railway

1. Set env variables:
   - `BOT_TOKEN`
   - `ADMIN_ID`
   - `DATABASE_URL`

2. Deploy `bot.py` as a worker service
3. Deploy `app.py` as a web service (uses port 5000)