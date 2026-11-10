# ChronosGraph — OpenCode v2.2.5 Durable All-Mode Ingestion Migration Design

**Status:** DRAFT / Owner decision pending; **not** implementation approval.  
**Scope:** documentation-only adaptation of PR [#385](https://github.com/yohi/chronos-graph/pull/385) at `54a21d2838e5c29eda12ae294c965a84b040d04d`.  
**Historical specification:** [V1 design](2026-10-05-opencode-all-durable-ingestion-design.md) and [V1 plan](../plans/2026-10-06-opencode-all-durable-ingestion.md). Neither historical document is replaced by this proposal.  
**Migration reference:** [MIGRATION.md fixed revision](https://gist.githubusercontent.com/yohi/0c3d8edea98d86e7f5c8d6c2d9f93d2d/raw/ea6921cea31f6053492cae29c3b2e6f9bc2c8b27/MIGRATION.md), R3.3, 2026-11-10 JST.  
**Tagged upstream:** [anomalyco/opencode v2.2.5](https://github.com/anomalyco/opencode/tree/v2.2.5) / `9bbb8ce18c80f099e0e448775f59d965ead40a21`. Source review is not installed-host validation.

## 1. Goal, support scope, and invariant boundary

Implement v2.2.5-native `CHRONOS_INGESTION_MODE=all` so each eligible delivered user-intent anchor in a root session converges to **one and only one** durable ChronosGraph receipt. Correctness must not depend on uninterrupted plugin life, exactly-once event delivery, non-mutating OpenCode history, stable project IDs, successful first ACK, or trusted local checkpoints.

The proposed version policy is **CLI 2.2.5 / @opencode/plugin 2.2.5** and **@opencode/client 2.2.5 only if required**. The future `>=2.2.5` support floor is a policy proposal, not evidence of later-version compatibility. Recommend **V2-only** to avoid implementing an unrequested V1 adapter; explicit V1+V2 requirements would need a separate compatibility matrix and Owner decision.

Preserve the previously approved durability architecture: server-authoritative canonicalization; immutable receipts; PREPARE followed by transactionally fenced COMMIT; generation-CAS keyring manifest and independently managed keys; source-scope binding/alias continuity; stable alias identity through PREPARE→COMMIT; optimistic dedupe checks; Graph-controlled graph intent/outbox; SQLite and non-skippable PostgreSQL/Supabase persistence acceptance; lost-ACK recovery; crash-recoverable per-root locking; ordered contiguous checkpoint advancement; versioned divergence evidence.

Preserve normal MCP / ingestion / operator principal separation and all fail-closed security boundaries. Preserve selective-mode behavior, Claude Code/Codex behavior, and the `memory_save==0`, `session_flush==0`, detached-V1-hook==0 requirements for OpenCode all-mode.

**Do not import as V2 facts** the historical V1 `session.status` idle map, limit-doubling `Session.list()` discovery, part-ID ordering, V1 synthetic-control constructors, `metadata.compaction_continue`, overflow replay transform, `finish/time.completed` terminality, or `opencode-ai@1.18.34` acceptance fixtures.

## 2. Plugin contract and lifecycle

V2 uses `import { Plugin } from "@opencode/plugin"` and a stable-ID `Plugin.define({ id, async setup(ctx) { ...; return cleanup; } })` server entrypoint. The plugin ID is a persistent storage namespace decision, not a disposable identifier. Preserve a loader-only adapter and a shared pure reconciliation runtime so project-local and installed npm package paths behave identically.

`ctx.location` describes the loaded plugin location, **not** a universal session/event location. Use the authenticated actual session location for discovery and authorization; bind source scope and alias to that same effective routing domain.

`ctx.event.subscribe({ signal })` provides typed live hints, not a durable journal. The event-specific payload may differ by `event.type` and must not be decoded with a universal envelope. On unload/location idle timeout: cancel subscription, periodic sweep, retries and pending operations; release locks without leaking credentials. After crash/restart, recover from persisted public state and server receipts, not from a remembered event.

Potential `session.execution.started` / `.succeeded` / `.failed` / `.interrupted`, `session.status` and `session.idle` events may wake reconciliation but cannot themselves declare an exactly-once successful logical turn. `ctx.session.wait({sessionID})` can synchronize a known session where supported, not reconstruct historical outcomes.

## 3. Authoritative discovery, source scope and root identity

Read the complete public V2 session list with **cursor pagination** and stable query filters/order. Read every message page for each candidate root, with verified ascending ordering, scope, cursor progress and unique IDs. Do **not** carry over V1's N=100, N*=2 widening algorithm. Invalid, lost, repeated or truncated cursor pages must yield `DISCOVERY_INCOMPLETE` and prevent `caught_up`.

Use tagged V2 session `parentID` to recognize a root; a child session never receives independent receipt/checkpoint/pending ownership. Context from a child may be projected only within its verified owning root. Re-query at the end of the drain to reject a mid-read scope move or new eligible history. The versioned discovery descriptor must be identical to the descriptor used by canonical source-alias derivation. Project IDs/global IDs or path similarity alone do not identify lifetime source continuity; mismatch is `SOURCE_ROUTING_SCOPE_MISMATCH`.

If public plugin-domain reads are insufficient, use a scoped, authenticated `@opencode/client@2.2.5` API, with explicit transport, authorization and restart behavior. External Node service discovery/start APIs are **not** permission to spawn nested servers in plugin initialization. Private OpenCode internals and credential-file reads are forbidden.

## 4. Inbox, provenance and logical owner

Inbox enqueue/admission is **not** a user-message receipt. A canonical anchor requires a persisted **delivered** input whose provenance is authenticated from pinned public records. Account for `queue`, `steer`, `resume:false`, cancellation, retry of one message ID, and pending-but-undelivered messages. Such admissions cannot create a phantom anchor or double receipt.

Classify each relevant message as `USER_AUTHORED`, `USER_DERIVED`, `INTERNAL_CONTROL` or `UNRESOLVED_PROVENANCE`. `role=user` alone and text similarity are insufficient. File-only and structured prompts remain eligible when genuinely user-authored or user-derived and when their persisted identity can be verified; generated shell/subagent/compaction/continuation frames are not independent new user intent.

An execution may contain **multiple delivered anchors**. Define version-specific, deterministic ownership from delivered anchor to execution, assistant, tool and descendant sessions. When multiple anchors, steer, resume, child work or compaction make attribution ambiguous, return `TURN_OWNERSHIP_AMBIGUOUS` and stop only that root's ingestion without advancing its checkpoint. Never assume one execution equals one user turn.

## 5. Terminal outcome and immutable history

Only a **complete, quiescent, persisted lineage snapshot** may establish a terminal turn. Derive `SUCCESS`, `FAILED` and `ABORTED` from pinned persisted evidence, not from a single transient lifecycle event. In particular, `execution.interrupted` does not unconditionally mean user abort. Indeterminate state is `INCOMPLETE` / `TERMINAL_EVIDENCE_UNAVAILABLE` with no canonical hash, receipt or checkpoint advance.

`SUCCESS` persists user intent plus confirmed final assistant output and sanitized bounded execution context. `FAILED` and `ABORTED` persist **user intent only**. An acknowledged failed/aborted turn closes that anchor permanently. Subsequent generation under the same anchor is `POST_TERMINAL_CONTINUATION` / `COMMITTED_TURN_SEMANTICS_CHANGED` divergence, not receipt overwrite or second success. A distinct newly delivered eligible user anchor is required for another normal receipt.

Current-history deletion, revert, compaction or semantic alteration is reported by `receipt.validate` and divergence states, **not** by deleting previously committed Chronos memory.

## 6. Receipt key, schema, source identity and hash fence

**Owner decision required — recommended canonical key:** `opencode:v2:<rootSessionID>:<deliveredEligibleUserMessageID>` within the separately verified canonical source scope. The prior spec `1.5 uses anchor-based identity but the prior plan Task 12 also inserts a scope and lineage hash into the key. They conflict; do not implement either ambiguously. If the recommendation is accepted, unify the two original documents and fixtures before code implementation. Keep mutable lineage evidence in the versioned payload/divergence calculation, not in an identity key that should be stable across local checkpoint recovery.

Define V2-specific `canonical_schema_version` and `evidence_contract_version`. Retain historical V1 receipts and their original versions; never rewrite/re-hash V1 data under a V2 schema or infer cross-version equality without a receipt-pinned, authorized comparison/rebase.

Preserve the observed V2 heterogeneous input sequence and persisted resource identity. A filename/MIME alone is insufficient, and mutable source files/network resources may not be reread during reconciliation. Insufficient persisted identity returns `UNRESOLVED_USER_INPUT_IDENTITY`. Server canonicalization and privacy-preserving identity tokens remain authoritative; tool context stays allowlisted, bounded, deterministic and sanitized. COMMIT performs no embedding/provider/network calls.

## 7. Compaction, provider-native replay and optional features

The V2 events `session.compaction.started` / `.ended` replace removed `session.compacted`. Summary retained-message references use `metadata.keepID`; provider compaction replacement windows use `native.messages`. Decode legacy `metadata.recent` only when inspecting historical records. Native replay state is `native`, not old `providerState` / `providerResultState` / `resultState`; tool execution `state` remains a separate field. Preserve native tool call/result merging and identity.

Do **not** re-label the V1 overflow replay algorithm as V2. Classify new V2 compaction controls only from fixed-tag, persisted evidence; otherwise fail closed as `COMPACTION_LINEAGE_UNRESOLVED`. Numeric compaction buffers are supported; optional `compaction.buffer:"20%"` describes free **model-context headroom**, not chat-history retention.

Experimental idle/Goal Mode, background compaction, artifacts, schedules, TUI/GUI, images, persistent PTY, client-hosted MCP and LSP replacement are **not automatically in scope**. Inventory as used/not used/disabled/out of scope and test only relevant behaviors; do not invent an extra migration gate. Do not allow automatic agent-loop or review/fix/review recurrence without explicit Owner approval.

## 8. Policies, packaging, credentials

Use V2's native `.opencode/plugins/` and npm package entries, both invoking the same runtime. A local `plugins[].package` path is a **directory**, not a source file. Test the installed `npm pack` tarball, not only direct module imports. Do not introduce Effect/TUI peer packages absent a used feature.

Native `policies` (`plugin.use`, `mcp.use`, `skill.use`, `integration.use`) are not the interactive tool `permissions` (`allow/ask/deny`). In v2.2.3+ a bare/wildcard `integration.use` policy does **not** automatically cover MCP/skill/plugin actions: verify effective deny **before protected effects**. V2 defaults `external_directory` to allow; if V1 required outside-project approval, explicitly configure and test ordered `ask`. Protect Graph/Gate credentials, and preserve distinct regular-MCP, ingestion and operator capabilities.

## 9. Reconciler and durable state

Retain activation sweep, 60-second finite correctness sweep, trigger coalescing, bounded backoff, per-root crash-recoverable lock, source binding check, receipt inventory/rebase, and ordered contiguous prefix. The reconciler may mark a root `caught_up` **only** after verifying all pages, no older eligible gaps, no pending undelivered ambiguity, and a post-drain state/scope refresh.

Only `COMMITTED` or version/scope-correct `ALREADY_COMMITTED` authorizes checkpoint advancement. Retryable failure, unknown provenance, authorization/keyring error, incomplete pagination, conflict, or ambiguous execution owner leaves it unchanged and emits a typed reason. The Graph transaction is the exactly-once authority.

## 10. Native acceptance and evidence

Install real OpenCode CLI **2.2.5** and `@opencode/plugin@2.2.5`, plus `@opencode/client@2.2.5` if the implementation imports it. Use deterministic local AI SDK compatible provider with V2 config (`package: "aisdk:@ai-sdk/openai-compatible"`, `settings.baseURL`). Test both clean temporary npm-installed and repository-local plugin loading. Capture versions, hashes, observed records, tests and cleanup logs; source review or synthetic events alone never count as host PASS.

| Case | Executable requirement |
|---|---|
| V2-01 | setup/unload/reload, stable plugin ID, package parity, no V1 detached hook |
| V2-02 | complete cursor root discovery, parentID child exclusion, location and move isolation |
| V2-03 | complete ordered message cursor reads; duplicate/missing/cursor failure blocks |
| V2-04 | enqueued-but-not-delivered, queue/steer/cancel/retry: zero phantom receipt |
| V2-05 | real SUCCESS/provider FAILED/user ABORTED, no partial assistant output |
| V2-06 | multi-anchor execution, steer/resume attribution or explicit blocked state |
| V2-07 | child event storms create no child receipts/checkpoints |
| V2-08 | keepID/native compaction, replay controls and semantic divergence |
| V2-09 | events lost, process restarted/unloaded, ACK lost, state corruption, gap repair |
| V2-10 | source alias/project move and candidate-binding scope mismatch |
| V2-11 | policy deny, external_directory ask, credential isolation, redaction, zero legacy all side channel |
| V2-12 | SQLite/PostgreSQL/Supabase atomic receipts and graph intents, locked Gate/Graph environment |
| V2-13 | same-anchor terminal immutability and later new-anchor progress |
| V2-14 | documented N/A for genuinely unused optional features |

Use `PASS`, `FAIL`, `BLOCKED`, `NOT RUN` and evidence-backed `N/A` distinctly. Safety-critical unverified public API/authorization gates fail closed for affected operations; unrelated documentation is not held hostage to an endless review loop.

## 11. Owner checkpoint and stopping condition

Pending decisions: (1) V2-only versus explicitly verified dual V1/V2; (2) one canonical V2 receipt-key formula and resolution of original design/plan mismatch; (3) whether a public V2 historical terminal/provenance read proves sufficient for safe implementation. These are not silently approved by this draft's Git commit.

**STOP:** Documentation-only draft recorded. No production implementation, test execution, new PR, merge, release, external deployment, or independent review is authorized by the commit itself.
