# OpenCode v1.18.34 Durable All-Mode Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved OpenCode v1.18.34 `CHRONOS_INGESTION_MODE=all` design so eligible root-session turns converge to exactly one durable ChronosGraph receipt/memory commit across retries, event loss, restarts, source alias changes, and key rotation, without using the legacy detached OpenCode hook path.

**Architecture:** ChronosGraph owns canonicalization, keyrings, source/receipt authority, and backend-atomic COMMIT through a new durable-ingestion service plus private `context-store-control --stdio` server and local `context-store-admin` keyring CLI. ChronosGate exposes a dedicated authenticated `/internal/v1/opencode/control` endpoint backed by that private Graph control process while strengthening regular MCP `/messages` to Bearer+session-owner authorization. The OpenCode plugin becomes a root-only reconciler with deterministic v1.18.34 extraction, crash-safe local state, exhaustive discovery, contiguous checkpointing, and no legacy `memory_save`/`session_flush`/detached-hook side channel.

**Tech Stack:** Python 3.12+, Pydantic v2, asyncio, aiosqlite, asyncpg, Supabase/PostgREST RPC, FastAPI, FastMCP/MCP v1, Node.js CommonJS, OpenCode `opencode-ai@1.18.34`, node:test, pytest/pytest-asyncio, uv.

**Spec:** `docs/superpowers/specs/2026-10-05-opencode-all-durable-ingestion-design.md` at approved baseline `bafcef8b78b7bdc7506162f97e95b181a32ac518`.

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
- `src/context_store/admin/ingestion_keyring.py`, `src/context_store/admin/__main__.py` — Graph-local `context-store-admin ingestion-keyring {provision,verify,rotate}`.
- `.opencode/plugins/chronos/{canonicalize,lineage,control-client,state-store,source-scope,lock,reconciler,runtime}.js` — shared npm/local OpenCode runtime implementation.
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
  - `CONTROL_METHOD_PREFIX: Final[str] = "chronos.control.v1."`
  - `RESERVED_CONTROL_PRINCIPALS = frozenset({"opencode-ingestion", "chronos-setup"})`
  - `ControlOperation(StrEnum)` values: `source.resolve`, `source.register`, `source.authorize_alias_migration`, `receipt.list_roots`, `receipt.list`, `receipt.lookup`, `receipt.validate`, `turn.ingest`.
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
    - `SourceRegisterPayload(alias_schema_version: str, discovery_scope: dict[str, JsonValue], current_root_session_ids: tuple[str, ...])`
    - `SourceAliasMigrationPayload(alias_schema_version: str, discovery_scope: dict[str, JsonValue], canonical_source_scope_id: str)`
    - `ReceiptListRootsPayload(canonical_source_scope_id: str, page_token: str | None, limit: int)`
    - `ReceiptListPayload(canonical_source_scope_id: str, root_session_id: str, page_token: str | None, limit: int)`
    - `ReceiptLookupPayload(canonical_source_scope_id: str, turn_keys: tuple[str, ...])`
    - `ReceiptEvidence(turn_key: str, current_semantic_projection: dict[str, JsonValue] | None, current_identity_evidence: dict[str, JsonValue] | None)`
    - `ReceiptValidatePayload(canonical_source_scope_id: str, root_session_id: str, evidence: tuple[ReceiptEvidence, ...])`
    - `TurnIngestPayload(canonical_source_scope_id: str, source_binding: dict[str, JsonValue], turn_key: str, root_session_id: str, user_message_id: str, source_cursor_created_at: int, evidence_contract_version: str, semantic_projection: dict[str, JsonValue], identity_evidence: dict[str, JsonValue])`
  - wire result models:
    - `SourceResolutionResult(status: SourceResolutionStatus, code: SourceResolutionCode | None, canonical_source_scope_id: str | None, source_binding: SourceBindingWire | None)`.
    - `ReceiptWireRecord(canonical_source_scope_id: str, turn_key: str, root_session_id: str, user_message_id: str, source_cursor_created_at: int, payload_hash: str, canonical_schema_version: str, evidence_contract_version: str, identity_key_version: str)`.
    - `ReceiptRootRecord(canonical_source_scope_id: str, root_session_id: str)`.
    - `ReceiptRootPage(items: tuple[ReceiptRootRecord, ...], next_page_token: str | None)`.
    - `ReceiptPage(items: tuple[ReceiptWireRecord, ...], next_page_token: str | None)`.
    - `ReceiptLookupResult(items: tuple[ReceiptWireRecord, ...])`.
    - `ReceiptDivergence(code: DivergenceCode, canonical_source_scope_id: str, root_session_id: str, turn_key: str | None, receipt_payload_hash: str | None, current_payload_hash: str | None)`.
    - `ReceiptValidationStatus(StrEnum)`: `MATCH`, `DIVERGED`, `UNAVAILABLE`.
    - `ReceiptValidationResult(status: ReceiptValidationStatus, divergences: tuple[ReceiptDivergence, ...])`.
    - `TurnIngestWireResult(kind: TurnIngestResultKind, retry_reason: RetryReason | None, payload_hash: str | None)`.
  - `control_method(operation: ControlOperation) -> str`.
  - dispatcher/client tests must map every `ControlOperation` to exactly one payload model/result family; unknown fields remain rejected except inside the explicit JSON evidence/projection containers.

- [ ] **Step 1: Write shared protocol RED tests**

Add tests asserting all exact enum values, `chronos.control.v1.<operation>` mapping, reserved principal set, operation→payload/result mapping, page limit validation, and rejection of unsupported protocol strings or extra top-level operation fields. Add exact round-trip tests for `SourceBindingWire`, `CandidateSourceBindingWire`, `ReceiptWireRecord`, `ReceiptDivergence`, and every status enum; missing required receipt fields and unknown top-level receipt/divergence fields must fail validation. `source.resolve` must reject a binding supplied without its candidate canonical scope or a candidate scope supplied without its binding, because only the pair type is accepted.

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
- ChronosGraph — Modify: `tests/unit/test_migration_runner.py`
- ChronosGraph — Modify: `tests/unit/storage/test_supabase_migrations.py`
- ChronosGraph — Create: `tests/unit/storage/test_ingestion_schema_contract.py`

**Interfaces:**
- Consumes: Task 1 enum names only for tests/documentation.
- Produces:
  - `Memory.ingestion_revision: int = 1`.
  - tables `ingestion_source_scopes`, `ingestion_source_aliases`, `ingestion_source_alias_tokens`, `ingestion_receipts`, `ingestion_keyring_manifest`.
  - receipt uniqueness `(canonical_source_scope_id, turn_key)`.
  - `ingestion_receipts` columns map one-for-one to Task 1 `ReceiptWireRecord`: `canonical_source_scope_id`, `turn_key`, `root_session_id`, `user_message_id`, `source_cursor_created_at`, `payload_hash`, `canonical_schema_version`, `evidence_contract_version`, `identity_key_version`.
  - alias-token uniqueness `(alias_schema_version, key_version, keyed_token)`.
  - singleton manifest row identity, but migration creates schema/constraint only — no manifest value row.
  - `memories.ingestion_revision NOT NULL DEFAULT 1`.
  - Supabase durable-ingestion tables enable RLS and add no anonymous/user write policy; durable mutation is reserved for the service-role/admin backend path.
  - ordinary update paths increment `ingestion_revision` for dedupe-relevant updates.

- [ ] **Step 1: Add RED migration/model tests**

Pin table/column/unique constraints, assert fresh migrations leave `ingestion_keyring_manifest` empty, assert `Memory(...).ingestion_revision == 1`, and assert row conversion preserves a non-default revision.

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/test_migration_runner.py tests/unit/storage/test_supabase_migrations.py tests/unit/storage/test_ingestion_schema_contract.py -v`

Expected: FAIL for missing migration/table/revision fields.

- [ ] **Step 3: Add migration SQL and revision mapping**

Use `0004` for both native DB runners and `20261006000003` for Supabase. Update `MigrationRunner._handle_baseline()` requirements for the new durable tables without treating the manifest row as baseline data.

- [ ] **Step 4: Make existing mutation paths maintain `ingestion_revision`**

Update SQLite/PostgreSQL/Supabase insert/read/update projections. Every successful dedupe-relevant `update_memory` increments the revision atomically; read-only/access-count-only behavior follows the spec-defined dedupe relevance and must be pinned by tests.

- [ ] **Step 5: Run GREEN**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/test_migration_runner.py tests/unit/storage/test_supabase_migrations.py tests/unit/storage/test_ingestion_schema_contract.py -v`

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/storage -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd "$GRAPH_ROOT"
git add src/context_store/storage/migrations src/context_store/models/memory.py   src/context_store/storage/sqlite.py src/context_store/storage/postgres.py   src/context_store/storage/postgres_helpers.py src/context_store/storage/supabase.py   supabase/migrations/20261006000003_opencode_durable_ingestion.sql   tests/unit/test_migration_runner.py tests/unit/storage
git commit -m "feat: durable ingestion schema と revision authority を追加"
```

---

### Task 3: Implement keyring parsing, fingerprints, binding MACs, and readiness

**Files:**
- ChronosGraph — Create: `src/context_store/security/ingestion_keyring.py`
- ChronosGraph — Modify: `src/context_store/config.py`
- ChronosGraph — Create: `tests/unit/security/test_ingestion_keyring.py`
- ChronosGraph — Modify: `.env.example`

**Interfaces:**
- Consumes: Task 2 manifest schema.
- Produces:
  - `Settings.ingestion_keyring_path: str = "~/.context-store/ingestion-keyring.json"` via `CHRONOS_INGESTION_KEYRING_PATH`.
  - immutable `IngestionKeyring`, `KeyFamilyState`, `KeyringManifest`, `KeyringAuthority` models.
  - `KeyFamily(StrEnum)` with `identity`, `source_alias`, `source_binding`.
  - `FamilyVersion(family: KeyFamily, version: str)`.
  - `KeyringTransition(promotions: tuple[FamilyVersion, ...], retirements: tuple[FamilyVersion, ...])`.
  - `KeyringAdminResult(status: str, generation: int | None, readiness_code: str | None)` containing no raw secrets.
  - `load_ingestion_keyring(path: Path) -> IngestionKeyring`.
  - `IngestionKeyringProvider(Protocol).load_snapshot() -> IngestionKeyring`.
  - `FileIngestionKeyringProvider(path: Path)` whose every `load_snapshot()` re-opens and validates the atomically replaceable file; it does not cache a successful snapshot across PREPARE attempts.
  - `derive_key_fingerprint(family: str, version: str, raw_key: bytes) -> str` using the spec domain string.
  - `derive_identity_token(...)->str`.
  - immutable `SourceBinding(schema: str, issuer: Literal["chronos-graph"], key_version: str, token: str)`.
  - `issue_source_binding(scope_id: str, keyring: IngestionKeyring) -> SourceBinding`.
  - `verify_source_binding(scope_id: str, binding: SourceBinding, keyring: IngestionKeyring) -> bool`; verification reconstructs the MAC input from binding schema + issuer + the supplied candidate canonical scope.
  - readiness codes `INGESTION_KEYRING_NOT_READY`, `INGESTION_KEYRING_MISMATCH`, `INGESTION_KEYRING_MANIFEST_INCONSISTENT`.

- [ ] **Step 1: Write RED keyring tests**

Cover 0600 enforcement where POSIX supports it, malformed schema, missing active key, <256-bit material, deterministic domain-separated fingerprints, no raw secret in model repr/serialization, binding tamper failure, same-version/different-secret fingerprint mismatch, provider reread after atomic file replacement, and scope-bound binding verification: binding issued for scope A verifies for A and fails for scope B.

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/security/test_ingestion_keyring.py -v`

Expected: FAIL because the module/settings do not exist.

- [ ] **Step 3: Implement keyring primitives**

Do not create/write keys in runtime loader. Parsing/verification is pure local I/O plus cryptographic derivation; no backend mutation in this task.

- [ ] **Step 4: Run GREEN**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/security/test_ingestion_keyring.py -v && uv run mypy src/context_store/security src/context_store/config.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GRAPH_ROOT"
git add src/context_store/security/ingestion_keyring.py src/context_store/config.py   tests/unit/security/test_ingestion_keyring.py .env.example
git commit -m "feat: ingestion keyring authority を追加"
```

---

### Task 4: Add durable domain models and the side-effect-free dedupe planner

**Files:**
- ChronosGraph — Create: `src/context_store/ingestion/durable/models.py`
- ChronosGraph — Create: `src/context_store/ingestion/durable/planner.py`
- ChronosGraph — Create: `tests/unit/ingestion/test_durable_models.py`
- ChronosGraph — Create: `tests/unit/ingestion/test_durable_planner.py`

**Interfaces:**
- Consumes: Task 1 `JsonValue`; Task 2 `Memory.ingestion_revision`; Task 3 `KeyringAuthority` and `SourceBinding`.
- Produces:
  - `DedupeReadStore` protocol exposing only `vector_search(embedding: list[float], top_k: int, project: str | None) -> list[ScoredMemory]`; existing storage adapters satisfy it structurally.
  - `DestructiveAssumption(memory_id: str, ingestion_revision: int)`.
  - `DedupePlan(action: DeduplicationAction, existing_memory: Memory | None, similarity: float, assumption: DestructiveAssumption | None)`.
  - `TurnIngestRequest(canonical_source_scope_id: str, source_binding: SourceBinding, turn_key: str, root_session_id: str, user_message_id: str, source_cursor_created_at: int, evidence_contract_version: str, semantic_projection: dict[str, JsonValue], identity_evidence: dict[str, JsonValue])`.
  - `SourceMutationKind(StrEnum)`: `REGISTER_NEW_SOURCE_SCOPE`, `ATTACH_ALIAS`, `MIGRATE_ALIAS`, `BACKFILL_ALIAS_TOKEN`, `ISSUE_OR_REFRESH_BINDING`.
  - `PreparedSourceMutation(kind: SourceMutationKind, keyring_manifest_generation: int, target_canonical_source_scope_id: str, target_alias_id: str | None, alias_schema_version: str, alias_key_version_used: str | None, keyed_alias_token: str | None, binding_key_version_used: str | None, prepared_source_binding: SourceBinding | None)`. It contains only non-secret keyed artifacts plus pinned authority; raw key bytes and raw mutable routing evidence are not carried into COMMIT. `BACKFILL_ALIAS_TOKEN` requires `target_alias_id`; the transaction may only add the new token to that exact existing alias identity.
  - `PreparedAliasLookup(alias_schema_version: str, key_version: str, keyed_token: str)` for read-only current/retained alias lookup before mutation.
  - `AliasLookupStatus(StrEnum)`: `NOT_FOUND`, `UNIQUE`, `AMBIGUOUS`.
  - `ResolvedAliasMatch(alias_id: str, canonical_source_scope_id: str, alias_schema_version: str, matched_key_version: str)`.
  - `AliasLookupResult(status: AliasLookupStatus, match: ResolvedAliasMatch | None)`; `UNIQUE` requires exactly one match, while `NOT_FOUND/AMBIGUOUS` require `match is None`.
  - `PreparedTurn` fields required by the spec, including `keyring_manifest_generation`, `identity_active_version_at_prepare`, `identity_key_version_used`, prepared embeddings, turn/source identifiers, canonical hash inputs, desired mutation, and destructive assumptions.
  - `CommitResult(kind: TurnIngestResultKind, retry_reason: RetryReason | None, payload_hash: str | None)`.
  - `IngestionDedupePlanner(read_store: DedupeReadStore)`.
  - `IngestionDedupePlanner.plan(new_memory: Memory) -> DedupePlan` with **no mutation**.

- [ ] **Step 1: Write RED planner tests**

Reuse current similarity thresholds but assert a REPLACE plan leaves the existing memory unarchived and captures its exact `ingestion_revision`. Add an explicit regression proving existing `Deduplicator.deduplicate()` is not called. Add model tests proving `PreparedSourceMutation` requires a pinned manifest generation and the key version matching every present keyed artifact, cannot serialize raw key material, and rejects `BACKFILL_ALIAS_TOKEN` without `target_alias_id`. Add `AliasLookupResult` invariants so ambiguous/not-found lookup cannot accidentally carry a chosen alias.

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/ingestion/test_durable_models.py tests/unit/ingestion/test_durable_planner.py -v`

Expected: FAIL because durable models/planner do not exist.

- [ ] **Step 3: Implement models and pure planner**

Depend only on `DedupeReadStore.vector_search()` for candidate discovery. A normal StorageAdapter may be injected structurally, but the durable planner receives no mutation methods. Do not modify the legacy `Deduplicator`; selective mode continues to use it.

- [ ] **Step 4: Run GREEN**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/ingestion/test_durable_models.py tests/unit/ingestion/test_durable_planner.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd "$GRAPH_ROOT"
git add src/context_store/ingestion/durable tests/unit/ingestion/test_durable_*.py
git commit -m "feat: side-effect-free durable ingestion planner を追加"
```

---

### Task 5: Define the ingestion authority store interfaces and SQLite implementation

**Files:**
- ChronosGraph — Create: `src/context_store/storage/ingestion/protocols.py`
- ChronosGraph — Create: `src/context_store/storage/ingestion/sqlite.py`
- ChronosGraph — Create: `src/context_store/storage/ingestion/factory.py`
- ChronosGraph — Create: `tests/integration/storage/test_ingestion_authority_sqlite.py`

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces:
  - `IngestionCommitStore.commit_turn(prepared: PreparedTurn) -> CommitResult`.
  - `IngestionRegistryStore.read_manifest() -> KeyringManifest | None`.
  - `IngestionRegistryStore.lookup_source_alias(candidates: tuple[PreparedAliasLookup, ...]) -> AliasLookupResult` is read-only and never creates/backfills tokens or bindings. A unique lookup returns the stable `alias_id` plus canonical scope/schema/matched-key identity in `ResolvedAliasMatch`; ambiguity returns no selected match.
  - `IngestionRegistryStore.commit_source_mutation(prepared: PreparedSourceMutation) -> SourceResolutionResult` is the **only** source/alias/binding durable mutation entrypoint. It acquires the manifest fence first, requires `current_manifest.generation == prepared.keyring_manifest_generation`, requires every `*_key_version_used` is still authorized/active as applicable, then applies the source/alias/token/binding mutation atomically.
  - `KEYRING_GENERATION_CHANGED` from `commit_source_mutation` means zero source/alias/binding mutation and the returned `SourceResolutionResult.source_binding` is `None`; a prepared binding token is released to the caller only after the transaction commits successfully.
  - `IngestionRegistryStore.list_receipt_roots(scope_id: str, *, page_token: str | None, limit: int) -> ReceiptRootPage`.
  - `IngestionRegistryStore.list_receipts(scope_id: str, root_session_id: str, *, page_token: str | None, limit: int) -> ReceiptPage`.
  - `IngestionRegistryStore.lookup_receipts(scope_id: str, turn_keys: tuple[str, ...]) -> ReceiptLookupResult`.
  - `IngestionRegistryStore.validate_receipts(scope_id: str, root_session_id: str, evidence: tuple[ReceiptEvidence, ...]) -> ReceiptValidationResult`.
  - source registration, alias attachment/migration, active-key alias-token backfill, and binding issuance/refresh all enter the backend only as `PreparedSourceMutation`; no storage implementation receives the raw keyring or derives HMAC/MAC values inside the transaction.
  - for `BACKFILL_ALIAS_TOKEN`, `commit_source_mutation` requires `target_alias_id` to identify an already-existing alias row and inserts the prepared active-key token under that **same alias_id**. It must not choose an alias by canonical scope alone or create a sibling alias implicitly.
  - `IngestionKeyringAdminStore.provision_manifest(candidate: KeyringManifest) -> KeyringAdminResult` with create-if-absent semantics.
  - `IngestionKeyringAdminStore.rotate_manifest(*, expected_generation: int, transition: KeyringTransition, candidate_manifest: KeyringManifest) -> KeyringAdminResult` whose backend transaction reacquires the manifest fence and re-reads current receipt/alias/binding retirement authority before update.
  - `IngestionAuthorityStore` protocol combines `IngestionCommitStore`, `IngestionRegistryStore`, `IngestionKeyringAdminStore`, and `async dispose() -> None`.
  - `async def create_ingestion_store(settings: Settings) -> IngestionAuthorityStore`.
  - SQLite transaction fence: one `BEGIN IMMEDIATE` transaction reads manifest generation first, validates key authority/CAS assumptions, mutates memory/outbox/receipt, then commits.
  - source/alias key-dependent writes use the same manifest row/generation fence.

- [ ] **Step 1: Write RED SQLite atomicity tests**

Cover:
  - successful COMMIT writes memory+outbox+receipt atomically;
  - injected failure after memory mutation leaves all three absent;
  - stale `ingestion_revision` returns `STALE_DEDUPE_PLAN` with zero mutation;
  - stale manifest generation returns `KEYRING_GENERATION_CHANGED` with zero mutation;
  - source registration, alias migration, alias-token backfill, and binding refresh prepared under stale generation each return `KEYRING_GENERATION_CHANGED`, perform zero durable mutation, and release no binding token;
  - one canonical scope with sibling aliases A and B where an old-key token resolves B: active-key backfill mutates token rows for B only, leaves A unchanged, and preserves B's stable `alias_id`.

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/integration/storage/test_ingestion_authority_sqlite.py -v`

Expected: FAIL because authority store/factory do not exist.

- [ ] **Step 3: Implement protocols and SQLite store**

Keep all SQL inside the backend implementation. COMMIT must consume prepared embeddings/data only. Do not call `EmbeddingProvider`, HTTP, Neo4j, or the legacy side-effecting deduplicator.

- [ ] **Step 4: Add deterministic manifest-fence concurrency test**

Use asyncio barriers around two SQLite write transactions. Assert:
  - turn-first → receipt commits and retirement reread refuses to remove its key;
  - rotate-first → old turn gets `KEYRING_GENERATION_CHANGED` and zero mutation.

- [ ] **Step 5: Run GREEN**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/integration/storage/test_ingestion_authority_sqlite.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd "$GRAPH_ROOT"
git add src/context_store/storage/ingestion tests/integration/storage/test_ingestion_authority_sqlite.py
git commit -m "feat: SQLite durable ingestion transaction boundary を追加"
```

---

### Task 6: Implement PostgreSQL and Supabase authority stores and transactional RPCs

**Files:**
- ChronosGraph — Create: `src/context_store/storage/ingestion/postgres.py`
- ChronosGraph — Create: `src/context_store/storage/ingestion/supabase.py`
- ChronosGraph — Create: `supabase/migrations/20261006000004_opencode_durable_rpc.sql`
- ChronosGraph — Modify: `src/context_store/storage/ingestion/factory.py`
- ChronosGraph — Create: `tests/integration/storage/test_ingestion_authority_postgres.py`
- ChronosGraph — Create: `tests/unit/storage/test_supabase_durable_rpc.py`
- ChronosGraph — Create: `tests/integration/storage/test_ingestion_authority_supabase.py`

**Interfaces:**
- Consumes: Task 5 protocols.
- Produces:
  - PostgreSQL implementation using one asyncpg connection/transaction and manifest-row serialization before key-dependent writes.
  - Supabase adapter calling `commit_ingested_turn_v1` for turn COMMIT and versioned server-side functions `commit_ingestion_source_mutation_v1` and `rotate_ingestion_keyring_manifest_v1` for key-dependent transactions.
  - `commit_ingestion_source_mutation_v1` receives at minimum `expected_manifest_generation`, operation kind, target canonical scope, exact `target_alias_id` when the operation targets an existing alias (mandatory for `BACKFILL_ALIAS_TOKEN`), alias schema/version + non-secret keyed alias token when present, and binding key version + prepared binding token when present. It receives no raw key bytes or raw keyring JSON and returns the binding only after transactional generation/key-authority revalidation succeeds.
  - Supabase durable mutation functions use invoker permissions with a fixed public schema search path; execution is granted only to the service-role backend identity, not anonymous/user roles.
  - identical `CommitResult` / retry reason semantics across backends.
  - external integration fixture contract:
    - PostgreSQL: `TEST_POSTGRES_DSN`.
    - Supabase: `TEST_SUPABASE_URL` + `TEST_SUPABASE_SERVICE_ROLE_KEY`.
    - ordinary developer runs may skip an unavailable external backend, but when `CHRONOS_REQUIRE_EXTERNAL_BACKENDS=1`, missing fixture variables are a test failure, never a skip.

- [ ] **Step 1: Write RED backend tests**

PostgreSQL mirrors Task 5 atomicity/fence schedules. SQL contract tests assert Supabase RPC contains receipt/CAS/memory/outbox/manifest-fence logic inside one PL/pgSQL transaction, does not rely on multiple PostgREST writes, and is executable only by the service-role backend identity.

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/integration/storage/test_ingestion_authority_postgres.py tests/unit/storage/test_supabase_durable_rpc.py -v`

Expected: FAIL for missing implementations/RPC.

- [ ] **Step 3: Implement PostgreSQL authority store**

Acquire the manifest row as the first key-dependent transaction fence. Keep exact SQL lock primitive private to this backend while preserving Task 5 semantics.

- [ ] **Step 4: Implement Supabase RPC/store**

Create `commit_ingested_turn_v1` and the required source/manifest transactional functions. The Python adapter sends prepared data and maps stable domain statuses; no client-side multi-call emulation of atomic COMMIT is allowed.

- [ ] **Step 5: Run GREEN**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/integration/storage/test_ingestion_authority_postgres.py tests/unit/storage/test_supabase_durable_rpc.py -v`

Run the Supabase integration case whenever its fixture is available:
`cd "$GRAPH_ROOT" && uv run pytest tests/integration/storage/test_ingestion_authority_supabase.py -v`

Expected: PASS for every configured backend fixture. During ordinary Task development an intentionally unavailable external fixture may skip; Task 18 is the release gate and reruns PostgreSQL + Supabase with `CHRONOS_REQUIRE_EXTERNAL_BACKENDS=1`, where any skip or missing fixture configuration is a failure.

- [ ] **Step 6: Commit**

```bash
cd "$GRAPH_ROOT"
git add src/context_store/storage/ingestion/postgres.py   src/context_store/storage/ingestion/supabase.py   src/context_store/storage/ingestion/factory.py   supabase/migrations/20261006000004_opencode_durable_rpc.sql   tests/integration/storage tests/unit/storage/test_supabase_durable_rpc.py
git commit -m "feat: PostgreSQL と Supabase durable commit を追加"
```

---

### Task 7: Implement keyring admin service and the real Graph-local CLI

**Files:**
- ChronosGraph — Create: `src/context_store/admin/ingestion_keyring.py`
- ChronosGraph — Create: `src/context_store/admin/__main__.py`
- ChronosGraph — Modify: `pyproject.toml`
- ChronosGraph — Create: `tests/unit/admin/test_ingestion_keyring_cli.py`
- ChronosGraph — Create: `tests/integration/admin/test_ingestion_keyring_admin.py`

**Interfaces:**
- Consumes: Task 3 keyring parser; Tasks 5-6 registry/manifest store.
- Produces:
  - console script `context-store-admin = "context_store.admin.__main__:main"`.
  - commands `ingestion-keyring provision|verify|rotate`.
  - consumes Task 3 `FamilyVersion`, `KeyringTransition`, and `KeyringAdminResult`; does not redefine them.
  - `provision(settings: Settings, store: IngestionAuthorityStore) -> KeyringAdminResult`.
  - `verify(settings: Settings, store: IngestionAuthorityStore) -> KeyringAdminResult` read-only.
  - `rotate(settings: Settings, store: IngestionAuthorityStore, *, expected_generation: int, transition: KeyringTransition) -> KeyringAdminResult`.
  - exact CLI:
    - `context-store-admin ingestion-keyring provision`
    - `context-store-admin ingestion-keyring verify`
    - `context-store-admin ingestion-keyring rotate --expected-generation <int> [--promote <family>:<version>]... [--retire <family>:<version>]...`
  - `rotate` requires at least one `--promote` or `--retire`; promoted keys must already exist in the staged local file.
  - one invocation may not promote a successor and retire that family's previous active key simultaneously.
  - manifest CAS plus transactionally current receipt/alias/binding retirement validation.
  - no raw-key CLI arguments or Gate/RPC transport.

- [ ] **Step 1: Write RED CLI/security tests**

Assert command names, no raw-secret argument, missing/malformed keyring fails, verify is read-only, initial provision is create-if-absent, second incompatible provision does not overwrite, and output contains no raw key bytes.

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/admin/test_ingestion_keyring_cli.py tests/integration/admin/test_ingestion_keyring_admin.py -v`

Expected: FAIL because admin entrypoint/service do not exist.

- [ ] **Step 3: Implement provision/verify**

Provision consumes a pre-staged local keyring only; runtime/CLI never auto-generates replacement keys.

- [ ] **Step 4: Implement exact rotate/retire CLI parsing and the manifest fence**

Parse repeatable `--promote family:version` / `--retire family:version` into `KeyringTransition`. Promotion G→G+1 keeps the previous active version required. Reject same-family promote+previous-active-retire in one command. Retirement is a later generation and re-reads authoritative references in the same transaction as manifest update.

- [ ] **Step 5: Add Scenario AA concurrency schedules**

Use real admin service calls plus transaction barriers:
  - COMMIT-first → later retirement sees reference and rejects;
  - rotate-first → stale prepared mutation returns `KEYRING_GENERATION_CHANGED`;
  - equivalent alias/binding schedules;
  - all successful receipts reference manifest-required identity versions.

- [ ] **Step 6: Run GREEN**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/admin/test_ingestion_keyring_cli.py tests/integration/admin/test_ingestion_keyring_admin.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd "$GRAPH_ROOT"
git add pyproject.toml src/context_store/admin tests/unit/admin tests/integration/admin
git commit -m "feat: ingestion keyring admin CLI を追加"
```

---

### Task 8: Implement source authority, canonicalization, receipts, and turn ingestion service

**Files:**
- ChronosGraph — Create: `src/context_store/ingestion/durable/canonicalizer.py`
- ChronosGraph — Create: `src/context_store/ingestion/durable/service.py`
- ChronosGraph — Create: `tests/unit/ingestion/test_durable_canonicalizer.py`
- ChronosGraph — Create: `tests/integration/ingestion/test_durable_ingestion_service.py`

**Interfaces:**
- Consumes: Tasks 3-7, specifically Task 4 `DedupeReadStore` and Task 5 `IngestionAuthorityStore`.
- Produces:
  - `DurableIngestionService(*, read_store: DedupeReadStore, authority_store: IngestionAuthorityStore, embedding_provider: EmbeddingProvider, keyring_provider: IngestionKeyringProvider)`; no long-lived immutable keyring snapshot is stored.
  - `resolve_source(request: SourceResolvePayload) -> SourceResolutionResult`.
  - `register_source(request: SourceRegisterPayload) -> SourceResolutionResult`.
  - `authorize_alias_migration(request: SourceAliasMigrationPayload) -> SourceResolutionResult`.
  - `list_receipt_roots(scope_id: str, page_token: str | None, limit: int) -> ReceiptRootPage`.
  - `list_receipts(scope_id: str, root_session_id: str, page_token: str | None, limit: int) -> ReceiptPage`.
  - `lookup_receipts(scope_id: str, turn_keys: tuple[str, ...]) -> ReceiptLookupResult`.
  - `validate_receipts(scope_id: str, root_session_id: str, evidence: tuple[ReceiptEvidence, ...]) -> ReceiptValidationResult`.
  - `ingest_turn(request: TurnIngestRequest) -> CommitResult`.
  - server-authoritative HMAC identity derivation and final payload hash.
  - receipt-pinned canonical/evidence/key rebase.
  - `load_ready_key_authority() -> KeyringAuthority` starts every key-dependent PREPARE by calling `keyring_provider.load_snapshot()`, reading the authoritative manifest, verifying required fingerprints, and requiring local active versions to match manifest active versions. Any local/manifest mismatch returns the approved NOT READY code and performs zero source/receipt/turn mutation.
  - `resolve_source` treats `SourceResolvePayload.candidate` as an indivisible pair and calls `verify_source_binding(request.candidate.canonical_source_scope_id, request.candidate.binding, fresh_keyring)`; the binding alone never selects or authenticates a scope.
  - source wire methods perform read-only alias/continuity lookup, derive non-secret keyed artifacts from that fresh READY snapshot, build one or more exact `PreparedSourceMutation` objects, and call `commit_source_mutation`; raw wire payloads are never passed directly to a mutation transaction.
  - when a retained-key alias lookup returns `ResolvedAliasMatch(alias_id=A, ...)` and active-key token A is absent, the service derives the active-key token and prepares `BACKFILL_ALIAS_TOKEN` with `target_alias_id=A`; the stable alias identity from lookup is carried unchanged across PREPARE→COMMIT.
  - Graph-issued local source binding issue/verify/refresh uses the exact candidate scope from `CandidateSourceBindingWire`.
  - after `KEYRING_GENERATION_CHANGED`, the service discards all prepared keyed artifacts and restarts the full PREPARE path, including a fresh keyring-file read and manifest verification.
  - `IDEMPOTENCY_REBASE_UNAVAILABLE`, `IDEMPOTENCY_CONFLICT`, `STALE_DEDUPE_PLAN`, and `KEYRING_GENERATION_CHANGED` exact behavior.

- [ ] **Step 1: Write RED canonicalization tests**

Cover domain-separated keyed identity tokens, volatile evidence not present in receipt/memory/log model, receipt-pinned old-key comparison, unavailable old key, and canonical version mismatch rebase.

- [ ] **Step 2: Write RED source/binding tests**

Cover unknown/ambiguous continuity fail-closed, explicit new-source enrollment, alias migration continuity proof, global+directory isolation, scope-bound binding MAC candidate authentication without continuity authority, and stale generation zero mutation/token release. Add candidate-pair tests: scope A + binding(A) authenticates the candidate; scope B + binding(A) yields `SOURCE_SCOPE_CONTINUITY_UNRESOLVED` with zero mutation; no unpaired candidate is accepted by the shared payload. Add sibling-alias backfill: one canonical scope has aliases A and B, retained-key lookup resolves B, and the prepared/committed active-key token targets B's exact `alias_id` while A remains unchanged. Add a service test proving local-active/manifest-active mismatch is NOT READY with zero mutation and that a fresh PREPARE after `KEYRING_GENERATION_CHANGED` reloads a newly atomically replaced keyring file before deriving new keyed artifacts.

- [ ] **Step 3: Write RED turn service tests**

Cover COMMITTED, ALREADY_COMMITTED, lost unique-insert race rebase, conflict, stale dedupe retry, keyring generation retry, FAILED/ABORTED user-only persistence, and post-terminal same-anchor divergence.

- [ ] **Step 4: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/ingestion/test_durable_canonicalizer.py tests/integration/ingestion/test_durable_ingestion_service.py -v`

Expected: FAIL because canonicalizer/service do not exist.

- [ ] **Step 5: Implement minimum service**

Keep PREPARE side-effect-free. On receipt/version or manifest-generation changes, discard stale prepared state and restart PREPARE rather than adapting mutation in-place.

- [ ] **Step 6: Run GREEN**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/ingestion/test_durable_canonicalizer.py tests/integration/ingestion/test_durable_ingestion_service.py -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd "$GRAPH_ROOT"
git add src/context_store/ingestion/durable tests/unit/ingestion tests/integration/ingestion
git commit -m "feat: durable ingestion authority service を追加"
```

---

### Task 9: Add the private Graph control stdio server

**Files:**
- ChronosGraph — Create: `src/context_store/control/composition.py`
- ChronosGraph — Create: `src/context_store/control/server.py`
- ChronosGraph — Create: `src/context_store/control/__main__.py`
- ChronosGraph — Modify: `pyproject.toml`
- ChronosGraph — Create: `tests/unit/control/test_control_dispatcher.py`
- ChronosGraph — Create: `tests/integration/control/test_control_stdio.py`
- ChronosGraph — Modify: `tests/unit/test_chronos_gate_migration_guards.py`

**Interfaces:**
- Consumes: Task 1 protocol; Task 8 service.
- Produces:
  - console script `context-store-control = "context_store.control.__main__:main"`.
  - `async def create_control_service(settings: Settings) -> DurableIngestionService` in `control/composition.py`.
  - composition uses `_create_storage_adapter(settings)` as the `DedupeReadStore`, `create_ingestion_store(settings)` as the single `IngestionAuthorityStore`, `create_embedding_provider(settings)`, and one `FileIngestionKeyringProvider(Path(os.path.expanduser(settings.ingestion_keyring_path)))`. The provider, not a loaded snapshot, is injected into `DurableIngestionService`.
  - composition does **not** construct the full `Orchestrator`, cache adapters, dashboard, FastMCP server, lifecycle manager, or external Neo4j client.
  - private wire framing is newline-delimited UTF-8 JSON (NDJSON): exactly one JSON-RPC 2.0 request/response object per line; no Content-Length/MCP framing.
  - newline-framed JSON-RPC 2.0 stdio methods `chronos.control.v1.<operation>`.
  - one dispatcher mapping exactly the Task 1 operation set to `DurableIngestionService`.
  - no registration as FastMCP tool/resource/prompt.

- [ ] **Step 1: Write RED dispatcher/isolation tests**

Assert all eight methods dispatch, unsupported method/version returns protocol error, malformed JSON is isolated, and `context_store.server.mcp` tool list does not contain any control method. Add a long-lived-process acceptance: start one `context-store-control` process READY on v1, atomically replace the keyring file with staged v2/local-active-v2, promote the backend manifest G→G+1, assert an old prepared G request returns `KEYRING_GENERATION_CHANGED`, then without process restart assert a fresh request reloads the file, uses v2, and becomes READY. Also assert local-active != manifest-active keeps the same process NOT READY with zero mutation until reverified.

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/unit/control/test_control_dispatcher.py tests/integration/control/test_control_stdio.py tests/unit/test_chronos_gate_migration_guards.py -v`

Expected: FAIL because the private server/entrypoint are absent.

- [ ] **Step 3: Implement the focused composition root**

Implement `create_control_service(settings)` with the exact factories in Interfaces. Own and dispose the read storage adapter, durable-ingestion store, and embedding provider where their protocols expose disposal; do not start cache/lifecycle/outbox workers unrelated to durable COMMIT.

- [ ] **Step 4: Implement dispatcher and stdio process**

Use the focused service composition. Keep stdout protocol-clean; diagnostics go to stderr/logging.

- [ ] **Step 5: Run GREEN**

Run the same focused command. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd "$GRAPH_ROOT"
git add pyproject.toml src/context_store/control tests/unit/control tests/integration/control   tests/unit/test_chronos_gate_migration_guards.py
git commit -m "feat: private durable ingestion control server を追加"
```

---

### Task 10: Strengthen regular ChronosGate MCP sessions to Bearer+owner authorization

**Files:**
- ChronosGate — Modify: `src/chronos_gate/auth/handshake.py`
- ChronosGate — Modify: `src/chronos_gate/server.py`
- ChronosGate — Create: `tests/test_session_bound_messages.py`

**Interfaces:**
- Consumes: Task 1 `RESERVED_CONTROL_PRINCIPALS` via editable/current ChronosGraph package during development.
- Produces:
  - `HandshakeService(..., denied_agent_ids: frozenset[str])`.
  - `_authenticate_message_principal(request: Request, api_authenticator: ApiKeyAuthenticator) -> str`.
  - `_handle_messages(..., api_authenticator: ApiKeyAuthenticator, reserved_principals: frozenset[str])`.
  - fixed status ordering: 401 missing/invalid Bearer; 404 authenticated unknown session; 403 owner mismatch/reserved principal.
  - development dependency workflow is fixed: `uv sync --extra dev` first, then `uv pip install -e "$GRAPH_ROOT"`, then every Gate command in Tasks 10-11 uses `uv run --no-sync` until Task 18 removes the editable override. Before RED/GREEN, assert `chronos_shared.opencode_control.__file__` resolves under `$GRAPH_ROOT`.

- [ ] **Step 1: Write Scenario Y session RED tests**

Create principal A session SA, then assert:
  - A+SA allowed;
  - no/bad Bearer+SA → 401;
  - B+SA → 403;
  - A+unknown session → 404;
  - `opencode-ingestion`/`chronos-setup` cannot create/reuse regular sessions.

- [ ] **Step 2: Run RED**

Run:
```bash
cd "$GATE_ROOT"
uv sync --extra dev
uv pip install -e "$GRAPH_ROOT"
GRAPH_ROOT="$GRAPH_ROOT" uv run --no-sync python -c 'import os, pathlib, chronos_shared.opencode_control as m; p=pathlib.Path(m.__file__).resolve(); root=pathlib.Path(os.environ["GRAPH_ROOT"]).resolve(); assert p.is_relative_to(root), (p, root)'
uv run --no-sync pytest tests/test_session_bound_messages.py -v
```

Expected: FAIL because `/messages` currently authorizes by session id only.

- [ ] **Step 3: Implement Bearer/session-owner enforcement**

Authenticate before lookup; compare authenticated principal to immutable `SessionRecord.agent_id`. Reject reserved principals before regular session creation and reuse.

- [ ] **Step 4: Run GREEN and existing Gate tests**

Run:
`cd "$GATE_ROOT" && uv run --no-sync pytest tests/test_session_bound_messages.py -v && uv run --no-sync pytest tests -v`

Expected: PASS.

- [ ] **Step 5: Commit in ChronosGate**

```bash
cd "$GATE_ROOT"
git add src/chronos_gate/auth/handshake.py src/chronos_gate/server.py tests/test_session_bound_messages.py
git commit -m "feat: MCP session Bearer ownership を強制"
```

---

### Task 11: Add ChronosGate private control client and HTTP control endpoint

**Files:**
- ChronosGate — Create: `src/chronos_gate/control/client.py`
- ChronosGate — Create: `src/chronos_gate/control/http.py`
- ChronosGate — Modify: `src/chronos_gate/config.py`
- ChronosGate — Modify: `src/chronos_gate/app.py`
- ChronosGate — Modify: `src/chronos_gate/server.py`
- ChronosGate — Create: `tests/test_control_client.py`
- ChronosGate — Create: `tests/test_opencode_control_endpoint.py`

**Interfaces:**
- Consumes: Task 1 shared envelopes; Task 9 private server; Task 10's synchronized Gate env + editable current-Graph `--no-sync` development workflow.
- Produces:
  - `ControlUpstreamClient.start()/stop()/call(operation, payload, request_id)`.
  - `GatewaySettings.control_upstream_command: list[str] = ["context-store-control", "--stdio"]`.
  - `GatewaySettings.control_upstream_env_passthrough` exactly allows:
    `CHRONOS_INGESTION_MODE`, `STORAGE_BACKEND`, `SQLITE_DB_PATH`,
    `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
    `POSTGRES_SSL`, `POSTGRES_SSL_NO_VERIFY`, `POSTGRES_STATEMENT_CACHE_SIZE`,
    `SUPABASE_URL`, `SUPABASE_KEY`, `SUPABASE_REQUEST_TIMEOUT_SECONDS`,
    `GRAPH_ENABLED`, `GRAPH_SYNC_MODE`,
    `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`,
    `EMBEDDING_PROVIDER`, `EMBEDDING_DIMENSION`, `OPENAI_API_KEY`, `LOCAL_MODEL_NAME`,
    `LITELLM_API_BASE`, `LITELLM_MODEL`, `CUSTOM_API_ENDPOINT`, `CUSTOM_API_MODEL_NAME`,
    `CHRONOS_INGESTION_KEYRING_PATH`, and `LOG_LEVEL`.
  - reuse `build_upstream_env()`, so its existing base passthrough remains only `PATH`, `HOME`, `LANG`, `LC_ALL`, `TZ`.
  - raw key **contents** are never copied by Gate; only the keyring path may pass.
  - `POST /internal/v1/opencode/control`.
  - capability matrix:
    - `opencode-ingestion`: source.resolve, receipt reads/validate, turn.ingest.
    - `chronos-setup`: source.resolve/register/authorize_alias_migration + receipt reads/validate.
  - no keyring admin operations.
  - HTTP 400/401/403/413/503 transport mapping; HTTP 200 domain result envelope.

- [ ] **Step 1: Write RED control-client framing tests**

Assert request-id correlation, timeout/subprocess failure → retryable upstream error, stderr does not corrupt stdout framing, and no raw payload logging.

- [ ] **Step 2: Write RED endpoint capability tests**

Assert control/legacy/operator credentials are distinct principals, legacy MCP credential → control 403, runtime cannot register/migrate manually, operator cannot `turn.ingest`, normal MCP cannot reach control methods, and no control method appears in regular `tools/list`.

- [ ] **Step 3: Run RED**

Run:
```bash
cd "$GATE_ROOT"
uv sync --extra dev
uv pip install -e "$GRAPH_ROOT"
GRAPH_ROOT="$GRAPH_ROOT" uv run --no-sync python -c 'import os, pathlib, chronos_shared.opencode_control as m; p=pathlib.Path(m.__file__).resolve(); root=pathlib.Path(os.environ["GRAPH_ROOT"]).resolve(); assert p.is_relative_to(root), (p, root)'
uv run --no-sync pytest tests/test_control_client.py tests/test_opencode_control_endpoint.py -v
```

Expected: FAIL because control client/endpoint do not exist.

- [ ] **Step 4: Implement client/app lifecycle/config**

Add the exact `control_upstream_command` and `control_upstream_env_passthrough` settings above. Build its environment through the existing `build_upstream_env()`; add a test proving an unrelated secret such as `MCP_GATEWAY_CONTROL_API_KEY` is **not** inherited by the Graph subprocess. Start/stop normal MCP upstream and private control upstream independently.

- [ ] **Step 5: Implement endpoint/capability dispatcher**

Use Task 1 envelope parsing and operation enum. Keep control authorization separate from MCP intents.

- [ ] **Step 6: Run GREEN**

Run:
`cd "$GATE_ROOT" && uv run --no-sync pytest tests/test_control_client.py tests/test_opencode_control_endpoint.py tests/test_session_bound_messages.py -v`

Expected: PASS.

- [ ] **Step 7: Commit in ChronosGate**

```bash
cd "$GATE_ROOT"
git add src/chronos_gate/control src/chronos_gate/config.py src/chronos_gate/app.py   src/chronos_gate/server.py tests/test_control_client.py tests/test_opencode_control_endpoint.py
git commit -m "feat: OpenCode durable control endpoint を追加"
```

---

### Task 12: Implement deterministic OpenCode v1.18.34 turn extraction and lineage

**Files:**
- ChronosGraph — Create: `.opencode/plugins/chronos/canonicalize.js`
- ChronosGraph — Create: `.opencode/plugins/chronos/lineage.js`
- ChronosGraph — Create: `tests/integration/opencode/test_turn_canonicalization.cjs`

**Interfaces:**
- Consumes: persisted OpenCode v1.18.34 message/part shapes fixed by the spec.
- Produces:
  - `orderMessages(messages) -> messages` by `(time.created, id)`.
  - `orderParts(parts) -> parts` by persisted part id.
  - `classifyUserProvenance(message, parts)`.
  - `buildLogicalTurns(snapshot) -> LogicalTurn[]`.
  - `classifyTerminalOutcome(turn) -> SUCCESS|FAILED|ABORTED|INCOMPLETE`.
  - `buildSemanticProjection(turn)` preserving heterogeneous order.
  - exact overflow-compaction replay recognizer; no text-similarity fallback.
  - unresolved file/resource identity blocks canonical turn emission.

- [ ] **Step 1: Write RED fixtures for all prompt kinds and identity evidence**

Include text-only, file-only, AgentPart-only, SubtaskPart-only, mixed ordered parts, user-executed synthetic shell control, compaction summary/continue, and failed/aborted turns.

For FilePart identity fixtures, pin persisted v1.18.34 execution-relevant fields: `mime`, `filename?`, `url`, and when present `source.type`, `source.text.value/start/end`, file/symbol `path`, symbol `name/kind/range`, or resource `clientName/uri`. Prove reconciliation never rereads the filesystem/network.

For SubtaskPart identity fixtures, pin `prompt`, `description`, `agent`, optional `model {providerID, modelID}`, and optional `command`. Distinct model/command values must not collapse.

- [ ] **Step 2: Write exact replay RED fixtures**

Pin v1.18.34 overflow replay transform including CompactionPart omission and media FilePart `[Attached <mime>: <filename-or-file>]` conversion.

- [ ] **Step 3: Run RED**

Run: `cd "$GRAPH_ROOT" && node --test tests/integration/opencode/test_turn_canonicalization.cjs`

Expected: FAIL because modules do not exist.

- [ ] **Step 4: Implement extractor/lineage only**

No storage/network calls in these modules.

- [ ] **Step 5: Run GREEN**

Run the same command. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd "$GRAPH_ROOT"
git add .opencode/plugins/chronos/canonicalize.js .opencode/plugins/chronos/lineage.js   tests/integration/opencode/test_turn_canonicalization.cjs
git commit -m "feat: OpenCode v1.18.34 turn canonicalization を追加"
```

---

### Task 13: Implement OpenCode control client, source scope, crash-safe state, and root lock

**Files:**
- ChronosGraph — Create: `.opencode/plugins/chronos/control-client.js`
- ChronosGraph — Create: `.opencode/plugins/chronos/source-scope.js`
- ChronosGraph — Create: `.opencode/plugins/chronos/state-store.js`
- ChronosGraph — Create: `.opencode/plugins/chronos/lock.js`
- ChronosGraph — Create: `tests/integration/opencode/test_runtime_state.cjs`

**Interfaces:**
- Consumes: Task 1 HTTP envelope; Task 11 Gate endpoint.
- Produces:
  - `ControlClient.call(operation, payload) -> result` using `MCP_GATEWAY_CONTROL_API_KEY`.
  - `DiscoveryScopeV1` builder as single source for alias evidence and `Session.list` query.
  - local state under `~/.context-store/opencode-ingestion/<canonical-scope-id>/` owns exactly `source.json`, `<root-session-hash>.json`, and `<root-session-hash>.lock`.
  - `LocalSourceStateV1 { schema: "chronos.opencode.local-source.v1", canonical_source_scope_id, binding: SourceBindingWire }`.
  - `loadSourceState(scopeId)`, `writeSourceStateAtomic(state)`, and `quarantineInvalidSourceState(scopeId)` own `source.json`; successful enrollment/migration/binding refresh writes temp → fsync temp → rename → fsync directory.
  - startup/source resolution loads `source.json` and sends `CandidateSourceBindingWire { canonical_source_scope_id: state.canonical_source_scope_id, binding: state.binding }` as `SourceResolvePayload.candidate`; the client never sends an unpaired binding or substitutes mutable routing evidence for the candidate scope ID. Graph remains the verifier/continuity authority.
  - a Graph response containing a refreshed active-key binding atomically replaces the retained old binding only after successful source resolution/commit.
  - invalid/tampered/unknown-key local binding is unusable, is quarantined/diagnosed, and resolves as `SOURCE_SCOPE_CONTINUITY_UNRESOLVED` without receipt/checkpoint/source mutation.
  - `RootStateV1` stores only canonical scope/root opaque ids, committed cursor/turn/hash, pending retry state, blocked/divergence codes, and for pending work the pinned `evidence_contract_version`; raw path/URI/command/identity evidence is forbidden.
  - atomic temp+fsync+rename state replacement.
  - corrupt-state quarantine.
  - per-root inter-process lease lock with owner token, PID, expiry, 30s heartbeat, 120s lease; dead/stale owner reclaim; file existence alone is not authority.

- [ ] **Step 1: Write RED source-scope tests**

Assert `global + directory A != global + directory B`, alias/query scope symmetry, project-wide global invalidity, relocation produces unknown alias rather than new canonical identity.

- [ ] **Step 2: Write RED state/lock tests**

Assert atomic root/source state replacement, binding survives plugin restart, source resolution emits the exact stored scope ID + binding pair, tampered binding fails closed, refreshed binding atomically replaces the old token, raw routing/path evidence is absent from `source.json`, corruption quarantine, lock same-root exclusion, hard-owner death/stale lease reclaim, and finite reacquisition.

- [ ] **Step 3: Run RED**

Run: `cd "$GRAPH_ROOT" && node --test tests/integration/opencode/test_runtime_state.cjs`

Expected: FAIL because runtime state modules do not exist.

- [ ] **Step 4: Implement minimum client/source/state/lock modules**

Keep lock correctness local-only; server receipts remain final exactly-once authority.

- [ ] **Step 5: Run GREEN**

Run the same command. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd "$GRAPH_ROOT"
git add .opencode/plugins/chronos/control-client.js .opencode/plugins/chronos/source-scope.js   .opencode/plugins/chronos/state-store.js .opencode/plugins/chronos/lock.js   tests/integration/opencode/test_runtime_state.cjs
git commit -m "feat: OpenCode durable runtime state を追加"
```

---

### Task 14: Implement root reconciliation, checkpointing, recovery, and divergence

**Files:**
- ChronosGraph — Create: `.opencode/plugins/chronos/reconciler.js`
- ChronosGraph — Create: `.opencode/plugins/chronos/runtime.js`
- ChronosGraph — Create: `tests/integration/opencode/test_reconciler.cjs`

**Interfaces:**
- Consumes: Tasks 12-13.
- Produces:
  - activation + `session.status idle` + deprecated `session.idle` + 60s periodic sweep triggers.
  - exhaustive root discovery using widening limits 100→200→400… until unsaturated.
  - correctness targets per resolved scope are exactly: exhaustive current roots UNION locally known roots UNION exhaustively paged server receipt roots.
  - recovery/divergence consumes Task 1 `ReceiptRootRecord`, `ReceiptWireRecord`, `ReceiptValidationResult`, and `ReceiptDivergence` only. It reads the fixed receipt fields `root_session_id`, `turn_key`, `user_message_id`, `source_cursor_created_at`, `payload_hash`, `canonical_schema_version`, `evidence_contract_version`, and `identity_key_version`; no plugin-local interpretation of generic result dictionaries is allowed.
  - every `receipt.list_roots` / `receipt.list` recovery/divergence loop follows `next_page_token` until null; first-page-only inventory is forbidden.
  - `resolveRootSessionId(client, sessionId) -> Promise<string>` follows persisted `parentID` links to the root; missing/cyclic ancestry fails closed and creates no reconciliation state.
  - root-only event mapping; child events resolve to/dirty the owning root but never create child state.
  - full persisted root snapshot reconstruction followed by one eligible turn at a time.
  - contiguous checkpoint advance on `COMMITTED/ALREADY_COMMITTED` only.
  - retry backoff/pending state, same-root single flight + dirty coalescing.
  - lost-ACK retry, receipt-backed corrupt-state recovery, full committed-prefix divergence validation.
  - FAILED/ABORTED terminal closure and same-anchor `POST_TERMINAL_CONTINUATION`.

- [ ] **Step 1: Write RED trigger/discovery/root-resolution tests**

Assert lost event still converges via periodic sweep, >100 roots require widening, saturated maximum is incomplete, busy/retry roots defer, child→root parent-chain resolution works, and missing/cyclic ancestry fails closed with zero child/root state creation.

- [ ] **Step 2: Write RED checkpoint/retry tests**

Assert contiguous barrier, INCOMPLETE blocks later turns, retryable failure does not advance, lost ACK → ALREADY → checkpoint, trigger storm remains one active root reconciler.

- [ ] **Step 3: Write RED recovery/divergence tests**

Corrupt local state rebuilds from typed `ReceiptWireRecord` inventory without skipping a gap; missing required wire fields are rejected before checkpoint logic; lost delete/update events are detected by periodic whole-prefix validation using typed `ReceiptDivergence.code`; root deletion remains discoverable via local/server root union.

- [ ] **Step 4: Run RED**

Run: `cd "$GRAPH_ROOT" && node --test tests/integration/opencode/test_reconciler.cjs`

Expected: FAIL because reconciler/runtime do not exist.

- [ ] **Step 5: Implement reconciler**

Treat events as hints only. Do not introduce a code path that directly durable-writes from an event callback.

- [ ] **Step 6: Run GREEN**

Run the same command. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd "$GRAPH_ROOT"
git add .opencode/plugins/chronos/reconciler.js .opencode/plugins/chronos/runtime.js   tests/integration/opencode/test_reconciler.cjs
git commit -m "feat: OpenCode durable reconciliation loop を追加"
```

---

### Task 15: Replace the OpenCode plugin adapter and prove zero legacy side channel

**Files:**
- ChronosGraph — Modify: `.opencode/plugins/chronos-turn-end.js`
- ChronosGraph — Modify: `package.json`
- ChronosGraph — Modify: `tests/integration/test_opencode_turn_end_plugin.cjs`
- ChronosGraph — Modify: `tests/unit/test_chronos_gate_migration_guards.py`

**Interfaces:**
- Consumes: Task 14 `OpenCodeIngestionRuntime`.
- Produces:
  - plugin entrypoint is loader/adapter only.
  - npm/local path both instantiate the same runtime.
  - package ships `.opencode/plugins/chronos/**`.
  - OpenCode `all` never spawns `agent_turn_hook.py`; selective mode does not start durable reconciliation.
  - legacy non-OpenCode `scripts/agent_turn_hook.py` remains unchanged.

- [ ] **Step 1: Rewrite existing integration test as RED negative proof**

For `all`, assert runtime reconcile is invoked while fake `spawn` count is zero. Add spies proving no legacy hook script is opened/executed. For `selective`, assert no durable reconciler mutation.

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && node --test tests/integration/test_opencode_turn_end_plugin.cjs`

Expected: FAIL because current plugin spawns the detached hook.

- [ ] **Step 3: Replace plugin internals with runtime adapter**

Keep existing package id/SSOT guard; remove conversation rendering/detached subprocess path from OpenCode plugin.

- [ ] **Step 4: Update package export guard**

Update `package.json.files` and `test_package_exports_only_turn_end_opencode_plugin` to include runtime modules while keeping a single public plugin entrypoint.

- [ ] **Step 5: Run GREEN**

Run:
`cd "$GRAPH_ROOT" && node --test tests/integration/test_opencode_turn_end_plugin.cjs tests/integration/opencode/*.cjs`

Run:
`cd "$GRAPH_ROOT" && uv run pytest tests/unit/test_chronos_gate_migration_guards.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd "$GRAPH_ROOT"
git add .opencode/plugins package.json tests/integration tests/unit/test_chronos_gate_migration_guards.py
git commit -m "feat: OpenCode all-mode を durable reconciler へ切替"
```

---

### Task 16: Integrate bootstrap/setup, credentials, source enrollment, and real-turn smoke

**Files:**
- ChronosGraph — Modify: `scripts/bootstrap.sh`
- ChronosGraph — Modify: `scripts/agent_assets/hooks.py`
- ChronosGraph — Modify: `.env.example`
- ChronosGraph — Modify: `docs/agent-setup-protocol.md`
- ChronosGraph — Modify: `docs/agent-setup-protocol.ja.md`
- ChronosGraph — Modify: `docs/configuration.md`
- ChronosGraph — Modify: `tests/unit/test_sync_agent_assets.py`
- ChronosGraph — Modify: `tests/integration/test_sync_agent_assets.py`
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
  - when the staged keyring exists and the migrated manifest value row is absent, first-time setup invokes `context-store-admin ingestion-keyring provision`; when the file is absent/malformed, setup stops incomplete with staging instructions rather than generating keys.
  - existing manifests use `verify`; rotation remains an explicit operator `rotate` action and is not implicit bootstrap behavior.
  - explicit source `REGISTER_NEW_SOURCE_SCOPE`/alias migration via operator control only.
  - OpenCode all-mode smoke creates a unique real turn, waits for receipt/checkpoint, and performs read-side verification.
  - cleanup may use only the exact memory IDs/receipt IDs captured from that probe. If the setup context has an existing exact-ID deletion capability (for example an authorized regular MCP `memory_delete` call), use it only for those IDs; otherwise report `SMOKE_CLEANUP_INCOMPLETE`. Search-by-marker/broad deletion is forbidden.
  - setup never substitutes direct `memory_save`/`session_flush`/`ingest_turn` calls.

- [ ] **Step 1: Write RED setup tests**

Cover missing keyring/manifest, distinct credential requirement, unresolved source zero mutation, explicit new-source transition, local/npm plugin configuration preservation, smoke refusing to claim complete without real-turn receipt+readback, exact-ID-only cleanup, and `SMOKE_CLEANUP_INCOMPLETE` when exact deletion is unavailable. Add effective-registry tests that parse the generated `MCP_GATEWAY_API_KEYS_JSON` through the real Gate `ApiKeyAuthenticator` semantics and prove: legacy key authenticates as `default`, control key as `opencode-ingestion`, operator key as `chronos-setup`; all raw values are distinct; unrelated registry entries survive; malformed/duplicate registry input fails before write; `--rotate-keys` rotates all three managed entries together. The integration test invokes the Task 11 Gate environment through `uv --directory "$GATE_ROOT" run --no-sync`; missing `GATE_ROOT` is a test failure, not a skip. Reuse Scenario Y routing assertions so control/operator keys are denied on regular MCP and the legacy key is denied on the control endpoint.

- [ ] **Step 2: Run RED**

Run:
`cd "$GRAPH_ROOT" && GATE_ROOT="$GATE_ROOT" uv run pytest tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py tests/integration/test_opencode_durable_setup.py -v`

Expected: FAIL on new durable setup expectations.

- [ ] **Step 3: Implement setup wiring**

Do not write `.npmrc`, generate ingestion key material, or accept raw ingestion keys as CLI arguments. For Gate API credentials, parse/preserve the existing principal registry, materialize the three managed env values, validate global raw-key uniqueness, then atomically rewrite the effective registry plus managed env values; `--rotate-keys` rotates the whole managed set only. If the staged ingestion keyring is absent/malformed, fail setup before source enrollment. If the keyring is valid and the manifest row is absent, invoke `context-store-admin ingestion-keyring provision`; otherwise invoke `verify`. Setup may invoke the Graph-local admin CLI but must not implement keyring DB/file mutation itself.

- [ ] **Step 4: Update English/Japanese docs and config reference**

Keep selective instructions intact; document exact control/operator/keyring prerequisites and real-turn smoke.

- [ ] **Step 5: Run GREEN**

Run the same focused pytest command with `GATE_ROOT` plus `bash -n scripts/bootstrap.sh`.

Expected: PASS, including the real Gate `ApiKeyAuthenticator` principal mapping and Scenario Y path-separation assertions.

- [ ] **Step 6: Commit**

```bash
cd "$GRAPH_ROOT"
git add scripts/bootstrap.sh scripts/agent_assets/hooks.py .env.example docs   tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py   tests/integration/test_opencode_durable_setup.py
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
  - exact command target `npx --yes opencode-ai@1.18.34`.
  - harness requires `GATE_ROOT`; before starting Gate it runs `uv --directory "$GATE_ROOT" sync --extra dev`, then installs the current Graph worktree editable with `uv --directory "$GATE_ROOT" pip install -e "$GRAPH_ROOT"`, asserts `chronos_shared.opencode_control.__file__` resolves under `$GRAPH_ROOT`, and launches `uv --directory "$GATE_ROOT" run --no-sync chronos-gate`. No later native-harness Gate command may omit `--no-sync` before Task 18.
  - local OpenAI-compatible deterministic provider configured in generated `opencode.json` as provider id `chronos-fixture`, npm `@ai-sdk/openai-compatible`, model id `fixture-model`, local `baseURL=http://127.0.0.1:<fixture-port>/v1`, and non-secret fixture API key.
  - OpenCode model selection is exactly `chronos-fixture/fixture-model`.
  - npm-style mode builds the current implementation with `npm pack --json`, installs that tarball into the temporary project with `npm install --ignore-scripts <tarball>`, and configures OpenCode with plugin identity `@yohi/opencode-plugin-chronos-turn-end`; no package publication is required for acceptance.
  - repository-local mode loads the project-local `.opencode/plugins/chronos-turn-end.js`.
  - clean temp HOME/project/npm-path and repository-local plugin acceptance modes.
  - fixture scripts deterministic SUCCESS, provider-error FAILED, tool call, compaction pressure, and child/sub-agent behavior without external LLM credits.
  - ABORTED is produced by starting a deliberately long streaming fixture response and invoking OpenCode's session-abort path while generation is in flight; do not fake the persisted `MessageAbortedError` record.

- [ ] **Step 1: Write native harness RED smoke**

Require `GATE_ROOT`; run Gate `uv sync --extra dev` first, install current `$GRAPH_ROOT` editable second, assert the loaded shared module path is under `$GRAPH_ROOT`, and launch Gate with `uv --directory "$GATE_ROOT" run --no-sync chronos-gate`. Generate the exact `chronos-fixture` provider/model configuration above. For npm-style mode run `npm pack --json` and install the produced tarball into the temporary project before configuring the package identity; for local mode use the repository-local plugin. Start the deterministic provider and OpenCode v1.18.34; Gate owns startup of the private Graph control subprocess. Assert actual plugin load and a root persisted session.

- [ ] **Step 2: Run RED**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/native/opencode/test_native_opencode_all.py -k smoke -v`

Expected: FAIL until harness/config/plugin integration is complete.

- [ ] **Step 3: Add native scenarios A-H/R/Q**

At minimum execute:
  - normal success and failed/aborted;
  - event loss with periodic recovery;
  - >100 roots;
  - lost ACK/restart;
  - duplicate hint storm;
  - real child session exists/events observed but child receipt/checkpoint/pending remain zero;
  - npm and local plugin path both show `memory_save==0`, `session_flush==0`, detached hook spawn==0`.

- [ ] **Step 4: Add post-terminal Scenario AB**

Commit FAILED/ABORTED user-only receipt, resume same user anchor to success, assert immutable receipt + divergence, then a new eligible user anchor commits normally.

- [ ] **Step 5: Run GREEN**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/native/opencode/test_native_opencode_all.py -v`

Expected: PASS using exact `opencode-ai@1.18.34`; no external provider/credit required.

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

- [ ] **Step 7: Run Scenario Y in Gate**

Run:
`cd "$GATE_ROOT" && uv sync --frozen --extra dev && uv run --frozen pytest tests/test_session_bound_messages.py tests/test_control_client.py tests/test_opencode_control_endpoint.py -v`

Expected: PASS, including legacy/control/operator credential separation and no control operation through normal MCP.

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

- [ ] **Step 9: Run native Scenario AB and zero-legacy acceptance**

Run: `cd "$GRAPH_ROOT" && uv run pytest tests/native/opencode/test_native_opencode_all.py -v`

Expected: PASS; actual v1.18.34 npm/local loader paths both satisfy negative invariants.

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

Run:
```bash
cd "$GATE_ROOT"
uv sync --frozen --extra dev
uv run --frozen pytest tests -v
uv run --frozen mypy src
uv run --frozen ruff check src tests
uv run --frozen ruff format --check src tests
git diff --check
```

Expected: all commands succeed.

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
  typed SourceBindingWire / ReceiptWireRecord / ReceiptDivergence
  stable source/divergence/validation enums
  Task 14 consumes exact shared fields, never generic dict authority

PLAN-RG-004:
  LocalSourceStateV1 owns source.json
  atomic persist/restart/refresh/tamper-failure tests

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
- [x] Review Focus conditions are each pinned by a named Task/test.
- [x] Production implementation remains blocked until this plan passes its own Review Gate.
