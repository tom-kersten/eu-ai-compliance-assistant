# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.13.0-python3.12-trixie-slim AS base

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home --shell /bin/bash app \
    && mkdir -p /opt/venv \
    && chown -R app:app /app /opt/venv

COPY --chown=app:app pyproject.toml uv.lock ./

FROM base AS runtime

USER app
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --frozen --no-dev --no-install-project

COPY --chown=app:app src ./src

USER app
EXPOSE 8501
CMD ["streamlit", "run", "src/ui/app.py", "--server.address", "0.0.0.0", "--server.port", "8501"]

FROM base AS dev

USER app
RUN --mount=type=cache,target=/home/app/.cache/uv,uid=1000,gid=1000 \
    uv sync --frozen --no-install-project

COPY --chown=app:app src ./src
COPY --chown=app:app tests ./tests

USER app
EXPOSE 8501
CMD ["streamlit", "run", "src/ui/app.py", "--server.address", "0.0.0.0", "--server.port", "8501"]
