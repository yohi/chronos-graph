# OpenCode v1.18.34 Durable All-Mode Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved OpenCode v1.18.34 `CHRONOS_INGESTION_MODE=all` design so eligible root-session turns converge to exactly one durable ChronosGraph receipt/memory commit across retries, event loss, restarts, source alias changes, and key rotation, without using the legacy detached OpenCode hook path.

**Architecture:** ChronosGraph owns canonicalization, keyrings, source/receipt authority, and backend-atomic COMMIT through a new durable-ingestion service plus private `context-store-control --stdio` server and local `context-store-admin` keyring CLI. ChronosGate exposes a dedicated authenticated `/internal/v1/opencode/control` endpoint backed by that private Graph control process while strengthening regular MCP `/messages` to Bearer+session-owner authorization. The OpenCode plugin becomes a root-only reconciler with deterministic v1.18.34 extraction, crash-safe local state, exhaustive discovery, contiguous checkpointing, and no legacy `memory_save`/`session_flush`/detached-hook side channel.

**Tech Stack:** Python 3.12+, Pydantic v2, asyncio, aiosqlite, asyncpg, Supabase/PostgREST RPC, FastAPI, FastMCP/MCP v1, Node.js CommonJS, OpenCode `opencode-ai@1.18.34`, node:test, pytest/pytest-asyncio, uv.

**Design/Spec:** `docs/superpowers/specs/2026-10-05-opencode-all-durable-ingestion-design.md` at approved baseline `bafcef8b78b7bdc7506162f97e95b181a32ac518`. This plan embeds the design contracts required for implementation; the spec remains the authoritative source for background and rationale.
**Repositories:**
- ChronosGraph baseline: `yohi/chronos-graph@bafcef8b78b7bdc7506162f97e95b181a32ac518`
- ChronosGate planning baseline: `yohi/chronos-gate@45938202c9542e76fa6c59c8b085cb2457ce20d8`
- Execute in isolated worktrees. Set `GRAPH_ROOT` and `GATE_ROOT` to their roots before running commands.

## Global Constraints

- Exact native compatibility target: `opencode-ai@1.18.34`; a different OpenCode version does not satisfy native acceptance.
- Events are reconciliation hints only; activation plus a finite 60-second correctness sweep must recover lost hints.
- Only root OpenCode sessions own durable turns; child/sub-agent sessions never own independent receipt/checkpoint/pending state.
- OpenCode `all` must never call `memory_save`, `session_flush`, or spawn detached `scripts/agent_turn_hook.py`.
- PREPARE is side-effect-free; all external embedding/model/network work finishes before COMMIT.
- COMMIT performs no external I/O and advances local checkpoint only after `COMMITTED` or `ALREADY_COMMITTED`.
- `STALE_DEDUPE_PLAN` and `KEYRING_GENERATION_CHANGED` are retryable reasons requiring full rollback and fresh PREPARE.
- `ingestion_keyring_manifest` is the common serialization fence for every key-dependent durable mutation and key promotion/retirement.
- Active-key promotion retains the previous key; retirement is a later manifest generation.
- No raw ingestion key material may cross ChronosGate, MCP, the private control wire, logs, receipts, or the backend manifest.
- Regular MCP, OpenCode control, and operator control credentials remain distinct.
- Run Python tools through `uv`; use migrations for all schema changes; never perform network/LLM I/O while holding DB transaction locks.
- Existing `selective` behavior and non-OpenCode Claude/Codex hook behavior remain regression-protected.
- Do not run CodeRabbit actions; review output may be analyzed only when explicitly provided.
- Do not begin production implementation until this plan passes its own Review Gate.
- **Mandatory TDD order for every implementation Task:** write the named RED test → run the named RED command and observe the expected design-specific failure → implement the minimum GREEN behavior → run the named GREEN command → **REFACTOR only inside that Task's listed files without adding behavior** → rerun the same GREEN command → commit. Task 18 has its own dependency-pin RED/GREEN plus final integrated verification.
- A Task must not commit while its focused GREEN command is failing or while a required backend/native acceptance case is skipped.

- **Canonicalization contract:** `semantic_projection` and `identity_evidence` are JSON-serializable dicts derived deterministically from OpenCode v1.18.34 message lineage (Task 12). `identity_evidence` must be stable across key promotion and must not include mutable routing aliases. `turn_key` is derived from the deterministic root session ID, user message ID, and a stable ordering of the user anchor and immediate context. The exact derivation is owned by Task 12 and pinned by native acceptance.
- **Dedupe classification contract:** `DedupePlan` classification values are `BACKFILL` (existing alias token maps to canonical scope), `NEW_SCOPE` (no match; requires operator registration), `MIGRATE_ALIAS` (operator authorizes alias migration), `CONFLICT` (alias matches multiple scopes or scope mismatch; terminal), `NO_MATCH` (keyring not ready or lookup degraded; retryable). A `STALE_DEDUPE_PLAN` is raised when the keyring generation or source alias state changes between PREPARE and COMMIT.
- **Local source state contract:** `LocalSourceStateV1` stores `source.json` with `canonical_source_scope_id`, active binding (key_version + token, never raw key), alias_schema_version. `CheckpointStateV1` is stored in `checkpoint.json` with `committed_turns: tuple[CheckpointEntry, ...]`, `pending_turn_key: str | None`, and `pending_since: int | None` (Unix ms). Both files are persisted atomically with write-then-rename.

## File Structure
### ChronosGraph — new focused modules
- `src/chronos_shared/opencode_control.py` — versioned Gate↔Graph/OpenCode control enums/envelopes shared without importing Gate policy.
- `src/context_store/ingestion/durable/models.py` — prepared-turn, dedupe, receipt, source, and key-authority domain types.
- `src/context_store/ingestion/durable/planner.py` — side-effect-free dedupe planning.
- `src/context_store/ingestion/durable/canonicalizer.py` — server-authoritative evidence validation, HMAC identity tokens, canonical hash/rebase.
- `src/context_store/ingestion/durable/service.py` — source/receipt/turn orchestration; owns PREPARE→COMMIT retry semantics.
- `src/context_store/security/ingestion_keyring.py` — keyring parsing/fingerprints/binding MACs/readiness.
- `src/context_store/storage/ingestion/protocols.py` — `IngestionCommitStore` / registry / manifest interfaces.
- `src/context_store/storage/ingestion/sqlite.py` — SQLite atomic authority implementation.
- `src/context_store/storage/ingestion/postgres.py` — asyncpg atomic authority implementation.
- `src/context_store/storage/ingestion/supabase.py` — Supabase RPC-backed authority implementation.
- `src/context_store/storage/ingestion/factory.py` — select durable-ingestion store for configured backend.
- `src/context_store/control/composition.py` — focused private-control composition root; creates only Settings, primary storage/read source, durable-ingestion authority store, embedding provider, keyring authority, and `DurableIngestionService`.
- `src/context_store/control/server.py`, `src/context_store/control/__main__.py` — private `chronos.control.v1` stdio server.
- `src/context_store/admin/ingestion_keyring.py`, `src/context_store/admin/__main__.py` — Graph-local `context-store-admin ingestion-keyring {provision,verify,promote,retire}`.
- `.opencode/plugins/chronos/{canonicalize,lineage,control-client,state-store,source-scope,lock,reconciler,runtime}.js` — shared npm/local OpenCode runtime implementation. These are regular source files under the repository-owned `.opencode/plugins/` path, not new agent config directories.
- `tests/native/opencode/` — exact v1.18.34 deterministic-provider/native-loader acceptance harness.

### ChronosGraph — existing files modified
- `pyproject.toml` — add `context-store-control` and `context-store-admin` console scripts.
- `src/context_store/config.py` — add `CHRONOS_INGESTION_KEYRING_PATH` setting.
- `src/context_store/models/memory.py` and storage row conversion/write paths — add/maintain `ingestion_revision`.
- `src/context_store/storage/migrations/{sqlite,postgres}/0004_opencode_durable_ingestion.sql` — durable-ingestion schema.
- `supabase/migrations/20261006000003_opencode_durable_ingestion.sql` — Supabase durable-ingestion schema.
- `supabase/migrations/20261006000004_opencode_durable_rpc.sql` — transactional RPC/functions.
- `.opencode/plugins/chronos-turn-end.js` and `package.json` — loader-only adapter/package runtime files.
- `scripts/bootstrap.sh`, `scripts/agent_assets/hooks.py`, `.env.example`, setup docs — control credential/keyring/source enrollment/smoke integration.

### ChronosGate — new focused modules
- `src/chronos_gate/control/client.py` — private long-lived `context-store-control --stdio` JSON-RPC client.
- `src/chronos_gate/control/http.py` — versioned `/internal/v1/opencode/control` operation/capability dispatcher.

### ChronosGate — existing files modified
- `src/chronos_gate/server.py` — Bearer+session-owner `/messages` authority and control route wiring.
- `src/chronos_gate/auth/handshake.py` — reject reserved control principals from regular MCP sessions.
- `src/chronos_gate/config.py` — private control subprocess settings/passthrough.
- `src/chronos_gate/app.py` — construct/start/stop both normal MCP and private control upstreams.
- `pyproject.toml` — pin to the final ChronosGraph implementation SHA after Graph tasks complete.

## Review Focus

1. **Prepared work crossing key rotation:** a turn/source/binding prepared under manifest generation G must either commit before rotation and make retirement observe its reference, or roll back with `KEYRING_GENERATION_CHANGED`; Task 6/7 tests and Scenario AA pin both schedules.
2. **Lost server ACK plus corrupt local checkpoint:** a server-committed turn must recover via receipt inventory without duplicate memory and without skipping a gap; Task 14 owns lost-ACK/corrupt-state tests.
3. **OpenCode internal/synthetic inputs:** file-only, AgentPart/SubtaskPart, compaction continuation, overflow replay, and synthetic shell/control messages must preserve authorship/lineage exactly; Task 12 owns deterministic v1.18.34 fixtures.
4. **Real child-session event storms:** child sessions may emit status/message events but must never acquire receipt/checkpoint/pending ownership; Task 14 and Task 17 native acceptance own this.
5. **Credential/session and legacy-path confusion:** a control credential must not reuse a regular MCP session, and OpenCode all-mode must prove zero legacy `memory_save`/detached-hook invocation while Claude/Codex legacy ingestion still works; Tasks 10, 11, 15, and 17 own this.

---

### Task 1: Freeze the shared control protocol contract

**Files:**
- ChronosGraph — Create: `src/chronos_shared/opencode_control.py`
- ChronosGraph — Create: `tests/test_chronos_shared/test_opencode_control.py`

**Interfaces:**
- Consumes: approved spec §§1.4, 8.4-8.7.
- Produces:
  - `CONTROL_PROTOCOL: Final[str] = "chronos.opencode-control.v1"`
  - `RESERVED_CONTROL_PRINCIPALS: Final[frozenset[str]] = frozenset({"opencode-ingestion", "chronos-setup"})`.
  - `ControlOperation(StrEnum)` values: `source.resolve`, `source.register`, `source.authorize_alias_migration`, `source.backfill_alias`, `receipt.list_roots`, `receipt.list`, `receipt.lookup`, `receipt.validate`, `turn.ingest`.
  - `SourceBackfillStatus(StrEnum)`: `BACKFILLED`, `ALREADY_BOUND`, `ALIAS_NOT_FOUND`, `CONFLICT`.
  - `TurnIngestResultKind(StrEnum)`: `COMMITTED`, `ALREADY_COMMITTED`, `RETRYABLE_FAILED`, `TERMINAL_FAILED`, `IDEMPOTENCY_CONFLICT`, `IDEMPOTENCY_REBASE_UNAVAILABLE`.
  - `RetryReason(StrEnum)`: `STALE_DEDUPE_PLAN`, `KEYRING_GENERATION_CHANGED`.
  - `SourceResolutionStatus(StrEnum)`: `RESOLVED`, `REGISTERED`, `MIGRATED`, `UNRESOLVED`, `NOT_READY`.
  - `SourceResolutionCode(StrEnum)`: `SOURCE_SCOPE_CONTINUITY_UNRESOLVED`, `SOURCE_ROUTING_SCOPE_MISMATCH`, `SOURCE_SCOPE_ALIAS_CONFLICT`, `SOURCE_SCOPE_LOOKUP_DEGRADED`, `INGESTION_KEYRING_NOT_READY`, `INGESTION_KEYRING_MISMATCH`, `INGESTION_KEYRING_MANIFEST_INCONSISTENT`, `KEYRING_GENERATION_CHANGED`.
  - `DivergenceCode(StrEnum)`: `OPEN_CODE_HISTORY_DIVERGED`, `POST_TERMINAL_CONTINUATION`, `COMMITTED_TURN_REMOVED`, `COMMITTED_TURN_SEMANTICS_CHANGED`, `ROOT_SESSION_REMOVED`, `COMMITTED_PREFIX_MEMBERSHIP_CHANGED`.
  - recursive `JsonValue` wire alias; semantic projection / identity evidence remain JSON values, never arbitrary Python objects.
  - Pydantic `ControlRequest`, `ControlSuccess`, `ControlFailure` envelopes with fixed protocol/request-id fields.
  - `SourceBindingWire(schema: str, issuer: Literal["chronos-graph"], key_version: str, token: str)`.
  - `CandidateSourceBindingWire(canonical_source_scope_id: str, binding: SourceBindingWire)`; candidate scope identity and its MAC are one indivisible wire value.
  - operation payload models:
    - `SourceResolvePayload(alias_schema_version: str, discovery_scope: dict[str, JsonValue], candidate: CandidateSourceBindingWire | None, current_root_session_ids: tuple[str, ...])`
    - `SourceRegisterPayload(alias_schema_version: str, discovery_scope: dict[str, JsonValue], current_root_session_ids: tuple[str, ...])` — operator-only; creates a new source scope.
    - `SourceRegisterResult(status: SourceResolutionStatus, code: SourceResolutionCode | None, canonical_source_scope_id: str | None, source_binding: SourceBindingWire | None)` — reuses `SourceResolutionResult` shape.
    - `SourceAliasMigrationPayload(alias_schema_version: str, discovery_scope: dict[str, JsonValue], canonical_source_scope_id: str)` — operator-only alias migration.
    - `SourceAliasMigrationResult(status: SourceBackfillStatus, alias_id: str, canonical_source_scope_id: str)` — reuses `SourceBackfillWireResult` shape.
    - `ReceiptListRootsPayload(canonical_source_scope_id: str, page_token: str | None, limit: int)`
    - `ReceiptListPayload(canonical_source_scope_id: str, root_session_id: str, page_token: str | None, limit: int)`
    - `ReceiptLookupPayload(canonical_source_scope_id: str, turn_keys: tuple[str, ...])`
    - `ReceiptEvidence(turn_key: str, current_semantic_projection: dict[str, JsonValue] | None, current_identity_evidence: dict[str, JsonValue] | None, current_payload_hash: str | None)` — when `current_payload_hash` differs from the stored receipt's `payload_hash`, the divergence code is `COMMITTED_TURN_SEMANTICS_CHANGED`; when the turn is missing from the committed prefix, the code is `COMMITTED_TURN_REMOVED`.
    - `ReceiptValidatePayload(canonical_source_scope_id: str, root_session_id: str, evidence: tuple[ReceiptEvidence, ...])` — validates the committed prefix for the given root session. The caller supplies the current `(turn_key, current_semantic_projection, current_identity_evidence, current_payload_hash)` for each turn in the committed prefix; the service compares each against the stored receipt and reports `MATCH`, `DIVERGED` (with `ReceiptDivergence` codes), or `UNAVAILABLE` (receipt inventory unreachable).
    - `SourceBackfillAliasPayload(alias_schema_version: str, canonical_source_scope_id: str, alias_id: str)` — operator-only backfill of an existing alias token into the canonical scope.
    - `TurnIngestPayload(canonical_source_scope_id: str, source_binding: dict[str, JsonValue], turn_key: str, root_session_id: str, user_message_id: str, source_cursor_created_at: int, evidence_contract_version: str, semantic_projection: dict[str, JsonValue], identity_evidence: dict[str, JsonValue])` — `identity_evidence` is a stable, key-version-independent canonicalization of identity; `source_binding` carries the current key_version and MAC for verification only. `graph_intent` is **not** a client input; it is produced by the Graph-side PREPARE (Task 8) and passed internally to COMMIT (Task 5/6).
  - wire result models:
    - `SourceResolutionResult(status: SourceResolutionStatus, code: SourceResolutionCode | None, canonical_source_scope_id: str | None, source_binding: SourceBindingWire | None)`.
    - `ReceiptWireRecord(canonical_source_scope_id: str, turn_key: str, root_session_id: str, user_message_id: str, source_cursor_created_at: int, payload_hash: str, canonical_schema_version: str, evidence_contract_version: str, identity_key_version: str, memory_id: str | None)` — `memory_id` is `None` for `ALREADY_COMMITTED` or dedupe-resolved receipts, and a non-empty string for newly committed memories.
    - `ReceiptRootRecord(canonical_source_scope_id: str, root_session_id: str)`.
    - `ReceiptRootPage(items: tuple[ReceiptRootRecord, ...], next_page_token: str | None)`.
    - `ReceiptPage(items: tuple[ReceiptWireRecord, ...], next_page_token: str | None)`.
    - `ReceiptLookupResult(items: tuple[ReceiptWireRecord, ...]).`
    - `ReceiptDivergence(code: DivergenceCode, canonical_source_scope_id: str, root_session_id: str, turn_key: str | None, receipt_payload_hash: str | None, current_payload_hash: str | None)`.
    - `ReceiptValidationStatus(StrEnum)`: `MATCH`, `DIVERGED`, `UNAVAILABLE`.
    - `ReceiptValidationResult(status: ReceiptValidationStatus, divergences: tuple[ReceiptDivergence, ...])`.
    - `SourceBackfillWireResult(status: SourceBackfillStatus, alias_id: str, canonical_source_scope_id: str)`.
    - `TurnIngestWireResult(kind: TurnIngestResultKind, retry_reason: RetryReason | None, payload_hash: str | None, memory_id: str | None)` — `memory_id` is `None` for `ALREADY_COMMITTED` and dedupe results.
  - `control_method(operation: ControlOperation) -> str`.
  - Exact operation→payload/result mapping:
    | Operation | Payload | Result |
    |---|---|---|
    | `source.resolve` | `SourceResolvePayload` | `SourceResolutionResult` |
    | `source.register` | `SourceRegisterPayload` | `SourceRegisterResult` |
    | `source.authorize_alias_migration` | `SourceAliasMigrationPayload` | `SourceAliasMigrationResult` |
    | `source.backfill_alias` | `SourceBackfillAliasPayload` | `SourceBackfillWireResult` |
    | `receipt.list_roots` | `ReceiptListRootsPayload` | `ReceiptRootPage` |
    | `receipt.list` | `ReceiptListPayload` | `ReceiptPage` |
    | `receipt.lookup` | `ReceiptLookupPayload` | `ReceiptLookupResult` |
    | `receipt.validate` | `ReceiptValidatePayload` | `ReceiptValidationResult` |
    Add tests asserting all exact enum values, `chronos.control.v1.<operation>` mapping, reserved principal set, exact operation→payload/result mapping table (all ten operations: `source.resolve`, `source.register`, `source.authorize_alias_migration`, `source.backfill_alias`, `receipt.list_roots`, `receipt.list`, `receipt.lookup`, `receipt.validate`, `turn.ingest`), page limit validation, and rejection of unsupported protocol strings or extra top-level operation fields. Add exact round-trip tests for `SourceBindingWire`, `CandidateSourceBindingWire`, `ReceiptWireRecord`, `ReceiptDivergence`, `TurnIngestWireResult`, `ReceiptValidatePayload`, and every status enum;
missing required receipt fields and unknown top-level receipt/divergence fields must fail validation. `source.resolve` must reject a binding supplied without its candidate canonical scope or a candidate scope supplied without its binding, because only the pair type is accepted. `source.backfill_alias` must map to `SourceBackfillAliasPayload` and return `SourceBackfillWireResult`, and the dispatcher test must assert it is operator-only at the Gate layer (Task 11 tests the actual enforcement).

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/test_chronos_shared/test_opencode_control.py -v`

Expected: FAIL because `chronos_shared.opencode_control` does not exist.

- [ ] **Step 3: Implement the shared protocol module**

Implement only the values/models/signatures above; keep Gate policy and Graph storage types out of `chronos_shared`.

- [ ] **Step 4: Run GREEN and type/lint checks**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/test_chronos_shared/test_opencode_control.py -v && uv run mypy src/chronos_shared && uv run ruff check src/chronos_shared tests/test_chronos_shared`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GRAPH_ROOT"
git add src/chronos_shared/opencode_control.py tests/test_chronos_shared/test_opencode_control.py
git commit -m "feat: OpenCode control protocol contract を追加"
```

---

### Task 2: Add the durable-ingestion schema and memory revision authority

**Files:**
- ChronosGraph — Create: `src/context_store/storage/migrations/sqlite/0004_opencode_durable_ingestion.sql`
- ChronosGraph — Create: `src/context_store/storage/migrations/postgres/0004_opencode_durable_ingestion.sql`
- ChronosGraph — Create: `supabase/migrations/20261006000003_opencode_durable_ingestion.sql`
- ChronosGraph — Modify: `src/context_store/storage/migrations/runner.py`
- ChronosGraph — Modify: `src/context_store/models/memory.py`
- ChronosGraph — Modify: `src/context_store/storage/sqlite.py`
- ChronosGraph — Modify: `src/context_store/storage/postgres.py`
- ChronosGraph — Modify: `src/context_store/storage/postgres_helpers.py`
- ChronosGraph — Modify: `src/context_store/storage/supabase.py`
- ChronosGraph — Create: `src/context_store/storage/migrations/{sqlite,postgres}/0005_opencode_graph_intent_edges.sql` — follow-up migration for `memory_graph_edges`.
- ChronosGraph — Create: `supabase/migrations/20261006000005_opencode_graph_intent_edges.sql` — follow-up migration for `memory_graph_edges`.

**Interfaces:**
- Consumes: Task 1 enum names only for tests/documentation.
- Produces:
  - `Memory.ingestion_revision: int = 1`.
  - tables `ingestion_source_scopes`, `ingestion_source_aliases`, `ingestion_source_alias_tokens`, `ingestion_receipts`, `ingestion_keyring_manifest`.
  - receipt uniqueness `(canonical_source_scope_id, turn_key)`.
  - `ingestion_receipts` columns map one-for-one to Task 1 `ReceiptWireRecord`, including a nullable `memory_id` column; a `NULL` value means the receipt resolved to an existing memory (`ALREADY_COMMITTED` or dedupe) and no new memory row was created.
  - alias-token uniqueness `(alias_schema_version, key_version, keyed_token)`.
  - singleton manifest row identity, but migration creates schema/constraint only — no manifest value row.
  - `memories.ingestion_revision NOT NULL DEFAULT 1`.
  - ordinary update paths increment `ingestion_revision` for dedupe-relevant updates.
  - `durable_graph_intents` table (created in this migration). `memory_graph_edges` is deliberately **not** created here; it is added by the follow-up migration `0005_opencode_graph_intent_edges.sql` so that Task 2/6 schema validation can complete before Task 9 adds the graph-worker schema.
- [ ] **Step 1: Add RED migration/model tests**

Pin table/column/unique constraints for `ingestion_receipts`, `durable_graph_intents`, and related tables; assert the `ingestion_receipts.memory_id` nullable column exists; assert fresh migrations leave `ingestion_keyring_manifest` empty; assert `Memory(...).ingestion_revision == 1`; assert row conversion preserves a non-default revision. Add RED tests that verify every ordinary update path able to invalidate a prepared destructive dedupe assumption increments `ingestion_revision`; these tests must fail if any such path is missed. Add a Supabase-specific contract asserting RLS is on and only service-role writes reach durable tables.

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/storage/test_ingestion_schema_contract.py tests/unit/test_migration_runner.py -v`

Expected: FAIL on missing migration/table expectations.

Keep schema changes in the named migration files only, including the new `durable_graph_intents` table. Update `Memory`, row conversion, and ordinary write paths to maintain `ingestion_revision`.

- [ ] **Step 4: Run GREEN and full Graph schema tests**

Run:
```bash
cd "$GRAPH_ROOT"
uv run pytest tests/unit/storage/test_ingestion_schema_contract.py tests/unit/test_migration_runner.py tests/unit/storage/test_supabase_migrations.py -v
uv run mypy src/context_store/models/memory.py src/context_store/storage/sqlite.py src/context_store/storage/postgres.py
uv run ruff check src/context_store tests/unit/storage
```

Expected: PASS.

- [ ] **Step 5: Commit**

git add src/context_store/storage/migrations/ src/context_store/models/memory.py src/context_store/storage/sqlite.py src/context_store/storage/postgres.py src/context_store/storage/postgres_helpers.py src/context_store/storage/supabase.py src/context_store/storage/migrations/runner.py supabase/migrations/20261006000003_opencode_durable_ingestion.sql tests/unit/storage/test_ingestion_schema_contract.py tests/unit/test_migration_runner.py tests/unit/storage/test_supabase_migrations.py
git commit -m "feat: durable ingestion schema と memory ingestion_revision を追加"
```

---

### Task 3: Build ingestion-keyring primitives

**Files:**
- ChronosGraph — Create: `src/context_store/security/ingestion_keyring.py`
- ChronosGraph — Create: `tests/unit/security/test_ingestion_keyring.py`

**Interfaces:**
- Consumes: approved spec §2, Task 1 `SourceBindingWire`/`CandidateSourceBindingWire` shape.
- Produces:
  - `IngestionKeyring` parsed from a local JSON file (path from `CHRONOS_INGESTION_KEYRING_PATH`).
  - `KeyPair` with `key_id`, `generation`, `algorithm`, `sealed_key_material` (never leaves keyring module).
  - `KeyFingerprint` and public `key_version` strings derived only from non-secret material.
  - `IngestionKeyringProvider.reload()` returns current-or-new instance and reports `keyring_generation`.
  - `verify_source_binding(scope_id, binding, keyring)` uses candidate scope and keyed MAC; returns `VerifyBindingResult` with `valid: bool`, `code`, `current_generation`.
  - `compute_binding_mac(scope_id, key)` returns deterministic token for `SourceBindingWire.token`. The MAC tuple is `(binding_schema_version, issuer="chronos-graph", canonical_source_scope_id)`; mutable routing evidence such as project/directory/workspace/path aliases is deliberately excluded per spec §5.9.
  - Errors raise `IngestionKeyringError`; never log or return raw key bytes.

- [ ] **Step 1: Write RED keyring tests**

Test file parsing, generation ordering, fingerprint/version derivation, binding MAC round-trip, tampered binding rejection, unknown key version, promotion/retirement reference checks, and raw-key non-exposure (no `__dict__` leak, no str/logging leak).

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/security/test_ingestion_keyring.py -v`

Expected: FAIL; module missing.

- [ ] **Step 3: Implement keyring module**

No persistence here; only parsing/verification/derivation. Keep cryptography explicit (HMAC-SHA256 for binding tokens over the fixed tuple `(binding_schema_version, issuer, canonical_source_scope_id)`).

- [ ] **Step 4: Run GREEN**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/security/test_ingestion_keyring.py -v && uv run mypy src/context_store/security/ingestion_keyring.py && uv run ruff check src/context_store/security tests/unit/security`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GRAPH_ROOT"
git add src/context_store/security/ingestion_keyring.py tests/unit/security/test_ingestion_keyring.py
git commit -m "feat: ingestion keyring primitives を追加"
```

---

### Task 4: Add prepared-turn dedupe planning

**Files:**
- ChronosGraph — Create: `src/context_store/ingestion/durable/models.py`
- ChronosGraph — Create: `src/context_store/ingestion/durable/planner.py`
- ChronosGraph — Create: `tests/unit/ingestion/durable/test_planner.py`

**Interfaces:**
- Consumes: spec §§1, 4, 5; Task 1 enums.
  - `PreparedTurn`, `PreparedSourceMutation`, `DedupePlan`, `CanonicalMatch`, `ResolvedAliasMatch`, `AliasConflict`, `NewSourceScope` domain models. `PreparedSourceMutation` fields: `classification` (one of `BACKFILL`/`NEW_SCOPE`/`MIGRATE_ALIAS`/`CONFLICT`/`NO_MATCH`), `canonical_source_scope_id` (optional), `alias_id` (optional), `planned_generation` (int), `candidate_binding` (`CandidateSourceBindingWire` | None). No raw key bytes.
  - `PreparedTurn` carries `prepared_embeddings: tuple[EmbeddingVector, ...] | None` so that COMMIT performs **zero** embedding/model/network calls. `PreparedTurn` does **not** include `graph_intent`; graph intent is produced by the Graph-side `DurableIngestionService` during PREPARE (Task 8) and passed internally to COMMIT (Task 5/6). The OpenCode runtime never constructs or transmits `graph_intent`.
  - `DurableGraphIntent` is a JSON-serializable value produced during PREPARE by `DurableIngestionService.build_graph_intent(prepared_turn, existing_receipt_hint)`. It contains a list of graph edges to create and any vertex properties to set. When `GRAPH_ENABLED=true`, a missing or incomplete `DurableGraphIntent` causes COMMIT to fail fast with `TERMINAL_FAILED` and no mutation. When `GRAPH_ENABLED=false`, `DurableGraphIntent` may be `None` and the intent/outbox row is skipped.
- [ ] **Step 1: RED tests for planner**

Cover exact dedupe classifications (`BACKFILL`, `NEW_SCOPE`, `MIGRATE_ALIAS`, `CONFLICT`, `NO_MATCH`), stale-generation rollback, alias migration planning, conflict cases, `PreparedSourceMutation` field contract, and JSON-serializability.

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/ingestion/durable/test_planner.py -v`

Pure logic; no I/O, no embedding. `PreparedTurn` does not include `graph_intent`; graph intent generation is a Task 8 service responsibility.

- [ ] **Step 4: Run GREEN**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/ingestion/durable/test_planner.py -v && uv run mypy src/context_store/ingestion/durable && uv run ruff check src/context_store/ingestion/durable tests/unit/ingestion/durable`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GRAPH_ROOT"
git add src/context_store/ingestion/durable/models.py src/context_store/ingestion/durable/planner.py tests/unit/ingestion/durable/test_planner.py
git commit -m "feat: durable ingestion dedupe planner を追加"
```

---

### Task 5: Implement SQLite durable-ingestion authority store

**Files:**
- ChronosGraph — Create: `src/context_store/storage/ingestion/protocols.py`
- ChronosGraph — Create: `src/context_store/storage/ingestion/sqlite.py`
- ChronosGraph — Create: `tests/integration/storage/test_ingestion_authority_sqlite.py`

**Interfaces:**
- Consumes: Tasks 2, 4; Task 1 wire models.
- Produces:
  - `IngestionCommitStore` protocol with `prepare_source_mutation`, `commit_turn`, `list_receipt_roots`, `list_receipts`, `lookup_receipts`, `validate_receipts`, `current_manifest_generation`.
  - SQLite implementation with explicit `BEGIN IMMEDIATE` and short transactions; embedding/model work done **outside** transactions.
  - If `GRAPH_ENABLED=true` and the commit's `graph_intent` is `None`/incomplete, COMMIT fails fast with `TERMINAL_FAILED` before writing anything.
  - Returns `TurnIngestWireResult`/`ReceiptPage`/etc. from Task 1 with `memory_id` populated for new memories and `None` for idempotent/dedupe results.
  - `STALE_DEDUPE_PLAN`/`KEYRING_GENERATION_CHANGED` surfaced as retryable.

Test happy-path commit, idempotency, duplicate detection, stale plan, key-generation mismatch, lost-ACK recovery, partial-mutation injection, atomic durable graph intent/outbox persistence, and fail-fast when graph mode is enabled without a complete durable intent.

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/integration/storage/test_ingestion_authority_sqlite.py -v`

Expected: FAIL, missing store.

Use aiosqlite. COMMIT writes the receipt, memory, and `durable_graph_intents` row in one transaction. Keep embedding provider out of the transaction.

- [ ] **Step 4: Run GREEN**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/integration/storage/test_ingestion_authority_sqlite.py -v && uv run mypy src/context_store/storage/ingestion/sqlite.py && uv run ruff check src/context_store/storage/ingestion tests/integration/storage`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: SQLite durable ingestion authority store を追加"
```

---

### Task 6: Implement PostgreSQL/Supabase durable-ingestion authority stores

**Files:**
- ChronosGraph — Create: `src/context_store/storage/ingestion/postgres.py`
- ChronosGraph — Create: `src/context_store/storage/ingestion/supabase.py`
- ChronosGraph — Create: `tests/integration/storage/test_ingestion_authority_postgres.py`
- ChronosGraph — Create: `tests/integration/storage/test_ingestion_authority_supabase.py`
- ChronosGraph — Modify: `supabase/migrations/20261006000004_opencode_durable_rpc.sql` — durable RPC only (no `memory_graph_edges`).

**Interfaces:**
- Consumes: Task 5 protocol; Task 1 wire models.
- Produces:
  - asyncpg implementation matching SQLite semantics, including atomic durable graph intent/outbox persistence and graph-mode fail-fast.
  - Supabase implementation using PostgREST RPC; migration adds durable RPC functions inside a single Supabase transaction.
  - Same atomicity/invariant surface as SQLite.

Same scenario coverage as SQLite plus backend-specific failure injection. Distinguish two cases:
  - **Pre-commit failure:** a network or RPC error before the backend commits the transaction must leave no partial receipt/memory/intent/outbox.
  - **Lost-ACK/post-commit response failure:** a network error after the backend has committed but before the client receives the response must be recoverable. The same `turn_key` + `canonical_source_scope_id` idempotency key is used to look up the existing receipt on retry; the retry must converge to `ALREADY_COMMITTED` and must not create a duplicate memory. Test this by injecting a response failure after commit and then reissuing the same `turn.ingest`.
Required env: `TEST_POSTGRES_DSN`, `TEST_SUPABASE_URL`, `TEST_SUPABASE_SERVICE_ROLE_KEY`. The tests use `pytest.fail` instead of `skip` when these env vars are absent **and** `CHRONOS_REQUIRE_EXTERNAL_BACKENDS=1` is set, so the Task 18 release gate cannot pass by skipping. Expected: FAIL on missing stores.

- [ ] **Step 3: Implement postgres and supabase stores**

No I/O inside DB locks. Supabase RPC must validate manifest fence before mutation.

- [ ] **Step 4: Run GREEN**

Run:
```bash
cd "$GRAPH_ROOT"
uv run pytest tests/integration/storage/test_ingestion_authority_postgres.py tests/integration/storage/test_ingestion_authority_supabase.py -v
uv run mypy src/context_store/storage/ingestion/postgres.py src/context_store/storage/ingestion/supabase.py
uv run ruff check src/context_store/storage/ingestion tests/integration/storage
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: PostgreSQL/Supabase durable ingestion authority stores を追加"
```

---

### Task 7: Add ingestion-keyring admin CLI

**Files:**
- ChronosGraph — Create: `src/context_store/admin/ingestion_keyring.py`
- ChronosGraph — Create: `src/context_store/admin/__main__.py`
- ChronosGraph — Modify: `pyproject.toml`
- ChronosGraph — Create: `tests/integration/admin/test_ingestion_keyring_admin.py`

**Interfaces:**
- Consumes: spec §2; Task 3 primitives; Task 2 manifest table.
- Produces:
  - `pyproject.toml` adds `context-store-admin = "context_store.admin.__main__:main"`.
  - `src/context_store/config.py` adds `CHRONOS_INGESTION_KEYRING_PATH: Path | None`, validates that the path is absolute when set, and loads it into the private control composition root (Task 9) via `Settings`.
  - `tests/unit/test_config.py` adds RED/GREEN assertions for parsing/validation of `CHRONOS_INGESTION_KEYRING_PATH` (unset, valid absolute path, relative path rejected, non-existent path allowed because the file may be staged after process start).

Cover provision idempotency, verify mismatch, promotion retains previous generation, promotion generation CAS failure, retirement blocked while receipts/tokens/bindings reference the generation, retirement succeeds only when unreferenced, raw-key non-exposure, and manifest-fence ordering.

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/integration/admin/test_ingestion_keyring_admin.py -v`

Expected: FAIL; CLI missing.

Use `argparse`. Add `CHRONOS_INGESTION_KEYRING_PATH` to `Settings`, wire it into the private control composition root so `IngestionKeyringProvider` receives the configured path, and keep DB writes short and serializable.

- [ ] **Step 4: Run GREEN**

Run:
```bash
cd "$GRAPH_ROOT"
uv run pytest tests/integration/admin/test_ingestion_keyring_admin.py tests/unit/test_config.py -v
uv run mypy src/context_store/admin src/context_store/config.py
uv run ruff check src/context_store/admin src/context_store/config.py tests/integration/admin tests/unit/test_config.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GRAPH_ROOT"
git add src/context_store/admin/ingestion_keyring.py src/context_store/admin/__main__.py src/context_store/config.py pyproject.toml tests/integration/admin/test_ingestion_keyring_admin.py tests/unit/test_config.py
git commit -m "feat: ingestion keyring admin CLI を追加"

---

### Task 8: Add source/canonical/turn durable-ingestion service

**Files:**
- ChronosGraph — Create: `src/context_store/ingestion/durable/canonicalizer.py`
- ChronosGraph — Create: `src/context_store/ingestion/durable/service.py`
- ChronosGraph — Create: `src/context_store/storage/ingestion/factory.py`
- ChronosGraph — Create: `tests/unit/ingestion/durable/test_service.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 4, 5, 7.
- Produces:
  - **Payload hash contract:** `payload_hash = SHA-256(canonical_json(hash_input_object))` where `hash_input_object` is a versioned dict with fixed key order:
    ```json
    {"v":1,"turn_key":"T","canonical_source_scope_id":"S","evidence_contract_version":"V","semantic_projection":{...},"identity_evidence":{...}}
    ```
    `canonical_json` means: UTF-8 JSON, object keys sorted lexicographically, no insignificant whitespace, arrays preserved, `null` for missing/None optional fields, floats rendered as decimal with at least one digit after the point, Unicode characters left unescaped. The nested `semantic_projection` and `identity_evidence` values are themselves canonicalized before being placed in `hash_input_object`, so the final input is a single well-defined JSON object. This rule is applied identically by Python and JavaScript implementations;
  - **Durable graph intent contract:** during PREPARE, `DurableIngestionService.build_graph_intent(prepared_turn, existing_receipt_hint)` returns a `DurableGraphIntent` value. When `GRAPH_ENABLED=true`, a `None` or structurally incomplete intent causes `ingest_turn` to return `TERMINAL_FAILED` with no database mutation. When `GRAPH_ENABLED=false`, the intent may be `None` and no intent/outbox row is written. The intent is passed to `commit_turn` as an internal argument (not on the wire) and stored atomically with the receipt/memory in `durable_graph_intents`.
  - **Idempotency comparison:** the service compares the candidate turn's `payload_hash` against the stored receipt's `payload_hash`. Because `identity_evidence` is key-independent and `turn_key` is stable across resumption (Task 12), the same turn submitted with a binding issued under a promoted key K2 still yields the same `payload_hash` and matches the receipt created under K1.
Test source resolution, alias migration, turn commit/idempotency, retryable reasons, terminal divergence, key-promotion idempotency (resubmit with new active binding → `ALREADY_COMMITTED`, original `payload_hash`), retired-key `IDEMPOTENCY_REBASE_UNAVAILABLE`, and graph-mode fail-fast when `build_graph_intent` returns `None`/incomplete.
Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/ingestion/durable/test_service.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement service + canonicalizer + factory**

Factory selects store by `STORAGE_BACKEND`. Canonicalizer delegates binding verification to Task 3. Implement `build_graph_intent` and wire the internal `graph_intent` argument from PREPARE to COMMIT.

- [ ] **Step 4: Run GREEN**

Run:
```bash
cd "$GRAPH_ROOT"
uv run pytest tests/unit/ingestion/durable/test_service.py -v
uv run mypy src/context_store/ingestion/durable/canonicalizer.py src/context_store/ingestion/durable/service.py src/context_store/storage/ingestion/factory.py
uv run ruff check src/context_store/ingestion/durable src/context_store/storage/ingestion tests/unit/ingestion/durable
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GRAPH_ROOT"
git add src/context_store/ingestion/durable/canonicalizer.py src/context_store/ingestion/durable/service.py src/context_store/storage/ingestion/factory.py tests/unit/ingestion/durable/test_service.py
git commit -m "feat: durable ingestion service と canonicalizer を追加"
```

---

### Task 9: Add private Graph control server

**Files:**
- ChronosGraph — Create: `src/context_store/control/composition.py`
- ChronosGraph — Create: `src/context_store/control/server.py`
- ChronosGraph — Create: `src/context_store/control/__main__.py`
- ChronosGraph — Create: `src/context_store/graph/intent_worker.py`
- ChronosGraph — Modify: `src/context_store/storage/sqlite.py`, `src/context_store/storage/postgres.py`, `src/context_store/storage/supabase.py` — add graph edge upsert helpers.
- ChronosGraph — Modify: `pyproject.toml`
- ChronosGraph — Create: `tests/integration/test_control_server.py`
- ChronosGraph — Create: `tests/integration/graph/test_intent_worker.py`

**Interfaces:**
- Consumes: Tasks 1, 8; spec §8.
- Produces:
  - `DurableGraphIntentWorker` polls `durable_graph_intents` for unprocessed rows and materializes graph edges. The worker is started/stopped with the control server lifecycle. The `memory_graph_edges` table is created by the follow-up migration `0005_opencode_graph_intent_edges.sql` (SQLite/PostgreSQL) and `20261006000005_opencode_graph_intent_edges.sql` (Supabase); Task 9 tests run all migrations up to the latest version before asserting worker behavior.
  - Graph edge upserts go through `src/context_store/graph/edges.py` into `memory_graph_edges` with a unique constraint on `(intent_id, edge_relationship, target_memory_id)`; duplicate processing after a crash, restart, or concurrent worker race does not create duplicate edges. After the graph upsert succeeds, the worker marks the intent processed with a CAS on `processed_at`/`processed_attempts`; if the CAS fails because another worker already processed it, the DB-level unique constraint makes the upsert harmless.
- [ ] **Step 1: RED control-server tests**

Test stdio request/response framing, unknown method rejection, protocol/version mismatch, operation dispatch round-trip, durable graph intent worker start/stop/resume, idempotent intent processing, crash-after-mutation-before-CAS recovery, concurrent worker race producing no duplicate graph edges, and no direct network in COMMIT path.

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/integration/test_control_server.py tests/integration/graph/test_intent_worker.py -v`

Expected: FAIL; modules missing.

Use asyncio stdin/stdout. Validate `CONTROL_PROTOCOL` and request-id. Implement `DurableGraphIntentWorker` and graph edge upsert helpers.

- [ ] **Step 4: Run GREEN**

Run:
```bash
cd "$GRAPH_ROOT"
uv run pytest tests/integration/test_control_server.py tests/integration/graph/test_intent_worker.py -v
uv run mypy src/context_store/control src/context_store/graph
uv run ruff check src/context_store/control src/context_store/graph tests/integration/test_control_server.py tests/integration/graph/test_intent_worker.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GRAPH_ROOT"
git add src/context_store/control/ src/context_store/graph/ src/context_store/storage/migrations/ src/context_store/storage/sqlite.py src/context_store/storage/postgres.py src/context_store/storage/supabase.py supabase/migrations/ pyproject.toml tests/integration/test_control_server.py tests/integration/graph/test_intent_worker.py
git commit -m "feat: private Graph control server と durable graph intent worker を追加"

---

### Task 10: Strengthen ChronosGate MCP session auth

**Files:**
- ChronosGate — Modify: `src/chronos_gate/auth/handshake.py`
- ChronosGate — Modify: `src/chronos_gate/server.py`
- ChronosGate — Create: `tests/test_session_bound_messages.py`

**Interfaces:**
- Consumes: Task 1 `RESERVED_CONTROL_PRINCIPALS`.
- Produces:
  - Regular MCP `/messages` enforces Bearer token present and resolves to a session owner; the resolved principal **must equal** the session owner; requests with a valid token belonging to a different principal return 403.
  - Existing legacy principal `default` still authenticates regular MCP.

Run: `cd "$GATE_ROOT" && uv run --no-sync pytest tests/test_session_bound_messages.py -v`

Expected: FAIL on new auth expectations.
Before running this RED, install the current Graph worktree editable into the Gate environment so `chronos_shared.opencode_control` is available:

```bash
cd "$GATE_ROOT"
uv sync --extra dev
uv --directory "$GATE_ROOT" pip install -e "$GRAPH_ROOT"
uv run --no-sync python -c 'import chronos_shared.opencode_control; assert chronos_shared.opencode_control.__file__.startswith("'$GRAPH_ROOT'")'
```

Keep changes localized to handshake and server message handler. Run the editable-install preparation commands above before the RED/GREEN steps.

Run:
```bash
cd "$GATE_ROOT"
uv run --no-sync pytest tests/test_session_bound_messages.py -v
uv run --no-sync mypy src/chronos_gate/auth/handshake.py src/chronos_gate/server.py
uv run --no-sync ruff check src/chronos_gate tests/test_session_bound_messages.py
uv run --no-sync python -c 'import chronos_shared.opencode_control; assert chronos_shared.opencode_control.__file__.startswith("'$GRAPH_ROOT'")'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GATE_ROOT"
git add src/chronos_gate/auth/handshake.py src/chronos_gate/server.py tests/test_session_bound_messages.py
git commit -m "feat: ChronosGate session-bound MCP auth を強化"
```

---

### Task 11: Add ChronosGate control plane

**Files:**
- ChronosGate — Create: `src/chronos_gate/control/client.py`
- ChronosGate — Create: `src/chronos_gate/control/http.py`
- ChronosGate — Modify: `src/chronos_gate/server.py`
- ChronosGate — Modify: `src/chronos_gate/config.py`
- ChronosGate — Modify: `src/chronos_gate/app.py`
- ChronosGate — Create: `tests/test_control_client.py`
- ChronosGate — Create: `tests/test_opencode_control_endpoint.py`

**Interfaces:**
- Consumes: Tasks 1, 9; Task 10 auth.
- Produces:
  - `/internal/v1/opencode/control` capability matrix:
    | Operation | Allowed credential | Notes |
    |---|---|---|
    | `source.resolve` | control (`opencode-ingestion`) | read-only; must not mutate aliases/tokens |
    | `source.register` | operator (`chronos-setup`) | creates new source scope |
    | `source.authorize_alias_migration` | operator (`chronos-setup`) | migrates alias to canonical scope |
    | `source.backfill_alias` | operator (`chronos-setup`) | backfills existing alias token |
    | `receipt.list_roots` | control (`opencode-ingestion`) | read-only inventory |
    | `receipt.list` | control (`opencode-ingestion`) | read-only inventory |
    | `receipt.lookup` | control (`opencode-ingestion`) | read-only inventory |
    | `receipt.validate` | control (`opencode-ingestion`) | read-only validation |
    | `turn.ingest` | control (`opencode-ingestion`) | durable turn commit |
    | all control methods | legacy (`default`) | denied (403) |
    | all regular MCP methods | control/operator | denied (403) |
  - The control client subprocess is launched with a **strict environment allowlist** that includes: storage backend (`STORAGE_BACKEND`, `DATABASE_URL`, `SQLITE_PATH`, `SQLITE_VEC_PATH`), Supabase/Postgres connection (`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `TEST_SUPABASE_URL`, `TEST_SUPABASE_SERVICE_ROLE_KEY`, `TEST_POSTGRES_DSN`), graph mode (`GRAPH_ENABLED`, `GRAPH_BACKEND`, `NEO4J_*`, `NEO4J_URI`), embedding (`OPENAI_API_KEY`, `EMBEDDING_*`), keyring (`CHRONOS_INGESTION_KEYRING_PATH`), logging, and uv/Python runtime variables. **Gate credentials (`MCP_GATEWAY_*`) and the Gate HTTP port/listen config are explicitly stripped** so the private Graph control process cannot impersonate Gate or leak control/operator credentials. The subprocess inherits the Gate virtualenv but not the Gate service environment.
Before running this RED, ensure the current Graph worktree is installed editable into the Gate environment:

```bash
cd "$GATE_ROOT"
uv sync --extra dev
uv --directory "$GATE_ROOT" pip install -e "$GRAPH_ROOT"
uv run --no-sync python -c 'import chronos_shared.opencode_control; assert chronos_shared.opencode_control.__file__.startswith("'$GRAPH_ROOT'")'
```

Then run:
`cd "$GATE_ROOT" && uv run --no-sync pytest tests/test_control_client.py tests/test_opencode_control_endpoint.py -v`
Expected: FAIL on missing control plane.
Cover client start/stop, method routing, HTTP 401/403 for wrong credentials, control operation round-trip, operator-only source enrollment paths, control credential denied on operator-only methods, startup duplicate-credential rejection, read-only `source.resolve` behavior, capability matrix denial tests for every non-allowed (credential, operation) pair, subprocess environment isolation (Gate credentials stripped, allowlist enforced in both editable and locked modes), and concurrent request safety.
The control client launches `context-store-control` as a subprocess with the strict environment allowlist and speaks JSON-RPC. HTTP layer maps to Task 1 operations and enforces the operator/control method allowlist. Add a config switch `CHRONOS_GRAPH_CONTROL_FROM_LOCKED` (default 0); when set, the Gate launches `uv run --frozen context-store-control` from the locked Graph dependency instead of the editable worktree executable used in development. In both modes the subprocess must receive only the allowlisted environment; verify this with a dedicated test.
Run:
```bash
cd "$GATE_ROOT"
uv run --no-sync pytest tests/test_control_client.py tests/test_opencode_control_endpoint.py -v
uv run --no-sync mypy src/chronos_gate/control src/chronos_gate/app.py src/chronos_gate/config.py src/chronos_gate/server.py
uv run --no-sync ruff check src/chronos_gate tests/test_control_client.py tests/test_opencode_control_endpoint.py
uv run --no-sync python -c 'import chronos_shared.opencode_control; assert chronos_shared.opencode_control.__file__.startswith("'$GRAPH_ROOT'")'
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GATE_ROOT"
git add src/chronos_gate/control src/chronos_gate/server.py src/chronos_gate/config.py src/chronos_gate/app.py tests/test_control_client.py tests/test_opencode_control_endpoint.py
git commit -m "feat: ChronosGate OpenCode control plane を追加"
```

---

### Task 12: Implement deterministic OpenCode v1.18.34 turn extraction

**Files:**
- ChronosGraph — Create: `.opencode/plugins/chronos/canonicalize.js`
- ChronosGraph — Create: `.opencode/plugins/chronos/lineage.js`
- ChronosGraph — Create: `.opencode/plugins/chronos/control-client.js`
- ChronosGraph — Create: `tests/integration/opencode/test_canonicalize.cjs`
- ChronosGraph — Create: `tests/integration/opencode/test_lineage.cjs`

**Interfaces:**
- Consumes: spec §3; opencode-ai@1.18.34 internal message shapes.
- Produces:
  - Deterministic extraction of user anchor, assistant response, tool results, child-session events, compaction continuation, overflow replay, and synthetic shell/control messages.
  - **Eligible turn contract:** a turn is eligible for durable ingestion only when it is owned by a **root** OpenCode session and ends with a deterministic terminal status. The user anchor is the first user message in the root session that has not yet been committed. A root session is identified by `root_session_id` being equal to the session's own stable ID (child sessions have a non-root `root_session_id`). Eligible terminal statuses are `SUCCESS`, `FAILED` (provider/tool error), and `ABORTED` (user-initiated abort). Synthetic inputs (file-only turns with no user message, shell/control messages not authored by the user, AgentPart/SubtaskPart continuation messages, overflow replay markers, and compaction continuation frames) are **not** eligible as user anchors but must be captured inside `semantic_projection` so that history changes affecting the turn are detected by `receipt.validate`.
  - **Turn key derivation:** `turn_key` is derived from immutable OpenCode native identifiers only, so it is recoverable from an empty or corrupted local state. `turn_key = canonical_source_scope_id + ":" + root_session_id + ":" + user_message_id + ":" + lineage_hash` where `lineage_hash = SHA-256(canonical_json(lineage_vector))`. `lineage_vector` is the ordered list of `(root_session_id, user_message_id)` pairs for the eligible user anchor and every immediately preceding eligible user anchor in the same root session, truncated to the last 32 entries for compaction resistance. `user_message_id` is OpenCode's stable native message ID for the user anchor. The derivation uses **only** native IDs, not local `committed_turns`;
  therefore reconstituting the local state from scratch or recovering a missing earlier turn does not change `turn_key`.

Use fixed v1.18.34 fixtures (or minimal synthetic objects where native loader unavailable). Cover normal success, failed, aborted, child events, compaction, overflow, file-only, AgentPart/SubtaskPart. For each fixture, assert the exact `turn_key`, `semantic_projection`, and `identity_evidence` JSON values; assert that resubmitting the same fixture after a no-op change produces identical outputs; assert that compaction, history rebase, or adding/removing a synthetic context changes either `turn_key` or the payload hash; assert that child-session events do not produce a separate eligible user anchor; assert that the same fixture with an empty/corrupt local state reproduces the same `turn_key` and converges to `ALREADY_COMMITTED` when the receipt already exists.

Run:
```bash
cd "$GRAPH_ROOT"
node --test tests/integration/opencode/test_canonicalize.cjs tests/integration/opencode/test_lineage.cjs
Expected: FAIL; modules missing.

- [ ] **Step 3: Implement canonicalizer + lineage modules**

No external I/O. Keep extraction rules explicit and versioned. Implement the eligible turn contract, turn key derivation, `semantic_projection` JSON shape, and `identity_evidence` JSON shape described in the Interfaces above.
```bash
cd "$GRAPH_ROOT"
node --test tests/integration/opencode/test_canonicalize.cjs tests/integration/opencode/test_lineage.cjs
```

Expected: FAIL; modules missing.

- [ ] **Step 3: Implement canonicalizer + lineage modules**

No external I/O. Keep extraction rules explicit and versioned.

- [ ] **Step 4: Run GREEN**

Run the same node --test command plus `uv run ruff check .opencode/plugins/chronos` (if Python wrappers exist).

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GRAPH_ROOT"
git add .opencode/plugins/chronos/canonicalize.js .opencode/plugins/chronos/lineage.js .opencode/plugins/chronos/control-client.js tests/integration/opencode/test_canonicalize.cjs tests/integration/opencode/test_lineage.cjs
git commit -m "feat: OpenCode v1.18.34 extraction helpers を追加"
```

---

### Task 13: Add source scope, local state, and lock modules

**Files:**
- ChronosGraph — Create: `.opencode/plugins/chronos/source-scope.js`
- ChronosGraph — Create: `.opencode/plugins/chronos/state-store.js`
- ChronosGraph — Create: `.opencode/plugins/chronos/lock.js`
- ChronosGraph — Create: `tests/integration/opencode/test_source_scope.cjs`
- ChronosGraph — Create: `tests/integration/opencode/test_state_store.cjs`
- ChronosGraph — Create: `tests/integration/opencode/test_lock.cjs`
**Interfaces:**
- Consumes: spec §§4-5; Task 1 control operations.
- Produces:
  - `source-scope.js` calls `source.resolve` with the control credential and caches the returned binding. If `source.resolve` returns `UNRESOLVED` or `NOT_READY`, the plugin stops durable ingestion for this turn **without side effects**; it must **not** call `source.register` or `source.authorize_alias_migration` itself. Source registration and alias migration are operator-only actions performed through the setup path (Task 16) using the operator credential.
  - `state-store.js` persists `LocalSourceStateV1` to `source.json` and `CheckpointStateV1` to `checkpoint.json` atomically using write-then-rename; restart refreshes from receipt inventory. `source.json` fields: `canonical_source_scope_id`, `binding` (`SourceBindingWire` token/key_version, never raw key), `alias_schema_version`. `checkpoint.json` fields: `committed_turns: tuple[CheckpointEntry, ...]`, `pending_turn_key: str | None`, `pending_since: int | None` (Unix ms).
Run:
```bash
cd "$GRAPH_ROOT"
node --test tests/integration/opencode/test_source_scope.cjs tests/integration/opencode/test_state_store.cjs tests/integration/opencode/test_lock.cjs
```

Expected: FAIL; modules missing.

Use Node fs/promises and proper-lockfile-like behavior. No network in state writes.

- [ ] **Step 4: Run GREEN**

Run:
```bash
cd "$GRAPH_ROOT"
node --test tests/integration/opencode/test_source_scope.cjs tests/integration/opencode/test_state_store.cjs tests/integration/opencode/test_lock.cjs
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GRAPH_ROOT"
git add .opencode/plugins/chronos/source-scope.js .opencode/plugins/chronos/state-store.js .opencode/plugins/chronos/lock.js tests/integration/opencode/
git commit -m "feat: OpenCode source scope, state store, lock helpers を追加"
```

---

### Task 14: Implement reconciler and recovery

**Files:**
- ChronosGraph — Create: `.opencode/plugins/chronos/reconciler.js`
- ChronosGraph — Create: `.opencode/plugins/chronos/runtime.js`
- ChronosGraph — Create: `tests/integration/opencode/test_reconciler.cjs`
- ChronosGraph — Create: `tests/integration/opencode/test_recovery.cjs`
- ChronosGraph — Create: `tests/integration/opencode/test_divergence.cjs`
**Interfaces:**
- Consumes: Tasks 12-13; Task 1 result kinds/retry reasons.
- Produces:
  - Reconciler processes turn-end events, performs 60-second correctness sweep, contiguous checkpointing, and recovers lost ACK/corrupt state via `receipt.list`/`receipt.lookup`. The confirmed checkpoint prefix is the longest prefix of eligible turns (ordered by `(source_cursor_created_at, root_session_id, turn_key)`) where every earlier eligible turn is either present in the receipt inventory or still pending within the timeout. A gap is detected when the OpenCode-side eligible-turn enumeration (from native history) contains a turn older than the current checkpoint prefix that is **not** present in `committed_turns` and not in `pending_turn_key`; the reconciler pauses advancing the checkpoint and issues `turn.ingest` for the missing eligible turn(s) before accepting new turns.
Run:
```bash
cd "$GRAPH_ROOT"
node --test tests/integration/opencode/test_reconciler.cjs tests/integration/opencode/test_recovery.cjs tests/integration/opencode/test_divergence.cjs
Expected: FAIL; modules missing.
- [ ] **Step 3: Implement reconciler + runtime**

Runtime wires canonicalizer, source-scope, state-store, lock, control-client, reconciler. Keep side effects explicit. The OpenCode runtime must not construct or consume `graph_intent`; Graph-side worker owns materialization.

Run:
```bash
node --test tests/integration/opencode/test_reconciler.cjs tests/integration/opencode/test_recovery.cjs tests/integration/opencode/test_divergence.cjs
uv run ruff check .opencode/plugins/chronos
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GRAPH_ROOT"
git add .opencode/plugins/chronos/reconciler.js .opencode/plugins/chronos/runtime.js tests/integration/opencode/test_reconciler.cjs tests/integration/opencode/test_recovery.cjs tests/integration/opencode/test_divergence.cjs
git commit -m "feat: OpenCode durable reconciler と runtime を追加"
```

---

### Task 15: Wire loader-only plugin and package runtime

**Files:**
- ChronosGraph — Modify: `package.json` (root) if needed for npm pack

**Interfaces:**
- Consumes: Tasks 12-14.
- Produces:
  - `.opencode/plugins/chronos-turn-end.js` is updated to be a loader-only adapter that imports runtime from `chronos/` submodules.
  - npm package `@yohi/opencode-plugin-chronos-turn-end` exposes the same loader via `package.json`.
  - Root `package.json` `files` list and `tests/unit/test_chronos_gate_migration_guards.py` exact-files assertion are updated to include the new `.opencode/plugins/chronos/` runtime modules and the loader adapter; otherwise `npm pack` omits required files or the guard test fails. No new agent config directory is created; `.opencode/plugins/` is an existing repository-owned path.

Cover root activation, child no-op, npm pack install, local plugin path, `files` list correctness through the existing migration guard, and negative invariants (memory_save==0, session_flush==0, detached hook==0).

Run:
```bash
cd "$GRAPH_ROOT"
node --test tests/integration/test_opencode_turn_end_plugin.cjs
```

Expected: FAIL; module missing.

Keep the top-level plugin minimal; delegate to runtime. Update root `package.json` `files` and `tests/unit/test_chronos_gate_migration_guards.py` expectations so the new runtime modules are included and the guard passes.

- [ ] **Step 4: Run GREEN**

Run the same node --test command.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GRAPH_ROOT"
git add .opencode/plugins/chronos-turn-end.js .opencode/plugins/chronos/package.json .opencode/plugins/chronos/*.js tests/integration/test_opencode_turn_end_plugin.cjs tests/unit/test_chronos_gate_migration_guards.py package.json
git commit -m "feat: OpenCode turn-end loader plugin と package runtime を追加"
```

---

### Task 16: Integrate durable setup and smoke

**Files:**
- ChronosGraph — Modify: `scripts/bootstrap.sh`
- ChronosGraph — Modify: `scripts/agent_assets/hooks.py` (update the legacy hook to reference the new loader-only plugin path `@yohi/opencode-plugin-chronos-turn-end` for all-mode, keep selective mode intact, and update npm registry validation to cover the package runtime)
- ChronosGraph — Modify: `.env.example`
- ChronosGraph — Modify: `docs/agent-setup-protocol.md`
- ChronosGraph — Create/Modify: `tests/unit/test_sync_agent_assets.py`
- ChronosGraph — Create/Modify: `tests/integration/test_sync_agent_assets.py`
- ChronosGraph — Create: `tests/integration/test_opencode_durable_setup.py`

**Interfaces:**
- Consumes: Tasks 7, 11, 15. The setup-auth integration test also requires `GATE_ROOT` pointing at the Task 11 ChronosGate worktree and uses that worktree's current-Graph editable `uv run --no-sync` environment.
- Produces:
  - distinct documented `MCP_GATEWAY_API_KEY`, `MCP_GATEWAY_CONTROL_API_KEY`, `MCP_GATEWAY_OPERATOR_API_KEY`.
  - bootstrap owns three **managed** `MCP_GATEWAY_API_KEYS_JSON` principal entries while preserving unrelated valid existing entries:
    - `"default" -> MCP_GATEWAY_API_KEY` for the legacy regular-MCP compatibility principal used by existing hooks;
    - `"opencode-ingestion" -> MCP_GATEWAY_CONTROL_API_KEY`;
    - `"chronos-setup" -> MCP_GATEWAY_OPERATOR_API_KEY`.
  - existing `MCP_GATEWAY_API_KEYS_JSON` is parsed as JSON before mutation; malformed/non-object JSON fails setup without overwrite. Managed principal entries are replaced from the three managed env values; every unrelated principal/key entry is preserved verbatim.
  - on a normal all-mode setup, missing managed raw values are generated independently and existing managed values are retained. `--rotate-keys` rotates **all three managed Gate credentials together**, rewrites the three managed registry entries, and preserves unrelated entries. Partial managed rotation is not supported by bootstrap.
  - all three managed raw values must be pairwise distinct and must not duplicate any preserved registry value; otherwise setup fails before writing, matching `ApiKeyAuthenticator` duplicate-key authority.
  - setup verifies `context-store-admin ingestion-keyring verify`.
  - bootstrap never generates/distributes ingestion key material. For all-mode production, `CHRONOS_INGESTION_KEYRING_PATH` must already point to an operator/secret-manager staged file.
  - existing manifests use `verify`;
  key promotion/retirement remain explicit operator `promote`/`retire` actions and are not implicit bootstrap behavior.
  - explicit source `REGISTER_NEW_SOURCE_SCOPE`/alias migration via operator control only.
  - OpenCode all-mode smoke creates a unique real turn, waits for receipt/checkpoint, and performs read-side verification. The receipt returned by `turn.ingest` (or looked up via `receipt.list`/`receipt.lookup`) MUST include a `memory_id` field when the commit produced a new memory, and MUST be `None` when the commit resolved to an already-committed receipt (`ALREADY_COMMITTED`) or to an existing deduplicated memory. The probe turn MUST embed a deterministic `probe_marker` (`chronos:smoke:<iso-now-utc>:<random-hex-8>`) in the user message content so that the saved memory can be unambiguously attributed to the probe and never confused with pre-existing user data.
  - cleanup may use only the exact `memory_id` captured from the probe's own receipt. If `memory_id` is `None` because the receipt was already committed or deduplicated, skip deletion and report `SMOKE_CLEANUP_NOT_REQUIRED`. If the setup context has an authorized exact-ID deletion capability (for example a regular MCP `memory_delete` call), use it only for the probe-owned `memory_id`; otherwise report `SMOKE_CLEANUP_INCOMPLETE`. Search-by-marker/broad deletion is forbidden.
  - setup never substitutes direct `memory_save`/`session_flush`/`ingest_turn` calls.

- [ ] **Step 1: Write RED setup tests**

Cover missing keyring/manifest, distinct credential requirement, unresolved source zero mutation, explicit new-source transition, local/npm plugin configuration preservation, smoke refusing to claim complete without real-turn receipt+readback, exact-ID-only cleanup, and `SMOKE_CLEANUP_INCOMPLETE` when exact deletion is unavailable. Add effective-registry tests that parse the generated `MCP_GATEWAY_API_KEYS_JSON` through the real Gate `ApiKeyAuthenticator` semantics and prove: legacy key authenticates as `default`, control key as `opencode-ingestion`, operator key as `chronos-setup`; all raw values are distinct; unrelated registry entries survive; malformed/duplicate registry input fails before write; `--rotate-keys` rotates all three managed entries together. The integration test invokes the Task 11 Gate environment through `uv --directory "$GATE_ROOT" run --no-sync`; missing `GATE_ROOT` is a test failure, not a skip. Reuse Scenario Y routing assertions so control/operator keys are denied on regular MCP and the legacy key is denied on the control endpoint.

- [ ] **Step 2: Run RED**

Run:
`cd "$GRAPH_ROOT" && GATE_ROOT="$GATE_ROOT" uv run pytest tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py tests/integration/test_opencode_durable_setup.py -v`

Expected: FAIL on new durable setup expectations.

Do not write `.npmrc`, generate ingestion key material, or accept raw ingestion keys as CLI arguments. For Gate API credentials, parse/preserve the existing principal registry, materialize the three managed env values, validate global raw-key uniqueness, then atomically rewrite the effective registry plus managed env values; `--rotate-keys` rotates the whole managed set only. If the staged ingestion keyring is absent/malformed, fail setup before source enrollment. If the keyring is valid and the manifest row is absent, invoke `context-store-admin ingestion-keyring provision`; otherwise invoke `verify`. Setup may invoke the Graph-local admin CLI but must not implement keyring DB/file mutation itself. In `scripts/agent_assets/hooks.py`, replace the legacy all-mode plugin registration path with the loader-only adapter and update npm registry validation to use the new package runtime.

- [ ] **Step 4: Update English/Japanese docs and config reference**

Keep selective instructions intact; document exact control/operator/keyring prerequisites and real-turn smoke.

- [ ] **Step 5: Run GREEN**

Run the same focused pytest command with `GATE_ROOT` plus `bash -n scripts/bootstrap.sh`.

Expected: PASS, including the real Gate `ApiKeyAuthenticator` principal mapping and Scenario Y path-separation assertions.

- [ ] **Step 6: Commit**

```bash
cd "$GRAPH_ROOT"
git add scripts/bootstrap.sh scripts/agent_assets/hooks.py .env.example docs   tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py tests/integration/test_opencode_durable_setup.py
git commit -m "feat: durable OpenCode setup と smoke を統合"
```

---

### Task 17: Add actual OpenCode v1.18.34 native acceptance with deterministic provider

**Files:**
- ChronosGraph — Create: `tests/native/opencode/fixture_provider.py`
- ChronosGraph — Create: `tests/native/opencode/harness.py`
- ChronosGraph — Create: `tests/native/opencode/test_native_opencode_all.py`
- ChronosGraph — Create: `tests/native/opencode/README.md`

**Interfaces:**
- Consumes: Tasks 11, 15-16.
- Produces:
  - local OpenAI-compatible deterministic provider configured via a generated **per-test OpenCode configuration file** placed inside the temporary project directory. This file is created by the harness at runtime, is not committed, and is not placed under any repository-level `.opencode/` config directory. Its contents are limited to the deterministic provider entry (`chronos-fixture` using npm `@ai-sdk/openai-compatible`, model `fixture-model`, local `baseURL=http://127.0.0.1:<fixture-port>/v1`, and a non-secret fixture API key) and the plugin identity;
  it does not create a new agent-level config directory. This is a test-only ephemeral artifact analogous to a temporary database file, not a repository-owned agent configuration file.
  - OpenCode model selection is exactly `chronos-fixture/fixture-model`.
  - npm-style mode builds the current implementation with `npm pack --json`, installs that tarball into the temporary project with `npm install --ignore-scripts <tarball>`, and configures OpenCode with plugin identity `@yohi/opencode-plugin-chronos-turn-end`; no package publication is required for acceptance.
  - repository-local mode loads the project-local `.opencode/plugins/chronos-turn-end.js`.
  - clean temp HOME/project/npm-path and repository-local plugin acceptance modes.
  - fixture scripts deterministic SUCCESS, provider-error FAILED, tool call, compaction pressure, and child/sub-agent behavior without external LLM credits.
  - ABORTED is produced by starting a deliberately long streaming fixture response and invoking OpenCode's session-abort path while generation is in flight; do not fake the persisted `MessageAbortedError` record.

The harness exposes `locked_mode` via a pytest CLI option or environment variable. Use `--chronos-locked-mode` (or env `CHRONOS_NATIVE_LOCKED_MODE=1`) to select `locked_mode=True`; absence selects editable development mode. `CHRONOS_GRAPH_CONTROL_FROM_LOCKED=1` additionally tells the Gate to launch its private control subprocess from the locked Graph package.
- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/native/opencode/test_native_opencode_all.py -k smoke -v`

Expected: FAIL until harness/config/plugin integration is complete.

At minimum execute:
  - normal success and failed/aborted;
  - event loss with periodic recovery;
  - real child session exists/events observed but child receipt/checkpoint/pending remain zero;
  - committed-history divergence scenarios I/J/K (removed turn, removed root session, changed prefix membership);
  - npm and local plugin path both show `memory_save==0`, `session_flush==0`, detached hook spawn==0.

- [ ] **Step 4: Add post-terminal Scenario AB**

Commit FAILED/ABORTED user-only receipt, resume same user anchor to success, assert immutable receipt + divergence, then a new eligible user anchor commits normally.

Run editable development mode:
uv run pytest tests/native/opencode/test_native_opencode_all.py -v
```

Expected: PASS using exact `opencode-ai@1.18.34`; no external provider/credit required. Locked-mode native acceptance is deferred to Task 18 because it requires the final pinned Graph SHA.

Expected: PASS using exact `opencode-ai@1.18.34`; no external provider/credit required. Locked-mode native acceptance is deferred to Task 18 because it requires the final pinned Graph SHA.

- [ ] **Step 6: Commit**

```bash
cd "$GRAPH_ROOT"
git add tests/native/opencode
git commit -m "test: OpenCode v1.18.34 native durable acceptance を追加"
```

---

### Task 18: Run cross-repository acceptance, pin the Gate dependency, and prepare the Plan Review Gate handoff

**Files:**
- ChronosGate — Modify: `pyproject.toml`
- ChronosGate — Modify: `uv.lock`
- ChronosGate — Create: `tests/test_graph_dependency_pin.py`
- ChronosGraph — Verify: all files/tasks above
- ChronosGate — Verify: all files/tasks above

**Interfaces:**
- Consumes: Tasks 1-17.
- Produces:
  - Scenario Y (credential/session/control isolation), Z (three-backend atomic COMMIT), AA (keyring admin/rotation concurrency), AB (post-terminal native behavior) all executable and green.
  - Gate direct-reference dependency pinned to the final ChronosGraph implementation commit produced by the completed Graph tasks.
  - clean implementation branches ready for separate code-review/merge workflow.

- [ ] **Step 1: Capture the completed Graph implementation SHA**

Run:
`GRAPH_IMPLEMENTATION_SHA="$(cd "$GRAPH_ROOT" && git rev-parse HEAD)" && printf '%s\n' "$GRAPH_IMPLEMENTATION_SHA"`

Expected: a 40-character SHA after all Graph implementation commits.

- [ ] **Step 2: Publish the Graph implementation review branch without merging**

Run: `cd "$GRAPH_ROOT" && git push origin HEAD`

Expected: the exact `$GRAPH_IMPLEMENTATION_SHA` is reachable from the remote review branch; do not merge it.

- [ ] **Step 3: Add the Gate dependency-pin RED guard**

Create `tests/test_graph_dependency_pin.py` to parse both `pyproject.toml` and tracked `uv.lock` with `tomllib`. Extract the Graph SHA from the direct `context-store-mcp @ git+...` dependency and the locked `context-store-mcp` Git source/revision; read required env `EXPECTED_CHRONOS_GRAPH_SHA`; assert **both** equal that exact 40-character SHA and equal each other.

- [ ] **Step 4: Run RED before updating Gate**

Run:
`cd "$GATE_ROOT" && EXPECTED_CHRONOS_GRAPH_SHA="$GRAPH_IMPLEMENTATION_SHA" uv run --no-sync pytest tests/test_graph_dependency_pin.py -v`

Expected: FAIL because Gate `pyproject.toml` and `uv.lock` still reference the previous ChronosGraph SHA.

- [ ] **Step 5: Pin ChronosGate to that Graph SHA**

Replace the existing `context-store-mcp @ git+https://github.com/yohi/chronos-graph.git@...` SHA in `$GATE_ROOT/pyproject.toml` with `$GRAPH_IMPLEMENTATION_SHA`, then run `cd "$GATE_ROOT" && uv lock` so tracked `uv.lock` resolves the same remote Graph commit. Do not hand-edit the lockfile.

- [ ] **Step 6: Run dependency-pin GREEN**

Run:
`cd "$GATE_ROOT" && EXPECTED_CHRONOS_GRAPH_SHA="$GRAPH_IMPLEMENTATION_SHA" uv run --no-sync pytest tests/test_graph_dependency_pin.py -v`

Expected: PASS for both project and lock metadata.

Then remove the development editable override and prove the normal locked environment is authoritative:

```bash
cd "$GATE_ROOT"
uv sync --frozen --extra dev
EXPECTED_CHRONOS_GRAPH_SHA="$GRAPH_IMPLEMENTATION_SHA" uv run --frozen pytest tests/test_graph_dependency_pin.py -v
uv run --frozen python -c 'import chronos_shared.opencode_control'
```

Expected: PASS without any editable Graph override.

- [ ] **Step 7: Run Scenario Y in Gate against the locked Graph dependency**

Run:
```bash
cd "$GATE_ROOT"
export EXPECTED_CHRONOS_GRAPH_SHA="$GRAPH_IMPLEMENTATION_SHA"
uv sync --frozen --extra dev
uv run --frozen pytest tests/test_session_bound_messages.py tests/test_control_client.py tests/test_opencode_control_endpoint.py -v
EXPECTED_CHRONOS_GRAPH_SHA="$GRAPH_IMPLEMENTATION_SHA" uv run --frozen pytest tests/test_graph_dependency_pin.py -v
```

Expected: PASS, including legacy/control/operator credential separation and no control operation through normal MCP. The dependency-pin test also passes, confirming the Gate environment is using the locked Graph dependency.

- [ ] **Step 8: Run Scenario Z/AA Graph suites**

Run:
`cd "$GRAPH_ROOT" && uv run pytest tests/integration/storage/test_ingestion_authority_sqlite.py tests/integration/admin/test_ingestion_keyring_admin.py -v`

Then run the external-backend release gate:
```bash
cd "$GRAPH_ROOT"
CHRONOS_REQUIRE_EXTERNAL_BACKENDS=1 \
  uv run pytest \
    tests/integration/storage/test_ingestion_authority_postgres.py \
    tests/integration/storage/test_ingestion_authority_supabase.py -v
```

Required environment is `TEST_POSTGRES_DSN`, `TEST_SUPABASE_URL`, and `TEST_SUPABASE_SERVICE_ROLE_KEY`. Expected: PASS with **zero skipped backend tests**, zero partial mutation on injected failures, and both manifest-fence orderings.

Use the Task 17 harness in `locked_mode=True`. In this mode the harness skips editable Graph installation, uses `uv --directory "$GATE_ROOT" sync --frozen --extra dev`, launches Gate with `uv --directory "$GATE_ROOT" run --frozen chronos-gate`, and asserts `chronos_shared.opencode_control.__file__` resolves under the Gate virtualenv rather than `$GRAPH_ROOT`. The Gate's private control subprocess must also originate from the locked Graph package (`context-store-control` in the Gate venv). Set `CHRONOS_GRAPH_CONTROL_FROM_LOCKED=1` so the Gate explicitly selects the locked-package control executable.

Run:
```bash
cd "$GRAPH_ROOT"
EXPECTED_CHRONOS_GRAPH_SHA="$GRAPH_IMPLEMENTATION_SHA" CHRONOS_NATIVE_LOCKED_MODE=1 CHRONOS_GRAPH_CONTROL_FROM_LOCKED=1 uv run pytest tests/native/opencode/test_native_opencode_all.py --chronos-locked-mode -v
Expected: PASS; actual v1.18.34 npm/local loader paths both satisfy negative invariants, and both Gate and its private control subprocess use the locked Graph dependency, not the editable worktree. The Task 17 harness runs in `locked_mode=True` for this step.
- [ ] **Step 10: Run full Graph verification**

Run:
```bash
cd "$GRAPH_ROOT"
uv run pytest tests/unit -v
uv run pytest tests/integration -v
node --test tests/integration/test_opencode_turn_end_plugin.cjs tests/integration/opencode/*.cjs
uv run mypy src scripts
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
git diff --check
```

Expected: all commands succeed.

- [ ] **Step 11: Run full Gate verification**

Export the expected Graph SHA for the dependency-pin test, then run the full frozen Gate verification suite:

```bash
cd "$GATE_ROOT"
export EXPECTED_CHRONOS_GRAPH_SHA="$GRAPH_IMPLEMENTATION_SHA"
uv sync --frozen --extra dev
uv run --frozen pytest tests -v
uv run --frozen mypy src
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
git diff --check
EXPECTED_CHRONOS_GRAPH_SHA="$GRAPH_IMPLEMENTATION_SHA" uv run --frozen pytest tests/test_graph_dependency_pin.py -v
```

Expected: all commands succeed, including the dependency-pin guard.

- [ ] **Step 12: REFACTOR boundary and commit the Gate dependency pin**

```bash
cd "$GATE_ROOT"
# REFACTOR only dependency-pin test/helper naming if needed; do not change behavior.
EXPECTED_CHRONOS_GRAPH_SHA="$GRAPH_IMPLEMENTATION_SHA" uv run --frozen pytest tests/test_graph_dependency_pin.py -v
git add pyproject.toml uv.lock tests/test_graph_dependency_pin.py
git commit -m "chore: ChronosGraph durable control contract を固定"
```

- [ ] **Step 13: Inspect both final diffs**

Run:
`cd "$GRAPH_ROOT" && git status --short --branch && git diff --stat && git log --oneline -20`

Run:
`cd "$GATE_ROOT" && git status --short --branch && git diff --stat && git log --oneline -20`

Expected: no uncommitted production changes; each commit maps to one reviewed Task; no secrets/key bytes are present.

- [ ] **Step 14: Stop before production merge**

Do not merge or begin a deployment. Submit the completed implementation branches for the normal implementation/code Review Gate defined by the workflow.

---

## Task Dependency Summary

```text
Task 1  shared protocol
  |
  +--> Task 10 Gate session auth
  +--> Task 11 Gate control plane
  +--> Task 9 Graph private control
  |
Task 2  schema/revision
  |
Task 3  keyring primitives
  |
Task 4  prepared-turn/planner
  |
Task 5  SQLite authority store
  |
Task 6  PostgreSQL/Supabase authority stores
  |
Task 7  admin CLI / manifest rotation
  |
Task 8  source/canonical/turn service
  |
Task 9  Graph private control server
  |
  +--------------------------+
                             |
Task 10 Gate session auth    |
  |                          |
Task 11 Gate control plane <-+
  |
Task 12 OpenCode extraction
  |
Task 13 source/state/lock
  |
Task 14 reconciler/recovery
  |
Task 15 plugin/package zero-legacy
  |
Task 16 setup/smoke
  |
Task 17 native v1.18.34 acceptance
  |
Task 18 cross-repo verification + Gate pin
```

## Traceability Summary

- Spec §§1.1-1.10 durability/PREPARE/COMMIT/key fence → Tasks 4-8.
- Spec §2 canonical identity/keyring → Tasks 3, 7, 8.
- Spec §3 turn extraction/lineage/post-terminal → Tasks 12, 14, 17.
- Spec §4 reconciliation/checkpoint/recovery → Tasks 13-14.
- Spec §5 source scope/alias/binding → Tasks 8, 13-14.
- Spec §§6-7 corrupt state/divergence → Task 14.
- Spec §8 control transport/auth/repository ownership → Tasks 1, 9-11.
- Spec §9 observability/readiness → Tasks 3, 7-8, 11, 14.
- Spec §10 setup/smoke → Task 16.
- Spec §11 compatibility → Tasks 10, 15-18.
- Spec §§12-14 acceptance/release gates → Tasks 5-7, 10-11, 17-18.
- Scenarios Y/Z/AA/AB → Tasks 10-11 / 5-6 / 7 / 17, with Task 18 running the integrated gate.

## Review Finding Resolution Map

```text
PLAN-RG-001:
  CandidateSourceBindingWire carries canonical scope ID + binding as one wire authority
  verify_source_binding(scope_id, binding, keyring) uses that exact candidate scope
  ResolvedAliasMatch carries stable alias_id from read-only lookup
  PreparedSourceMutation pins manifest generation/non-secret keyed artifacts and target_alias_id
  BACKFILL_ALIAS_TOKEN commits only to the exact matched alias_id
  stale generation -> zero mutation / no binding token release

PLAN-RG-002:
  FileIngestionKeyringProvider reloads on every PREPARE
  long-lived control process reload acceptance without restart
  local/manifest active mismatch -> NOT READY / zero mutation

PLAN-RG-003:
  typed SourceBindingWire / ReceiptWireRecord / ReceiptDivergence / TurnIngestWireResult
  stable source/divergence/validation enums
  exact operation→payload/result mapping table
  Task 14 consumes exact shared fields, never generic dict authority
PLAN-RG-004:
  LocalSourceStateV1 and CheckpointStateV1 fields defined in Global Constraints and Task 13
  atomic persist/restart/refresh/tamper-failure tests
  checkpoint gap detection via `source_cursor_created_at` continuity
PLAN-RG-005:
  Tasks 10/11/17 use sync -> editable Graph -> uv run --no-sync
  Task 18 pins pyproject.toml + uv.lock, removes editable override with frozen sync,
  then reruns Gate against the normal locked environment

PLAN-RG-006:
  bootstrap manages default/opencode-ingestion/chronos-setup registry entries
  preserves unrelated entries
  --rotate-keys rotates all managed Gate credentials together
  real Gate ApiKeyAuthenticator/path-separation integration evidence
```

## Plan Self-Review Checklist

- [x] Every architecture-critical spec section has an owning Task.
- [x] Shared names are introduced once and consumed through Interfaces blocks.
- [x] No Task asks the implementer to choose transport, credential architecture, transaction authority, keyring administration surface, or rotation serialization.
- [x] SQLite/PostgreSQL/Supabase responsibilities are explicit.
- [x] Private Graph control composition and Gate→Graph environment allowlist are explicit.
- [x] Admin CLI transition syntax, setup key staging rules, and native fixture provider configuration are explicit.
- [x] RED commands and expected failure reasons precede implementation steps.
- [x] Every implementation Task has an explicit global REFACTOR-before-commit boundary; Task 18 also has its own dependency-pin RED/GREEN.
- [x] Required PostgreSQL/Supabase release acceptance cannot pass by skipping unavailable fixtures.
- [x] Scenario Y/Z/AA/AB have executable owning Tasks.
- [x] Canonicalization, dedupe classification, checkpoint continuity, prepared source mutation, and local source state contracts are embedded in this plan.
- [x] Production implementation remains blocked until this plan passes its own Review Gate.
