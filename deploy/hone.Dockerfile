# The Hone service and its web UI, with the office tools the demo build runs.

FROM node:26.12.1-trixie-slim AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web/ ./
ARG HONE_WEB_BASE=/
RUN HONE_WEB_BASE="$HONE_WEB_BASE" npm run build

FROM python:3.13-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv
# Harbor drives the optimization sandboxes with the Docker CLI and Compose.
COPY --from=docker:29-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:29-cli /usr/local/libexec/docker/cli-plugins/ /usr/local/libexec/docker/cli-plugins/
RUN apt-get update \
 && apt-get install -y --no-install-recommends git poppler-utils libreoffice-writer-nogui fonts-liberation \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project
COPY hone.yaml ./
COPY packages/ packages/
RUN uv sync --no-dev
COPY --from=web /web/dist apps/web/dist

RUN useradd --create-home --uid 1000 hone && install -d -o hone -g hone /data
USER hone
ENV PATH=/app/.venv/bin:$PATH \
    HONE_DATA_DIR=/data \
    HONE_PORT=8080
EXPOSE 8080
CMD ["uvicorn", "hone.api:app", "--host", "0.0.0.0", "--port", "8080"]
