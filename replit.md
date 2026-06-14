# Telegram Mini App — Clicker + VPN Shop

## Overview
A Telegram Mini App featuring:
- **Clicker game** — tap to earn clicks, sync to server
- **Upgrade shop** — buy click multipliers
- **VPN shop** — purchase VPN configs using clicks
- **Profile** — stats, VPN purchase history
- **Admin panel** — in-bot (/admin) and in-app (admin users only)

## Tech Stack
- **Backend**: Python 3.11, FastAPI, aiogram 3.x
- **Database**: PostgreSQL via SQLAlchemy async + asyncpg
- **Frontend**: Vanilla HTML/CSS/JS (Telegram Mini App SDK)
- **Deployment**: Railway.com (Dockerfile or nixpacks)

## Deployment on Railway

### Required Environment Variables
| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram Bot Token from @BotFather |
| `DATABASE_URL` | PostgreSQL URL (Railway provides this) — format: `postgresql+asyncpg://...` |
| `ADMIN_IDS` | Comma-separated Telegram IDs of super-admins, e.g. `123456789,987654321` |
| `WEBAPP_URL` | Public Railway URL of the app, e.g. `https://yourapp.railway.app` |
| `SECRET_KEY` | Random secret string |
| `PORT` | Auto-set by Railway (default 8000) |

### Setup Steps
1. Create new project on Railway
2. Add a PostgreSQL plugin — copy the `DATABASE_URL`
3. Set env vars listed above
4. Deploy from GitHub or via Railway CLI
5. Set the Mini App URL in @BotFather → Bot Settings → Menu Button → URL = your Railway URL

## Project Structure
```
├── main.py              # Entry point — runs bot + web server
├── config.py            # Environment config
├── requirements.txt
├── Dockerfile
├── railway.toml
├── database/
│   ├── models.py        # SQLAlchemy models
│   └── db.py            # DB functions
├── bot/
│   ├── main.py          # Bot setup
│   └── handlers/
│       ├── start.py     # /start command
│       └── admin.py     # /admin and all admin commands
└── webapp/
    ├── app.py           # FastAPI routes
    └── static/
        └── index.html   # Full mini app frontend
```

## Admin Commands (in bot)
- `/admin` — show admin panel
- `/users` — list all users
- `/addbalance [tg_id] [amount]` — add clicks
- `/removebalance [tg_id] [amount]` — remove clicks
- `/addvpn` — add VPN config (step-by-step)
- `/vpnlist` — list all VPN configs
- `/togglevpn [id]` — enable/disable VPN config
- `/setadmin [tg_id]` — grant admin rights
- `/removeadmin [tg_id]` — revoke admin rights

## User Preferences
- Comments in code should be minimal
- Deploy on Railway.com
