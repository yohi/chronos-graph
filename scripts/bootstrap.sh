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

# New options
TYPE="mcp" # mcp | hook
MODE="production" # production | dry-run
SOURCE="local" # remote | local
INGESTION_MODE="selective" # selective | all
AGENTS="" # comma-separated list of agents
EVALUATOR_MODEL=""
DB_HOST=""
DB_PORT=""
DB_NAME=""
DB_USER=""
NEO4J_URI=""
NEO4J_USER=""
REDIS_URL=""
EMBEDDING_MODEL=""
GRAPH_SYNC_MODE="sync" # sync | async_outbox

# Track which flags were explicitly set to allow overwriting .env
EXPLICIT_FLAGS=""

# Parse arguments
while [[ "$#" -gt 0 ]]; do
    case $1 in
        --backend)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --backend requires a value (sqlite|postgres|supabase)"; exit 1; fi
            BACKEND="$2"
            if [[ "$BACKEND" != "sqlite" && "$BACKEND" != "postgres" && "$BACKEND" != "supabase" ]]; then
                echo "Error: --backend must be 'sqlite', 'postgres', or 'supabase'"
                exit 1
            fi
            EXPLICIT_FLAGS="$EXPLICIT_FLAGS STORAGE_BACKEND"; shift ;;
        --embedding)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --embedding requires a value (openai|litellm|local|local-model|custom|custom-api)"; exit 1; fi
            EMBEDDING_PROVIDER="$2"
            if [[ "$EMBEDDING_PROVIDER" != "openai" && "$EMBEDDING_PROVIDER" != "litellm" && "$EMBEDDING_PROVIDER" != "local" && "$EMBEDDING_PROVIDER" != "local-model" && "$EMBEDDING_PROVIDER" != "custom" && "$EMBEDDING_PROVIDER" != "custom-api" ]]; then
                echo "Error: --embedding must be 'openai', 'litellm', 'local', 'local-model', 'custom', or 'custom-api'"
                exit 1
            fi
            EXPLICIT_FLAGS="$EXPLICIT_FLAGS EMBEDDING_PROVIDER"; shift ;;
        --skip-tests) SKIP_TESTS=true ;;
        --ssl) POSTGRES_SSL=true; POSTGRES_SSL_NO_VERIFY=false; POSTGRES_STATEMENT_CACHE_SIZE=256; EXPLICIT_FLAGS="$EXPLICIT_FLAGS POSTGRES_SSL POSTGRES_SSL_NO_VERIFY POSTGRES_STATEMENT_CACHE_SIZE" ;;
        --ssl-no-verify) POSTGRES_SSL=true; POSTGRES_SSL_NO_VERIFY=true; POSTGRES_STATEMENT_CACHE_SIZE=0; EXPLICIT_FLAGS="$EXPLICIT_FLAGS POSTGRES_SSL POSTGRES_SSL_NO_VERIFY POSTGRES_STATEMENT_CACHE_SIZE" ;;
        --cache)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --cache requires a value (inmemory|redis)"; exit 1; fi
            CACHE_BACKEND="$2"
            if [[ "$CACHE_BACKEND" != "inmemory" && "$CACHE_BACKEND" != "redis" ]]; then
                echo "Error: --cache must be 'inmemory' or 'redis'"
                exit 1
            fi
            EXPLICIT_FLAGS="$EXPLICIT_FLAGS CACHE_BACKEND"; shift ;;
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
            GRAPH_ENABLED="$2"
            if [[ "$GRAPH_ENABLED" != "true" && "$GRAPH_ENABLED" != "false" ]]; then
                echo "Error: --graph must be 'true' or 'false'"
                exit 1
            fi
            EXPLICIT_FLAGS="$EXPLICIT_FLAGS GRAPH_ENABLED"; shift ;;
        
        # New options
        --type)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --type requires a value (mcp|hook)"; exit 1; fi
            TYPE="$2"
            if [[ "$TYPE" != "mcp" && "$TYPE" != "hook" ]]; then
                echo "Error: --type must be 'mcp' or 'hook'"
                exit 1
            fi
            shift ;;
        --mode)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --mode requires a value (production|dry-run)"; exit 1; fi
            MODE="$2"
            if [[ "$MODE" != "production" && "$MODE" != "dry-run" ]]; then
                echo "Error: --mode must be 'production' or 'dry-run'"
                exit 1
            fi
            shift ;;
        --source)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --source requires a value (remote|local)"; exit 1; fi
            SOURCE="$2"
            if [[ "$SOURCE" != "remote" && "$SOURCE" != "local" ]]; then
                echo "Error: --source must be 'remote' or 'local'"
                exit 1
            fi
            shift ;;
        --ingestion-mode)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --ingestion-mode requires a value (all|selective)"; exit 1; fi
            INGESTION_MODE="$2"
            if [[ "$INGESTION_MODE" != "all" && "$INGESTION_MODE" != "selective" ]]; then
                echo "Error: --ingestion-mode must be 'all' or 'selective'"
                exit 1
            fi
            EXPLICIT_FLAGS="$EXPLICIT_FLAGS CHRONOS_INGESTION_MODE"
            shift ;;
        --agents)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --agents requires a value"; exit 1; fi
            AGENTS="$2"; shift ;;
        --evaluator-model)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --evaluator-model requires a value"; exit 1; fi
            EVALUATOR_MODEL="$2"; shift ;;
        --db-host)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --db-host requires a value"; exit 1; fi
            DB_HOST="$2"; shift ;;
        --db-port)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --db-port requires a value"; exit 1; fi
            DB_PORT="$2"; shift ;;
        --db-name)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --db-name requires a value"; exit 1; fi
            DB_NAME="$2"; shift ;;
        --db-user)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --db-user requires a value"; exit 1; fi
            DB_USER="$2"; shift ;;
        --neo4j-uri)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --neo4j-uri requires a value"; exit 1; fi
            NEO4J_URI="$2"; shift ;;
        --neo4j-user)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --neo4j-user requires a value"; exit 1; fi
            NEO4J_USER="$2"; shift ;;
        --redis-url)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --redis-url requires a value"; exit 1; fi
            REDIS_URL="$2"; shift ;;
        --embedding-model)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --embedding-model requires a value"; exit 1; fi
            EMBEDDING_MODEL="$2"; shift ;;
        --graph-sync-mode)
            if [[ -z "$2" || "$2" == -* ]]; then echo "Error: --graph-sync-mode requires a value (sync|async_outbox)"; exit 1; fi
            GRAPH_SYNC_MODE="$2"
            if [[ "$GRAPH_SYNC_MODE" != "sync" && "$GRAPH_SYNC_MODE" != "async_outbox" ]]; then
                echo "Error: --graph-sync-mode must be 'sync' or 'async_outbox'"
                exit 1
            fi
            EXPLICIT_FLAGS="$EXPLICIT_FLAGS GRAPH_SYNC_MODE"
            shift ;;

        -h|--help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  --backend [sqlite|postgres|supabase] Set storage backend (default: sqlite)"
            echo "  --embedding [openai|litellm|local|local-model|custom|custom-api] Set embedding provider (default: openai)"
            echo "  --skip-tests                      Skip running unit tests"
            echo "  --ssl                             Enable SSL for PostgreSQL"
            echo "  --ssl-no-verify                   Enable SSL without certificate verification (for Supabase/pgBouncer)"
            echo "  --cache [inmemory|redis]          Set cache backend (default: inmemory)"
            echo "  --mcp-output [claude|cursor|generic] Set MCP configuration output format (default: generic)"
            echo "  --mcp-method [python|uv|uvx]         Set MCP activation method (default: python)"
            echo "  --uv-from [source]                Set source for uvx (e.g. git URL or PyPI package)"
            echo "  --graph [true|false]             Enable/disable graph features (default: true)"
            echo "  --type [mcp|hook]                 Set setup target type (default: mcp)"
            echo "  --mode [production|dry-run]       Set execution mode (default: production)"
            echo "  --source [remote|local]           Set config source activation (default: local)"
            echo "  --ingestion-mode [all|selective]  Set memory ingestion mode (default: selective)"
            echo "  --agents [list]                   Comma-separated list of agents to configure hooks for"
            echo "  --evaluator-model [model]         Evaluator model name for hook setup"
            echo "  --db-host [host]                  Database host for postgres"
            echo "  --db-port [port]                  Database port for postgres"
            echo "  --db-name [name]                  Database name for postgres"
            echo "  --db-user [user]                  Database user for postgres"
            echo "  --neo4j-uri [uri]                 Neo4j connection URI"
            echo "  --neo4j-user [user]               Neo4j username"
            echo "  --redis-url [url]                 Redis connection URL"
            echo "  --embedding-model [model]         OpenAI/LiteLLM embedding model name"
            echo "  --graph-sync-mode [mode]          Set graph sync mode (sync|async_outbox)"
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

# Correlation validation auto-correction
if [ "$BACKEND" = "supabase" ] && [ "$GRAPH_ENABLED" = "true" ]; then
    if [ "$GRAPH_SYNC_MODE" != "async_outbox" ]; then
        echo -e "${BLUE}Supabase combined with graph_enabled=true requires async_outbox mode. Overriding graph_sync_mode to async_outbox.${NC}"
        GRAPH_SYNC_MODE="async_outbox"
    fi
fi

# Dry-run check
if [ "$MODE" = "dry-run" ]; then
    echo -e "${BLUE}[Dry-run Mode] Simulation of bootstrap process...${NC}"
    echo -e "Target Setup Type: ${TYPE}"
    echo -e "Backend: ${BACKEND}, Embedding: ${EMBEDDING_PROVIDER}, Graph: ${GRAPH_ENABLED}, Cache: ${CACHE_BACKEND}"
    if [ "$TYPE" = "mcp" ]; then
        echo -e "Source: ${SOURCE}, Ingestion Mode: ${INGESTION_MODE}, Graph Sync Mode: ${GRAPH_SYNC_MODE}"
    else
        echo -e "Evaluator Model: ${EVALUATOR_MODEL}"
    fi
    echo -e "Selected Agents for hook configuration: ${AGENTS}"
    echo -e "\nWould execute:"
    echo -e "1. Install dependencies (uv sync --all-extras)"
    echo -e "2. Configure .env with settings (uncomment/comment out blocks as needed)"
    if [[ -n "$DB_HOST" ]]; then echo -e "   - Set DB_HOST=$DB_HOST, DB_PORT=$DB_PORT, DB_NAME=$DB_NAME, DB_USER=$DB_USER"; fi
    if [[ -n "$NEO4J_URI" ]]; then echo -e "   - Set NEO4J_URI=$NEO4J_URI, NEO4J_USER=$NEO4J_USER"; fi
    if [[ -n "$REDIS_URL" ]]; then echo -e "   - Set REDIS_URL=$REDIS_URL"; fi
    if [[ -n "$EMBEDDING_MODEL" ]]; then echo -e "   - Set OpenAI/Embedding model to $EMBEDDING_MODEL"; fi
    if [[ -n "$EVALUATOR_MODEL" ]]; then echo -e "   - Set CHRONOS_EVALUATOR_MODEL=$EVALUATOR_MODEL"; fi
    echo -e "   - Set GRAPH_SYNC_MODE=$GRAPH_SYNC_MODE"
    echo -e "3. Run unit tests to verify installation (unless skip-tests is set)"
    if [ "$TYPE" = "mcp" ] && [ "$SOURCE" = "local" ]; then
        echo -e "4. Run connectivity check: uv run python scripts/check_connectivity.py"
    fi
    if [[ -n "$AGENTS" ]]; then
        echo -e "5. Configure Hook files for agents: ${AGENTS}"
        if [[ "$AGENTS" == *"opencode"* ]]; then
            echo -e "   - For OpenCode: Guide user to add '@yohi/opencode-plugin-chronos-gate' to global plugins"
        fi
        if [[ "$AGENTS" == *"claudecode"* || "$AGENTS" == *"codex"* || "$AGENTS" == *"antigravitycl"* || "$AGENTS" == *"cursorcli"* ]]; then
            if [ "$INGESTION_MODE" = "all" ] || [ "$TYPE" = "hook" ]; then
                echo -e "   - Create wrapper scripts in scripts/ for selected agents"
            fi
        fi
    fi
    if [ "$TYPE" = "hook" ]; then
        echo -e "6. Run hook verification command"
    fi
    echo -e "${GREEN}[Dry-run Mode] Simulation complete. No files were modified.${NC}"
    exit 0
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
    local|local-model) EMBEDDING_PROVIDER="local-model" ;;
    custom|custom-api) EMBEDDING_PROVIDER="custom-api" ;;
esac

ENV_JUST_CREATED=false
if [ ! -f .env ]; then
    echo -e "${GREEN}Creating .env from .env.example...${NC}"
    cp .env.example .env
    ENV_JUST_CREATED=true
fi

# Helper function to comment/uncomment block
modify_var_status() {
    local prefix=$1
    local action=$2 # "comment" or "uncomment"
    if [ "$action" = "comment" ]; then
        "${SED_INPLACE[@]}" "s/^\([[:space:]]*$prefix[A-Z0-9_]*=\)/# \1/" .env
    else
        "${SED_INPLACE[@]}" "s/^#[[:space:]]*\($prefix[A-Z0-9_]*=\)/\1/" .env
    fi
}

# Helper function to update config value
update_env_key() {
    local key=$1
    local val=$2
    if [[ -z "$val" ]]; then
        return
    fi
    if grep -q "^#[[:space:]]*$key=\|^$key=" .env; then
        local escaped_val
        escaped_val=$(printf '%s' "$val" | sed 's/[&/\]/\\&/g')
        "${SED_INPLACE[@]}" "s/^#[[:space:]]*$key=.*/$key=$escaped_val/; s/^$key=.*/$key=$escaped_val/" .env
    else
        echo "$key=$val" >> .env
    fi
}

# Comment/Uncomment blocks
if [ "$BACKEND" = "sqlite" ]; then
    modify_var_status "SQLITE_" "uncomment"
    modify_var_status "POSTGRES_" "comment"
    modify_var_status "SUPABASE_" "comment"
elif [ "$BACKEND" = "postgres" ]; then
    modify_var_status "POSTGRES_" "uncomment"
    modify_var_status "SQLITE_" "comment"
    modify_var_status "SUPABASE_" "comment"
elif [ "$BACKEND" = "supabase" ]; then
    modify_var_status "SUPABASE_" "uncomment"
    modify_var_status "SQLITE_" "comment"
    modify_var_status "POSTGRES_" "comment"
fi

if [ "$GRAPH_ENABLED" = "true" ] && { [ "$BACKEND" = "postgres" ] || [ "$BACKEND" = "supabase" ]; }; then
    modify_var_status "NEO4J_" "uncomment"
else
    modify_var_status "NEO4J_" "comment"
fi

if [ "$CACHE_BACKEND" = "redis" ]; then
    modify_var_status "REDIS_" "uncomment"
else
    modify_var_status "REDIS_" "comment"
fi

if [ "$EMBEDDING_PROVIDER" = "openai" ]; then
    modify_var_status "OPENAI_" "uncomment"
    modify_var_status "LOCAL_MODEL_" "comment"
    modify_var_status "LITELLM_" "comment"
    modify_var_status "CUSTOM_API_" "comment"
elif [ "$EMBEDDING_PROVIDER" = "local-model" ]; then
    modify_var_status "LOCAL_MODEL_" "uncomment"
    modify_var_status "OPENAI_" "comment"
    modify_var_status "LITELLM_" "comment"
    modify_var_status "CUSTOM_API_" "comment"
elif [ "$EMBEDDING_PROVIDER" = "litellm" ]; then
    modify_var_status "LITELLM_" "uncomment"
    modify_var_status "OPENAI_" "comment"
    modify_var_status "LOCAL_MODEL_" "comment"
    modify_var_status "CUSTOM_API_" "comment"
elif [ "$EMBEDDING_PROVIDER" = "custom-api" ]; then
    modify_var_status "CUSTOM_API_" "uncomment"
    modify_var_status "OPENAI_" "comment"
    modify_var_status "LOCAL_MODEL_" "comment"
    modify_var_status "LITELLM_" "comment"
fi

if [ "$TYPE" = "hook" ]; then
    modify_var_status "CHRONOS_EVALUATOR_" "uncomment"
else
    modify_var_status "CHRONOS_EVALUATOR_" "comment"
fi

if [ "$TYPE" = "hook" ] || [ "$INGESTION_MODE" = "all" ]; then
    modify_var_status "MCP_GATEWAY_" "uncomment"
    # pydantic-settings 向けにリスト型変数を JSON 配列形式に更新
    update_env_key "MCP_GATEWAY_UPSTREAM_COMMAND" '["python", "-m", "context_store"]'
    update_env_key "MCP_GATEWAY_UPSTREAM_ENV_PASSTHROUGH" '["OPENAI_API_KEY", "SQLITE_DB_PATH", "GRAPH_ENABLED", "EMBEDDING_PROVIDER", "CHRONOS_INGESTION_MODE"]'
    
    # 認証用のセキュアキーを自動ランダム生成（Pythonのsecretsモジュールを使用）
    SECURE_KEY=$(python -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(16))" 2>/dev/null)
    if [[ -z "$SECURE_KEY" ]]; then
        echo "Error: Python is required to generate a secure key for MCP_GATEWAY_API_KEYS_JSON. Install Python and retry." >&2
        exit 1
    fi
    update_env_key "MCP_GATEWAY_API_KEYS_JSON" "{\"default\": \"$SECURE_KEY\"}"
    update_env_key "MCP_GATEWAY_API_KEY" "$SECURE_KEY"
else
    modify_var_status "MCP_GATEWAY_" "comment"
fi

# Outbox configuration uncomment check
if [ "$GRAPH_SYNC_MODE" = "async_outbox" ]; then
    modify_var_status "OUTBOX_" "uncomment"
else
    modify_var_status "OUTBOX_" "comment"
fi

# Values update
if [ "$TYPE" = "mcp" ] || [ "$TYPE" = "hook" ] || [[ "$EXPLICIT_FLAGS" == *"STORAGE_BACKEND"* ]]; then update_env_key "STORAGE_BACKEND" "$BACKEND"; fi
if [ "$TYPE" = "mcp" ] || [ "$TYPE" = "hook" ] || [[ "$EXPLICIT_FLAGS" == *"EMBEDDING_PROVIDER"* ]]; then update_env_key "EMBEDDING_PROVIDER" "$EMBEDDING_PROVIDER"; fi
if [ "$TYPE" = "mcp" ] || [ "$TYPE" = "hook" ] || [[ "$EXPLICIT_FLAGS" == *"GRAPH_ENABLED"* ]]; then update_env_key "GRAPH_ENABLED" "$GRAPH_ENABLED"; fi
if [ "$TYPE" = "mcp" ] || [ "$TYPE" = "hook" ] || [[ "$EXPLICIT_FLAGS" == *"CACHE_BACKEND"* ]]; then update_env_key "CACHE_BACKEND" "$CACHE_BACKEND"; fi
if [ "$TYPE" = "mcp" ] || [ "$TYPE" = "hook" ] || [[ "$EXPLICIT_FLAGS" == *"CHRONOS_INGESTION_MODE"* ]]; then update_env_key "CHRONOS_INGESTION_MODE" "$INGESTION_MODE"; fi
if [ "$TYPE" = "mcp" ] || [ "$TYPE" = "hook" ] || [[ "$EXPLICIT_FLAGS" == *"GRAPH_SYNC_MODE"* ]]; then update_env_key "GRAPH_SYNC_MODE" "$GRAPH_SYNC_MODE"; fi

if [[ -n "$DB_HOST" ]]; then update_env_key "POSTGRES_HOST" "$DB_HOST"; fi
if [[ -n "$DB_PORT" ]]; then update_env_key "POSTGRES_PORT" "$DB_PORT"; fi
if [[ -n "$DB_NAME" ]]; then update_env_key "POSTGRES_DB" "$DB_NAME"; fi
if [[ -n "$DB_USER" ]]; then update_env_key "POSTGRES_USER" "$DB_USER"; fi

if [[ -n "$NEO4J_URI" ]]; then update_env_key "NEO4J_URI" "$NEO4J_URI"; fi
if [[ -n "$NEO4J_USER" ]]; then update_env_key "NEO4J_USER" "$NEO4J_USER"; fi

if [[ -n "$REDIS_URL" ]]; then update_env_key "REDIS_URL" "$REDIS_URL"; fi

if [[ -n "$EMBEDDING_MODEL" ]]; then
    if [ "$EMBEDDING_PROVIDER" = "litellm" ]; then
        update_env_key "LITELLM_MODEL" "$EMBEDDING_MODEL"
    elif [ "$EMBEDDING_PROVIDER" = "custom-api" ]; then
        update_env_key "CUSTOM_API_MODEL_NAME" "$EMBEDDING_MODEL"
    elif [ "$EMBEDDING_PROVIDER" = "openai" ]; then
        update_env_key "OPENAI_EMBEDDING_MODEL" "$EMBEDDING_MODEL"
    fi
fi

if [[ -n "$EVALUATOR_MODEL" ]]; then
    update_env_key "CHRONOS_EVALUATOR_MODEL" "$EVALUATOR_MODEL"
fi

if [ "$BACKEND" = "postgres" ]; then
    for VAR in "POSTGRES_SSL" "POSTGRES_SSL_NO_VERIFY" "POSTGRES_STATEMENT_CACHE_SIZE"; do
        case $VAR in
            POSTGRES_SSL) VAL=$POSTGRES_SSL; EXPLICIT_VAR="POSTGRES_SSL" ;;
            POSTGRES_SSL_NO_VERIFY) VAL=$POSTGRES_SSL_NO_VERIFY; EXPLICIT_VAR="POSTGRES_SSL_NO_VERIFY" ;;
            POSTGRES_STATEMENT_CACHE_SIZE) VAL=$POSTGRES_STATEMENT_CACHE_SIZE; EXPLICIT_VAR="POSTGRES_STATEMENT_CACHE_SIZE" ;;
        esac
        if [[ -z "$VAL" ]]; then continue; fi
        if grep -q "^#[[:space:]]*$VAR=\|^$VAR=" .env; then
            CURRENT_VAL=$(grep "^#[[:space:]]*$VAR=\|^$VAR=" .env | cut -d'=' -f2)
            if [[ "$CURRENT_VAL" != "$VAL" ]]; then
                if [[ "$EXPLICIT_FLAGS" == *"$EXPLICIT_VAR"* || "$ENV_JUST_CREATED" == "true" ]]; then
                    echo -e "${BLUE}Updating $VAR in .env: $CURRENT_VAL -> $VAL${NC}"
                    "${SED_INPLACE[@]}" "s/^#[[:space:]]*$VAR=.*/$VAR=$VAL/; s/^$VAR=.*/$VAR=$VAL/" .env
                fi
            fi
        else
            echo "$VAR=$VAL" >> .env
        fi
    done
fi

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
if [ "$TYPE" = "mcp" ]; then
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

    if "${GEN_CONFIG_CMD[@]}" > "$TMP_CONFIG" && [ -s "$TMP_CONFIG" ]; then
        mv "$TMP_CONFIG" mcp_config.json
        echo -e "${GREEN}mcp_config.json generated successfully.${NC}"
    else
        echo -e "\033[0;31mError: Failed to generate MCP configuration.\033[0m"
        exit 1
    fi
fi

# 5. Connection test
if [ "$TYPE" = "mcp" ] && [ "$SOURCE" = "local" ]; then
    echo -e "${BLUE}Running connection check...${NC}"
    if command -v uv &> /dev/null; then
        uv run python scripts/check_connectivity.py
    else
        python scripts/check_connectivity.py
    fi
fi

# 6. Hook configuration
if [[ -n "$AGENTS" ]]; then
    echo -e "${BLUE}Configuring hooks for agents: ${AGENTS}...${NC}"
    
    # 6.1 Turn hook setup
    if [ "$TYPE" = "mcp" ] && [ "$INGESTION_MODE" = "all" ]; then
        if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
            HOOK_FILE="scripts/chronos-turn-hook.cmd"
            cat << 'EOF' > "$HOOK_FILE"
@echo off
rem Auto-generated by bootstrap.sh
python "%~dp0\agent_turn_hook.py" %*
EOF
            echo -e "${GREEN}Generated $HOOK_FILE${NC}"
        else
            HOOK_FILE="scripts/chronos-turn-hook.sh"
            cat << 'EOF' > "$HOOK_FILE"
#!/usr/bin/env bash
# Auto-generated by bootstrap.sh
python "$(dirname "$0")/agent_turn_hook.py" "$@"
EOF
            chmod +x "$HOOK_FILE"
            echo -e "${GREEN}Generated $HOOK_FILE and granted execution permission.${NC}"
            ls -la "$HOOK_FILE"
        fi
    fi

    # 6.2 Evaluator hook setup
    if [ "$TYPE" = "hook" ]; then
        if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
            EVAL_HOOK_FILE="scripts/chronos-evaluator-hook.cmd"
            if [ "$SOURCE" = "remote" ]; then
                cat << 'EOF' > "$EVAL_HOOK_FILE"
@echo off
rem Auto-generated by bootstrap.sh
uvx --quiet --from "context-store-mcp[all] @ git+https://github.com/yohi/chronos-graph.git" chronos-mcp-gateway evaluate --json-io --policy-path "%CHRONOS_EVALUATOR_POLICY_PATH%"
EOF
            else
                cat << 'EOF' > "$EVAL_HOOK_FILE"
@echo off
rem Auto-generated by bootstrap.sh
where uv >nul 2>nul
if %ERRORLEVEL% equ 0 (
    uv --directory "%~dp0\.." run python -m mcp_gateway evaluate --json-io --policy-path "%CHRONOS_EVALUATOR_POLICY_PATH%"
) else (
    python -m mcp_gateway evaluate --json-io --policy-path "%CHRONOS_EVALUATOR_POLICY_PATH%"
)
EOF
            fi
            echo -e "${GREEN}Generated $EVAL_HOOK_FILE${NC}"
        else
            EVAL_HOOK_FILE="scripts/chronos-evaluator-hook.sh"
            if [ "$SOURCE" = "remote" ]; then
                cat << 'EOF' > "$EVAL_HOOK_FILE"
#!/usr/bin/env bash
# Auto-generated by bootstrap.sh
uvx --quiet --from "context-store-mcp[all] @ git+https://github.com/yohi/chronos-graph.git" \
  chronos-mcp-gateway evaluate \
  --json-io \
  --policy-path "${CHRONOS_EVALUATOR_POLICY_PATH:-$HOME/.config/chronos/intents.yaml}"
EOF
            else
                cat << 'EOF' > "$EVAL_HOOK_FILE"
#!/usr/bin/env bash
# Auto-generated by bootstrap.sh
if command -v uv &> /dev/null; then
  uv --directory "$(dirname "$0")/.." run python -m mcp_gateway evaluate \
    --json-io \
    --policy-path "${CHRONOS_EVALUATOR_POLICY_PATH:-$(dirname "$0")/../src/mcp_gateway/policies/intents.yaml}"
else
  python -m mcp_gateway evaluate \
    --json-io \
    --policy-path "${CHRONOS_EVALUATOR_POLICY_PATH:-$(dirname "$0")/../src/mcp_gateway/policies/intents.yaml}"
fi
EOF
            fi
            chmod +x "$EVAL_HOOK_FILE"
            echo -e "${GREEN}Generated $EVAL_HOOK_FILE and granted execution permission.${NC}"
            ls -la "$EVAL_HOOK_FILE"
        fi
    fi

    # 6.3 OpenCode specific plugin configuration
    if [[ "$AGENTS" == *"opencode"* ]]; then
        echo -e "${BLUE}Attempting to register OpenCode plugin...${NC}"
        OPCODE_CONFIG_DIR="$HOME/.config/opencode"
        if [ -f "$OPCODE_CONFIG_DIR/opencode.json" ]; then
            python -c "
import json, os
path = os.path.expanduser('~/.config/opencode/opencode.json')
try:
    try:
        with open(path, 'r') as f:
            data = json.load(f)
    except Exception:
        data = {}
    plugin_list = data.get('plugins', [])
    if '@yohi/opencode-plugin-chronos-gate' not in plugin_list:
        plugin_list.append('@yohi/opencode-plugin-chronos-gate')
        data['plugins'] = plugin_list
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        print('✅ Successfully added plugin to opencode.json')
except Exception as e:
    print('⚠️ Failed to update opencode.json automatically:', e)
"
        elif [ -f "$OPCODE_CONFIG_DIR/opencode.jsonc" ]; then
            echo -e "⚠️ opencode.jsonc detected. Automatic JSON editing is skipped for jsonc format to preserve comments."
        else
            echo -e "⚠️ opencode.json not found in $OPCODE_CONFIG_DIR."
        fi
        
        echo -e "\n${BLUE}--- OpenCode Setup Steps ---${NC}"
        echo -e "1. Add GitHub Packages registry to your ~/.npmrc:"
        echo -e "   ${GREEN}@yohi:registry=https://npm.pkg.github.com${NC}"
        echo -e "2. Register the plugin in ~/.config/opencode/opencode.json (or .jsonc):"
        echo -e "   ${GREEN}\"plugin\": [ \"@yohi/opencode-plugin-chronos-gate\" ]${NC}"
    fi
fi

# 7. Verification for Hook setup
if [ "$TYPE" = "hook" ]; then
    echo -e "${BLUE}Running hook verification test...${NC}"
    POLICY_PATH="./src/mcp_gateway/policies/intents.yaml"
    if [ ! -f "$POLICY_PATH" ]; then
        POLICY_PATH="./intents.yaml"
    fi
    if [ -f "$POLICY_PATH" ]; then
        if command -v uv &> /dev/null; then
            echo '{"tool_name":"bash","tool_input":{"command":"ls"}}' | uv run python -m mcp_gateway evaluate --json-io --policy-path "$POLICY_PATH"
        else
            echo '{"tool_name":"bash","tool_input":{"command":"ls"}}' | python -m mcp_gateway evaluate --json-io --policy-path "$POLICY_PATH"
        fi
    else
        echo -e "⚠️ Intents policy file not found for verification test."
    fi
fi

# 8. Agent Instruction Guidance (Optional)
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
