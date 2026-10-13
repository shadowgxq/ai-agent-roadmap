FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
COPY support-agent/pyproject.toml support-agent/uv.lock ./
COPY support-agent/src ./src
COPY support-agent/alembic.ini ./alembic.ini
COPY support-agent/migrations ./migrations
COPY support-agent/evals ./evals
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
RUN useradd --uid 10001 --create-home appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
CMD ["uvicorn", "support_agent.application.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
