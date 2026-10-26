# Community Discord Bot

A complete Discord bot for a Roblox game-development community. The administrator-only `/setup` command rebuilds the server with English categories, channels, roles, permissions, panels and automated messages.

## Installation

1. Install Python 3.11 or newer.
2. Create a virtual environment and install the dependencies:

   ```bash
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

3. Copy `.env.example` to `.env` and configure:

   - `DISCORD_TOKEN`: the bot token from the Discord Developer Portal.
   - `DISCORD_GUILD_ID`: target server ID. The configured default is `1564053052015771728`.
   - `PRESERVED_SETUP_CHANNEL_IDS`: optional comma-separated channel IDs that `/setup` must never delete.

4. Enable **Server Members Intent** and **Message Content Intent** in the Discord Developer Portal.
5. Give the bot the permissions required to manage channels, roles, messages, members and the audit log. Place the bot role above every role it manages.
6. Start the bot:

   ```bash
   .venv\Scripts\python.exe bot.py
   ```

## Server setup

- On the first startup of this version, the bot automatically rebuilds server `1564053052015771728`, then writes a local completion marker so ordinary restarts cannot wipe it again.
- `/setup` deletes every unprotected category and channel, clears obsolete dynamic data and rebuilds the complete server.
- Protected channel IDs from `PRESERVED_SETUP_CHANNEL_IDS` are preserved.
- Official information channels are read-only, while community, media, suggestion, bug-report and Roblox-creation channels remain writable by verified members.
- New members receive `🔒・Unverified`; accepting the rules gives them `✅・Member`.
- Bots automatically receive `🤖・Bots`.
- The role-selection panel offers notification, player and platform roles. `💡・Creator` and `🐛・Bug Hunter` can only be assigned by staff.

## Main systems

- Temporary voice channels with `/voice-limit`, `/voice-private`, `/voice-invite` and `/voice-kick`.
- Message and voice XP, rank cards, `/level`, `/leaderboard`, `/level-give` and `/level-reset`.
- A unified ticket panel for Assistance, Partnership, Report, Bug, Purchase Issue and Sanction Appeal.
- Helper claiming, private permissions, points and ticket transcripts.
- Anti-spam, mass-mention protection and suspicious-link detection.
- Invite tracking with automatic Recruiter, Ambassador, Influencer and Master Recruiter roles.
- Weighted giveaways with invite and booster bonuses.
- Suggestions with votes and official staff decisions.
- Community events with registration, waiting lists, reminders and podium roles.
- Moderation commands, internal notes, staff statistics and separate Discord audit logs.
- Automated social-media reminders, welcome messages, clip rules and changelog posts.

## VPS deployment

The recommended systemd service starts:

```text
/home/ubuntu/apps/radarok-bot/.venv/bin/python /home/ubuntu/apps/radarok-bot/bot.py
```

After updating the repository:

```bash
cd /home/ubuntu/apps/radarok-bot
git pull --ff-only origin main
sudo systemctl restart radarok-bot
sudo systemctl status radarok-bot --no-pager -l
```

Never commit `.env`, the Discord token or the SQLite database.
