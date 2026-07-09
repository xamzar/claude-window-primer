---
name: claude-window-primer
aliases: [claude-window-primer]
tags: [project]
stage: testing
---

# claude-window-primer

> Tracks and primes Claude Pro / Claude Code 5-hour rate-limit reset windows so
> the subscription clock starts on **your** schedule, not Anthropic's.

Claude's 5-hour usage window only starts counting from your **first** request
after a reset. If your limits reset at night but you don't touch Claude until
morning, that fresh window hasn't started yet — you burn hours of idle capacity.
This is a small Python service that sends a tiny `claude -p` ping on a schedule
anchored to a reset time you choose, chaining a new window every 5 hours so a
fresh one is always ticking when you sit down to work. A Telegram bot gives you
status and full remote control.

- **No dependencies** — pure Python 3.9+ stdlib (`urllib` + `zoneinfo`).
- **One schedule, always.** Your last command replaces the previous one; no
  overlapping timers, no cron drift.
- **Self-correcting.** Prime too early and Claude returns a 429 naming the real
  reset time — the primer parses it and re-anchors automatically.

## How it works

You can only *restart* the clock by priming **after** the current window has
expired. So each prime is scheduled a few minutes *after* the expected reset
(`margin_minutes`, default 3). After a successful prime, the next one is chained
to `cycle_minutes + margin` from the **actual prime moment** — not a fixed clock
time — which avoids the drift a plain cron would cause (24 ÷ 5 isn't even).

If a prime lands before the window has actually reset, Claude replies with a 429
whose message names the real reset time (e.g. `resets 9:20pm (UTC)`). The primer
parses that time, re-anchors the next prime to `reset + margin`, and escalates
the retry margin (30s → 60s → config margin) so it recovers fast instead of
drifting a whole cycle.

## Requirements

- `claude` CLI installed and logged into your Pro subscription
  (`claude -p "hi"` should return a reply)
- Python 3.9+
- A Telegram bot token from [@BotFather](https://t.me/BotFather) *(optional —
  without one it runs schedule-only, no notifications or remote control)*

## Install

```bash
# 1. Secrets (gitignored) — token from @BotFather; chat auto-links on first message
echo 'TELEGRAM_TOKEN=your_bot_token_here' > .env

# 2. Settings (copy defaults, edit if needed)
cp config.example.json config.json

# 3. Install the systemd user service
mkdir -p ~/.config/systemd/user
cp claude-window-primer.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now claude-window-primer

# Keep it running after logout
loginctl enable-linger "$USER"
```

The service runs `primer.py bot` from `~/testing/claude-window-primer` — adjust
`WorkingDirectory`/`ExecStart` in the unit file if you cloned elsewhere.

## Set the schedule

Message your bot on Telegram (it auto-links to your chat on the first message):

```
/start
/init 09:00 Asia/Taipei
```

Or from the CLI:

```bash
python3 primer.py init --reset 09:00 --tz Asia/Taipei
```

## Run modes

```
primer.py bot                          run the Telegram bot + scheduler (main; used by systemd)
primer.py init --reset HH:MM --tz Zone set the anchor reset time from the CLI
primer.py prime                        force a prime right now
primer.py tick                         prime once if due (cron alternative to `bot`)
primer.py status                       print current window state
primer.py test-telegram                send a test Telegram notification
```

Without a `TELEGRAM_TOKEN`, `bot` runs in schedule-only mode: it keeps priming
on schedule but skips notifications and remote control (add a token and restart
to enable them).

## Telegram bot commands

There is always **exactly one schedule**. Your last command is the single source
of truth and fully replaces the previous one; after each prime the chain
continues every 5h automatically.

| Command | What it does |
|---------|--------------|
| `/start` | Link chat + show help |
| `/prime` | Limits reset **now**: prime immediately and chain every 5h from this moment |
| `/reset` | Same as `/prime`; `/reset HH:MM` changes the anchor clock time |
| `/init HH:MM [Zone]` | Schedule the **first** prime at a clock time (e.g. `/init 02:00 Asia/Taipei`) |
| `/status` | Current window state and next prime |
| `/pause` | Pause auto-priming |
| `/resume` | Resume auto-priming |
| `/cycle N` | Window length in minutes (default 300 = 5h) |
| `/margin N` | Minutes after reset to prime (default 3) |
| `/tz Zone` | Set timezone (e.g. `Europe/Moscow`) |
| `/help` | Show help |

The bot links to the first chat that messages it and ignores every other chat
thereafter, so only you can control it.

## Configuration

Non-secret settings live in `config.json`:

| Key | Default | Meaning |
|-----|---------|---------|
| `tz` | `Asia/Taipei` | Your timezone |
| `model` | `claude-haiku-4-5-20251001` | Cheapest model for the ping |
| `cycle_minutes` | `300` | Window length (5 hours) |
| `margin_minutes` | `3` | Minutes after reset to prime |
| `retry_minutes` | `10` | After a transient failure (network/timeout), retry this soon instead of a full cycle later |
| `prompt` | `Reply with exactly one word: pong` | The throwaway prompt |
| `claude_timeout_secs` | `120` | Max seconds for the claude CLI call |
| `notify_on_prime` | `true` | Telegram notification on each prime |
| `notify_on_failure` | `true` | Telegram notification on failure |

Secrets (`TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`) live only in `.env` (gitignored)
and are never written back to `config.json`. `TELEGRAM_CHAT_ID` is optional — it
is auto-captured when you first message the bot.

## Troubleshooting

```bash
systemctl --user status claude-window-primer          # service status
journalctl --user -u claude-window-primer -f          # follow logs
tail -f ~/testing/claude-window-primer/primer.log     # local log file
python3 primer.py status                              # inspect window state
python3 primer.py prime                               # force a manual prime
claude login                                          # re-auth if the session expired
```

## Tests

Offline unit tests — no network, no `claude` CLI needed:

```bash
python3 -m unittest test_primer
```

## Cost

Each prime is a single request to Haiku with a one-word reply — a few thousand
tokens, ~5 times a day. On a Claude Pro subscription this is negligible.

See [SETUP.md](SETUP.md) for the full step-by-step setup guide.

## Related
- [[claude-limit-primer]] — upstream reference
- [[xmzr-stack/docs/AGENT-ROUTING]] — Hermes territory
