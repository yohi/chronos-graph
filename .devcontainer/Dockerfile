# syntax=docker/dockerfile:1

# Use official Python image with uv pre-installed
# Use bookworm specifically to avoid compatibility issues with devcontainer features on trixie
FROM python:3.12-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_HTTP_TIMEOUT=1800

# Install system dependencies and tools needed for development
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast package management
COPY --from=ghcr.io/astral-sh/uv:0.4.0 /uv /usr/local/bin/uv
COPY --from=ghcr.io/astral-sh/uv:0.4.0 /uvx /usr/local/bin/uvx

# Install the project dependencies using uv
WORKDIR /workspaces/chronos-graph

# Copy dependency files and source code for installation
COPY pyproject.toml uv.lock ./
COPY src/ src/
COPY tests/ tests/

# Codacy: Synchronize dependencies during build instead of runtime for predictability.
# We use --frozen to ensure it matches the lockfile exactly.
# This single sync handles essential dependencies. 
# We skip --all-extras here to avoid downloading massive NVIDIA/PyTorch packages (GBs) during build.
RUN uv sync --frozen

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
