# Setup

## Prerequisites
- `claude` CLI installed and logged into your Pro subscription (`claude -p "hi"` should work)
- Python 3.9+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)

## Quick start

### 1. Create a Telegram bot
1. Message **@BotFather** → `/newbot` → give it a name → copy the **token**.
2. The bot will auto-link to your chat on first message — no need to find your chat ID.

### 2. Configure

```bash
cd ~/playground/claude-window-primer

# Secrets (never committed)
echo 'TELEGRAM_TOKEN=your_bot_token_here' > .env

# Settings (copy defaults, edit if needed)
cp config.example.json config.json
```

### 3. Install the systemd service

```bash
mkdir -p ~/.config/systemd/user
cp claude-window-primer.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-window-primer

# Keep it running after logout
loginctl enable-linger "$USER"
```

### 4. Configure the schedule

Message your bot on Telegram:
```
/start
/init 09:00 Asia/Taipei
```

Or from the CLI:
```bash
python3 primer.py init --reset 09:00 --tz Asia/Taipei
```

## Bot commands

| Command | What it does |
|---------|-------------|
| `/start` | Link chat + show help |
| `/prime` | Limits reset **now**: prime immediately and chain every 5h from this moment |
| `/reset` | Same as `/prime`; `/reset HH:MM` changes the anchor clock time |
| `/init HH:MM [Zone]` | Schedule the **first** prime at a clock time (e.g. `/init 02:00 Asia/Taipei`) |
| `/status` | Current window state and next prime time |
| `/pause` | Pause auto-priming |
| `/resume` | Resume auto-priming |
| `/cycle N` | Window length in minutes (default 300 = 5h) |
| `/margin N` | Minutes after reset to prime (default 3) |
| `/tz Zone` | Change timezone |
| `/help` | Show help |

## CLI commands

```bash
python3 primer.py status           # show window state
python3 primer.py prime            # force a prime now
python3 primer.py init --reset 02:00 --tz Asia/Taipei
python3 primer.py test-telegram    # test notification
```

## How it works

The scheduler model: there is always **exactly one schedule**. Your last command
is the single source of truth — it fully replaces whatever was scheduled before.
No overlapping timers, no cron entries.

After each prime, the bot chains the next prime to 5 hours + margin from the
**actual prime moment** (not a fixed clock time). This prevents the drift that
fixed cron would cause (24 ÷ 5 doesn't divide evenly).

## Troubleshooting

```bash
# Check service status
systemctl --user status claude-window-primer

# Follow logs
journalctl --user -u claude-window-primer -f

# Check the local log file
tail -f ~/playground/claude-window-primer/primer.log

# Test claude CLI works
claude -p "test" --model claude-haiku-4-5-20251001 --output-format json

# Dry-run a manual prime
cd ~/playground/claude-window-primer && python3 primer.py prime

# Check state file
cat ~/playground/claude-window-primer/state.json

# Force re-auth if expired
claude login
```

## Configuration reference

`config.json` (all non-secret settings):

| Key | Default | Meaning |
|-----|---------|---------|
| `tz` | `Asia/Taipei` | Your timezone |
| `model` | `claude-haiku-4-5-20251001` | Cheapest model for the ping |
| `cycle_minutes` | `300` | Window length (5 hours) |
| `margin_minutes` | `3` | Minutes after reset to prime |
| `prompt` | `Reply with exactly one word: pong` | The throwaway prompt |
| `claude_timeout_secs` | `120` | Max seconds for claude CLI call |
| `notify_on_prime` | `true` | Telegram notification on each prime |
| `notify_on_failure` | `true` | Telegram notification on failure |

Secrets (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`) live only in `.env` (gitignored)
and are never written back to `config.json`.

## Cost

Each prime is one request to Haiku with a one-word reply — a few thousand tokens,
~5 times per day. On a Claude Pro subscription this is negligible.
