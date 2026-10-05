# OpenCode v1.18.34 `CHRONOS_INGESTION_MODE=all` Durable Ingestion Design

## Status

**APPROVED / FIXED design baseline**

- Design 1 — architecture / durability ownership: APPROVED / FIXED
- Design 2 — turn extraction / canonical payload: APPROVED / FIXED
- Design 3 — runtime reconciliation / recovery / source continuity: APPROVED / FIXED
- Design 4 — integration / observability / setup / acceptance: APPROVED / FIXED

This document is the normative design baseline for implementing reliable OpenCode v1.18.34 ingestion when `CHRONOS_INGESTION_MODE=all`.

Implementation must not silently weaken or reinterpret the contracts below. Any change to the fixed semantics requires a new design review.

## Goal

Make OpenCode v1.18.34 `all`-mode ingestion converge to exactly one durable ChronosGraph commit per eligible root-session logical turn despite event loss, duplicate delivery, retry, process restart, lost ACKs, checkpoint corruption, OpenCode history mutation, source alias changes, project-ID migration, and concurrent plugin activity.

The system must preserve:

- root-session ownership;
- durable exactly-once receipt semantics;
- contiguous checkpoint advancement;
- deterministic turn extraction;
- failed/aborted user intent without persisting unfinished assistant output;
- bounded, sanitized execution context;
- event-loss-safe reconciliation;
- explicit divergence observability without retroactively deleting durable memory;
- source-scope continuity across routing/project alias changes;
- existing selective-mode and non-OpenCode compatibility.

## Non-goals

This design does not:

- redesign Claude Code or Codex `all`-mode hooks into the same exactly-once reconciler;
- make Neo4j projection part of the synchronous durability ACK boundary;
- make model-visible `memory_save` or `session_flush` responsible for OpenCode `all` persistence;
- auto-delete already durable Chronos memory when OpenCode history is undone, reverted, edited, or deleted;
- infer source migration from path/title/content similarity;
- depend on external nondeterministic LLM providers in release acceptance.

## Pinned upstream baseline

The implementation and acceptance baseline is **OpenCode v1.18.34**.

Relevant verified upstream behavior includes:

- canonical `session.status` events with `status.type = idle`; deprecated `session.idle` still exists;
- idle sessions are absent from the v1.18.34 status map;
- sessions expose `parentID`; root sessions have no parent;
- message order is deterministic by `(time.created, id)`;
- `Session.list()` defaults to a limit of 100 and must not be treated as exhaustive without explicit widening;
- session list routing is constrained by project plus effective routing dimensions such as directory/workspace/path;
- non-Git directories may share `ProjectV2.ID.global`;
- OpenCode may migrate project IDs through `migrateProjectId(oldID, newID)`, including existing session/workspace rows;
- internal user-role messages exist for compaction, continuation, shell/subtask control, and replay;
- overflow compaction may replay a prior user message under a new message ID;
- `message.removed` and `message.part.removed` exist and can mutate current history after a turn was committed.

Upstream implementation details are version-specific inputs to this design. Support for a different OpenCode version requires explicit compatibility validation.

---

# 1. Durability architecture

## 1.1 Events are hints; reconciliation is authority

OpenCode events accelerate reconciliation but are not a correctness boundary.

```text
event delivered
  -> reconcile sooner

event lost
  -> activation / periodic exhaustive reconciliation still discovers work
```

No durable guarantee may depend on a particular idle/update/delete event being delivered.

## 1.2 OpenCode `all` owns a dedicated acknowledged path

The existing detached path:

```text
OpenCode event
  -> detached scripts/agent_turn_hook.py
  -> ChronosGate
  -> memory_save
```

is not the durability path for OpenCode `all` mode.

The new path is:

```text
OpenCode plugin
  -> OpenCodeIngestionRuntime
  -> authenticated ChronosGate internal ingestion surface
  -> ChronosGraph ingest_turn
  -> durable result
  -> local checkpoint advance
```

`memory_save`, `session_flush`, and detached `agent_turn_hook.py` execution are forbidden side channels for OpenCode `all` turns.

Retries may issue `ingest_turn` more than once. Exactly-once means one durable receipt outcome for one scoped logical turn, not one transport call.

## 1.3 PREPARE / COMMIT split

Turn ingestion has two phases.

### PREPARE

PREPARE is strictly side-effect-free.

It may:

- validate request and evidence schema;
- reconstruct the logical turn;
- classify terminal outcome;
- validate/canonicalize semantic content;
- derive privacy-preserving identity tokens;
- produce a dedupe/mutation proposal;
- derive a candidate canonical envelope and payload hash.

It must not:

- persist memory;
- archive/replace existing memories;
- write graph outbox rows;
- create/update receipts;
- advance checkpoints;
- invoke any side-effecting deduplicator.

### COMMIT

COMMIT is the authoritative durability boundary.

Within the primary storage transaction it performs:

1. authoritative receipt/idempotency revalidation;
2. commit-time dedupe revalidation;
3. all primary memory mutations for the logical turn;
4. durable graph intent/outbox writes when graph mode requires them;
5. ingestion receipt creation/update as applicable;
6. atomic transaction commit.

Neo4j projection is post-commit convergence. It is not required for `COMMITTED`.

## 1.4 Result taxonomy

`ingest_turn` returns a structured result:

```text
COMMITTED
ALREADY_COMMITTED
RETRYABLE_FAILED
TERMINAL_FAILED
IDEMPOTENCY_CONFLICT
IDEMPOTENCY_REBASE_UNAVAILABLE
```

Only `COMMITTED` and `ALREADY_COMMITTED` permit local checkpoint advancement.

`IDEMPOTENCY_CONFLICT` blocks that root and later eligible turns until operator resolution. It must never be used when the server merely lacks an old key/canonicalizer required to reproduce the comparison contract.

## 1.5 Receipt identity

The logical turn key remains:

```text
turn_key = opencode:v1:<rootSessionID>:<eligibleUserMessageID>
```

Receipt storage/idempotency is scoped by canonical source scope:

```text
UNIQUE(canonical_source_scope_id, turn_key)
```

This avoids relying on session/message IDs being globally unique across unrelated OpenCode source domains.

## 1.6 Receipt contract

A committed receipt records the immutable operational facts required for duplicate validation, recovery, and discovery, including at least:

```text
canonical_source_scope_id
turn_key
root_session_id
user_message_id
source_cursor(created_at, user_message_id)
payload_hash
canonical_schema_version
evidence_contract_version
identity_key_version
```

Receipt creation is atomic with the primary memory mutation and graph-intent durability.

---

# 2. Server-authoritative canonicalization

## 2.1 Caller does not own final identity

The OpenCode plugin does not provide authoritative inner fingerprints or an authoritative final `payload_hash`.

The request conceptually contains:

```text
ingest_turn {
  source routing/scope evidence,
  turn_key,
  evidence_contract_version,
  semantic_projection,
  identity_evidence
}
```

`identity_evidence` is transport-only sensitive input.

ChronosGraph is authoritative for:

- evidence validation;
- privacy-preserving identity-token derivation;
- canonical envelope construction;
- final `payload_hash` derivation.

## 2.2 Ephemeral identity evidence

Sensitive source material such as command values, file/resource locators, source selections, data-URL bytes, or persisted user-derived expansion content may cross the authenticated ingestion transport when required for validation.

It must never enter durable or diagnostic state:

```text
receipt      NO
memory       NO
source metadata NO
graph/outbox NO
checkpoint   NO
logs         NO
traces       NO
metric labels NO
```

Evidence remains available in volatile request execution memory until the final idempotency outcome is established, including any receipt-version rebase.

Silent truncation is forbidden. If required identity evidence cannot be represented losslessly within the supported contract, canonicalization fails explicitly rather than collapsing to lossy identity.

## 2.3 Privacy-preserving durable identity tokens

Low-entropy sensitive values are not persisted as plain SHA-256 digests.

ChronosGraph derives domain-separated keyed fingerprints, conceptually:

```text
HMAC-SHA256(identity_key, domain || 0x00 || JCS(identity_material))
```

Domains are versioned by semantic category, for example file/resource/command identity.

The identity keyring is stable across restart, versioned independently from API credentials, and retained as required for receipt-pinned duplicate comparison.

## 2.4 Receipt-pinned duplicate comparison

An existing receipt owns the comparison contract:

```text
canonical_schema_version
evidence_contract_version
identity_key_version
```

If the receipt already exists before PREPARE, canonicalization uses the receipt-pinned contract.

If PREPARE observed no receipt but COMMIT finds one:

```text
prepared contract == receipt contract
  -> compare prepared hash

prepared contract != receipt contract
  -> rollback
  -> discard prepared result
  -> recanonicalize side-effect-free using receipt-pinned contract
  -> compare
```

A unique-insert race lost during COMMIT follows the same rollback -> re-read receipt -> receipt-pinned rebase path.

Prepared hashes from different key/schema versions must never be compared directly to declare conflict.

Outcomes after rebase:

```text
rebased hash == receipt hash
  -> ALREADY_COMMITTED

rebased hash != receipt hash
  -> IDEMPOTENCY_CONFLICT

required old comparison contract unavailable
  -> IDEMPOTENCY_REBASE_UNAVAILABLE
```

---

# 3. Logical turn extraction

## 3.1 Root-session ownership

Only root sessions create durable logical turns.

A child/sub-agent session may exist, emit events, and contribute execution context to the owning root's eventual projection, but it never owns an independent receipt/checkpoint/pending state.

## 3.2 Eligible user input provenance

`role = user` is not sufficient to create a logical turn.

User-message provenance is classified as:

```text
USER_AUTHORED
USER_DERIVED
INTERNAL_CONTROL
```

`synthetic = true` is a transformation property, not an authorship decision.

Eligible logical-turn anchors are root-session user messages with provenance in:

```text
USER_AUTHORED
USER_DERIVED
```

Known OpenCode internal control constructors/patterns are `INTERNAL_CONTROL` and do not receive their own turn key.

All legitimate v1.18.34 user-facing PromptInput kinds participate in eligibility and canonical user intent, including:

- text;
- file/resource input;
- agent input;
- subtask input.

File-only, AgentPart-only, and SubtaskPart-only prompts are valid turns.

## 3.3 Ordered heterogeneous canonical user parts

Canonical user input preserves cross-kind part order as one ordered heterogeneous sequence.

For the pinned v1.18.34 representation, persisted parts are ordered by `part.id` ascending before heterogeneous canonical projection. Generated user-derived expansion fragments are then collapsed according to their recognized source-input grouping while preserving the group's position at its earliest persisted part.

Kind-separated arrays may exist only as derived views; they are not the hash authority.

Relative reordering of meaningful user inputs changes canonical identity.

OpenCode-generated expansion fragments representing one original user input are collapsed deterministically so helper text/body expansions are not double-counted.

## 3.4 Logical ownership and continuation

Logical ownership is distinct from provenance.

Internal messages can be continuation controls that inherit an existing logical-turn owner.

Recognized continuation/control forms include the v1.18.34 compaction and continuation transitions fixed by this design, including:

- compaction controls;
- `metadata.compaction_continue = true` continuation;
- supported subtask continuation pattern;
- exact overflow-compaction replay transition.

`NON-TURN` does not imply lineage boundary.

Assistant messages are classified conceptually as:

```text
TURN_ASSISTANT
CONTROL_ASSISTANT
```

Compaction summaries/control assistants may participate in lineage and terminal evidence where appropriate, but are not canonical final assistant content.

## 3.5 Overflow-compaction replay

An OpenCode-generated replay of a prior user prompt is continuation control, not new user intent.

Replay recognition must reproduce the exact v1.18.34 transition and deterministic replay transform. Text similarity is never sufficient.

For the pinned v1.18.34 contract, recognition requires the overflow-compaction transition: an owned `CompactionPart` with `overflow = true`; its successful compaction summary assistant (`summary = true`, parented by the compaction control); the source user selected using OpenCode's nearest-prior non-compaction-user replay rule and its `hasContent` guard; and a candidate replay whose message-level execution fields (`agent`, `model`, `format`, `tools`, `system`) and transformed parts match the upstream replay transform. The transform omits `CompactionPart`, converts media `FilePart` values to the `[Attached <mime>: <filename-or-file>]` text descriptor, and otherwise semantically copies parts. Generated message/part IDs, session IDs, and creation timestamps are excluded from replay semantic equality.

Recognized replay:

```text
provenance = INTERNAL_CONTROL
logical role = COMPACTION_REPLAY_CONTROL
owner = original/source logical owner
turn_key = NONE
canonical user contribution = NONE
```

Generated message/part IDs are not semantic replay identity.

## 3.6 Terminal outcome

Turn terminality is determined from the persisted settled logical lineage, not from `session.error` alone.

Outcome classification:

```text
ABORTED:
  terminal assistant.error.name == MessageAbortedError

FAILED:
  terminal assistant.error exists
  AND error.name != MessageAbortedError

SUCCESS:
  terminal assistant.error absent
  AND time.completed exists
  AND finish exists
  AND finish NOT IN {tool-calls, unknown}

INCOMPLETE:
  none of the above
```

`INCOMPLETE` has no canonical payload/hash, performs no ingest, advances no checkpoint, and remains pending for future reconciliation.

## 3.7 Durable content by outcome

SUCCESS persists:

- canonical user intent;
- final/confirmed `TURN_ASSISTANT` content;
- required bounded/sanitized tool context.

FAILED and ABORTED persist:

- canonical user intent only;
- no unfinished/error-aborted/partial assistant content as confirmed durable memory.

Later normal completion is handled as a later confirmed increment according to the fixed lineage/ordering rules.

## 3.8 Tool context

Useful tool context may include important commands/tests/files/results when needed to preserve engineering intent.

Excluded or transformed:

- giant raw command/build logs;
- binary bodies;
- copied full files;
- irrelevant attachments;
- secrets and noisy/raw payloads.

Tool projection is deterministic, allowlisted, bounded, and non-LLM-dependent for hash reproducibility.

## 3.9 Subtask canonical identity

User-authored Subtask identity includes execution-relevant fields:

```text
prompt
description
agent
model? { provider_id, model_id }
command?
```

Different model/command semantics must not collapse to the same canonical identity.

Raw sensitive command text need not be durable memory content; server-side privacy-preserving identity preserves the distinction.

## 3.10 File/resource identity

Filename and MIME alone are never sufficient when different inputs could collapse.

Identity is derived only from persisted OpenCode state used for the actual input. Reconciliation must not re-read mutable external files/resources/network locations.

Persisted source metadata/content used by v1.18.34 user-input expansion may contribute to identity evidence as required to preserve execution-relevant distinctions.

If sufficient identity fidelity cannot be recovered:

```text
UNRESOLVED_USER_INPUT_IDENTITY
-> no payload_hash
-> no ingest
-> no checkpoint advance
-> observable blocked root state
```

---

# 4. Local reconciliation and checkpointing

## 4.1 Local state

Local OpenCode ingestion state is stored under a canonical source-scope namespace:

```text
~/.context-store/opencode-ingestion/
  <canonical-source-scope-id>/
    source.json
    <root-session-hash>.json
    <root-session-hash>.lock
```

Raw identity evidence, raw paths/URIs/commands, and caller-authoritative payload hashes are never persisted here.

A root state conceptually contains:

- canonical source scope binding;
- committed checkpoint cursor/turn key/server-returned payload hash;
- pending retry metadata, including the pinned `evidence_contract_version` used to re-extract that pending turn across plugin upgrades;
- blocked/recovery status;
- bounded divergence diagnostics.

## 4.2 Atomic local durability

State replacement is crash-safe:

```text
write temp
fsync temp
rename
fsync directory where supported
```

The checkpoint invariant is:

```text
local checkpoint exists/advances
  => server COMMITTED or ALREADY_COMMITTED was already established
```

The reverse ordering is forbidden.

## 4.3 Per-root single flight

Same source scope + same root has at most one active local reconciler.

In-process triggers coalesce into `dirty/queued/running` state. Inter-process duplicate work is suppressed with the per-root file lock.

Local locking is optimization/suppression; the server receipt remains the final correctness boundary.

Different roots may reconcile with bounded parallelism.

## 4.4 Quiescence gate

For v1.18.34 status semantics:

```text
status[root] = busy/retry
  -> not quiescent

status[root] absent
  -> quiescent/idle
```

Terminal ingestion proceeds only from a quiescent root snapshot.

## 4.5 Reconciliation triggers

Correctness uses all of:

1. plugin activation exhaustive sweep;
2. `session.status` idle hint;
3. deprecated `session.idle` hint;
4. finite periodic exhaustive correctness sweep.

The baseline periodic correctness interval is 60 seconds (configurable without permitting normal `all` mode to disable the finite recovery sweep entirely).

Busy/retry/update/delete events may mark roots dirty, but event delivery is not required.

## 4.6 Exhaustive root discovery

A fixed default `Session.list()` page is never treated as complete.

Baseline v1 discovery uses `roots=true` and widening scan:

```text
N = 100
fetch roots, limit=N

result.length == N
  -> saturated
  -> N *= 2
  -> refetch

result.length < N
  -> exhaustive response established for that query scope
```

Failure to widen, transport error, malformed response, or saturation at an implementation maximum yields `DISCOVERY_INCOMPLETE`, not `caught_up`.

## 4.7 Discovery scope and source alias must be identical domains

A single versioned `DiscoveryScopeV1` descriptor is the source of truth for both:

```text
source alias derivation
exhaustive Session.list query
```

Every routing dimension that restricts authoritative session discovery must also be represented in the current-source alias contract.

For directory-scoped reconciliation this includes the effective directory routing context.

For shared/global project identifiers, project ID alone is insufficient. `ProjectV2.ID.global` with project-wide aggregation that would merge independent directories is invalid.

Detected alias/query domain mismatch fails closed as `SOURCE_ROUTING_SCOPE_MISMATCH` before receipt/checkpoint correctness decisions.

## 4.8 Full snapshot reconstruction, incremental durable drain

Reconciliation may fetch the complete persisted root-session message snapshot required to reconstruct v1.18.34 lineage, compaction, replay, and ownership correctly. This does not mean full-history durable re-ingestion.

```text
fetch full persisted root snapshot
  -> reconstruct lineage locally
  -> select the next eligible logical turn after checkpoint
  -> call ingest_turn only for that turn
```

Optimization of snapshot reads is allowed only if it preserves the same reconstruction semantics.

## 4.9 Contiguous-prefix drain

Eligible turns are processed in deterministic order after the checkpoint.

For each turn:

```text
COMMITTED / ALREADY_COMMITTED
  -> atomically advance checkpoint immediately
  -> continue

INCOMPLETE / retryable / blocked/conflict
  -> do not skip
  -> stop the contiguous prefix
```

Later terminal turns never pass an unresolved earlier eligible turn.

## 4.10 Retry

`RETRYABLE_FAILED` keeps the checkpoint unchanged and persists bounded retry metadata with exponential backoff.

Retry timers are not the only recovery mechanism; activation and periodic sweeps rediscover the same pending state.

Repeated quiescent `INCOMPLETE` may emit `STUCK_INCOMPLETE` diagnostics without changing the outcome classification.

## 4.11 Crash windows

Supported convergence:

```text
crash before server commit
  -> checkpoint unchanged
  -> retry

server commit succeeds, ACK lost
  -> checkpoint unchanged
  -> resend
  -> ALREADY_COMMITTED
  -> checkpoint advances

ACK received, crash before checkpoint write
  -> same ALREADY_COMMITTED recovery

checkpoint write succeeds, crash before next turn
  -> resume after checkpoint
```

## 4.12 Post-drain recheck

Before declaring a root caught up, the reconciler refreshes current status/persisted state.

Triggers arriving during the run set dirty state and cause a coalesced follow-up. New persisted state discovered before lock release is reconciled again.

---

# 5. Canonical source scope and alias continuity

## 5.1 Three-layer source identity model

Source identity has three layers:

```text
CanonicalSourceScope
  = lifetime-stable Chronos identity

CurrentSourceAlias
  = mutable version-specific OpenCode routing domain

EphemeralRoutingEvidence
  = current project/directory/workspace/path values used to resolve the alias
```

Canonical source scope is not a path, project ID, or HMAC digest.

## 5.2 Canonical scope registry

ChronosGraph issues a random stable opaque `canonical_source_scope_id`.

Project/routing evidence resolves through alias records into that canonical scope.

Keyed HMAC values are lookup indexes/tokens only. They are not the durable scope identity.

## 5.3 Alias lookup key lifecycle

Source-alias lookup keys are versioned independently from canonical scope IDs and independently from Design 2 identity keys.

Key rotation must preserve alias reachability to the same canonical scope. Old keys may be retired only after still-supported aliases are provably reachable under retained successor keys.

Loss/incomplete rotation must never silently create a new namespace. Resolution fails closed as source-scope lookup/continuity failure.

## 5.4 OpenCode project IDs are aliases, not lifetime identity

`PluginInput.project.id` is current OpenCode project identity/routing evidence, but is not assumed lifetime-immutable.

OpenCode project-ID migration must preserve the existing canonical source scope through explicit alias migration.

## 5.5 Versioned routing alias

The current alias must uniquely identify the same effective OpenCode routing domain used for root discovery.

Conceptually:

```text
OpenCodeSourceAliasV1 {
  schema,
  project_id,
  routing { kind, discriminator... }
}
```

For a shared/global project identifier, the directory routing discriminator is required for directory-scoped reconciliation.

Directory/workspace/path values are mutable alias material, not canonical scope identity.

## 5.6 Alias migration trust model

A valid local/server source binding authenticates a candidate scope but does not prove that the current OpenCode alias belongs to it.

Automatic `SOURCE_SCOPE_ALIAS_MIGRATION` requires:

```text
authenticated candidate canonical scope
AND
independent unambiguous continuity edge
```

Allowed continuity evidence is explicit/versioned and may include:

- exact current root-session overlap with uniquely matching server receipt roots;
- exact current root overlap with authenticated local root state;
- supported v1.18.34 project migration evidence from an already-bound prior alias;
- explicit operator/setup migration authorization.

Insufficient evidence includes:

- only one local binding exists;
- only one valid binding token exists;
- same path/worktree/title/name;
- similar session/message content;
- candidate ordering.

Zero or multiple proven candidate scopes yields `SOURCE_SCOPE_CONTINUITY_UNRESOLVED`.

## 5.7 Explicit enrollment

Unknown alias resolution never implicitly creates a source scope.

A genuinely new project/source is enrolled only through explicit `REGISTER_NEW_SOURCE_SCOPE`.

Explicit new-source enrollment and alias migration are different state transitions.

Until source resolution succeeds, normal ingest, checkpoint mutation, receipt creation, and source alias mutation are forbidden.

---

# 6. Corrupt local-state recovery

## 6.1 Corruption is diagnosable, not automatically permanent

A corrupt root checkpoint/state file is preserved/quarantined and is never silently interpreted as `checkpoint = null`.

Corruption alone must not permanently block a root when authority can be reconstructed.

## 6.2 Read-only receipt recovery

ChronosGraph provides source-scoped read-only receipt inventory/lookup surfaces.

Recovery flow:

```text
quarantine corrupt state
-> resolve canonical source scope
-> reconstruct current logical turns using fixed Design 2 rules
-> fetch authoritative server receipt inventory
-> determine highest safe contiguous committed prefix
-> atomically rebuild local checkpoint/state
-> resume normal reconciliation
```

A committed receipt after a real uncommitted gap does not move the checkpoint across the gap.

A receipt-only historical turn that disappeared from mutable OpenCode history remains a durable historical fact and is handled as divergence, not as an uncommitted gap.

Temporary receipt-authority outage yields retryable recovery, not guessed checkpoint state.

If current history/required comparison contracts are genuinely insufficient, recovery may become `LOCAL_STATE_RECOVERY_UNAVAILABLE` and require intervention.

---

# 7. Committed-history divergence

## 7.1 Durable history is append-only relative to mutable OpenCode history

OpenCode undo/revert/edit/delete does not automatically delete or rewrite already durable Chronos memory or receipts.

Divergence is observable.

## 7.2 Divergence sources

Potential sources include:

- undo/revert;
- message deletion;
- part deletion;
- committed-content edit/update;
- root-session deletion;
- committed-prefix membership change.

Events are only fast hints. Periodic correctness validation must detect divergence even when the corresponding event was lost.

## 7.3 Validate the entire committed prefix

Validation is not limited to the latest checkpoint turn.

For a root with committed receipts `U1..Un`, periodic correctness validation compares the entire authoritative committed prefix against current OpenCode history.

Required read-only server surfaces can enumerate source-scoped roots and source-scoped receipts, including receipts for turns no longer present in current OpenCode history.

Examples:

```text
receipt exists, current committed turn missing
  -> COMMITTED_TURN_REMOVED

current committed semantics != receipt-pinned semantics
  -> COMMITTED_TURN_SEMANTICS_CHANGED

eligible turn appears inside historical committed region with no corresponding receipt
  -> COMMITTED_PREFIX_MEMBERSHIP_CHANGED

known receipt root no longer exists in OpenCode
  -> ROOT_SESSION_REMOVED
```

Validation uses the receipt-pinned canonical/evidence/key contract from Design 2.

## 7.4 Periodic correctness targets

For resolved canonical source scope `S`:

```text
targets(S) =
  exhaustive current OpenCode roots in the same DiscoveryScope
  UNION locally known roots(S)
  UNION server receipt roots(S)
```

Server receipt-root inventory itself must be exhaustively pageable; a truncated first page is never complete.

## 7.5 Divergence effects

`OPEN_CODE_HISTORY_DIVERGED` is diagnostic.

It never:

- deletes durable memory;
- rewrites receipts;
- moves checkpoint backward.

Deterministic forward ingestion after the unchanged historical checkpoint cursor remains allowed unless another blocking condition applies.

---

# 8. ChronosGate / ChronosGraph integration

## 8.1 Internal control-plane surface

The following operations are internal authenticated control-plane APIs and are not model-callable tools:

- `ingest_turn`;
- source-scope resolve/register/migrate operations;
- receipt lookup;
- receipt-root inventory;
- root receipt inventory;
- receipt semantic validation.

ChronosGate is responsible for authentication, authorization, schema/size validation, safe diagnostics, and transport.

ChronosGraph remains canonicalization and durability authority.

## 8.2 Read-only operational surfaces

Conceptual source-scoped surfaces include:

```text
list_ingestion_receipt_roots(source scope)
list_ingestion_receipts(source scope, root_session_id)
lookup_ingestion_receipts(source scope, turn_keys[])
validate_ingestion_receipts(source scope, root_session_id, evidence[])
```

These operations do not mutate memory, receipts, graph state, or checkpoints.

## 8.3 Shared runtime / loader adapters

npm and repository-local OpenCode plugin entrypoints use one shared `OpenCodeIngestionRuntime` implementation.

Correctness logic must not fork by packaging path.

---

# 9. Observability

## 9.1 Structured state codes

At minimum, expose structured operational codes for:

### Discovery / routing

```text
DISCOVERY_COMPLETE
DISCOVERY_SATURATED
DISCOVERY_INCOMPLETE
SOURCE_ROUTING_SCOPE_MISMATCH
```

### Source continuity

```text
SOURCE_SCOPE_CONTINUITY_UNRESOLVED
SOURCE_SCOPE_ALIAS_MIGRATION
SOURCE_SCOPE_ALIAS_CONFLICT
SOURCE_SCOPE_LOOKUP_DEGRADED
```

### Reconciliation

```text
ROOT_PENDING
STUCK_INCOMPLETE
RETRYABLE_FAILED
TERMINAL_FAILED
IDEMPOTENCY_CONFLICT
IDEMPOTENCY_REBASE_UNAVAILABLE
```

### Local recovery

```text
LOCAL_STATE_CORRUPT
LOCAL_STATE_RECOVERY_RETRYABLE
LOCAL_STATE_RECOVERY_UNAVAILABLE
LOCAL_STATE_SOURCE_SCOPE_MISMATCH
```

### Divergence

```text
OPEN_CODE_HISTORY_DIVERGED
COMMITTED_TURN_REMOVED
COMMITTED_TURN_SEMANTICS_CHANGED
ROOT_SESSION_REMOVED
COMMITTED_PREFIX_MEMBERSHIP_CHANGED
```

## 9.2 Health projection

A read-only health/status projection should expose at least:

- source scope resolved/unresolved;
- exhaustive discovery complete/incomplete;
- root counts by caught-up/pending/retrying/blocked/diverged;
- oldest pending age;
- last successful exhaustive sweep;
- last successful durable commit.

`plugin loaded` alone is never sufficient to report ingestion healthy.

## 9.3 Sensitive-data discipline

Observability must not emit raw identity evidence, raw commands, file bodies, resource URIs, user/assistant full text, or sensitive filesystem paths.

Use opaque scope/root/turn identifiers and bounded error codes instead.

---

# 10. Setup and smoke verification

## 10.1 Setup protocol

OpenCode `all` production setup continues to require the configured ChronosGate to be reachable.

Unknown source continuity must be resolved explicitly by either:

- `REGISTER_NEW_SOURCE_SCOPE` for a confirmed new source;
- authorized/proven `SOURCE_SCOPE_ALIAS_MIGRATION` for an existing source.

Background reconciliation may not guess.

## 10.2 Real-turn smoke test

A setup smoke test for OpenCode `all` must traverse the actual durable path:

```text
real OpenCode v1.18.34 turn
-> actual plugin loader/runtime
-> source resolution
-> reconciliation
-> ChronosGate
-> ChronosGraph COMMIT/ALREADY
-> checkpoint
-> read-side memory verification
```

Direct calls to `memory_save`, `session_flush`, or `ingest_turn` cannot substitute for the smoke turn.

A unique random setup probe marker and exact IDs are used so verification/cleanup cannot accidentally target unrelated memories.

Cleanup, when supported, is restricted to the exact IDs produced by that probe. Broad search-and-delete cleanup is forbidden. If the backend/configuration cannot safely complete exact probe cleanup, report `SMOKE_CLEANUP_INCOMPLETE` rather than claiming cleanup succeeded.

Setup is incomplete if the real turn does not reach durable commit and readback.

---

# 11. Compatibility

## 11.1 Selective mode

`CHRONOS_INGESTION_MODE=selective` retains the existing model/tool-driven `memory_save` behavior.

The OpenCode `all` reconciler must not mutate turns in selective mode.

## 11.2 Other agents

Existing Claude Code / Codex `all` hook behavior remains a compatibility surface and is not redesigned here.

Shared `scripts/agent_turn_hook.py` behavior for non-OpenCode consumers must remain regression-protected.

---

# 12. Acceptance architecture

## 12.1 Test layers

Use three layers:

```text
Unit
  -> provenance/lineage/canonicalization/sanitizer/source-alias/state-machine logic

Integration
  -> Graph transactions/receipts/Gate/checkpoints/recovery/fault injection

Native OpenCode acceptance
  -> actual v1.18.34 process/plugin loader/persisted sessions/events/restart behavior
```

Unit/integration green is not sufficient if native acceptance fails.

## 12.2 Deterministic provider

Native acceptance uses real OpenCode v1.18.34 with a deterministic local test provider/model fixture.

External provider credits, network availability, or nondeterministic generation are not correctness dependencies.

## 12.3 Principal packaging path

The principal release path is the actual npm-style package loaded by OpenCode v1.18.34.

Repository-local plugin loading is also required and must exercise the same shared runtime.

Mocked direct `require()` + artificial event tests remain supplemental only.

---

# 13. Required acceptance matrix

The release gate must include executable scenarios for all of the following.

## A. Normal success

```text
real user turn
-> SUCCESS
-> one durable scoped receipt outcome
-> checkpoint advances
```

## B. Failed / aborted

User semantics persist; unfinished/error-aborted assistant content does not persist as confirmed durable assistant memory.

## C. Prompt kinds and ordering

Exercise text-only, file-only, AgentPart-only, SubtaskPart-only, and mixed ordered parts.

## D. Continuation lineage

Exercise compaction, `compaction_continue`, overflow replay, and subtask continuation without creating duplicate logical turns.

## E. Event loss

Drop idle/event hints and prove periodic exhaustive reconciliation eventually commits.

## F. More than 100 roots

Create >100 roots and prove fixed first page is insufficient while widening exhaustive scan discovers older roots.

## G. Lost ACK / restart

Commit succeeds, ACK/checkpoint is lost, process restarts, retry returns `ALREADY_COMMITTED`, checkpoint recovers.

## H. Trigger storm

Concurrent idle/update/sweep hints never produce more than one active local reconciler for the same root.

## I. Corrupt local state

Corrupt checkpoint is quarantined, receipt-backed contiguous-prefix recovery succeeds, normal drain resumes.

## J. Historical deletion with event loss

Commit U1/U2, mutate/delete U1, drop delete event, periodic validation reports committed-prefix divergence.

## K. Root deletion

Delete a committed root, drop `session.deleted`, and prove root union/inventory detects `ROOT_SESSION_REMOVED`.

## L. Project-ID migration

OpenCode P1 -> P2 migration preserves the same canonical Chronos scope and existing receipt visibility when continuity is proven.

## M. Non-Git/global separation

Independent `global + directory A` and `global + directory B` routing domains resolve to distinct canonical scopes unless explicit continuity migration is proven.

## N. Routing relocation

Old routing alias -> unknown new alias -> authenticated candidate + exact continuity -> alias migration to the same canonical scope.

## O. Source-alias lookup key rotation

Lookup key rotation leaves canonical source scope and receipt namespace unchanged.

## P. PREPARE/COMMIT receipt rebase race

Receipt appears after PREPARE under a different comparison contract; losing request rolls back/rebases and returns `ALREADY_COMMITTED` rather than false conflict when evidence is identical.

## Q. Zero legacy OpenCode `all` side channel

For both npm and local plugin paths:

```text
real root turn

ingest_turn calls >= 1          # retries allowed
memory_save calls == 0
session_flush calls == 0
detached agent_turn_hook.py spawns == 0

durable scoped receipt outcomes == 1
```

Invocation/process boundaries must be observed directly. A final memory count of one is not sufficient because a legacy side write might have been deduplicated.

## R. Real child session is not an ingestion root

Generate a real OpenCode child/sub-agent session `C` under root `R` and observe child events.

Required negative assertions:

```text
C persisted in OpenCode
C.parentID == R
child events observed

child receipt-root ownership == 0
child-owned turn receipts == 0
child checkpoint == absent
child pending/blocked reconciliation state == absent

R remains the only durable reconciliation root
```

## S. Unknown source fails closed

Unknown alias + no valid continuity edge produces `SOURCE_SCOPE_CONTINUITY_UNRESOLVED` with:

```text
canonical scope creations == 0
alias mutations == 0
ingest mutations == 0
receipts created == 0
memories created == 0
checkpoints created == 0
```

## T. Explicit new-source enrollment

Following scenario S, only explicit `REGISTER_NEW_SOURCE_SCOPE` resolves the source and allows normal reconciliation/commit.

## U. Ambiguous continuity fails closed

Two valid candidate scopes with ambiguous continuity must attach to neither, create no new scope, and perform no ingest/checkpoint mutation.

## V. Explicit alias-migration authorization

From an unresolved source state, an operator-authorized `AUTHORIZE_SOURCE_SCOPE_ALIAS_MIGRATION` may bind the current alias to one selected existing canonical scope. The operation must not recreate the canonical scope or rewrite historical receipts, and normal reconciliation begins only after the explicit migration succeeds.

---

# 14. Release gate

Implementation is not READY until all of the following are green:

```text
unit suite
integration suite
selective-mode regressions
non-OpenCode hook regressions
actual opencode-ai@1.18.34 npm-loader acceptance
actual local-plugin acceptance
real-turn setup smoke
```

and the native negative invariants are proven:

```text
OpenCode all:
  memory_save == 0
  session_flush == 0
  detached legacy hook spawn == 0

real child session:
  child-owned receipt == 0
  child checkpoint/pending/root ownership == 0

source continuity:
  unknown alias fails closed
  ambiguous continuity fails closed
  explicit enrollment transition is required
```

A positive result cannot mask a forbidden side effect. For example, a correct root receipt plus one child receipt is release-blocking; a successful `ingest_turn` plus one legacy `memory_save` call is release-blocking.

Acceptance evidence should be machine-checkable and must itself avoid raw sensitive evidence.

---

# 15. Key invariants

1. Events are reconciliation hints, never the durability authority.
2. PREPARE is side-effect-free; COMMIT is authoritative and atomic.
3. `COMMITTED` means primary durability + durable graph intent/outbox + receipt, not completed Neo4j projection.
4. Checkpoint advances only after `COMMITTED` or `ALREADY_COMMITTED`.
5. One source-scoped logical turn converges to one durable receipt outcome.
6. Existing receipt determines duplicate-comparison contract, including races where it appears after PREPARE.
7. Caller-provided opaque fingerprints are not identity authority.
8. Sensitive identity evidence is ephemeral and never durable/logged.
9. Only root sessions own durable logical turns.
10. `role=user` and `synthetic` alone do not determine authorship or turn ownership.
11. Cross-kind user-part ordering is semantic.
12. Known internal continuations/replays inherit logical ownership and do not create new turns.
13. INCOMPLETE is pending, not failure/commit.
14. Failed/aborted turns preserve user intent but not unfinished assistant output.
15. File/resource identity must not collapse distinct inputs and must use persisted OpenCode state only.
16. Same root reconciles serially; different roots may run with bounded parallelism.
17. Discovery is exhaustive; saturated fixed-size results are incomplete.
18. Corrupt local state is recoverable from deterministic OpenCode identities plus server receipts when authority is available.
19. Divergence validation covers the entire committed receipt prefix, not only the latest checkpoint.
20. Divergence never deletes durable memory, rewrites receipts, or rolls checkpoint backward.
21. Canonical source scope is stable and distinct from mutable OpenCode routing aliases.
22. Source alias and `Session.list` discovery scope are derived from one normative routing descriptor.
23. Binding possession authenticates a candidate scope but does not prove continuity.
24. Unknown/ambiguous continuity fails closed.
25. New-source enrollment and alias migration are explicit distinct transitions.
26. OpenCode `all` uses no legacy `memory_save` / `session_flush` / detached-hook durable side channel.
27. Native acceptance must prove forbidden side effects are zero, not merely prove a successful positive path.

## Implementation-order constraint

Implementation planning begins only after this design spec passes its own review gate.

Until then, production source/test/CI/config behavior must not be changed as part of the design phase.
