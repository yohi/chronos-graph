# ChronosGraph

[日本語](README.ja.md)

> MCP-based long-term memory system for AI agents using temporal knowledge graphs.

---

[![CI](https://github.com/yohi/chronos-graph/actions/workflows/ci.yml/badge.svg)](https://github.com/yohi/chronos-graph/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

ChronosGraph gives AI agents (Claude Code, Gemini CLI, Cursor, etc.)
persistent, session-spanning long-term memory through a
[Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server.

Information is stored as a temporal, multi-layer graph rather than as isolated
vectors, tracking how memories evolve across **episodic** (experiences),
**semantic** (facts), and **procedural** (workflows) layers. A decay model and
importance scoring keep storage from growing indefinitely while preserving
useful knowledge.

> [!NOTE]
>
> Current implementation caveats:
>
> - `memory_search` accepts a `memory_type` filter for API compatibility, but
>   the filter is not yet applied to results.
>
> - `memory_search_graph` accepts `edge_types` and `depth`, but these take the
>   standard hybrid-search path; a dedicated graph traversal path is not yet
>   implemented.
>
> - Project names passed to `memory_save` / `memory_search` are normalized
>   automatically (trim, lowercase, basename). A value of `.` is replaced by the
>   current git repository root name. No filesystem access is performed.

---

## Get Started

| I want to... | Start here |
| --- | --- |
| Use ChronosGraph as an MCP memory server | [Quick Start](#quick-start) |
| Configure an AI agent to use it | [Agent Setup Protocol](docs/agent-setup-protocol.md) or [AGENTS.md](AGENTS.md) |
| Set up the repo for local development | [Development](#development) |
| See all configuration options | [Configuration Reference](docs/configuration.md) |
| Migrate from an older version | [Migration Guide](docs/migration.md) |
| Troubleshoot errors | [Troubleshooting guides](docs/troubleshooting/) |

---

## Quick Start

The fastest way to run ChronosGraph is with `uvx`, without cloning the
repository. Tagged releases are published through
[release-please](https://github.com/googleapis/release-please) and can be
installed directly from a GitHub tarball.

### Claude Desktop (release tarball)

Add the following block to
`~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or
`%APPDATA%\Claude\claude_desktop_config.json` (Windows). Replace `v2.0.0`
with the latest version from
[Releases](https://github.com/yohi/chronos-graph/releases).

```json
{
  "mcpServers": {
    "chronos-graph": {
      "command": "uvx",
      "args": [
        "--from",
        "context-store-mcp[all] @ https://github.com/yohi/chronos-graph/archive/<full-commit-sha>.tar.gz",
        "context-store"
      ],
      "env": {
        "STORAGE_BACKEND": "sqlite",
        "GRAPH_ENABLED": "true",
        "CACHE_BACKEND": "inmemory"
      }
    }
  }
}
```

For a production setup, replace `<full-commit-sha>` with the full commit SHA
published for the release and verify the corresponding source archive checksum
before registering the configuration. See the [Agent Setup Protocol](docs/agent-setup-protocol.md).

### Claude Desktop (latest `master`, development only)

To use the current `master` branch instead of waiting for a release:

```json
{
  "mcpServers": {
    "chronos-graph-dev": {
      "command": "uvx",
      "args": [
        "--from",
        "context-store-mcp[all] @ git+https://github.com/yohi/chronos-graph.git",
        "context-store"
      ],
      "env": {
        "STORAGE_BACKEND": "sqlite",
        "GRAPH_ENABLED": "true",
        "CACHE_BACKEND": "inmemory"
      }
    }
  }
}
```

> 💡 **Environment variables**: This Quick Start is the minimal configuration
> for the long-term memory MCP server (`context-store`). Claude Desktop does
> not expand `${VAR}` inside its JSON config; use a wrapper script that exports
> variables before launching Claude when you need to pass secrets.

---

## Features

- **Hybrid search** — vector + keyword + graph results merged with reciprocal
  rank fusion (when graph is enabled).
- **Multi-layer memory** — episodic / semantic / procedural layers.
- **Temporal decay** — exponential decay scores keep old memories tidy
  (explicit `memory_prune` currently runs only on the SQLite backend).
- **Deduplication** — append-only replacement with `SUPERSEDES` graph edges to
  track evolution.
- **Lightweight mode** — SQLite + `sqlite-vec` with zero external services.
- **Scalable backends** — PostgreSQL + Neo4j + Redis, plus Supabase Data API
  over HTTPS (Supabase + Neo4j Aura require `async_outbox` mode).
- **RL extension points** — `ActionLogger`, `RewardSignal`, `PolicyHook`
  interfaces for future reinforcement-learning integration.
- **Dashboard Web UI** — React + FastAPI dashboard with Cytoscape.js graph
  visualization and real-time log streaming.
- **ChronosGate integration** — pre-execution safety evaluation is provided by
  the separate [ChronosGate](https://github.com/yohi/chronos-gate) repository.

---

## How It Works

ChronosGraph runs as a FastMCP server written in Python 3.12+. Agents call
tools such as `memory_save`, `memory_search`, and `memory_search_graph` over
MCP. Saved memories are chunked, embedded, stored, and (when graph mode is
enabled) linked into a temporal graph. Search blends vector similarity,
full-text ranking, and graph traversal results into a single ranked list.

For exact tool contracts, state transitions, and design invariants, see
[SPEC.md](SPEC.md). For a human-oriented architecture walkthrough, see
[docs/embedding-models.md](docs/embedding-models.md) (model choices) and the
detailed troubleshooting guides under [docs/troubleshooting/](docs/troubleshooting/).

---

## Usage

Once the MCP server is registered, an agent can call tools such as:

```json
{
  "tool": "memory_save",
  "params": {
    "content": "User prefers concise answers with concrete examples.",
    "project": "my-project",
    "tags": ["preference"]
  }
}
```

```json
{
  "tool": "memory_search",
  "params": {
    "query": "What does the user prefer?",
    "project": "my-project",
    "top_k": 5
  }
}
```

The exact request/response schemas and error semantics are defined in
[SPEC.md](SPEC.md).

---

## Configuration

The most important variables are:

- `STORAGE_BACKEND` — `sqlite`, `postgres`, or `supabase`.
- `GRAPH_ENABLED` — `true` or `false`.
- `CACHE_BACKEND` — `inmemory` or `redis`.
- `EMBEDDING_PROVIDER` — `local-model`, `openai`, `litellm`, or `custom-api`.
- `EMBEDDING_DIMENSION` — must match the storage schema (default `768`).
- `CHRONOS_INGESTION_MODE` — `selective` (agent-driven tool calls) or `all`
  (turn-end auto-save via hook).

For the complete reference, defaults, required values, and security notes,
see [docs/configuration.md](docs/configuration.md). For model-specific
guidance, see [docs/embedding-models.md](docs/embedding-models.md).

---

## Documentation

- [Agent Setup Protocol](docs/agent-setup-protocol.md) — install and configure
  ChronosGraph as a long-term-memory MCP server for an AI agent.
- [AGENTS.md](AGENTS.md) — canonical repository-specific instructions for AI
  coding agents working on this repo.
- [Configuration Reference](docs/configuration.md) — complete environment-variable
  catalog.
- [Migration Guide](docs/migration.md) — version migration procedures.
- [Embedding Models Guide](docs/embedding-models.md) — choosing and switching
  embedding models.
- [Troubleshooting](docs/troubleshooting/) — operational problem solving.
- [SPEC.md](SPEC.md) — normative technical specification.

---

## Development

Run all Python commands through `uv`.

```bash
# Install dependencies
uv sync --all-extras

# Tests
uv run pytest tests/unit/ -v
uv run pytest tests/integration/ -v

# Lint / format
uv run ruff check src/ tests/
uv run ruff format src/ tests/

# Type check
uv run mypy src/
```

Frontend (in `frontend/`):

```bash
pnpm install
pnpm run lint
pnpm run test:unit
```

For isolated test/static-analysis sandboxes, see [SPEC.md §18](SPEC.md).

## Set up with an AI coding agent

You can hand off setup of this repository to an AI coding agent (Claude Code,
Cursor, OpenCode, etc.) by pasting one of the prompts below, depending on what
you want to set up.

### Use ChronosGraph as a long-term-memory MCP server

```text
Set up https://github.com/yohi/chronos-graph as a long-term-memory MCP server
for an AI agent. Read docs/agent-setup-protocol.md as the canonical setup
source, follow its installation instructions, ask before any privileged or
destructive operation, and verify by running the repository-defined test
command.
```

### Set up the repository for local development

```text
Set up this repository (https://github.com/yohi/chronos-graph) for local
development. Read AGENTS.md as the canonical setup source, follow its
installation and verification instructions, ask before any privileged or
destructive operation, and verify by running the repository-defined test
command.
```

---

## Migration

The default embedding dimension changed from **1024** to **768**. Upgrading from
an older schema without re-embedding or updating the storage column will raise a
`ConfigurationError` on startup. See [docs/migration.md](docs/migration.md) for
the re-embedding script and schema-update SQL.

---

## License

MIT License — [LICENSE](LICENSE)
