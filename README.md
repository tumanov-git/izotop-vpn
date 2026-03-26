# Izotop Connect Bot

Telegram bot for `Izotop Connect`:

- user flow via inline keyboards;
- Tribute subscription status via webhooks;
- Remnawave user creation and `subscription URL` issuance;
- lightweight admin tools in bot;
- SQLite storage for the first production iteration.

## Docs

- [Product and implementation plan](/Users/izotop/izotop vpn/docs/telegram-bot-plan.md)
- [Remnawave panel in Poland, node in NL](/Users/izotop/izotop vpn/docs/remnawave-poland-panel-nl-node-bot.md)

## Setup

Install Python `3.12`, then:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e .
cp .env.example .env
```

Run:

```bash
python -m izotop_connect_bot
```

The app starts:

- FastAPI server for webhooks and health checks
- Telegram bot polling loop

