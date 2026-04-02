# syntax=docker/dockerfile:1

# Use official Python image with uv pre-installed
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1

# Install system dependencies and tools needed for development
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
ARG UV_VERSION=0.4.0
RUN curl -LsSf https://astral.sh/uv/uv-${UV_VERSION}-x86_64-unknown-linux-musl.tar.gz | tar xzf - -C /usr/local/bin && \
    mv /usr/local/bin/uv-${UV_VERSION}-x86_64-unknown-linux-musl/uv /usr/local/bin/uv && \
    mv /usr/local/bin/uv-${UV_VERSION}-x86_64-unknown-linux-musl/uvx /usr/local/bin/uvx && \
    rm -rf /usr/local/bin/uv-${UV_VERSION}-x86_64-unknown-linux-musl

# Install the project dependencies using uv
WORKDIR /workspaces/chronos-graph

# Copy dependency files first for better caching
COPY pyproject.toml uv.lock ./

# Install dependencies with uv (faster than pip)
RUN uv sync --frozen --no-install-project

# Copy source code
COPY src/ src/
COPY tests/ tests/

# Install the project in editable mode with all dev dependencies
RUN uv sync --frozen --all-extras

# Set up the default user (VS Code will use this)
USER vscode

# Set up shell initialization for uv
RUN echo 'eval "$(uv generate-shell-completion bash)"' >> ~/.bashrc 2>/dev/null || true

# Default to bash
SHELL ["/bin/bash", "-c"]

# Default command (can be overridden in devcontainer.json)
CMD ["bash"]
