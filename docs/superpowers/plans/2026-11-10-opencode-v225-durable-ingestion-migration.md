# ChronosGraph — OpenCode v2.2.5 Durable All-Mode Ingestion Implementation Plan (migration draft)

> **For future implementation:** Follow the Superpowers plan task-by-task only after Human Owner approves the corresponding V2 design and authorizes implementation. Checklist entries here are **unexecuted**.

**Goal:** Port the PR #385 durable all-mode ingestion design to a verified OpenCode v2.2.5-native public API while retaining existing Graph/Gate durability, authentication and data-preservation contracts.  
**Architecture:** Keep authoritative PREPARE/COMMIT and Gate/Graph services. Replace V1-specific plugin extraction, discovery, lifecycle, reconciliation and native acceptance. Complete the public V2 evidence contract before treating adapter implementation as safe.  
**Tech stack:** OpenCode CLI 2.2.5, @opencode/plugin@2.2.5, conditional @opencode/client@2.2.5, JavaScript/Node, Python/pytest, SQLite, PostgreSQL/Supabase, ChronosGraph and ChronosGate.  
**Spec:** [OpenCode v2.2.5 migration design](../specs/2026-11-10-opencode-v225-durable-ingestion-migration-design.md).  
**Historical plan:** [PR #385 V1 implementation plan](2026-10-06-opencode-all-durable-ingestion.md).  
**Status:** Documentation-only; do not run or commit production steps before authorization.

## Global constraints

- Original Tasks **1–11** (protocol, stores, manifest/keyring, Graph service, Gate authentication/control) remain conceptually authoritative unless a proven V2-specific interface change demands a limited adjustment. Preserve their detailed negative tests and transaction gates, not merely this summary.
- Original Tasks **12–18** are mapped below to V2-A through V2-G. The old V1-native fixtures, SDK imports, widening pagination and completion classification cannot be treated as new V2 evidence.
- All OpenCode packages, installed binary and actual public artifacts must be release-pinned at **2.2.5**. A code/type review never substitutes for actual host execution.
- Maintain source-binding scope, immutable receipts, version-pinned hash comparison, all-mode zero-legacy-side-channel, selective/Claude/Codex compatibility and non-skippable database acceptance.
- V2-only is **recommended, not Owner-approved**. A dual-mode branch needs separate explicitly approved adapter/tests. The disputed `turn_key` formula remains a design checkpoint.
- Do not add unused optional experimental features, expand to an autonomous review loop, modify the existing PR or merge/release as part of this plan.

## Task mapping and file ownership

| Historical Task | V2 treatment | Deliverable |
|---|---|---|
| 1–11 | RETAIN, limited verified adaptation only | Existing Graph/Gate protocol, persistence, keys and authorization |
| 12 | V2-A + V2-B | Native data contract, provenance/lineage and deterministic projection |
| 13 | V2-C | Source scope, cursor paging, local state, crash-recoverable lock |
| 14 | V2-D | Event-hint reconciliation, persisted terminal evidence, recovery |
| 15 | V2-E | Plugin.define entrypoint, stable ID, local/npm packaging and cleanup |
| 16 | V2-E | V2 provider/config registration, principal-safe setup and smoke |
| 17 | V2-F | Real v2.2.5 process-native acceptance |
| 18 | V2-G | Cross-repository locked acceptance and Owner handoff |

## Review focus (bounded self-check, no recurring gate)

1. Admission without delivery, duplicate delivery and cancellation must not create ghost receipts.
2. Multiple delivered anchors within one running execution must be unambiguously attributed or stop ingestion.
3. Incomplete cursor pages, changed location and missing older turns must not yield false `caught_up`.
4. Interrupted/resumed/compacted same-anchor history must neither expose partial content nor rewrite acknowledged receipts.
5. Plugin unload/reload, policy wildcard differences, external_directory defaults and control principal confusion must not weaken authorization or leak side effects.

### Task V2-A: Freeze actual v2.2.5 public and native evidence

**Files:** `tests/native/opencode/README.md`; tagged fixture captures under `tests/native/opencode/` and `tests/integration/opencode/`; exact public type/fixture note under the V2 design.  
**Consumes:** upstream tag v2.2.5 and migration reference ``6–10, 16–17, 20, 29–30.  
**Produces:** verified `NativeSnapshotV225`, `DeliveredAnchorV225`, `ExecutionEvidenceV225` fixtures, all required API response fields, pagination and terminal evidence cases.

- [ ] Record `opencode --version`, resolved `@opencode/plugin`, conditional client version and package integrity; fail if not pinned 2.2.5.
- [ ] Execute real deterministic local-provider root+child sessions; capture sanitized persisted success, provider failure, real interruption, queue, steer, undelivered/cancelled inbox, compaction, resumed same-anchor and restart records.
- [ ] Confirm the public API for session root, location, pagination, inbox delivery, execution ownership and durable terminal outcome. Verify actual cursors, event envelopes and lifecycle timing, not names alone.
- [ ] For missing authority, classify the exact affected operation `BLOCKED` without inventing private API use. **Stop:** no implementation on that affected adapter until an allowed public source exists.
- [ ] Record evidence location/version digest and update the V2 spec's previously proposed contracts only where actual host facts require a correction.

### Task V2-B: Deterministic V2 canonical input and logical lineage (former Task 12)

**Files:** Create `.opencode/plugins/chronos/canonicalize.js`, `lineage.js` and `control-client.js`; create `tests/integration/opencode/test_canonicalize.cjs` and `test_lineage.cjs`.  
**Interfaces:** From `NativeSnapshotV225` produce deterministic anchor classification, ordered semantic projection, identity evidence and terminal/blocked reason. Do **not** depend on a local committed checkpoint to derive immutable identity.

- [ ] **RED:** tests for delivered versus only enqueued/cancelled, queue/steer, file-only user, synthetic controls, child session, multi-anchor execution, compaction replay, same-anchor resume and V1/V2 namespace distinction.
- [ ] **RED:** pin exactly **one Owner-approved** `turn_key` formula; never implement historical `design `1.5` and `plan Task 12` formulas simultaneously. Check local state loss/recovery preserves IDs.
- [ ] Implement pure extraction without network or original-file rereads. Map ambiguous provenance/ownership/resource identity/compaction to typed blocked states; preserve versioned sanitized input order, `native` fields and payload hashes.
- [ ] **GREEN:** `node --test tests/integration/opencode/test_canonicalize.cjs tests/integration/opencode/test_lineage.cjs`. Expected PASS only after real execution; presently NOT RUN.

### Task V2-C: Canonical source descriptor, cursor discovery, state and root lock (former Task 13)

**Files:** `.opencode/plugins/chronos/source-scope.js`, `state-store.js`, `lock.js` and focused discovery/lock tests under `tests/integration/opencode/`.  
**Interfaces:** Exhaustive root/message snapshot under one authenticated location descriptor. If cursor/scope changes, produce `DISCOVERY_INCOMPLETE` or `SOURCE_ROUTING_SCOPE_MISMATCH` rather than partial success.

- [ ] **RED:** more than one page, lost/nonadvancing cursor, duplicate message, root parentID, child, moved directory, shared global project ID and stale candidate binding.
- [ ] Implement stable location filters, exact cursor follow-through with verified end marker, ordered message pages and post-read scope revalidation. Do not port V1 N*=2 scan.
- [ ] Preserve source.json binding, atomic checkpoint, bounded diagnostics, inter-process lock crash recovery and no raw key/path persistence.
- [ ] **GREEN:** run focused Node integration tests with captured real V2 fixtures and document observable results.

### Task V2-D: Event-hint reconciler, terminal gate and recovery (former Task 14)

**Files:** `.opencode/plugins/chronos/reconciler.js`, `runtime.js`; `test_reconciler.cjs`, `test_recovery.cjs`, `test_divergence.cjs`.

- [ ] **RED:** lost/duplicated execution hints, unload, abort, unknown terminal evidence, inbox pending, multi-anchor delivery, incomplete cursor, quiescence changes, lost ACK and corrupt checkpoint.
- [ ] Subscribe with abort signal; treat typed events as hints only; activation and finite periodic 60-second full sweeps are correctness fallback.
- [ ] Require complete persisted all-page snapshot and verified terminal ownership before Graph `turn.ingest`. Failed/aborted store only confirmed user intent; post-terminal same anchor is divergence.
- [ ] Advance only contiguous acknowledged receipt prefix; prevent old holes from being skipped; post-drain recheck before `caught_up`. Bounded backoff and source-aware receipt readback for lost ACK.
- [ ] **GREEN:** `node --test tests/integration/opencode/test_reconciler.cjs tests/integration/opencode/test_recovery.cjs tests/integration/opencode/test_divergence.cjs`.

### Task V2-E: V2 loader/package and secure setup (former Tasks 15–16)

**Files:** `.opencode/plugins/chronos-turn-end.js`, `.opencode/plugins/chronos/package.json`, root `package.json`, `scripts/agent_assets/hooks.py`, `scripts/bootstrap.sh` and existing packaging/config tests.

- [ ] **RED:** V1 export cannot substitute for `Plugin.define({id, setup})`, stable plugin storage ID, unload cleanup, session/event location scopes, reload/duplicate activation, no detached hook and child no-op.
- [ ] Implement V2 native adapter using `@opencode/plugin@2.2.5`; conditional `@opencode/client@2.2.5` only when needed. Keep the shared runtime accessible from both packaged tarball and repository-local loader.
- [ ] Use temporary V2 provider config for fixture: `package: "aisdk:@ai-sdk/openai-compatible"` plus `settings.baseURL`; local `plugins[].package` denotes a directory.
- [ ] **RED/GREEN security:** principal split and actual effective `plugin.use`/`mcp.use`/`integration.use` denies; required `external_directory` ask; no raw secrets or all-mode legacy `memory_save`, `session_flush`, detached hook.
- [ ] **GREEN:** real `npm pack` package contents and existing migration-guard, setup and integration tests.

### Task V2-F: Pinned native v2.2.5 acceptance (former Task 17)

**Files:** `tests/native/opencode/fixture_provider.py`, `harness.py`, `test_native_opencode_all.py`, `README.md`.

- [ ] Install exact version with clean temporary HOME/project, record effective config, package versions/integrity and environment scope. No nondeterministic external LLM provider required.
- [ ] Run design cases V2-01 to V2-14 applicable to the implementation: success, provider error, real abort; inbox queue/steer/cancel; multi-anchor; child; compaction; event loss; restart; lost ACK; corrupt state; scope/binding/alias; same-anchor divergence.
- [ ] Exercise both **actual installed npm package** and repository-local plugin path; prove zero V1 side-channel and unchanged selective/non-OpenCode flow.
- [ ] Record exact PASS, FAIL, BLOCKED, NOT RUN and evidence-backed N/A for each case. Unit pass or mock persistence does not count as native pass.

### Task V2-G: Cross-repository locked acceptance and Owner checkpoint (former Task 18)

**Files:** existing Graph/Gate integration tests, Gate `pyproject.toml` and `uv.lock` **only after implementation authorization**.

- [ ] Run preserved transaction/keyring/alias/auth tests, SQLite and **non-skipped PostgreSQL/Supabase**, Graph-intent atomic outbox, operator and session restrictions, Native V2 and selective/non-OpenCode regressions.
- [ ] Pin final Graph implementation SHA in the Gate dependency only under approved implementation scope; verify locked install and rerun appropriate Gate/Graph acceptance.
- [ ] Deliver concise Owner decision table with actual failures, unknowns, blocked reasons and residual risks; no extra review/fix cycles solely for a new Finding.
- [ ] **STOP:** do not automatically create a PR, merge, release, start S2, implement optional V2 features or trigger independent re-review. Await explicit Owner GO/HOLD for any next task.

## Traceability and completion

V2-A/B cover design ``3–7; V2-C/D cover ``2–4, 9; V2-E covers ``2, 8; V2-F/G cover `10 and unchanged historical design ``1–2, 5–14. No host tests are reported as executed at the time this plan is committed. The new feature branch is only a place to record the migration design and plan; it does not replace the previously approved V1 files.
