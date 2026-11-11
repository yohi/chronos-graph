# ChronosGraph — OpenCode v2.2.5 Durable All-Mode Ingestion Implementation Plan (migration draft)

> **For future implementation:** Follow the Superpowers plan task-by-task only after Human Owner approves the corresponding V2 design and authorizes implementation. Checklist entries here are **unexecuted**.

**Goal:** Port the PR #385 durable all-mode ingestion design to a verified OpenCode v2.2.5-native public API while retaining existing Graph/Gate durability, authentication and data-preservation contracts.  
**Architecture:** Keep authoritative PREPARE/COMMIT and Gate/Graph services. Replace V1-specific plugin extraction, discovery, lifecycle, reconciliation and native acceptance. Complete the public V2 evidence contract before treating adapter implementation as safe.  
**Tech stack:** OpenCode CLI 2.2.5, @opencode/plugin@2.2.5, @opencode/client@2.2.5 (proposed authoritative public history adapter), JavaScript/Node, Python/pytest, SQLite, PostgreSQL/Supabase, ChronosGraph and ChronosGate.  
**Spec:** [OpenCode v2.2.5 migration design](../specs/2026-11-10-opencode-v225-durable-ingestion-migration-design.md).  
**Historical plan:** [PR #385 V1 implementation plan](2026-10-06-opencode-all-durable-ingestion.md).  
**Status:** DOCUMENT_READY_WITH_BLOCKERS / IMPLEMENTATION_BLOCKED; V2-only Owner-approved (2026-11-11 JST). Default CLI historical `session.created` event readback FAIL (observed). E01–E06, restart proof and Implementation tests NOT RUN. Documentation-only; no production or Host modification authorized.

## Global constraints

**Limited-remediation proof authority (F-001–F-003):** Use Design `4.1 `EvidenceStatus = PROVEN | NOT_PROVEN | CONTRADICTED`, `TerminalOutcomeV225 = SUCCESS | FAILED | ABORTED` and `RootEvidenceDecisionV225` exactly. `outcome` is `null` unless `PROVEN`. `NativeSnapshotV225` contains `session`, `messages`, `pending`, `durableEvents` and `replaySyncedWatermark`. These are **Chronos adapter DTOs**, not assumed upstream exports. Source inspection is not installed-host PASS; all commands below remain **NOT RUN**. An unproven/contradicted Root never invokes Graph PREPARE/COMMIT or advances checkpoint; other Roots are not stopped. V2-only, `turn_key` and sufficiency of historical public evidence remain Owner UNDECIDED.

- Original Tasks **1–11** (protocol, stores, manifest/keyring, Graph service, Gate authentication/control) remain conceptually authoritative unless a proven V2-specific interface change demands a limited adjustment. Preserve their detailed negative tests and transaction gates, not merely this summary.
- Original Tasks **12–18** are mapped below to V2-A through V2-G. The old V1-native fixtures, SDK imports, widening pagination and completion classification cannot be treated as new V2 evidence.
- All OpenCode packages, installed binary and actual public artifacts must be release-pinned at **2.2.5**. A code/type review never substitutes for actual host execution.
- Maintain source-binding scope, immutable receipts, version-pinned hash comparison, all-mode zero-legacy-side-channel, selective/Claude/Codex compatibility and non-skippable database acceptance.
- **V2-only was approved by the Human Owner on 2026-11-11 JST.** No dual-runtime adapter in this scope; preserve V1 historical receipts and Source Identity. The `turn_key` formula and supported Host policy remain distinct Owner decisions.
- Do not add unused optional experimental features, expand to an autonomous review loop, modify the existing PR or merge/release as part of this plan.

### F-001 capability blocker — observed prior to E01–E06

**User-supplied isolated PoC, 2026-11-11 JST (not independently rerun here):** Authenticated default `opencode serve` v2.2.5 returned a Root Session (`parentID:null`), zero Message and Pending entries, and **only `log.synced(seq:0)`** on two public historical log reads. `session.created` was absent. This is an **observed failure of initial event-body readback**, **not** evidence that E01–E06 or restart tests failed; those remain `NOT RUN`.

**Pinned upstream source:** `Bus.configured` uses `persist = options?.persist ?? false`; `EventTable` writes are conditional on persistence while sequence reservation proceeds. `Server.routes` passes `options.events?.persist`; the standard CLI `server-process.ts` launcher omits `events` and `serve` exposes no persist flag. Thus a successful public `Session.log` HTTP/SSE response with `log.synced` does **not** prove durable event bodies exist. See [Bus](https://github.com/anomalyco/opencode/blob/v2.2.5/packages/core/src/bus.ts), [Server routes](https://github.com/anomalyco/opencode/blob/v2.2.5/packages/server/src/routes.ts), [CLI launcher](https://github.com/anomalyco/opencode/blob/v2.2.5/packages/cli/src/server-process.ts).

**Consequences for Design `4.2:** The default CLI Host currently cannot satisfy the required historical `session.inbox.delivered` and `session.execution.*` evidence contract. The historical proof adapter must emit `RootEvidenceDecisionV225` with `evidenceStatus:"NOT_PROVEN"`, `outcome:null`, `reasonCode:"DURABLE_EVIDENCE_UNAVAILABLE"` and, only where host capability is independently established, diagnostic `EVENT_LOG_PERSISTENCE_DISABLED`. Missing event rows alone are **not `CONTRADICTED`**. No Graph `turn.ingest` / PREPARE/COMMIT, Checkpoint mutation or `caught_up`. Nonaffected Root handling remains separately governed by evidence sufficiency.

**Owner architecture decision required (not adopted by this update):** (A) Keep ordinary unmodified `opencode serve` as a mandatory support target; require separately proven **public persisted** historical evidence beyond this unavailable Event Log, or remain BLOCKED. (B) Explicitly authorize and support a separate Host with persistence enabled, then validate its effective setting, restart replay and all per-Anchor cases. `ServerOptions.events.persist:true` is an internal API facility, **not** a ready CLI flag or authority to build/deploy a custom Host. Evidence for B cannot certify A. No private-store fallback, synthetic past events, new independent review or automatic test/implementation.

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

**F-001/F-002 required acceptance (proposed, not yet executed):** Identify separately durable **Event Log** records (`session.inbox.enqueued/delivered/cancelled`, `session.execution.started/succeeded/failed/interrupted`, `session.step.*`), persisted **Message** (`user`, `assistant`, `idle`), persisted **Pending** state, and live-only `text.delta` / reasoning deltas. Produce the exact released 2.2.5 API field map to the `NativeSnapshotV225` DTO, including stable event/message IDs, origin, terminal and log-sync watermark. A source-level `durable` annotation cannot by itself establish replay availability after Host restart.

**Evidence RED scenarios:** replay with exclusive `after` reaches `log.synced`; delivered `inboxID` joins same User Message ID; queued/enqueued-but-not-delivered/cancelled produce no anchor; multi-anchor steers belong to one busy period; `execution.interrupted` reasons `user` versus `shutdown/superseded/inactivity`; log gap, missing message, unverified provenance or incompatible Idle outcomes yield `NOT_PROVEN` or `CONTRADICTED`. Shared aggregate sequence numbers need not be adjacent; validate absence of relevant loss without inventing a seq-contiguity rule.

**Future command / RED then GREEN (only after Owner test GO):**
```bash
cd "$GRAPH_ROOT"
uv run pytest tests/native/opencode/test_native_opencode_all.py -k "replay or evidence or delivery or ownership" -v
```
RED expected: newly added expected evidence assertions fail where V2 adapter/fixture is missing (environment/setup errors do not count). GREEN expected: public historical replay, cancellation, multi-anchor and fail-closed assertions PASS with real pinned Host evidence; otherwise `BLOCKED`, not PASS. Inadequate public proof -> stop affected adapter at Owner architecture checkpoint; no Private API substitute.

**Files:** `tests/native/opencode/README.md`; tagged fixture captures under `tests/native/opencode/` and `tests/integration/opencode/`; exact public type/fixture note under the V2 design.  
**Consumes:** upstream tag v2.2.5 and migration reference ``6–10, 16–17, 20, 29–30.  
**Produces:** verified `NativeSnapshotV225`, `DeliveredAnchorV225`, `ExecutionEvidenceV225` fixtures, all required API response fields, pagination and terminal evidence cases.

- [ ] **Already observed: INITIAL_EVENT_REPLAY FAIL (default CLI):** The `session.created` body is absent from public `Session.log` although `log.synced(seq:0)` is returned. This is **not** an E01–E06 run and does not establish missing Delivery/Terminal events in a completed execution.
- [ ] **BLOCKED prerequisite, subject to separate Owner authorization:** Confirm the supported Host mode and effective event persistence; obtain a newly created `session.created` through public `Session.log` **before and after Host restart** (not merely `log.synced`), then obtain `session.inbox.delivered` and `session.execution.*` for genuine eligible input. Only after this source is demonstrably complete may the existing V2-A per-anchor evidence proof proceed.
- [ ] If prerequisite fails, classify affected Root `NOT_PROVEN / DURABLE_EVIDENCE_UNAVAILABLE`; do **not** run broad native acceptance as a substitute, mutate Graph/Gate, inspect private OpenCode DB, start a nested Host or implement an unapproved alternative.

- [ ] Record `opencode --version`, resolved `@opencode/plugin`, conditional client version and package integrity; fail if not pinned 2.2.5.
- [ ] Execute real deterministic local-provider root+child sessions; capture sanitized persisted success, provider failure, real interruption, queue, steer, undelivered/cancelled inbox, compaction, resumed same-anchor and restart records.
- [ ] Confirm the public API for session root, location, pagination, inbox delivery, execution ownership and durable terminal outcome. Verify actual cursors, event envelopes and lifecycle timing, not names alone.
- [ ] For missing authority, classify the exact affected operation `BLOCKED` without inventing private API use. **Stop:** no implementation on that affected adapter until an allowed public source exists.
- [ ] Record evidence location/version digest and update the V2 spec's previously proposed contracts only where actual host facts require a correction.

### Task V2-B: Deterministic V2 canonical input and logical lineage (former Task 12)

**F-001 interface fence:** Consume complete `NativeSnapshotV225` from V2-C; produce `RootEvidenceDecisionV225` plus deterministic `semantic_projection` / `identity_evidence` **only when `PROVEN`**. A candidate Delivered Anchor requires durable `session.inbox.delivered` linked by `inboxID` to a persisted root User Message, verified `USER_AUTHORED` or `USER_DERIVED` and authentic canonical Source Scope. Text similarity or User type alone is not enough.

**RED requirements:** `DELIVERY_NOT_PROVEN` for enqueued/pending/cancelled; `TURN_OWNERSHIP_AMBIGUOUS` for multiple delivered anchors within one execution/Idle without provable per-anchor attribution; `TERMINAL_EVIDENCE_UNAVAILABLE` for missing matching durable terminal and Idle; `EVIDENCE_CONTRADICTED` for inconsistent log/message fields. `PROVEN SUCCESS` requires settled, uniquely attributable Assistant content; `PROVEN FAILED` an execution error and failed Idle; `PROVEN ABORTED` a user-reason interrupted event, matching interrupted Idle and no ambiguous resume. Non-user interruptions do not prove ABORTED. `NOT_PROVEN/CONTRADICTED` outputs `outcome:null` with no hash/ingest. Same-anchor post-terminal continuation is divergence.

**Future RED/GREEN command:** `node --test tests/integration/opencode/test_canonicalize.cjs tests/integration/opencode/test_lineage.cjs`. RED: new evidence/provenance assertions fail for unsafe mapping. GREEN: complete tagged fixture cases PASS; otherwise BLOCKED. **Human Owner's `turn_key` decision remains required before actual implementation**, and V1 receipts must not be rewritten.

**Files:** Create `.opencode/plugins/chronos/canonicalize.js`, `lineage.js` and `control-client.js`; create `tests/integration/opencode/test_canonicalize.cjs` and `test_lineage.cjs`.  
**Interfaces:** From `NativeSnapshotV225` produce deterministic anchor classification, ordered semantic projection, identity evidence and terminal/blocked reason. Do **not** depend on a local committed checkpoint to derive immutable identity.

- [ ] **RED:** tests for delivered versus only enqueued/cancelled, queue/steer, file-only user, synthetic controls, child session, multi-anchor execution, compaction replay, same-anchor resume and V1/V2 namespace distinction.
- [ ] **RED:** pin exactly **one Owner-approved** `turn_key` formula; never implement historical Design `1.5 and Plan Task 12 formulas simultaneously. Check local state loss/recovery preserves IDs.
- [ ] Implement pure extraction without network or original-file rereads. Map ambiguous provenance/ownership/resource identity/compaction to typed blocked states; preserve versioned sanitized input order, `native` fields and payload hashes.
- [ ] **GREEN:** `node --test tests/integration/opencode/test_canonicalize.cjs tests/integration/opencode/test_lineage.cjs`. Expected PASS only after real execution; presently NOT RUN.

### Task V2-C: Canonical source descriptor, cursor discovery, state and root lock (former Task 13)

**F-002 public client boundary and exact pagination assertions:** `ctx.session` provides in-process location-bound Plugin Domain operations (no asserted historical completeness); `@opencode/client@2.2.5` is the proposed single read-only public history adapter to the **existing operator-provisioned Host**. Operator owns exact Host base URL, supported authentication material and expected instance/location. Do not discover/start a Nested Server in `setup` or read Credential File/private APIs. If tagged published Client lacks the required method, report `PUBLIC_API_UNAVAILABLE` and seek Owner approval before an architectural change.

| Operation | Contract tested against pinned 2.2.5 Host |
|---|---|
| `Session.list` | first `order:asc,parentID:null,limit` plus selected `directory` or `project+subpath`; opaque `cursor` preserves filters; `{data,cursor:{previous?,next?}}` |
| `Session.get` | `sessionID` -> `{data:Session.Info}`; compare root `parentID`, actual location and canonical source binding |
| `Message.list` | initial `sessionID,order:asc,limit`; later `sessionID,cursor,limit` **without `order`**; `{data,cursor:{previous?,next?}}`, all message types |
| `Pending.list` | `sessionID` -> `{data:SessionInbox.Info[]}`; pending alone is never proof of delivery |
| `Session.log` | `sessionID,after?,follow?` -> public durable events and `log.synced`; restart replay completeness must be established |

**Historical-event Host capability is a prerequisite to exhaustive discovery:** With the ordinary CLI `persist:false` default, a well-formed Message cursor and `log.synced` marker are **insufficient** to construct a complete `NativeSnapshotV225`. V2-C must distinguish `PUBLIC_API_AVAILABLE` from `HISTORICAL_EVENT_ROWS_AVAILABLE` and return `DURABLE_EVIDENCE_UNAVAILABLE` for the documented CLI condition. An event-persisting Host remains an Owner support/architecture decision; do not assume changing `opencode serve` flags can enable it.

**Pagination stop:** `cursor.next` may exist on final nonempty page. Read until short/empty page with fixed page limit, monotonic unique IDs, no repeated cursor/missing earlier rows, and final scope/log watermark recheck. Invalid cursor/saturated page without progress/malformed or moving snapshot -> `DISCOVERY_INCOMPLETE`; Host 401/403 -> `OPENCODE_HISTORY_UNAUTHORIZED`; unavailable durable log -> `DURABLE_EVIDENCE_UNAVAILABLE`; location/source mismatch -> `SOURCE_ROUTING_SCOPE_MISMATCH`. Each error preserves checkpoint/Graph memory. The public HTTP schema and installed SDK method bindings must be recorded separately; no invented method signatures.

**Future RED/GREEN:** add named discovery/auth/cursor assertions under `tests/integration/opencode/` and run `node --test tests/integration/opencode/test_reconciler.cjs tests/integration/opencode/test_recovery.cjs` plus the focused new test file. RED: missing/incorrect pagination, auth and source-scope checks are detected. GREEN: all complete-history/negative cases PASS; NOT RUN now.

**Files:** `.opencode/plugins/chronos/source-scope.js`, `state-store.js`, `lock.js` and focused discovery/lock tests under `tests/integration/opencode/`.  
**Interfaces:** Exhaustive root/message snapshot under one authenticated location descriptor. If cursor/scope changes, produce `DISCOVERY_INCOMPLETE` or `SOURCE_ROUTING_SCOPE_MISMATCH` rather than partial success.

- [ ] **RED:** more than one page, lost/nonadvancing cursor, duplicate message, root parentID, child, moved directory, shared global project ID and stale candidate binding.
- [ ] Implement stable location filters, exact cursor follow-through with verified end marker, ordered message pages and post-read scope revalidation. Do not port V1 N*=2 scan.
- [ ] Preserve source.json binding, atomic checkpoint, bounded diagnostics, inter-process lock crash recovery and no raw key/path persistence.
- [ ] **GREEN:** run focused Node integration tests with captured real V2 fixtures and document observable results.

### Task V2-D: Event-hint reconciler, terminal gate and recovery (former Task 14)

**F-001 root-only Graph gate:** The reconciler consumes `NativeSnapshotV225` (V2-C) and `RootEvidenceDecisionV225` (V2-B). It may call `turn.ingest` only when `evidenceStatus==="PROVEN"`, `outcome` is one of `SUCCESS/FAILED/ABORTED`, current source binding matches, full history/log scope has been rechecked and the contiguous prior prefix is acknowledged.

**Default CLI root evidence stop (observed, not implemented):** Empty event payload history alongside `log.synced(seq:0)` after an authenticated new Root's creation is **not proof** of delivery/terminal outcome. On the affected Host `evidenceStatus=NOT_PROVEN`, `outcome=null`, `reasonCode=DURABLE_EVIDENCE_UNAVAILABLE`; do not call Graph PREPARE/COMMIT/`turn.ingest` or advance Checkpoint. Projected User/Idle state, if present later, cannot silently replace required historical Delivery and Execution evidence.

**RED assertions:** for undelivered input, missing log after restart, unknown provenance/owner, multi-anchor execution ambiguity, incomplete cursor, stale Host/location, contradictory Idle/execution outcome, `NOT_PROVEN` or `CONTRADICTED` => **zero PREPARE/COMMIT, zero `turn.ingest`, checkpoint unchanged, no `caught_up`**. No earlier gap may be skipped; unrelated Roots can continue. For `PROVEN FAILED/ABORTED` transmit only confirmed User intent; for `PROVEN SUCCESS` include only attributable settled assistant/tool context. Test lost ACK -> receipt inventory -> `ALREADY_COMMITTED` without duplicate Graph mutation, same-anchor post-terminal divergence, unchanged V1 Receipt/Source Identity.

**Future RED/GREEN command:** `node --test tests/integration/opencode/test_reconciler.cjs tests/integration/opencode/test_recovery.cjs tests/integration/opencode/test_divergence.cjs`. RED: unsafe non-Proven commits fail asserted invariants; GREEN: all safe outcomes and recovery cases PASS. **NOT RUN** in the document remediation.

**Files:** `.opencode/plugins/chronos/reconciler.js`, `runtime.js`; `test_reconciler.cjs`, `test_recovery.cjs`, `test_divergence.cjs`.

- [ ] **RED:** lost/duplicated execution hints, unload, abort, unknown terminal evidence, inbox pending, multi-anchor delivery, incomplete cursor, quiescence changes, lost ACK and corrupt checkpoint.
- [ ] Subscribe with abort signal; treat typed events as hints only; activation and finite periodic 60-second full sweeps are correctness fallback.
- [ ] Require complete persisted all-page snapshot and verified terminal ownership before Graph `turn.ingest`. Failed/aborted store only confirmed user intent; post-terminal same anchor is divergence.
- [ ] Advance only contiguous acknowledged receipt prefix; prevent old holes from being skipped; post-drain recheck before `caught_up`. Bounded backoff and source-aware receipt readback for lost ACK.
- [ ] **GREEN:** `node --test tests/integration/opencode/test_reconciler.cjs tests/integration/opencode/test_recovery.cjs tests/integration/opencode/test_divergence.cjs`.

### Task V2-E: V2 loader/package and secure setup (former Tasks 15–16)

**F-002/F-003 explicit setup contract:** The existing `scripts/agent_assets/hooks.py` `updated_plugin_config` currently appends managed Chronos to the V1 `plugin` list in all-mode. Tagged V2 normalizer concatenates legacy `plugin` + native `plugins` into one effective list; it does **not** prove uniqueness. Migrate only **provably installer-owned** Chronos entry to native `plugins`. Preserve unrelated entries, their options/order, current JSONC collision preflight, stale-file/atomic-write protections, and untouched selective/Claude Code/Codex paths.

| Initial/effective config | Required behavior |
|---|---|
| Only old `plugin` | Remove only owned Chronos entry, add one native `plugins` record; retain unrelated legacy plugins |
| Only native `plugins` | Reuse managed single entry unchanged or add once; repeat setup idempotent |
| Both present | Normalize effective array; remove duplicate **only** when exact managed ownership/identity is proven, else `CHRONOS_PLUGIN_CONFIG_COLLISION` before write |
| Local auto-loaded + npm or global + project duplicate | Select one load source; refuse `DUPLICATE_CHRONOS_ACTIVATION` before event subscription, timers, locks or Graph effects; do not delete unowned files |
| selective/other Agents | Zero all-mode plugin mutation; preserve unrelated Agents, normal MCP credentials and existing Claude Code/Codex hooks |

**Step 1 — RED tests, not executable yet:** In `tests/unit/test_sync_agent_assets.py`, `tests/integration/test_sync_agent_assets.py` and `tests/unit/test_chronos_gate_migration_guards.py` test all five rows, unmanaged options, JSONC collision, preflight file changes, repeated idempotence and exact root package `files` coverage. In `tests/integration/test_opencode_turn_end_plugin.cjs` assert `Plugin.define({id,setup})`, stable ID/cleanup, only one activation before side effects, child no-op and `memory_save==0`, `session_flush==0`, detached hook==0.

**Step 2 — Run RED after Owner implementation authorization (not now):**
```bash
cd "$GRAPH_ROOT"
node --test tests/integration/test_opencode_turn_end_plugin.cjs
uv run pytest tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py tests/unit/test_chronos_gate_migration_guards.py -v
```
**Expected RED:** New assertions specifically fail for missing native config migration, managed collision fencing or duplicate activation; a missing runtime/dependency or unrelated test failure is not a valid RED signal.

**Step 3 — Implement limited GREEN after separate Owner GO:** modify only the proposed `Plugin.define` loader/shared runtime, `hooks.py` config ownership and direct package tests. Local `plugins[].package` must name a **directory**, not a single JS file. Use V2-C's already-running authenticated public Host client; no nested server or private credential access. No new optional TUI/experimental functionality.

**Step 4 — Run GREEN after implementation approval (not now):**
```bash
cd "$GRAPH_ROOT"
node --test tests/integration/test_opencode_turn_end_plugin.cjs
uv run pytest tests/unit/test_sync_agent_assets.py tests/integration/test_sync_agent_assets.py tests/unit/test_chronos_gate_migration_guards.py -v
npm pack --dry-run --json
```
**Expected GREEN:** focused Node/pytest PASS with zero failures; packed tarball inventory contains loader + runtime assets. `npm pack --dry-run` is **not** proof of actual installed Host loading; V2-F separately tests both local and npm installs and their mutual exclusion.

**Future implementation Commit boundary (NOT authorized by this document-only commit):** only V2 loader/runtime, `package.json`/`hooks.py`/bootstrap setup and directly associated tests. No Graph/Gate durability schema/keyring, previously approved V1 Design/Plan, unrelated Agent configs, CI, deploy or release edits. STOP for Owner after bounded implementation; no automatic new review/task.

**Files:** `.opencode/plugins/chronos-turn-end.js`, `.opencode/plugins/chronos/package.json`, root `package.json`, `scripts/agent_assets/hooks.py`, `scripts/bootstrap.sh` and existing packaging/config tests.

- [ ] **RED:** V1 export cannot substitute for `Plugin.define({id, setup})`, stable plugin storage ID, unload cleanup, session/event location scopes, reload/duplicate activation, no detached hook and child no-op.
- [ ] Implement V2 native adapter using `@opencode/plugin@2.2.5`; conditional `@opencode/client@2.2.5` only when needed. Keep the shared runtime accessible from both packaged tarball and repository-local loader.
- [ ] Use temporary V2 provider config for fixture: `package: "aisdk:@ai-sdk/openai-compatible"` plus `settings.baseURL`; local `plugins[].package` denotes a directory.
- [ ] **RED/GREEN security:** principal split and actual effective `plugin.use`/`mcp.use`/`integration.use` denies; required `external_directory` ask; no raw secrets or all-mode legacy `memory_save`, `session_flush`, detached hook.
- [ ] **GREEN:** real `npm pack` package contents and existing migration-guard, setup and integration tests.

### Task V2-F: Pinned native v2.2.5 acceptance (former Task 17)

**Files:** `tests/native/opencode/fixture_provider.py`, `harness.py`, `test_native_opencode_all.py`, `README.md`.

- [ ] **Stop before native V2-01–V2-14 on default CLI:** First establish a supported Host mode and demonstrate real `session.created` durable payload replay after restart, then Delivered/Terminal records. `log.synced` alone cannot satisfy acceptance. Initial default CLI readback is **FAIL (observed)**; E01–E06 and broader native tests are **NOT RUN**. No default-CLI PASS can be inferred from a dedicated Host's eventual PASS.
- [ ] For a separately Owner-approved event-persisting Host, record its actual startup profile, effective storage setting and authenticated public replay independently; do not change source, Host or deployment in this document task.

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

V2-A/B cover design ``3–7; V2-C/D cover ``2–5, 9; V2-E covers ``2, 3, 8; V2-F/G cover `10 and historical ``1–2, 5–14. The user-run isolated *initial Session readback* observed missing `session.created` with `log.synced(seq:0)`; **E01–E06, restart and implementation acceptance were NOT RUN**. Normal CLI Historical Evidence is currently insufficient under the `4.2 contract; Host mode and canonical turn_key await Owner decisions. The new feature branch is only a place to record the migration design and plan; it does not replace the previously approved V1 files.
