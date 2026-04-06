FROM python:3.13-slim-bookworm

WORKDIR /app

# System deps for lxml
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libxml2-dev libxslt-dev && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
COPY tests/ ./tests/

# Install the project
RUN uv pip install --system --no-cache ".[dev]"

# Data directory for SQLite
RUN mkdir -p /data
ENV DEAL_HUNTER_DB_PATH=/data/deals.db

ENTRYPOINT ["deal-hunter"]
CMD ["version"]
