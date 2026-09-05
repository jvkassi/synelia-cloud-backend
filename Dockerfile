FROM python:3.13-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -sSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc \
    && chmod 755 /usr/local/bin/mc \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app/.venv
COPY pyproject.toml uv.lock ./
COPY apps ./apps
COPY packages ./packages
COPY tools ./tools
RUN uv sync --frozen --no-dev
RUN useradd -r -u 1001 synelia && chown -R synelia /app
USER synelia
ENV PATH="/app/.venv/bin:$PATH" PORT=4000
EXPOSE 4000
ENTRYPOINT ["synelia"]
CMD ["api"]
