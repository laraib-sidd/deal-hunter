FROM python:3.13-slim-bookworm AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libxml2-dev libxslt-dev && \
    rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./
COPY src/ ./src/

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy
RUN uv venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN uv pip install --no-cache "."

FROM python:3.13-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 libxslt1.1 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 1000 dealhunter && \
    mkdir -p /data && \
    chown dealhunter:dealhunter /data

USER dealhunter

ENV DEAL_HUNTER_DB_PATH=/data/deals.db

ENTRYPOINT ["deal-hunter"]
CMD ["version"]
