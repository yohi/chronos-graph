#!/bin/bash
set -e

# Ensure the script is run from the project root
if [ ! -f "pyproject.toml" ]; then
    echo -e "\033[0;31mError: Please run this script from the project root directory.\033[0m" >&2
    exit 2
fi

# Default options
BACKEND="sqlite"
EMBEDDING_PROVIDER="openai"
SKIP_TESTS=false
MCP_OUTPUT="generic"
GRAPH_ENABLED=true

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --backend) BACKEND="$2"; shift ;;
        --embedding) EMBEDDING_PROVIDER="$2"; shift ;;
        --skip-tests) SKIP_TESTS=true ;;
        --mcp-output) MCP_OUTPUT="$2"; shift ;;
        --graph) GRAPH_ENABLED="$2"; shift ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  --backend [sqlite|postgres]      Set storage backend (default: sqlite)"
            echo "  --embedding [openai|litellm|local|custom] Set embedding provider (default: openai)"
            echo "  --skip-tests                      Skip running unit tests"
            echo "  --mcp-output [claude|cursor|generic] Set MCP configuration output format (default: generic)"
            echo "  --graph [true|false]             Enable/disable graph features (default: true)"
            echo "  -h, --help                        Show this help message"
            exit 0
            ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}Starting ChronosGraph bootstrap process...${NC}"
echo -e "${BLUE}Backend: ${BACKEND}, Embedding: ${EMBEDDING_PROVIDER}, Skip Tests: ${SKIP_TESTS}, MCP Output: ${MCP_OUTPUT}, Graph: ${GRAPH_ENABLED}${NC}"

# 1. Dependency Resolution
if command -v uv &> /dev/null; then
    echo -e "${GREEN}Using uv for dependency resolution...${NC}"
    uv sync --all-extras
else
    echo -e "${GREEN}uv not found, falling back to pip...${NC}"
    pip install -e ".[all]"
fi

# 2. Environment Configuration
case $EMBEDDING_PROVIDER in
    local) EMBEDDING_PROVIDER="local-model" ;;
    custom) EMBEDDING_PROVIDER="custom-api" ;;
esac

if [ ! -f .env ]; then
    echo -e "${GREEN}Creating .env from .env.example...${NC}"
    cp .env.example .env
fi

# Update .env variables regardless of file creation
for VAR in "STORAGE_BACKEND" "EMBEDDING_PROVIDER" "GRAPH_ENABLED"; do
    case $VAR in
        STORAGE_BACKEND) VAL=$BACKEND ;;
        EMBEDDING_PROVIDER) VAL=$EMBEDDING_PROVIDER ;;
        GRAPH_ENABLED) VAL=$GRAPH_ENABLED ;;
    esac
    
    if grep -q "^$VAR=" .env; then
        sed -i "s/^$VAR=.*/$VAR=$VAL/" .env
    else
        echo "$VAR=$VAL" >> .env
    fi
done

echo -e "${BLUE}NOTE: Please edit .env to add your API keys (e.g., OPENAI_API_KEY).${NC}"

# 3. Verification
if [ "$SKIP_TESTS" = false ]; then
    echo -e "${BLUE}Running unit tests to verify installation...${NC}"
    if command -v uv &> /dev/null; then
        uv run pytest tests/unit/ -v
    else
        python -m pytest tests/unit/ -v
    fi
else
    echo -e "${BLUE}Skipping unit tests as requested.${NC}"
fi

# 4. MCP Configuration Generation
echo -e "${BLUE}Generating MCP configuration for ${MCP_OUTPUT}...${NC}"
TMP_CONFIG=$(mktemp)
trap 'rm -f "$TMP_CONFIG"' EXIT

GEN_CONFIG_CMD="python scripts/generate_config.py --backend $BACKEND --embedding $EMBEDDING_PROVIDER --graph $GRAPH_ENABLED --output $MCP_OUTPUT"
echo -e "Debug: Executing $GEN_CONFIG_CMD"
if command -v uv &> /dev/null; then
    GEN_CONFIG_CMD="uv run $GEN_CONFIG_CMD"
fi

# Generate config and check for success + non-empty file in one step
if $GEN_CONFIG_CMD > "$TMP_CONFIG" && [ -s "$TMP_CONFIG" ]; then
    mv "$TMP_CONFIG" mcp_config.json
    echo -e "${GREEN}mcp_config.json generated successfully.${NC}"
else
    echo -e "\033[0;31mError: Failed to generate MCP configuration.\033[0m"
    exit 1
fi

echo -e "${GREEN}Bootstrap complete!${NC}"
echo -e "Next steps:"
echo -e "1. Edit .env if you haven't already."
echo -e "2. Use mcp_config.json to configure your MCP client (Claude Desktop/Cursor)."
echo -e "3. Start the server with: ${BLUE}python -m context_store${NC}"
