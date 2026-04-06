#!/bin/bash
set -e

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Starting ChronosGraph bootstrap process...${NC}"

# 1. Dependency Resolution
if command -v uv &> /dev/null; then
    echo -e "${GREEN}Using uv for dependency resolution...${NC}"
    uv sync --all-extras
else
    echo -e "${GREEN}uv not found, falling back to pip...${NC}"
    pip install -e ".[dev]"
fi

# 2. Environment Configuration
if [ ! -f .env ]; then
    echo -e "${GREEN}Creating .env from .env.example...${NC}"
    cp .env.example .env
    echo -e "${BLUE}NOTE: Please edit .env to add your API keys (e.g., OPENAI_API_KEY).${NC}"
else
    echo -e "${BLUE}.env already exists, skipping copy.${NC}"
fi

# 3. Verification
echo -e "${BLUE}Running unit tests to verify installation...${NC}"
if command -v uv &> /dev/null; then
    uv run pytest tests/unit/ -v
else
    python -m pytest tests/unit/ -v
fi

# 4. MCP Configuration Generation
echo -e "${BLUE}Generating MCP configuration...${NC}"
if command -v uv &> /dev/null; then
    uv run python scripts/generate_config.py > mcp_config.json
else
    python scripts/generate_config.py > mcp_config.json
fi

echo -e "${GREEN}Bootstrap complete!${NC}"
echo -e "Next steps:"
echo -e "1. Edit .env if you haven't already."
echo -e "2. Use mcp_config.json to configure your MCP client (Claude Desktop/Cursor)."
echo -e "3. Start the server with: ${BLUE}python -m context_store${NC}"
