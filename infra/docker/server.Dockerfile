FROM python:3.11.18-slim-bookworm@sha256:94a8fee35252d06ab75856f15f12c7bae67b10e8a6da93c7fded82b2610926cd AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /bin/uv
WORKDIR /app
COPY apps/server/pyproject.toml apps/server/uv.lock ./
COPY apps/server/src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.11.18-slim-bookworm@sha256:94a8fee35252d06ab75856f15f12c7bae67b10e8a6da93c7fded82b2610926cd AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY apps/server/alembic.ini /app/alembic.ini
COPY apps/server/migrations /app/migrations
USER 10001:10001
EXPOSE 8000 8081
CMD ["uvicorn", "protohub.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]

FROM build AS checks
RUN uv sync --locked --no-editable
ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /repo
CMD ["python", "--version"]
