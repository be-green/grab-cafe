# GradCafe Discord Bot

A Discord bot that monitors the GradCafe economics section and posts new updates to a Discord channel.

## Features

- Scrapes GradCafe for new economics postings
- Stores messages in SQLite database
- Posts new messages to Discord channel
- Runs continuously with configurable check interval
- No external dependencies (R scripts or cron jobs)

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Copy the example environment file:

```bash
cp .env.example .env
```

Edit `.env` and fill in your credentials:

- `DISCORD_TOKEN`: Your Discord bot token
- `DISCORD_CHANNEL_ID`: The Discord channel ID where messages will be posted
- `CHECK_INTERVAL_SECONDS`: How often to check for new messages (default: 60)
- `DB_PATH`: Path to SQLite database file (default: gradcafe_messages.db)

### 3. Seed the Database

Run the seed script to populate the database with current GradCafe postings:

```bash
python seed_database.py
```

This will scrape GradCafe once, store all current postings, and mark them as already posted to avoid sending duplicates to Discord.

### 4. Run the Bot

```bash
python bot.py
```

The bot will:
1. Initialize the database
2. Check GradCafe every `CHECK_INTERVAL_SECONDS` seconds
3. Store new messages in the database
4. Post unposted messages to Discord

## Deployment

For deployment on cloud servers (DigitalOcean, Google Cloud, etc.):

1. Set environment variables in your server's configuration
2. Use a process manager like `systemd` or `supervisor` to keep the bot running
3. Ensure the bot restarts automatically if it crashes

Example systemd service file:

```ini
[Unit]
Description=GradCafe Discord Bot
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/path/to/grab-cafe
Environment="DISCORD_TOKEN=your_token"
Environment="DISCORD_CHANNEL_ID=your_channel_id"
ExecStart=/usr/bin/python3 bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## File Structure

- `bot.py`: Main Discord bot with background task
- `scraper.py`: Web scraping logic for GradCafe
- `database.py`: SQLite database operations
- `seed_database.py`: One-time seed script to populate database
- `requirements.txt`: Python dependencies
- `.env.example`: Template for environment variables

## Old Files (Can be removed)

- `grab-cafe-bot.py`: Old bot implementation
- `parse-grad-cafe.R`: Old R scraping script
- `messages.csv`: Old message storage
- `new_messages.csv`: Old temporary message file
