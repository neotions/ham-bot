# HAM Bot for Discord

This bot uses `discord.py` 2.7.1 and exposes a slash command:

- `/bandconditions`
- `/wavelength_to_frequency`
- `/frequency_to_wavelength`

## Setup

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Configure environment variables in `.env`:

```env
DISCORD_BOT_TOKEN=your_bot_token_here
LOG_LEVEL=INFO
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
