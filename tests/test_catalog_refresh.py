from unittest.mock import MagicMock

import pytest

from botapp import admin
from botapp.main import build_commands, refresh_catalog
from core import equipment
from core.fm import catalog
from tests.harness import Chat, make_app


@pytest.fixture(autouse=True)
def restore_catalog():
    saved = {k: dict(v) for k, v in catalog.CATEGORIES.items()}
    yield
    catalog.replace_categories(saved)


def test_a_type_added_in_the_website_reaches_the_bot_menu_and_commands(session, world):
    equipment.load_catalog()           # what main() does at start-up
    app, bot = make_app()
    admin.add_member(8001, 'Tess')
    chat = Chat(app, bot, 8001, 'Tess')
    equipment.create_type('crane', 'Tower Crane', 'Crane servicing', '\U0001F3D7')
    ctx = MagicMock(); ctx.bot = bot
    bot._loop.run_until_complete(refresh_catalog(ctx))
    assert 'crane' in catalog.CATEGORIES
    assert 'crane' in bot.menus[-1]                        # Telegram's menu was re-registered
    out = chat.say('/crane')                               # registered after start: handled generically
    assert 'TOWER CRANE' in out[1]
    assert 'Tower Crane' in chat.say('/start')[2] or 'Tower Crane' in str(chat.mine()[-1])


def test_nothing_changes_and_no_menu_churn_when_the_types_did_not_change(session, world):
    equipment.load_catalog()
    app, bot = make_app()
    before = len(bot.menus)
    ctx = MagicMock(); ctx.bot = bot
    bot._loop.run_until_complete(refresh_catalog(ctx))
    assert len(bot.menus) == before


def test_a_disabled_type_disappears_from_the_menu(session, world):
    equipment.load_catalog()
    app, bot = make_app()
    equipment.update_type(equipment.get_by_key_or_name('fire').id, active=False)
    ctx = MagicMock(); ctx.bot = bot
    bot._loop.run_until_complete(refresh_catalog(ctx))
    assert 'fire' not in bot.menus[-1] and 'fire' not in catalog.CATEGORIES


def test_menu_has_the_guided_commands_first_and_stays_within_telegrams_limit():
    names = [c.command for c in build_commands()]
    assert names[:3] == ['start', 'events', 'report'] and len(names) <= 100
