# syntax=docker/dockerfile:1

# Use official Python image with uv pre-installed
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies and tools needed for development
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    gnupg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv@sha256:e590846f4776907b254ac0f44b5b380347af5d90d668138ca7938d1b0c2f98d3 /uv /usr/local/bin/uv
COPY --from=ghcr.io/astral-sh/uv@sha256:e590846f4776907b254ac0f44b5b380347af5d90d668138ca7938d1b0c2f98d3 /uvx /usr/local/bin/uvx

WORKDIR /workspaces/chronos-graph

# Set up the default user (VS Code will use this)
RUN groupadd -g 1000 vscode && \
    useradd -m -u 1000 -g vscode -s /bin/bash vscode
USER vscode

# Set up shell initialization for uv
RUN echo 'eval "$(uv generate-shell-completion bash)"' >> ~/.bashrc 2>/dev/null || true

# Default to bash
SHELL ["/bin/bash", "-c"]

# Default command (can be overridden in devcontainer.json)
CMD ["bash"]
