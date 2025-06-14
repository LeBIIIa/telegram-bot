# Telegram Bot with Admin Panel

A Telegram bot that manages applicant registrations with an integrated admin panel for handling applications.

## Features

### Bot Features
- Collects applicant information:
  - Name
  - Age (with minimum age verification)
  - City
  - Phone number (optional)
- Automatic admin notifications with detailed applicant info
- Forum topic creation for each applicant in admin group
- Two-way communication between admin and applicant
- Support for text, voice messages, photos, and documents

### Admin Panel Features
- Web-based admin interface with secure token access
- View and filter applications by status:
  - New
  - In Progress
  - Accepted
  - Declined
- Manage applications:
  - Update application status
  - Add accepted city and date for approved applications
  - Delete applications
  - Direct link to applicant's Telegram profile
- Real-time status updates
- Automatic forum topic management

## Setup

### Prerequisites
- Python 3.7+
- PostgreSQL database
- Telegram Bot Token (from @BotFather)
- Telegram Group ID (for admin group)

### Environment Variables
- `BOT_TOKEN`: Your Telegram bot token
- `ADMIN_ID`: Admin's Telegram user ID
- `GROUP_ID`: Admin group's Telegram ID
- `DATABASE_URL`: PostgreSQL connection URL
- `APP_DOMAIN`: Domain where admin panel is hosted

### Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up environment variables
4. Initialize the database (tables are created automatically on first run)

### Deployment

#### Railway Deployment
1. Set required environment variables in Railway dashboard
2. Deploy `background-task/bot.py` as a worker service
3. Deploy `admin-panel/app.py` as a web service (uses port 5000)

#### Manual Deployment
1. Run the bot:
   ```bash
   python background-task/bot.py
   ```
2. Run the admin panel:
   ```bash
   python admin-panel/app.py
   ```

## Usage

### Bot Commands
- `/start` - Begin the application process
- `/cancel` - Cancel the current application process
- `/adminpanel` - Generate admin panel access link (admin group only)

### Admin Panel Access
1. Use `/adminpanel` command in the admin group
2. Click the generated link (valid for 10 minutes)
3. Manage applications through the web interface

## Security
- Admin panel access is protected by temporary tokens
- Tokens expire after 10 minutes
- All sensitive operations require admin group membership