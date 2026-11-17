# syntax=docker/dockerfile:1
# Remote deployment image: `lamarzocco-mcp serve --http` behind single-user OAuth.
FROM python:3.13-slim AS build
# git only while mcp-owner-auth is resolved from its git repository (see [tool.uv.sources])
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9.2 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --extra remote --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --extra remote --no-editable

FROM python:3.13-slim
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data && chown app:app /data && chmod 700 /data
COPY --from=build --chown=root:root /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    LAMARZOCCO_MCP_STATE_DIR=/data \
    LAMARZOCCO_CREDENTIALS_FILE=/run/secrets/lamarzocco_credentials
USER app
WORKDIR /home/app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4)"]
ENTRYPOINT ["lamarzocco-mcp"]
CMD ["serve", "--http", "--host", "0.0.0.0", "--port", "8000"]
