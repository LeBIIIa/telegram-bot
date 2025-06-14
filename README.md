# Telegram Bot

This is a simple Telegram bot that:
- Asks users for their name, age, and city
- Rejects users under 16 with a referral message
- Sends user info to the admin
- Allows admin to reply to the user via the bot

## Running Locally

1. Install requirements:
```bash
pip install -r requirements.txt
```

2. Set your environment variable:
```bash
export BOT_TOKEN=your_token_here
```

3. Run the bot:
```bash
python bot.py
```

## Deploying on Railway

- Connect this repo
- Add environment variable `BOT_TOKEN` with your bot token
- Use `python bot.py` as the start command
