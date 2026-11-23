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

from core import config            # noqa: E402
from core.db import Base           # noqa: E402
import core.models                 # noqa: E402,F401

def include_object(obj, name, type_, reflected, compare_to):
    """This application owns every table in its metadata. Ignore only what it does not map
    (for example a legacy web-app table such as refresh_tokens in an existing database)."""
    if type_ == 'table' and reflected and name not in Base.metadata.tables:
        return False
    return True


def run():
    engine = create_engine(config.database_url())
    with engine.connect() as conn:
        context.configure(
            connection=conn, target_metadata=Base.metadata,
            version_table='alembic_version_bot', include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


run()
