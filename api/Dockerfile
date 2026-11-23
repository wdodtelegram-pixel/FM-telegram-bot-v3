# The website API. Build from the repository root:  docker build -f api/Dockerfile .
FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./requirements.txt
COPY api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt
COPY core ./core
COPY botapp ./botapp
COPY api ./api
COPY migrations ./migrations
COPY docker/entrypoint.sh /entrypoint.sh

ENV PYTHONUNBUFFERED=1
EXPOSE 5000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "api.app:create_app()", "-b", "0.0.0.0:5000", "--workers", "2", "--access-logfile", "-"]
