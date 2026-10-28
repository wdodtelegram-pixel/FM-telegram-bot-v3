FROM python:3.11-slim

# psycopg2-binary ships wheels, but libpq is still needed at runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONUNBUFFERED=1

# Bot tables first (idempotent), then the bot itself.
CMD ["sh", "-c", "alembic -c migrations/alembic.ini upgrade head && python -m botapp.main"]
