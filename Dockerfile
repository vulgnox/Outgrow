FROM python:3.12-slim

# OUTGROW itself is stdlib-only Python + SQLite. Litestream streams the SQLite file to a free
# S3-compatible bucket so the data survives Render's ephemeral disk (restarts, redeploys, spin-downs).
ARG LITESTREAM_VERSION=0.3.13
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.tar.gz" \
    | tar -xz -C /usr/local/bin litestream

WORKDIR /app
COPY server.py /app/server.py
COPY static /app/static
COPY deploy/litestream.yml /app/deploy/litestream.yml
COPY deploy/render-start.sh /app/deploy/render-start.sh
COPY deploy/ghsync.py /app/deploy/ghsync.py
RUN chmod +x /app/deploy/render-start.sh && mkdir -p /app/data

# TZ is a POSIX string so no tzdata package is needed: streak day rolls over at 3 AM IST.
ENV OUTGROW_BIND=0.0.0.0 \
    OUTGROW_DB=/app/data/outgrow.db \
    TZ=IST-5:30 \
    PYTHONUNBUFFERED=1

CMD ["/app/deploy/render-start.sh"]
