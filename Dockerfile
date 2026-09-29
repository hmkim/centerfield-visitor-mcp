# Remote deployment image (streamable HTTP on 0.0.0.0:8000/mcp).
# Build:  docker build --platform linux/arm64 -t centerfield-visitor-mcp .
# Run:    docker run --rm -p 8000:8000 -e CF_COMPANY_NAME=... -e CF_PERSON_IN_CHARGE_MOBILE=... centerfield-visitor-mcp
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY centerfield_visitor_mcp ./centerfield_visitor_mcp
RUN uv sync --frozen --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH" \
    CF_TRANSPORT=streamable-http \
    CF_HTTP_HOST=0.0.0.0 \
    CF_HTTP_PORT=8000 \
    CF_HTTP_PATH=/mcp \
    CF_BULK_MAX_VISITORS=10

# Non-root runtime user
RUN useradd --create-home --uid 10001 mcp
USER mcp

EXPOSE 8000
CMD ["centerfield-visitor-mcp"]
