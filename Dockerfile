# Remote deployment image (streamable HTTP on the container network at 0.0.0.0:8000/mcp).
# Build:  docker build --platform linux/arm64 -t centerfield-visitor-mcp .
# Local run: docker run --rm -p 127.0.0.1:8000:8000 --env-file /absolute/path/to/.env centerfield-visitor-mcp
FROM public.ecr.aws/docker/library/python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.13.7@sha256:96f40d3904aad8d0bd010539001d36c8e2188b981e1334471a90c4a1d93bb490 /uv /uvx /bin/

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
