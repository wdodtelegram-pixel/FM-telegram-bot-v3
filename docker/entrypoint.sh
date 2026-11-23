#!/bin/sh
# Bring the schema up to date, then run whatever the container was asked to run.
# docker-compose sets RUN_MIGRATIONS=0 and uses its one-shot `migrate` service
# instead, so two containers never migrate at the same time.
set -e
if [ "${RUN_MIGRATIONS:-1}" != "0" ]; then
  alembic -c migrations/alembic.ini upgrade head
fi
exec "$@"
