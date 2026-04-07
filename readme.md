# HAM Bot for Discord 0.1

This bot uses `discord.py` 2.7.1 and exposes slash commands for:

- `/bandconditions`
- `/wavelength_to_frequency`
- `/frequency_to_wavelength`

Versioning:

- Bot version: `0.1`
- SQLite DB version: `0.1`

The `/bandconditions` command fetches XML from `https://www.hamqsl.com/solarxml.php` and archives the raw XML payload in a local SQLite database named `ham_bot.sqlite3`.

## Setup

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Configure environment variables in `.env`:

```env
DISCORD_BOT_TOKEN=your_bot_token_here
LOG_LEVEL=INFO
HAM_BOT_DB_PATH=ham_bot.sqlite3
```

## Discord App Settings

Invite scopes:

- `bot`
- `applications.commands`

Bot permissions:

- `View Channels`
- `Send Messages`
- `Embed Links`

Gateway intents:

- `MESSAGE CONTENT INTENT`: off
- `SERVER MEMBERS INTENT`: off
- `PRESENCE INTENT`: off
