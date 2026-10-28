"""
Alembic for the bot's OWN tables.

Two things keep this from colliding with the web API's migrations in the same
database:

* its own version table, `alembic_version_bot` (the API uses `alembic_version`);
* include_object skips every table the bot does not own, so autogenerate never
  proposes to touch users/defects/etc.
"""
import os
import sys

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from botapp import config            # noqa: E402
from botapp.db import Base           # noqa: E402
import botapp.models                 # noqa: E402,F401

OWNED = {'bot_members', 'bot_notification_log'}


def include_object(obj, name, type_, reflected, compare_to):
    return name in OWNED if type_ == 'table' else True


def run():
    engine = create_engine(config.database_url())
    with engine.connect() as conn:
        context.configure(
            connection=conn, target_metadata=Base.metadata,
            version_table='alembic_version_bot', include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


run()
