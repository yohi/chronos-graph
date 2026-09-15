# Configuration Reference

> [!NOTE]
> This document is the canonical source for ChronosGraph environment
> variables and runtime configuration. For a machine-usable template, see
> [.env.example](../.env.example). Gateway-specific settings for ChronosGate
> live in the [ChronosGate](https://github.com/yohi/chronos-gate) repository.

ChronosGraph is configured primarily through environment variables. Values are
read at startup and validated; mismatches such as an `EMBEDDING_DIMENSION` that
differs from the stored schema will raise a `ConfigurationError` or
`StorageError`.

---

## 1. Core Configuration

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `STORAGE_BACKEND` | `sqlite` | No | Storage backend: `sqlite`, `postgres`, or `supabase`. |
| `GRAPH_ENABLED` | `false` | No | Enable graph relationship features. SQLite uses an internal graph; PostgreSQL uses Neo4j. Supabase requires `GRAPH_SYNC_MODE=async_outbox`. |
| `CACHE_BACKEND` | `inmemory` | No | Cache backend: `inmemory` or `redis`. |
| `LOG_LEVEL` | `INFO` | No | Log level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |

## 2. SQLite Storage (`STORAGE_BACKEND=sqlite`)

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `SQLITE_DB_PATH` | `~/.context-store/memories.db` | No | Path to the SQLite database file. |
| `STALE_LOCK_TIMEOUT_SECONDS` | `600` | No | Multi-process concurrency control timeout. |
| `SQLITE_MAX_CONCURRENT_CONNECTIONS` | `5` | No | Maximum concurrent SQLite connections. |
| `SQLITE_MAX_QUEUED_REQUESTS` | `20` | No | Maximum queued SQLite requests. |
| `SQLITE_ACQUIRE_TIMEOUT` | `2.0` | No | Connection acquire timeout in seconds. |
| `WAL_TRUNCATE_SIZE_BYTES` | `104857600` | No | Write-ahead log truncate threshold in bytes. |
| `WAL_PASSIVE_FAIL_CONSECUTIVE_THRESHOLD` | `3` | No | Passive checkpoint failure consecutive threshold. |
| `WAL_PASSIVE_FAIL_WINDOW_SECONDS` | `600` | No | Passive checkpoint failure window in seconds. |
| `WAL_PASSIVE_FAIL_WINDOW_COUNT_THRESHOLD` | `5` | No | Passive checkpoint failure count threshold. |
| `CACHE_COHERENCE_POLL_INTERVAL_SECONDS` | `5.0` | No | Cache coherence polling interval for multi-process in-memory cache. |
| `FORCE_CACHE_COHERENCE_IN_READ_ONLY` | `false` | No | Force cache coherence in read-only mode. |

## 3. PostgreSQL Storage (`STORAGE_BACKEND=postgres`)

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `POSTGRES_HOST` | `localhost` | No | PostgreSQL host. |
| `POSTGRES_PORT` | `5435` | No | PostgreSQL port. |
| `POSTGRES_DB` | `context_store` | No | PostgreSQL database name. |
| `POSTGRES_USER` | `context_store` | No | PostgreSQL user. |
| `POSTGRES_PASSWORD` | — | Yes | PostgreSQL password. |
| `POSTGRES_SSL` | `false` | No | Enable SSL for PostgreSQL. |
| `POSTGRES_SSL_NO_VERIFY` | `false` | No | Disable SSL certificate verification. |
| `POSTGRES_STATEMENT_CACHE_SIZE` | `256` | No | Prepared statement cache size. |

## 4. Supabase Storage (`STORAGE_BACKEND=supabase`)

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `SUPABASE_URL` | — | Yes | Supabase project URL, e.g. `https://your-project.supabase.co`. |
| `SUPABASE_KEY` | — | Yes | Supabase Service Role Key. Treat as a secret. |
| `SUPABASE_REQUEST_TIMEOUT_SECONDS` | `10.0` | No | Timeout for Supabase Data API calls. |

## 5. Neo4j Graph Relationships (`GRAPH_ENABLED=true` with Postgres)

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `NEO4J_URI` | — | Yes | Neo4j connection URI, e.g. `bolt://localhost:7687`. |
| `NEO4J_USER` | — | Yes | Neo4j user. |
| `NEO4J_PASSWORD` | — | Yes | Neo4j password. |

## 6. Redis Cache (`CACHE_BACKEND=redis`)

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `REDIS_URL` | `redis://localhost:6379` | No | Redis connection URL. This default is used when `CACHE_BACKEND=redis`. There is no implicit fallback on connection failure. |
| `REDIS_SSL` | `false` | No | Enable SSL for Redis. |
| `REDIS_SOCKET_CONNECT_TIMEOUT` | `5.0` | No | Redis socket connect timeout. |
| `REDIS_SOCKET_TIMEOUT` | `5.0` | No | Redis socket timeout. |

## 7. Graph Sync Outbox

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `GRAPH_SYNC_MODE` | `sync` | No | Graph sync mode: `sync` (direct Neo4j write) or `async_outbox` (transactional outbox + worker). Required to be `async_outbox` when `STORAGE_BACKEND=supabase` and `GRAPH_ENABLED=true`. |
| `OUTBOX_POLL_INTERVAL_SECONDS` | `5.0` | No | Outbox worker polling interval. |
| `OUTBOX_BATCH_SIZE` | `100` | No | Maximum events processed per poll. |
| `OUTBOX_MAX_RETRIES` | `10` | No | Maximum retries for Neo4j sync failures. |
| `OUTBOX_BACKOFF_BASE_SECONDS` | `1.0` | No | Exponential backoff base wait. |
| `OUTBOX_BACKOFF_MAX_SECONDS` | `60.0` | No | Exponential backoff maximum wait. |

## 8. Embedding Provider

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `EMBEDDING_PROVIDER` | `local-model` | No | Provider: `local-model`, `openai`, `litellm`, or `custom-api`. |
| `EMBEDDING_DIMENSION` | `768` | No | Embedding vector dimension. Must match the storage schema. |
| `EMBEDDING_MAX_RETRIES` | `3` | No | Maximum retry attempts for OpenAI / LiteLLM APIs. |
| `EMBEDDING_MIN_WAIT` | `1.0` | No | Exponential backoff minimum wait in seconds. |
| `EMBEDDING_MAX_WAIT` | `10.0` | No | Exponential backoff maximum wait in seconds. |
| `EMBEDDING_PER_ATTEMPT_TIMEOUT` | `10.0` | No | HTTP timeout per retry attempt. |
| `LOCAL_MODEL_NAME` | `cl-nagoya/ruri-v3-310m` | No | Local model name for `local-model` provider. |
| `OPENAI_API_KEY` | — | Yes (OpenAI) | OpenAI API key. Treat as a secret. |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | No | OpenAI embedding model. |
| `LITELLM_API_BASE` | — | Yes (LiteLLM) | LiteLLM proxy base URL. |
| `LITELLM_MODEL` | — | Yes (LiteLLM) | LiteLLM model identifier. |
| `CUSTOM_API_ENDPOINT` | — | Yes (custom) | Custom embedding API endpoint. |
| `CUSTOM_API_MODEL_NAME` | — | Yes (custom) | Custom embedding model name. |

Total embedding-API latency is bounded to roughly 50 seconds (3 attempts × 10 s
plus 2 waits × 10 s). Invalid or non-positive values for
`CHUNK_PARALLEL_SEMAPHORE_SIZE` and `EMBEDDING_*` fall back to defaults with a
warning log.

## 9. Search & Retrieval

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `DEFAULT_TOP_K` | `10` | No | Default number of search results. |
| `SIMILARITY_THRESHOLD` | `0.70` | No | Minimum similarity score for results. |
| `DEDUP_THRESHOLD` | `0.90` | No | Similarity threshold for duplicate suppression. |
| `GRAPH_FANOUT_LIMIT` | `50` | No | Graph traversal fanout limit. |
| `GRAPH_MAX_LOGICAL_DEPTH` | `5` | No | Graph traversal logical depth limit. |
| `GRAPH_MAX_PHYSICAL_HOPS` | `50` | No | Graph traversal physical hop limit. |
| `GRAPH_TRAVERSAL_TIMEOUT_SECONDS` | `2.0` | No | Graph traversal timeout. |

## 10. Lifecycle & Maintenance

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `DECAY_HALF_LIFE_DAYS` | `30` | No | Time-decay half-life in days. |
| `ARCHIVE_THRESHOLD` | `0.05` | No | Score threshold for archiving. |
| `CONSOLIDATION_THRESHOLD` | `0.85` | No | Similarity threshold for memory consolidation. |
| `PURGE_RETENTION_DAYS` | `90` | No | Retention period after archiving. |
| `CLEANUP_SAVE_COUNT_THRESHOLD` | `50` | No | Lazy cleanup trigger by save count. |
| `CLEANUP_INTERVAL_HOURS` | `24` | No | Lazy cleanup interval in hours. |

## 11. Ingestion & Conversation Analysis

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `CHRONOS_INGESTION_MODE` | `selective` | No | Ingestion mode: `selective` (agent-driven tool calls) or `all` (turn-end auto-save via hook). |
| `CONVERSATION_CHUNK_SIZE` | `5` | No | Chunk size for conversation analysis. |
| `MAX_TOKENS_PER_CHUNK` | `1000` | No | Maximum tokens per chunk. |
| `MAX_TURNS_PER_CHUNK` | `3` | No | Maximum turns per chunk. |
| `CHARS_PER_TOKEN` | `3` | No | Character-per-token estimate for chunking. |
| `CHUNK_PARALLEL_SEMAPHORE_SIZE` | `10` | No | Maximum concurrent chunk processing when `GRAPH_ENABLED=false`. |
| `BATCH_MAX_CONCURRENT_JOBS` | `3` | No | Maximum concurrent batch jobs. |
| `BATCH_CANCEL_TIMEOUT` | `5.0` | No | Batch cancellation timeout. |
| `SESSION_FLUSH_MAX_LOG_LENGTH` | `200000` | No | Maximum conversation log length for turn-end flush. |

## 12. Dashboard (API Server)

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `DASHBOARD_HOST` | `127.0.0.1` | No | Dashboard API host. |
| `DASHBOARD_PORT` | `8000` | No | Dashboard API port. |
| `DASHBOARD_ALLOWED_HOSTS` | `localhost,127.0.0.1` | No | TrustedHostMiddleware allowed hosts. |
| `DASHBOARD_CORS_ORIGINS` | `http://localhost:5173` | No | CORS allowed origins. |

## 13. URL Fetch (SSRF Protection)

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `ALLOW_PRIVATE_URLS` | `false` | No | Allow fetching private/reserved IP ranges. |
| `URL_FETCH_CONCURRENCY` | `3` | No | Concurrent URL fetch limit. |
| `URL_MAX_REDIRECTS` | `3` | No | Maximum redirects. |
| `URL_MAX_RESPONSE_BYTES` | `10485760` | No | Maximum response size in bytes. |
| `URL_TIMEOUT_SECONDS` | `30` | No | URL fetch timeout. |
| `URL_ALLOWED_CONTENT_TYPES` | `text/*,application/json` | No | Allowed response content types. |

## 14. Context Store Hook (`agent_turn_hook.py`)

Used in `CHRONOS_INGESTION_MODE=all` to forward turn-end conversation logs to
a compatible gateway. The hook is fail-soft: it always exits `0` so the host
agent process is never blocked.

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `MCP_GATEWAY_URL` | `http://127.0.0.1:9100` | No | Gateway URL reachable by the hook. |
| `MCP_GATEWAY_API_KEY` | — | Yes (when using gateway) | Bearer-equivalent API key for the gateway. Treat as a secret. |
| `MCP_INTENT` | `memory.ingest` | No | Intent used by the gateway for ingestion. |
| `MCP_HOOK_TIMEOUT_SECONDS` | `2.0` | No | Overall hard timeout for the hook. |
| `MCP_HOOK_SSE_TIMEOUT_SECONDS` | `1.0` | No | SSE handshake timeout. |
| `MCP_HOOK_MAX_LOG_BYTES` | `8388608` (8 MB) | No | Maximum log size sent through the hook. Longer logs are truncated from the end. |

---

## Project Name Normalization

`memory_save`, `memory_search`, and related tools normalize the `project`
parameter automatically: trim whitespace, lowercase, and take the basename. A
value of `.` is replaced with the current git repository root name. No
filesystem access is performed during normalization. For example,
`/home/user/my-repo` becomes `my-repo`.

## Security Notes

- Store secrets (`SUPABASE_KEY`, `OPENAI_API_KEY`, `POSTGRES_PASSWORD`,
  `NEO4J_PASSWORD`, `MCP_GATEWAY_API_KEY`) in `.env` or a credential manager,
  never in source control.
- `.env` and `.env.*` are treated as secret-bearing. Confirm `.gitignore`
  excludes them before creating or modifying them.
- Claude Desktop does not expand `${VAR}` syntax inside its JSON config file.
  Use a wrapper script that exports environment variables before launching
  Claude when secrets are required.
