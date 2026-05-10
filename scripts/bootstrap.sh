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
MCP_METHOD="python"
UV_FROM=""
GRAPH_ENABLED=true  # bootstrap.sh では利便性のためデフォルトで有効（アプリデフォルトは false）
POSTGRES_SSL=false
CACHE_BACKEND=""

# Track which flags were explicitly set to allow overwriting .env
EXPLICIT_FLAGS=""

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --backend)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --backend requires a value (sqlite|postgres)"; exit 1; fi
            BACKEND="$2"; EXPLICIT_FLAGS="$EXPLICIT_FLAGS STORAGE_BACKEND"; shift ;;
        --embedding)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --embedding requires a value (openai|litellm|local|custom)"; exit 1; fi
            EMBEDDING_PROVIDER="$2"; EXPLICIT_FLAGS="$EXPLICIT_FLAGS EMBEDDING_PROVIDER"; shift ;;
        --skip-tests) SKIP_TESTS=true ;;
        --ssl) POSTGRES_SSL=true; EXPLICIT_FLAGS="$EXPLICIT_FLAGS POSTGRES_SSL" ;;
        --mcp-output)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --mcp-output requires a value (claude|cursor|generic)"; exit 1; fi
            MCP_OUTPUT="$2"; shift ;;
        --mcp-method)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --mcp-method requires a value (python|uv|uvx)"; exit 1; fi
            MCP_METHOD="$2"
            if [[ "$MCP_METHOD" != "python" && "$MCP_METHOD" != "uv" && "$MCP_METHOD" != "uvx" ]]; then
                echo "Error: --mcp-method must be 'python', 'uv', or 'uvx'"
                exit 1
            fi
            shift ;;
        --uv-from)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --uv-from requires a value"; exit 1; fi
            UV_FROM="$2"; shift ;;
        --graph)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --graph requires a value (true|false)"; exit 1; fi
            GRAPH_ENABLED="$2"; EXPLICIT_FLAGS="$EXPLICIT_FLAGS GRAPH_ENABLED"; shift ;;
        -h|--help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  --backend [sqlite|postgres]      Set storage backend (default: sqlite)"
            echo "  --embedding [openai|litellm|local|custom] Set embedding provider (default: openai)"
            echo "  --skip-tests                      Skip running unit tests"
            echo "  --ssl                             Enable SSL for PostgreSQL (default: false)"
            echo "  --mcp-output [claude|cursor|generic] Set MCP configuration output format (default: generic)"
            echo "  --mcp-method [python|uv|uvx]         Set MCP activation method (default: python)"
            echo "  --uv-from [source]                Set source for uvx (e.g. git URL or PyPI package)"
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

# Detect OS for portable sed -i
if [[ "$OSTYPE" == "darwin"* ]]; then
    SED_INPLACE=(sed -i '')
else
    SED_INPLACE=(sed -i)
fi

echo -e "${BLUE}Starting ChronosGraph bootstrap process...${NC}"
echo -e "${BLUE}Backend: ${BACKEND}, Embedding: ${EMBEDDING_PROVIDER}, Skip Tests: ${SKIP_TESTS}, MCP Output: ${MCP_OUTPUT}, MCP Method: ${MCP_METHOD}, Graph: ${GRAPH_ENABLED}${NC}"

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

ENV_JUST_CREATED=false
if [ ! -f .env ]; then
    echo -e "${GREEN}Creating .env from .env.example...${NC}"
    cp .env.example .env
    ENV_JUST_CREATED=true
fi

# Update .env variables
for VAR in "STORAGE_BACKEND" "EMBEDDING_PROVIDER" "GRAPH_ENABLED" "POSTGRES_SSL"; do
    case $VAR in
        STORAGE_BACKEND) VAL=$BACKEND; EXPLICIT_VAR="STORAGE_BACKEND" ;;
        EMBEDDING_PROVIDER) VAL=$EMBEDDING_PROVIDER; EXPLICIT_VAR="EMBEDDING_PROVIDER" ;;
        GRAPH_ENABLED) VAL=$GRAPH_ENABLED; EXPLICIT_VAR="GRAPH_ENABLED" ;;
        POSTGRES_SSL) VAL=$POSTGRES_SSL; EXPLICIT_VAR="POSTGRES_SSL" ;;
    esac

    # Only update if the variable doesn't exist OR if it's different from the default
    # This prevents overwriting user-defined values in .env when re-running without flags.
    if grep -q "^$VAR=" .env; then
        CURRENT_VAL=$(grep "^$VAR=" .env | cut -d'=' -f2)
        if [[ "$CURRENT_VAL" != "$VAL" ]]; then
            # Only override if the flag was explicitly passed in the command line
            # OR if we just created the .env file (to ensure defaults are applied)
            if [[ "$EXPLICIT_FLAGS" == *"$EXPLICIT_VAR"* || "$ENV_JUST_CREATED" == "true" ]]; then
                echo -e "${BLUE}Updating $VAR in .env: $CURRENT_VAL -> $VAL${NC}"
                "${SED_INPLACE[@]}" "s/^$VAR=.*/$VAR=$VAL/" .env
            fi
        fi
    else
        echo "$VAR=$VAL" >> .env
    fi
done

echo -e "${BLUE}NOTE: Please edit .env to add your API keys (e.g., OPENAI_API_KEY).${NC}"

# 3. Verification
if [ "$SKIP_TESTS" = "false" ]; then
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

GEN_CONFIG_ARGS=("scripts/generate_config.py" "--backend" "$BACKEND" "--embedding" "$EMBEDDING_PROVIDER" "--graph" "$GRAPH_ENABLED" "--output" "$MCP_OUTPUT" "--method" "$MCP_METHOD")
if [ "$POSTGRES_SSL" = "true" ]; then
    GEN_CONFIG_ARGS+=("--ssl")
fi
if [[ -n "$CACHE_BACKEND" ]]; then
    GEN_CONFIG_ARGS+=("--cache" "$CACHE_BACKEND")
fi
if [[ -n "$UV_FROM" ]]; then
    GEN_CONFIG_ARGS+=("--uv-from" "$UV_FROM")
fi

if command -v uv &> /dev/null; then
    GEN_CONFIG_CMD=(uv run python "${GEN_CONFIG_ARGS[@]}")
else
    GEN_CONFIG_CMD=(python "${GEN_CONFIG_ARGS[@]}")
fi

[[ "${VERBOSE:-false}" == "true" ]] && echo -e "Debug: Executing ${GEN_CONFIG_CMD[*]}"

# Generate config and check for success + non-empty file in one step
if "${GEN_CONFIG_CMD[@]}" > "$TMP_CONFIG" && [ -s "$TMP_CONFIG" ]; then
    mv "$TMP_CONFIG" mcp_config.json
    echo -e "${GREEN}mcp_config.json generated successfully.${NC}"
else
    echo -e "\033[0;31mError: Failed to generate MCP configuration.\033[0m"
    exit 1
fi

# 5. Agent Instruction Guidance (Optional)
NEXT_STEPS_MSG="
To allow your AI agent to save memories autonomously, you need to add instructions.
Since this project is often shared with a team, ${BLUE}DO NOT${NC} append these rules
to project-root files (like .cursorrules) if you don't want to affect others.

Recommended: Add the content of ${BLUE}docs/agent-prompts/memory-save-system-prompt.md${NC}
to your ${GREEN}GLOBAL${NC} configuration:
- ${BLUE}Gemini CLI:${NC}  Append to ${GREEN}~/.gemini/GEMINI.md${NC}
- ${BLUE}Cursor:${NC}      Copy to ${GREEN}Settings > General > Rules for AI${NC}
- ${BLUE}Claude Code:${NC} Append to ${GREEN}~/.clauderules${NC}

Next steps:
1. Edit .env if you haven't already.
2. Use mcp_config.json to configure your MCP client (Claude Desktop/Cursor).
3. ${BLUE}IMPORTANT:${NC} To enable autonomous memory saving, add the content of
   ${BLUE}docs/agent-prompts/memory-save-system-prompt.md${NC} to your ${GREEN}GLOBAL${NC} settings
   (e.g., ~/.gemini/GEMINI.md for Gemini CLI or Cursor Settings)."

echo -e "\n${BLUE}Final Step: Enabling Autonomous Memory${NC}"
echo -e "$NEXT_STEPS_MSG"

echo -e "\n${GREEN}Bootstrap complete!${NC}"

if [[ "$MCP_METHOD" == "uvx" ]]; then
    echo -e "4. Start the server with: ${BLUE}uv tool run context-store${NC}"
elif [[ "$MCP_METHOD" == "uv" ]]; then
    echo -e "4. Start the server with: ${BLUE}uv run context-store${NC}"
else
    echo -e "4. Start the server with: ${BLUE}python -m context_store${NC}"
fi
