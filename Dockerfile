FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /usr/local/bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY policies ./policies
COPY sim-harness/shared/field_registry.json ./sim-harness/shared/field_registry.json
RUN uv sync --frozen --no-dev
ENV UW_DB_PATH=/app/data/uwagent.db
EXPOSE 8090
CMD ["uv", "run", "--no-dev", "uwagent", "serve", "--host", "0.0.0.0", "--port", "8090"]
