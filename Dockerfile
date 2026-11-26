# The Telegram bot (and the migration / admin tools). No web framework inside.
FROM python:3.11-slim

# psycopg2-binary ships wheels, but libpq is still needed at runtime.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY core ./core
COPY botapp ./botapp
COPY migrations ./migrations
COPY docker/entrypoint.sh /entrypoint.sh
# Built on Windows the file may arrive without its executable bit or with CRLF line endings.
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "botapp.main"]
