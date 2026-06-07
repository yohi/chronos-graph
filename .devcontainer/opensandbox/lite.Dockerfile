# syntax=docker/dockerfile:1
FROM node:22.11.0-slim AS node_source
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/tmp/.venv

COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uv /usr/local/bin/uv
COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uvx /usr/local/bin/uvx

# Copy Node.js from node_source instead of downloading via curl | bash
COPY --from=node_source /usr/local/bin/node /usr/local/bin/node
COPY --from=node_source /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm && \
    ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && corepack enable && corepack prepare pnpm@9.15.4 --activate \
    && rm -rf /var/lib/apt/lists/*

# Validate tools as root
RUN uv --version && uvx --version && node -v && npm -v && pnpm -v

RUN groupadd -g 1000 sandbox && \
    useradd -m -u 1000 -g sandbox -s /bin/bash sandbox
USER sandbox

# Validate tools as sandbox user to check permissions and symlinks
RUN uv --version && uvx --version && node -v && npm -v && pnpm -v

WORKDIR /workspace
CMD ["bash"]
