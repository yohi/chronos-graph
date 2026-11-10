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

## 3. Public client boundary, cursor discovery and source scope (F-002)

**Chosen proposed adapter boundary:** `ctx.event.subscribe({ signal })` supplies location-scoped live wake-up hints; it is not a durable history reader. A single dedicated **`@opencode/client@2.2.5`** adapter shall fetch historical public records from an **already-running and operator-configured** OpenCode v2.2.5 Host. `ctx.session` is an in-process Plugin API with different lifecycle/scope, not an interchangeable external client nor a promise of exhaustive persisted records. Release-pinned SDK method spelling and runtime availability remain `NOT_PROVEN` until V2-A. If required historical operations are absent, fail closed as `PUBLIC_API_UNAVAILABLE` and escalate any new transport/storage architecture for Owner approval.

| Pinned v2.2.5 public operation | Inputs/initial query | Return and cursor contract |
|---|---|---|
| `Session.list` | `order:"asc"`, root `parentID:null`, `directory` **or** `project/subpath`, `limit`, then opaque `cursor` | `{data: Session.Info[],cursor:{previous?,next?}}`; cursor retains original filters, so do not override them while paging |
| `Session.get` | `sessionID` | `{data: Session.Info}`; verify current parentID, location, project and source scope |
| `Message.list` | `sessionID`; first page `order:"asc",limit`; next pages `cursor,limit` only | `{data: Session.Message.Info[],cursor:{previous?,next?}}`; Message handler rejects `cursor` together with `order` |
| `Pending.list` | `sessionID` | `{data: SessionInbox.Info[]}`, pending admission only and **not** proof of delivery |
| `Session.log` (experimental public durable stream) | `sessionID`, exclusive numeric `after?`, optional `follow?` | Durable Session Events plus `log.synced` replay watermark; completeness after restart is **NOT_PROVEN** until tested |

Source contracts: [Session handlers](https://github.com/anomalyco/opencode/blob/v2.2.5/packages/server/src/handlers/session.ts), [Message handler](https://github.com/anomalyco/opencode/blob/v2.2.5/packages/server/src/handlers/message.ts), [Session filters/cursor](https://github.com/anomalyco/opencode/blob/v2.2.5/packages/schema/src/session.ts), [Core session interface](https://github.com/anomalyco/opencode/blob/v2.2.5/packages/core/src/session.ts). These are **tagged source assertions**, not results of installed-host tests.

**Page termination is not simply `cursor.next==null`**: the pinned implementation may return `next` on the final nonempty page. Read with positive finite `limit` until an empty/short page, validating no duplicate IDs, order regression, cursor repetition, truncation or unexpected scope change. An absent/nonadvancing cursor on a saturated page, malformed page, missing earlier record, invalid cursor or a moving snapshot is `DISCOVERY_INCOMPLETE`, not `caught_up`. Repeat the stable-scope and log-watermark check after drain. All message types, including User, Assistant, Compaction and Idle, are required; do not filter to only User messages.

**Host/auth ownership:** Operator-owned setup provides and pins the exact base URL, supported Host authentication and expected instance/location; the adapter sends credentials only to that Host, verifies session-to-location and canonical source binding, and redacts secrets from logs. A 401/403 is `OPENCODE_HISTORY_UNAUTHORIZED`; unreachable/unsupported durable log is `DURABLE_EVIDENCE_UNAVAILABLE`; location/project mismatch is `SOURCE_ROUTING_SCOPE_MISMATCH`. No auto-discovery to a different Host, insecure no-auth fallback, private API, direct Credential File read, or Nested Server at Plugin initialization. If the public Client cannot support required transport/auth, stop at Owner architecture checkpoint.

`parentID` identifies a root; children never own receipts/checkpoints. `DiscoveryScopeV225` is the same authority for exact Session.list filters and canonical source-alias derivation, including directory context where project IDs are shared. `Session.get`, full cursor pages, and source binding are rechecked before advancing any root. Existing V1 Receipt and Source Identity are preserved.

## 4. Durable Evidence Contract — inbox, ownership and proof status (F-001)

The **pinned source** defines `session.inbox.enqueued/delivered/cancelled/delivery.changed`, `session.execution.started/succeeded/failed/interrupted` and `session.step.*` as **durable bus events**. `session.text.delta` and `session.reasoning.delta` are **ephemeral**. Persisted `Session.Message` includes `type:"user"`, `type:"assistant"` and `type:"idle"` with `outcome`. Pending inbox state is persisted but **admission is not delivery**. The tagged `Session.log` promises replay after an exclusive `after` cursor followed by `log.synced`; its sequence may exceed the last emitted event because aggregate sequence space is shared. Do not require adjacent event sequence numbers.

**Durable in source ≠ proven retrievable:** Retention, restart recovery, complete replay through `log.synced`, message/log consistency, and the user-anchor-to-execution mapping require real 2.2.5 Host evidence. A transient Plugin event is never durable proof by itself. If the historical public API omits necessary records, do not read private OpenCode storage to compensate.

### 4.1 Shared proposed Chronos DTOs (not official OpenCode SDK types)

```ts
type EvidenceStatus = "PROVEN" | "NOT_PROVEN" | "CONTRADICTED"
type TerminalOutcomeV225 = "SUCCESS" | "FAILED" | "ABORTED"
type RootEvidenceDecisionV225 = {
  rootSessionID: string
  anchorMessageID: string | null
  evidenceStatus: EvidenceStatus
  outcome: TerminalOutcomeV225 | null
  reasonCode: string | null
}
type NativeSnapshotV225 = {
  rootSessionID: string
  session: SessionInfoV225
  messages: readonly SessionMessageV225[]
  pending: readonly PendingInfoV225[]
  durableEvents: readonly DurableSessionEventV225[]
  replaySyncedWatermark: number | null
}
```

`SessionInfoV225` / `SessionMessageV225` / `PendingInfoV225` / `DurableSessionEventV225` are adapter mappings of tagged public records; their exact SDK representations are V2-A evidence deliverables. `outcome` is `null` unless `evidenceStatus==="PROVEN"`. `NOT_PROVEN` means insufficient/untested evidence, `CONTRADICTED` means observed conflict; neither is an observed FAILED/ABORTED terminal turn.

### 4.2 Required per-anchor proof

| Claim | Required **persisted** evidence | Unproven disposition |
|---|---|---|
| Delivered Anchor | Durable `session.inbox.delivered` linked by same `inboxID / Message ID` to visible persisted `type:"user"` under the same Root/Source; distinguish enqueued/cancelled; prove `USER_AUTHORED` or `USER_DERIVED` | `NOT_PROVEN / DELIVERY_NOT_PROVEN` |
| Execution Owner | Complete ordered delivered/step/execution events and User/Assistant/Idle history; unique attribution of confirmed assistant/tools to the specific delivered anchor | `NOT_PROVEN / TURN_OWNERSHIP_AMBIGUOUS` |
| SUCCESS | Durable `execution.succeeded` plus settled `idle.outcome:"succeeded"` and complete/attributable final Assistant/tool lineage | `NOT_PROVEN / TERMINAL_EVIDENCE_UNAVAILABLE` |
| FAILED | Durable `execution.failed` with error plus corresponding `idle.outcome:"failed"`, attributable anchor; retain only user intent | `NOT_PROVEN / TERMINAL_EVIDENCE_UNAVAILABLE` |
| ABORTED | Durable `execution.interrupted` with `reason:"user"` plus corresponding `idle.outcome:"interrupted"`; no ambiguous resume/replacement; retain only user intent | `NOT_PROVEN / TERMINAL_EVIDENCE_UNAVAILABLE` |

The tagged `Idle` message and terminal execution event cover a **busy period**, which can include *multiple* steered prompts; they do **not** individually certify terminality for each Anchor. If multi-anchor `queue/steer`, continuation, child work or compaction prevents deterministic partition, mark **`NOT_PROVEN`** and request Owner architecture decision if proof cannot be recovered via public records. Never turn one execution SUCCESS into several invented successful receipts. Conflicting durable event IDs, missing expected User Message, log/snapshot mismatch or incompatible terminal outcomes are `CONTRADICTED / EVIDENCE_CONTRADICTED`.

### 4.3 Provenance, root-only fail-closed and checkpoint

Classify `USER_AUTHORED` / `USER_DERIVED` / `INTERNAL_CONTROL` / `UNRESOLVED_PROVENANCE` from public persisted evidence. Text similarity or `type:"user"` alone is insufficient. File-only and structured input can qualify when ownership and persisted resource identity are established. Enqueue/pending/cancelled input without delivered User Message produces **no receipt**; `resume:false` is not proof of delivery.

For **any** `NOT_PROVEN` or `CONTRADICTED`: emit `RootEvidenceDecisionV225` with `outcome:null`, **do not invoke Graph PREPARE/COMMIT / `turn.ingest`**, do not advance or overwrite this Root's checkpoint, do not report `caught_up`; retain existing V1/V2 receipt and source binding and redact diagnostics. Do not skip the blocked contiguous prefix. Unrelated Roots may proceed. If this cannot be implemented through the public evidence contract, **STOP at Human Owner checkpoint** rather than silently change architecture.

## 5. Proven terminal outcome and immutable history

Only `PROVEN` per-anchor evidence as specified in `4.2 authorizes `SUCCESS`, `FAILED` or `ABORTED`. `session.execution.interrupted` has reasons including `user`, `shutdown`, `superseded` and `inactivity`; only a complete, non-resumed user interruption with matching persisted idle outcome can prove ABORTED. `shutdown` may preserve an in-flight claim. A quiescent snapshot, a single `idle` record, or an isolated execution success event is never proof for each member of a multi-anchor busy period.

`INCOMPLETE` denotes a nonterminal state; lack of data is `NOT_PROVEN`, not a failed execution. `TERMINAL_EVIDENCE_UNAVAILABLE` or `EVIDENCE_CONTRADICTED` blocks the Root with zero Graph mutation and unchanged checkpoint. Actual execution failure is distinct from evidence failure.

`PROVEN SUCCESS` persists canonical user intention and **attributable confirmed** assistant content plus bounded/sanitized tool context; `PROVEN FAILED` / `PROVEN ABORTED` persist **user intention only**. Graph transactional COMMIT alone establishes an immutable receipt. Later generation under the same already-committed anchor yields `POST_TERMINAL_CONTINUATION` / `COMMITTED_TURN_SEMANTICS_CHANGED` divergence, never overwrite, duplicate receipt or retroactive deletion. New durable progress requires a distinct eligible delivered anchor. Mutated or deleted OpenCode history is reported through `receipt.validate`/divergence, preserving existing V1 receipts and canonical source identity.

## 6. Receipt key, schema, source identity and hash fence

**Owner decision required — recommended canonical key:** `opencode:v2:<rootSessionID>:<deliveredEligibleUserMessageID>` within the separately verified canonical source scope. The prior spec `1.5 uses anchor-based identity but the prior plan Task 12 also inserts a scope and lineage hash into the key. They conflict; do not implement either ambiguously. If the recommendation is accepted, unify the two original documents and fixtures before code implementation. Keep mutable lineage evidence in the versioned payload/divergence calculation, not in an identity key that should be stable across local checkpoint recovery.

Define V2-specific `canonical_schema_version` and `evidence_contract_version`. Retain historical V1 receipts and their original versions; never rewrite/re-hash V1 data under a V2 schema or infer cross-version equality without a receipt-pinned, authorized comparison/rebase.

Preserve the observed V2 heterogeneous input sequence and persisted resource identity. A filename/MIME alone is insufficient, and mutable source files/network resources may not be reread during reconciliation. Insufficient persisted identity returns `UNRESOLVED_USER_INPUT_IDENTITY`. Server canonicalization and privacy-preserving identity tokens remain authoritative; tool context stays allowlisted, bounded, deterministic and sanitized. COMMIT performs no embedding/provider/network calls.

## 7. Compaction, provider-native replay and optional features

The V2 events `session.compaction.started` / `.ended` replace removed `session.compacted`. Summary retained-message references use `metadata.keepID`; provider compaction replacement windows use `native.messages`. Decode legacy `metadata.recent` only when inspecting historical records. Native replay state is `native`, not old `providerState` / `providerResultState` / `resultState`; tool execution `state` remains a separate field. Preserve native tool call/result merging and identity.

Do **not** re-label the V1 overflow replay algorithm as V2. Classify new V2 compaction controls only from fixed-tag, persisted evidence; otherwise fail closed as `COMPACTION_LINEAGE_UNRESOLVED`. Numeric compaction buffers are supported; optional `compaction.buffer:"20%"` describes free **model-context headroom**, not chat-history retention.

Experimental idle/Goal Mode, background compaction, artifacts, schedules, TUI/GUI, images, persistent PTY, client-hosted MCP and LSP replacement are **not automatically in scope**. Inventory as used/not used/disabled/out of scope and test only relevant behaviors; do not invent an extra migration gate. Do not allow automatic agent-loop or review/fix/review recurrence without explicit Owner approval.

## 8. V1→V2 plugin configuration, packaging and security (F-003)

### 8.1 Current ownership and V2 normalization

Current `scripts/agent_assets/hooks.py` only plans an OpenCode config in **all** mode. Its `updated_plugin_config` adds `@yohi/opencode-plugin-chronos-turn-end` to legacy `plugin[]` under `~/.config/opencode/opencode.json`. It rejects `opencode.jsonc` and `oh-my-opencode.jsonc` preflight collisions. V2 native format is `plugins[]` (string or `{package,options?}`); the pinned `ConfigNormalize` composes effective `plugins` as `[...legacyPlugins,...nativePlugins]`. A legacy+native Chronos entry is therefore **not assumed deduplicated**. Project/global/local auto-loaded plugins must also be counted.

### 8.2 Explicit installer-owned migration matrix

| Effective preflight state | Proposed all-mode change |
|---|---|
| Legacy `plugin` only | Migrate **only the exact installer-owned Chronos record** to native `plugins`. Leave unrelated legacy entries and ordering intact; ownership uncertain -> `CHRONOS_PLUGIN_CONFIG_COLLISION` |
| Native `plugins` only | Reuse one valid managed Chronos registration (idempotent `UNCHANGED`), or add exactly one managed entry |
| Both arrays | Normalize first. If duplicate Chronos is provably installer-owned and identical, remove only owned duplicate; any user-owned or semantically different Chronos entry -> fail before write |
| Local auto-discovery + npm, or project + global Chronos | Select exactly one explicit runtime/load source. Do not delete unowned local/project files; ambiguous effective config -> preflight fail |
| selective/other Agents | No V2 all-mode registration, no migration of their config, preserved Claude Code/Codex hook paths and unrelated agent/provider/MCP settings |

Setup owns **effective registry inventory**, provenance of managed entries, preflight collision detection, atomic write/rollback against stale snapshots and idempotent repeated setup. It must not rewrite unowned JSONC, provider, agent or plugin settings. When only a documented owned migration is possible, preserve unrelated config values and ordering. A required legacy outside-project `ask` permission must be tested because V2 defaults `external_directory` to allow.

### 8.3 Two-load and lifecycle fence

Native `Plugin.define({ id, setup })` uses a stable ID. Packaged `@yohi/opencode-plugin-chronos-turn-end` and local `.opencode/plugins/` entrypoint share one runtime, **not** concurrent activation. A local `plugins[].package` points to a **directory**, not one JS file. Validate package `main`/`files`, real npm tarball, local loader and reload. Detect duplicate effective Host/location/Chronos activation **before** event subscription, timers, lock acquisition or Graph calls; emit `DUPLICATE_CHRONOS_ACTIVATION` and make no side effects. Server Graph receipts still enforce cross-process exactly-once.

V2 `policies` (`plugin.use` / `mcp.use` / `skill.use` / `integration.use`) are separate from interactive `permissions`. Bare `integration.use:"*"` does not cover dedicated plugin/MCP/skill denies. Preserve the Gate ingestion, operator and normal MCP credential separation. No Credential File reads, private OpenCode API, or Plugin-init Nested Server.

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

## 11. Owner decisions, document status and stop

| Undecided authority | Recommended **proposal**, not approval | Alternative |
|---|---|---|
| V2-only support | New V2 native adapter; leave V1 receipts and accepted history intact | Dual V1+V2 with independent adapters and host tests |
| Canonical V2 `turn_key` | Stable root User Message ID within separately verified Source Scope; resolve historical Spec `1.5 vs Plan Task 12 mismatch before implementation | Lineage-inclusive key only after proving stable identity under resume/compaction |
| Historical durable evidence | Complete replayable public `Session.log` plus Message/Pending/Session snapshot with verified multi-anchor ownership | If unavailable, keep affected Roots fail-closed and request approved architecture change, not a private-store shim |

**Evidence still NOT PROVEN:** installed host replay after restart, coverage/retention, SDK method mapping, multi-anchor attribution, exact outcome proof and full negative regression. Source/type inspection is not a host PASS.

**IMPLEMENTATION_HOLD / STOP:** These corrections document F-001–F-003 only. Human Owner must separately approve outstanding choices, source/host verification and implementation. No source code, tests, deploy, merge, new PR, automatic review loop or follow-on task is authorized by this document-only commit. Historical PR #385 Design/Plan remain unchanged.

