# Agent Setup Prompt Hardening Design

## Goal

Make the AI-agent setup prompts lead to a usable and verifiable ChronosGraph
installation. Document references in user-facing prompts must use GitHub Raw
URLs on `master`; commands executed inside a checked-out repository may keep
local paths.

## Decisions

1. README setup prompts will reference the canonical setup documents with Raw
   URLs and explicitly require structured questions before side effects.
2. The setup protocol will require MCP client registration and an MCP startup
   or tool-call smoke test before production setup is considered complete.
3. `all` ingestion will document the gateway dependency and per-client hook
   registration. A missing gateway or unregistered hook will be reported as
   incomplete, not as successful setup.
4. Provider-specific required values will be collected and passed through
   bootstrap: LiteLLM base URL and custom API endpoint in addition to model.
5. Bootstrap will default local MCP launch configuration to `uv`, so the
   generated client configuration uses the project environment.
6. Supabase configuration generation will preserve graph enablement, emit the
   required `async_outbox` mode, and include Neo4j settings when graph mode is
   enabled.
7. Dry-run documentation will require an existing checkout as input. Archive
   download, extraction, and all filesystem writes remain prohibited in every
   dry-run; supplying a checkout never authorizes persistent writes.

## Scope

Modify the README prompts, English and Japanese setup protocols, bootstrap
argument handling, MCP configuration generation, and focused tests. Do not add
new agent configuration files, alter storage schemas, or register clients
automatically in machine-global configuration.

## Verification

Add regression coverage for new bootstrap arguments, local `uv` defaults,
Supabase graph configuration, and prompt/protocol Raw URL requirements. Run
the focused tests, the full unit suite, Ruff, format checks, shell syntax
checks, and inspect the final diff for secrets and unintended files.
