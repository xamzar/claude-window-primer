---
name: claude-window-primer
aliases: [claude-window-primer]
tags: [project]
stage: testing
---

# claude-window-primer

> Tracks and primes Claude Pro 5-hour rate-limit reset windows so the subscription clock starts on YOUR schedule, not Anthropic's.

## What it is
A lightweight Python service that sends a minimal `claude -p` request every 5 hours, anchored to a user-configured reset time. Telegram bot for status and control.

Based on the open-source [[claude-limit-primer]].

## Status
Playground — working on the core VM. Self-correcting schedule (parses the real
reset time out of a 429), offline unit tests pass, ready to promote to testing.

## Related
- [[claude-limit-primer]] — upstream reference
- [[xmzr-stack/docs/AGENT-ROUTING]] — Hermes territory
