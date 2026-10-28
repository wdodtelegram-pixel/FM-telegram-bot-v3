"""
Everything the bot reads from the environment, in one place.

The bot is its own application, so it has its own .env (Bot/.env) and needs
exactly three settings. No SECRET_KEY: it signs nothing, because sign-in is by
the allowlist (bot_members) rather than a token minted by the web app.
"""

import os

from dotenv import load_dotenv

# Bot/.env, next to requirements.txt -- not the platform's Backend/.env.
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))


def token():
    return (os.environ.get('TELEGRAM_BOT_TOKEN') or '').strip()


def database_url():
    url = (os.environ.get('DATABASE_URL') or '').strip()
    if not url:
        raise RuntimeError(
            'DATABASE_URL is not set. Point it at the same PostgreSQL database '
            'the web API uses, e.g. postgresql://user:pass@localhost:5432/building_defect_db'
        )
    # SQLAlchemy 2 only knows the "postgresql" name, not Heroku-style "postgres".
    if url.startswith('postgres://'):
        url = 'postgresql://' + url[len('postgres://'):]
    return url


def timezone():
    return os.environ.get('TZ', 'UTC')


def today():
    """Today's date in the configured timezone (TZ), not the server's clock."""
    import datetime
    from zoneinfo import ZoneInfo
    try:
        return datetime.datetime.now(ZoneInfo(timezone())).date()
    except Exception:
        return datetime.datetime.utcnow().date()
