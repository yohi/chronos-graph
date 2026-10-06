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
- complete all external embedding/model work required by the prepared turn;
- read the authoritative ingestion keyring manifest and pin its generation/identity authority;
- derive privacy-preserving identity tokens only from keys authorized by that pinned manifest;
- produce a dedupe/mutation proposal together with the embeddings and destructive-state assumptions required to revalidate that proposal at COMMIT;
- derive a candidate canonical envelope and payload hash.

`PreparedTurn` conceptually carries at least:

```text
prepared embeddings
keyring_manifest_generation
identity_active_version_at_prepare
identity_key_version_used
destructive dedupe assumptions
candidate mutations / receipt inputs
```

For a new receipt, `identity_key_version_used` must equal the pinned manifest's active identity version. For receipt-pinned duplicate comparison it may be an older manifest-required version referenced by the existing receipt.

COMMIT must never need to call an embedding/model provider to reconstruct dedupe state.

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

1. acquire/read the authoritative `ingestion_keyring_manifest` serialization fence;
2. require `current_manifest.generation == PreparedTurn.keyring_manifest_generation`;
3. require `identity_key_version_used` is still authorized by the current manifest and, for a new receipt, is still the active identity version;
4. authoritative receipt/idempotency revalidation;
5. commit-time dedupe revalidation against current transactional state using only the prepared embeddings/data carried by `PreparedTurn`;
6. optimistic validation of every destructive dedupe assumption, including the current identity/version/state of any memory planned for archive/replace;
7. all primary memory mutations for the logical turn;
8. durable graph intent/outbox writes when graph mode requires them;
9. ingestion receipt creation/update as applicable;
10. atomic transaction commit.

The manifest fence is acquired before any turn mutation and remains held until COMMIT/ROLLBACK establishes transaction ordering against concurrent keyring promotion/retirement.

If manifest generation or required key authority changed since PREPARE:

```text
KEYRING_GENERATION_CHANGED
  -> rollback the entire turn transaction
  -> memory mutations == 0
  -> graph/outbox mutations == 0
  -> receipt mutations == 0
  -> RETRYABLE_FAILED(KEYRING_GENERATION_CHANGED)
  -> fresh PREPARE against the new manifest generation
```

COMMIT must never silently reuse identity material prepared under an older manifest generation.

External embedding/model/network calls are forbidden inside the COMMIT transaction.

If any destructive prepared dedupe assumption is stale at COMMIT:

```text
stale prepared dedupe assumption
  -> rollback the entire turn transaction
  -> memory mutations == 0
  -> graph/outbox mutations == 0
  -> receipt mutations == 0
  -> RETRYABLE_FAILED(STALE_DEDUPE_PLAN)
  -> perform a fresh PREPARE before retry
```

COMMIT must not silently adapt a stale destructive plan in-place. The fresh PREPARE owns any newly required embedding/model work and derives a new proposal from current state.

Neo4j projection is post-commit convergence. It is not required for `COMMITTED`.

## 1.4 Result taxonomy

`ingest_turn` returns a structured result:

```text
COMMITTED
ALREADY_COMMITTED
RETRYABLE_FAILED
  - STALE_DEDUPE_PLAN
  - KEYRING_GENERATION_CHANGED
TERMINAL_FAILED
IDEMPOTENCY_CONFLICT
IDEMPOTENCY_REBASE_UNAVAILABLE
```

Only `COMMITTED` and `ALREADY_COMMITTED` permit local checkpoint advancement.

`RETRYABLE_FAILED` has stable retry reasons including at least:

```text
STALE_DEDUPE_PLAN
KEYRING_GENERATION_CHANGED
```

Both require a fresh PREPARE and leave checkpoint unchanged.

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

## 1.7 Transaction-capable ingestion persistence boundary

The existing operation-oriented `StorageAdapter` is not the COMMIT transaction owner. OpenCode durable-all adds a dedicated ChronosGraph persistence boundary, conceptually named `IngestionCommitStore`.

`IngestionCommitStore` is owned by ChronosGraph and is the **only** component allowed to perform the authoritative turn COMMIT transaction. Existing `StorageAdapter.save_memory()` / `update_memory()` calls are not composed to emulate atomic turn commit.

PREPARE uses a new side-effect-free dedupe planner. The existing side-effecting `Deduplicator.deduplicate()`, which may archive a REPLACE target immediately, is forbidden on the OpenCode durable-all PREPARE path.

Conceptually:

```text
IngestionDedupePlanner
  -> read-only candidate search
  -> PreparedTurn {
       prepared embeddings,
       keyring manifest generation,
       identity active/key version authority,
       desired memory mutations,
       destructive target ids,
       destructive concurrency tokens,
       receipt/canonicalization inputs
     }

IngestionCommitStore.commit_ingested_turn(PreparedTurn)
  -> one backend transaction
```

The COMMIT transaction owns, in order:

```text
1. acquire/read keyring manifest serialization fence
2. validate pinned manifest generation + key authority
3. authoritative receipt read/revalidation
4. receipt-pinned rebase decision, if required
5. destructive-target concurrency-token validation
6. archive/replace/insert memory mutations
7. durable graph-intent/outbox mutations
8. receipt insert/update
9. atomic commit
```

The same manifest serialization fence is shared with keyring promotion/retirement and every other key-dependent durable mutation described in §1.10.

If receipt-pinned recanonicalization is required, the current transaction performs no mutation and returns a rebase requirement to the orchestration layer. Recanonicalization occurs outside the transaction and a fresh COMMIT attempt follows.

## 1.8 Destructive concurrency token

Every persisted memory row participating in durable-all dedupe has an authoritative integer `ingestion_revision`.

Normative semantics:

```text
insert:
  ingestion_revision = 1

any mutation that can invalidate a prepared dedupe/destructive assumption:
  ingestion_revision = ingestion_revision + 1

delete:
  row absence invalidates the prepared token
```

PREPARE captures at least:

```text
target_memory_id
target_ingestion_revision
relevant prepared target state
```

COMMIT performs an atomic compare against the current row. A missing row or revision mismatch is `STALE_DEDUPE_PLAN`.

All ordinary ChronosGraph mutation paths that can change dedupe-relevant memory state must maintain `ingestion_revision`; the durable-all path must not rely on timestamps as the concurrency authority.

## 1.9 Backend support matrix

OpenCode durable-all is supported on all three primary storage backends, with one transaction boundary per turn:

```text
SQLite:
  one aiosqlite connection
  BEGIN IMMEDIATE (or equivalent write transaction)
  read/validate manifest generation inside that write transaction
  receipt + CAS + memory + outbox + receipt mutation
  rotate/retire uses the same serialized write-transaction authority
  one COMMIT / ROLLBACK

PostgreSQL:
  one asyncpg connection
  one asyncpg transaction
  acquire the manifest row as the serialization fence before key-dependent mutation
  receipt/target locking as needed
  ingestion_revision CAS
  memory + outbox + receipt mutation
  rotate/retire acquires the same manifest-row fence
  one COMMIT / ROLLBACK

Supabase:
  one versioned server-side PostgreSQL RPC/function
  (commit_ingested_turn_v1)
  validates/locks the manifest fence inside the function transaction
  performs receipt + CAS + memory + outbox + receipt mutation
  rotate/retire and other key-dependent writes use server-side transactional
  functions with the same manifest-fence ordering semantics
```

Multiple PostgREST mutations are never accepted as an atomic Supabase COMMIT implementation.

When external graph projection is enabled, COMMIT persists a primary-store graph intent/outbox record inside the same transaction. External Neo4j I/O occurs only after primary COMMIT; a configuration that cannot provide durable primary graph intent is unsupported for OpenCode durable-all and must fail fast.

The canonical source-scope registry, source aliases/tokens, and ingestion receipts are part of the same primary durable storage family and are migrated through the repository's normal backend migration mechanism.

## 1.10 Keyring-manifest serialization fence

The singleton `ingestion_keyring_manifest` row is the **common serialization authority for every key-dependent durable mutation** in one receipt namespace.

Covered mutations include:

```text
turn COMMIT / new ingestion receipt creation
source registration
source alias attachment/migration
source-alias active-key token creation/backfill
Graph-issued local binding issuance/refresh that authorizes source.json replacement
any future durable mutation that creates state under an identity/source-alias/source-binding key version
```

Read-only receipt/source inspection that creates no key-dependent durable/local state does not require the fence.

Each key-dependent operation has a side-effect-free preparation/read phase that pins:

```text
keyring_manifest_generation
relevant active key version(s)
relevant key version(s) actually used
```

Before its first durable mutation or before releasing a newly issued binding token for local durable replacement, the authoritative primary-store transaction must acquire/read the manifest fence and revalidate the pinned generation/key authority.

If the generation changed:

```text
KEYRING_GENERATION_CHANGED
  -> full transaction rollback / no durable mutation
  -> no binding token is released for local replacement
  -> retryable domain outcome
  -> rebuild operation from current manifest
```

For `turn.ingest` this is `RETRYABLE_FAILED(KEYRING_GENERATION_CHANGED)`. Source/alias/binding control operations return the same stable `KEYRING_GENERATION_CHANGED` retryable reason in their structured domain result.

This fence establishes one total ordering between key-dependent durable writes and keyring manifest changes. Process-level readiness checks alone are never retirement authority.

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

## 2.5 Cryptographic keyring ownership and persistence

All ingestion identity/source-continuity cryptographic key material is owned and consumed by **ChronosGraph**, never by the OpenCode plugin and never by ChronosGate policy code.

ChronosGraph loads a server-side keyring file from:

```text
CHRONOS_INGESTION_KEYRING_PATH
```

Default:

```text
~/.context-store/ingestion-keyring.json
```

The file is a Graph-owned secret file (mode 0600 on POSIX), is never committed, and is generated/distributed/staged by the operator or secret manager using atomic replace or secret-manager mount semantics. The Graph-local `context-store-admin` surface validates and consumes this staged file but never transports raw key material. Container/cloud deployments may mount the same file from their secret manager.

Normative logical shape:

```json
{
  "schema": "chronos.ingestion-keyring.v1",
  "identity": {
    "active": "identity-vN",
    "keys": {
      "identity-vN": "<base64url secret>"
    }
  },
  "source_alias": {
    "active": "alias-vN",
    "keys": {
      "alias-vN": "<base64url secret>"
    }
  },
  "source_binding": {
    "active": "binding-vN",
    "keys": {
      "binding-vN": "<base64url secret>"
    }
  }
}
```

Each key is independently generated cryptographic random material of at least 256 bits. Key contents never appear in receipts, local checkpoints, API responses, logs, traces, or metrics.

All ChronosGraph control instances that share one primary durable backend/receipt namespace must load cryptographically equivalent keyring material for every manifest-required key version. Consistency is enforced mechanically through a **non-secret keyring manifest stored in that primary durable backend**; local version names alone are never trusted.

### Keyring consistency manifest

ChronosGraph migrations create the **storage schema, constraints, and singleton identity slot** for exactly one authoritative manifest per primary durable receipt namespace. Migrations do **not** populate the manifest value/row itself.

The manifest value is created only by the Graph-local `context-store-admin ingestion-keyring provision` operation after operator/secret-manager staging, conceptually:

```text
ingestion_keyring_manifest

schema = chronos.ingestion-keyring-manifest.v1
generation = monotonic integer

identity:
  active_version
  required_versions[] {
    version
    fingerprint
  }

source_alias:
  active_version
  required_versions[] {
    version
    fingerprint
  }

source_binding:
  active_version
  required_versions[] {
    version
    fingerprint
  }

updated_at
```

For each local secret key, ChronosGraph derives a non-secret verification fingerprint:

```text
SHA-256(
  "chronos.ingestion-key-fingerprint.v1"
  || 0x00
  || key_family
  || 0x00
  || key_version
  || 0x00
  || raw_256bit_or_stronger_key_bytes
)
```

Only this fingerprint is persisted in the manifest. Raw key material never enters the database.

Durable-all readiness requires:

```text
for each family:
  local active version == manifest active version

for every manifest-required version:
  local key exists
  derived fingerprint == manifest fingerprint

local key with same version but different secret:
  mismatch -> NOT READY

manifest-required key missing locally:
  mismatch -> NOT READY
```

A local keyring may contain additional **inactive staging keys** not yet present in the manifest. They are ignored for durable operations until an explicit manifest rotation promotes/adds them. This permits safe fleet staging without treating local extras as authority.

Readiness also validates manifest coverage against durable authority:

```text
every identity_key_version referenced by any ingestion receipt
  -> MUST appear in identity.required_versions

every source-alias key version still required by persisted alias-token retirement rules
  -> MUST remain represented as required
```

If durable state references a version that the manifest no longer declares, the manifest itself is inconsistent:

```text
INGESTION_KEYRING_MANIFEST_INCONSISTENT
durable-all readiness = failed
all control mutations = disabled
automatic repair/retirement = forbidden
```

On local-vs-manifest mismatch:

```text
INGESTION_KEYRING_MISMATCH
durable-all readiness = failed
source mutation = disabled
receipt mutation = disabled
turn.ingest mutation = disabled
automatic key/manifest replacement = forbidden
```

Read-only health/diagnostic reporting may remain available, but key-dependent source/receipt resolution must fail closed.

### Administrative surface, explicit provisioning, and rotation

Keyring/manifest administration is owned exclusively by a **Graph-local administrative CLI** installed by the ChronosGraph package:

```text
context-store-admin ingestion-keyring provision
context-store-admin ingestion-keyring verify
context-store-admin ingestion-keyring rotate
```

The exact internal module/file placement is an implementation-planning detail, but this CLI/process boundary is normative.

The keyring administration surface is **not exposed through**:

```text
POST /internal/v1/opencode/control
chronos.control.v1 private stdio RPC
normal MCP tools/resources/prompts
ChronosGate
```

Accordingly, no keyring/manifest administration operation is added to the `opencode-ingestion` or `chronos-setup` Bearer capability matrices.

#### Administrative authentication / execution boundary

The admin CLI is a local operator process. Its authority comes from:

```text
local OS/process identity
+
permission to read CHRONOS_INGESTION_KEYRING_PATH
+
the configured ChronosGraph primary-backend administrative credentials
```

It does not accept a ChronosGate Bearer credential and does not call ChronosGate.

Raw key material is never accepted as a command-line argument, environment variable value other than the **path** to the keyring file, HTTP/RPC payload, stdin JSON field, or database field. The CLI reads raw keys only from the local Graph-owned keyring file.

#### Secret generation/distribution ownership

Raw secret generation and distribution are operator/secret-manager responsibilities, not ChronosGate responsibilities.

For a single-instance installation, the operator may generate a valid keyring with an approved cryptographic secret-management mechanism and atomically install it at `CHRONOS_INGESTION_KEYRING_PATH`.

For multiple control instances sharing one receipt namespace:

```text
operator / secret manager:
  generate identical key material
  securely distribute the same staged keyring material
  to every intended ChronosGraph control instance
  using atomic file replacement / secret-manager mount semantics

ChronosGraph admin CLI:
  validates the local staged file
  derives non-secret fingerprints
  verifies/commits backend manifest authority
  never transports raw key material between instances
```

ChronosGraph and ChronosGate do not provide a fleet secret-distribution protocol in this design.

#### `provision`

Fresh installation requires a real local admin invocation.

Precondition:

```text
migration:
  manifest schema/constraints/singleton identity exist
  manifest value row absent

operator:
  valid keyring already staged atomically at CHRONOS_INGESTION_KEYRING_PATH
```

`context-store-admin ingestion-keyring provision` performs:

```text
1. open/validate the local staged keyring
2. validate file ownership/permissions where enforceable
3. validate all families/versions/key lengths/schema
4. derive the non-secret manifest
5. INSERT singleton ingestion_keyring_manifest with create-if-absent semantics
6. if INSERT loses because a row already exists:
     read the authoritative row
     require compatible identity/fingerprints
     never overwrite it implicitly
7. verify the local keyring against the committed manifest
8. return READY/verified only after exact verification
```

The CLI does not generate replacement keys as a side effect of `provision`.

#### `verify`

`context-store-admin ingestion-keyring verify` is read-only.

It performs the exact durable-all readiness validation defined in this section:

```text
local keyring validity
manifest existence/schema/generation
required-version fingerprint equality
receipt/alias durable-reference coverage
active-version consistency
```

It never mutates local secrets, source state, receipts, aliases, or the manifest.

#### `rotate`

Rotation is a Graph-local admin mutation and is generation-CAS protected.

Precondition:

```text
operator / secret manager has already staged the proposed key material
on every intended control instance

the local admin host has the proposed local keyring material
and knows the non-secret target active/required version set
```

The rotation request identifies only non-secret family/version transitions; raw key material remains in the local file.

`context-store-admin ingestion-keyring rotate` performs the authoritative retirement/promotion decision inside one primary-store transaction:

```text
outside mutation transaction:
  1. read/validate local staged keyring
  2. derive proposed non-secret fingerprints
  3. prepare expected generation G and proposed family/version transition

inside one primary-store transaction:
  4. acquire/read the manifest serialization fence
  5. require manifest generation == expected G
  6. re-read authoritative receipt identity-key references
  7. re-read authoritative source-alias token/coverage state
  8. validate source-binding retirement policy/state
  9. validate promotion/retirement against those current references
 10. update manifest to generation G+1
 11. commit

after commit:
 12. re-read and verify committed manifest
 13. report success only after verification
```

Retirement validation and manifest update are therefore indivisible with respect to concurrent key-dependent durable mutations.

A stale expected generation fails without overwriting the manifest.

For an active-key change, the fleet transition is deliberately fail-closed:

```text
A. distribute new key as inactive staging material everywhere
   -> current instances remain READY

B. operator updates intended instance-local keyring active metadata
   to the proposed active version
   -> instances whose local active != current manifest active become NOT READY
   -> mutation disabled during the transition window

C. designated Graph admin host executes rotate
   -> generation-CAS promotes the new manifest active version

D. instances reload/verify
   -> matching instances become READY
   -> any unstaged/mismatched instance remains NOT READY
```

This design prefers bounded fail-closed unavailability over accepting divergent key authority.

Active-key promotion and old-key retirement are **separate manifest generations**:

```text
promotion G -> G+1:
  new version becomes active
  previous active version remains required/retained

retirement G+1 -> G+2 or later:
  candidate version is already inactive
  no fresh mutation may choose it as an active key
  retirement transaction revalidates all authoritative retention references
  then, and only then, may remove it from required_versions
```

Directly replacing an active key and dropping that previous active version in one manifest transition is forbidden.

Retirement is performed through the same `rotate` operation by proposing a manifest that drops an already-inactive retained version. It is rejected unless the family-specific retirement rules and durable-reference coverage checks already permit removal.

#### Rotation-versus-mutation ordering guarantee

All supported backends must implement the same semantic ordering:

```text
key-dependent mutation wins manifest fence first:
  -> validates generation G
  -> creates durable reference/state under key K
  -> commits and releases fence
  -> promotion/retirement acquires fence afterward
  -> re-reads newly committed reference/state
  -> any proposed transition that would remove required K is rejected
  -> an active-key promotion may proceed only while retaining K as required

rotate/retire wins manifest fence first:
  -> validates references
  -> commits manifest G+1
  -> releases fence
  -> stale prepared mutation acquires fence afterward
  -> sees generation mismatch
  -> zero mutation
  -> KEYRING_GENERATION_CHANGED
  -> fresh preparation under G+1
```

No successful execution may leave:

```text
receipt.identity_key_version
  NOT IN manifest.identity.required_versions
```

Likewise, no successful alias-token/source mutation may depend on an alias key no longer represented by the manifest, and no newly issued binding token may be released under a binding-key authority invalidated by an earlier manifest generation.

For binding-key rotation, promotion first makes the successor active while retaining the previous key. New binding issuance then uses only the successor. Final old-key retirement occurs only in a later manifest generation after the explicit fleet refresh/retirement policy permits invalidating remaining old local bindings.

#### Audit / output boundary

Admin operations may report:

```text
manifest generation
family/version identifiers
non-secret fingerprints or bounded fingerprint prefixes
readiness/error codes
```

They must never print/log raw key bytes, full local keyring contents, source binding tokens, or other sensitive identity evidence.

### Whole-keyring failure semantics

If `CHRONOS_INGESTION_KEYRING_PATH` is absent, unreadable, malformed, has unsupported schema, contains invalid/duplicate versions, lacks an active key, references an active key not present in its family, contains invalid key material, or has insecure permissions where enforceable:

```text
runtime MUST NOT generate replacement keys
runtime MUST NOT rewrite the keyring
durable-all readiness = failed
control mutations = disabled
status = INGESTION_KEYRING_NOT_READY
```

If the primary manifest **value row** is absent after schema migrations, normal runtime remains NOT READY. Only the Graph-local `context-store-admin ingestion-keyring provision` operation may create that initial row.

### Identity key lifecycle

The active identity key version is used for new canonical identity tokens/receipts. Old identity key versions remain loaded while any durable receipt references that version.

An identity key version may be retired only when authoritative receipt inventory proves that no receipt references it, and the manifest update removing that version must be generation-CAS protected.

If a manifest-required referenced identity key is unexpectedly absent locally, the instance is NOT READY and performs no control mutation. As a defense-in-depth domain rule, any duplicate-validation path that nevertheless reaches canonicalization without the receipt-pinned key returns `IDEMPOTENCY_REBASE_UNAVAILABLE` and performs no mutation. A healthy READY instance must not reach that condition.

### Source-alias lookup key lifecycle

Source aliases have stable opaque `alias_id` rows plus one or more keyed alias-token rows:

```text
SourceAlias(alias_id, canonical_source_scope_id, alias_schema_version, ...)
SourceAliasToken(alias_id, key_version, keyed_token)
```

Raw project/directory/workspace/path evidence is not durable registry state.

On resolution, the server tries every retained source-alias key against current alias evidence. If an old-key token resolves an alias and the active-key token is absent, the active-key token is added to that same `alias_id`.

A source-alias key version may be retired only after every still-supported alias has a token under a retained successor key. Unexpected key loss must fail closed and must not create a new canonical source scope.

### Source-binding key lifecycle

Authenticated local source bindings use a separate source-binding keyring. Old binding keys are retained for verification until an explicit operator-managed fleet refresh/retirement declares old local bindings invalid.

A binding signed by a missing/retired key is not accepted as candidate-scope authentication. It cannot trigger implicit enrollment or migration.

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

A FAILED/ABORTED receipt terminally closes that logical-turn identity. A later confirmed increment is durable only when OpenCode creates a **new eligible user anchor**, and therefore a new `turn_key`.

If OpenCode later resumes generation under the **same already-committed eligible user anchor**, that later assistant output does not mutate or supersede the immutable FAILED/ABORTED receipt. It is classified as committed-history divergence (`POST_TERMINAL_CONTINUATION` / `COMMITTED_TURN_SEMANTICS_CHANGED`) and requires a new eligible user input before additional assistant content can become a new durable turn.

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

## 3.11 Post-terminal lineage is immutable

Once a FAILED or ABORTED logical turn is durably acknowledged, its `turn_key` and user-only payload are immutable and terminal.

```text
FAILED/ABORTED turn T committed
  -> T is closed permanently

same eligible user anchor later receives another assistant generation
  -> NOT a new increment
  -> NOT a receipt rewrite
  -> NOT ALREADY_COMMITTED
  -> committed-history divergence:
       POST_TERMINAL_CONTINUATION
       / COMMITTED_TURN_SEMANTICS_CHANGED
```

A later durable success requires a **new eligible user message anchor**, producing a new normal `turn_key`.

This rule intentionally preserves the fixed one-user-anchor/one-receipt identity contract even though OpenCode v1.18.34 can resume its loop against the same last user message after an interrupted/failed assistant. Such same-anchor post-terminal output remains observable current OpenCode history but is not silently folded into immutable durable memory.

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

In-process triggers coalesce into `dirty/queued/running` state. Inter-process duplicate work is suppressed with the per-root lock.

Inter-process lock ownership must be crash-recoverable. A crashed, terminated, or restarted owner must never leave the root permanently unreconcilable.

Valid implementations include process-lifetime OS advisory locking or an explicit owner/lease/stale-reclamation protocol. Persistent lock-file existence alone is never ownership authority.

After owner loss, activation/periodic reconciliation must be able to reacquire ownership in finite time and resume pending work.

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

## 5.8 Canonical source registry persistence

Canonical source continuity is persisted in the primary ChronosGraph backend through migration-managed ingestion tables:

```text
ingestion_source_scopes
  canonical_source_scope_id
  scope_schema_version
  integration
  created_at

ingestion_source_aliases
  alias_id
  canonical_source_scope_id
  alias_schema_version
  status
  created_at

ingestion_source_alias_tokens
  alias_id
  key_version
  keyed_token

ingestion_keyring_manifest
  schema
  generation
  active/required version metadata
  non-secret key fingerprints

ingestion_receipts
  ...
```

The exact SQL type names may be backend-specific, but these ownership/uniqueness semantics are fixed:

```text
canonical_source_scope_id:
  stable opaque server-issued identity

(alias_schema_version, key_version, keyed_token):
  globally unique alias lookup key

alias_id:
  stable grouping that allows key rotation without raw alias evidence

receipt:
  unique by (canonical_source_scope_id, turn_key)
```

Source registration and explicit alias migration use their own atomic primary-store transactions. They never rewrite historical receipts.

Every source/alias mutation that creates or backfills keyed alias state, and every Graph-issued binding issuance/refresh that can replace local `source.json`, participates in the §1.10 manifest-generation fence. A stale prepared source/binding operation returns retryable `KEYRING_GENERATION_CHANGED` with zero mutation/replacement.

## 5.9 Authenticated local source binding

`source.json` stores an integrity-protected Graph-issued candidate-scope binding, not a source-continuity proof and not an authorization credential.

Normative shape:

```json
{
  "schema": "chronos.opencode.local-source.v1",
  "canonical_source_scope_id": "<opaque S>",
  "binding": {
    "schema": "chronos.source-binding.v1",
    "issuer": "chronos-graph",
    "key_version": "binding-vN",
    "token": "<base64url MAC>"
  }
}
```

The MAC authenticates the JCS-encoded tuple:

```text
binding schema version
issuer = chronos-graph
canonical_source_scope_id
```

It deliberately does **not** bind mutable project/directory/workspace/path alias evidence. Continuity still requires the independent edge fixed in §5.6.

Properties:

```text
issuer:
  ChronosGraph control plane

verifier:
  ChronosGraph control plane

secret?:
  no; it is integrity-protected candidate-scope evidence,
  not an authorization bearer credential

logging:
  full token forbidden

invalid MAC / unknown key version:
  local candidate binding is unusable
  -> SOURCE_SCOPE_CONTINUITY_UNRESOLVED
  -> no source/receipt/checkpoint mutation
```

When a retained old binding key verifies a token, Graph may return a refreshed token under the active binding key. Local replacement uses the same crash-safe atomic state-write rules.

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

## 8.4 OpenCode runtime -> ChronosGate control protocol

The control plane uses a dedicated HTTP JSON endpoint owned by ChronosGate:

```text
POST /internal/v1/opencode/control
Authorization: Bearer <control credential>
Content-Type: application/json
```

It does **not** use `GET /sse`, `POST /messages`, `tools/list`, or externally accepted `tools/call`.

Versioned request envelope:

```json
{
  "protocol": "chronos.opencode-control.v1",
  "request_id": "<opaque request id>",
  "operation": "<operation name>",
  "payload": {}
}
```

Versioned success/domain-result envelope:

```json
{
  "protocol": "chronos.opencode-control.v1",
  "request_id": "<same id>",
  "ok": true,
  "result": {}
}
```

Versioned control error envelope:

```json
{
  "protocol": "chronos.opencode-control.v1",
  "request_id": "<same id when available>",
  "ok": false,
  "error": {
    "code": "<stable control error code>",
    "retryable": true
  }
}
```

Allowed operation names are fixed by protocol version:

```text
source.resolve
source.register
source.authorize_alias_migration
receipt.list_roots
receipt.list
receipt.lookup
receipt.validate
turn.ingest
```

Keyring/manifest provisioning, verification, rotation, or retirement operations are intentionally absent from this protocol. They are Graph-local admin CLI operations only.

Raw sensitive identity evidence may occur only inside the authenticated request payload needed by the corresponding operation and follows the existing ephemeral/redaction contract.

## 8.5 ChronosGate authentication and authorization

The dedicated control endpoint reuses ChronosGate's Bearer API-key authenticator implementation and server-side `MCP_GATEWAY_API_KEYS_JSON` principal registry, but **control credentials are separate raw secrets from every legacy/regular MCP agent credential**.

### Credential ownership

Legacy MCP turn-end hooks retain the existing compatibility contract:

```text
MCP_GATEWAY_API_KEY
  -> legacy agent principal (for example claude-code / codex)
  -> GET /sse
  -> x-mcp-intent: memory.ingest
  -> POST /messages
  -> tools/call memory_save
```

OpenCode durable-all uses a new dedicated credential:

```text
MCP_GATEWAY_CONTROL_API_KEY
  -> reserved principal opencode-ingestion
  -> POST /internal/v1/opencode/control only
```

Setup/operator control uses a third dedicated credential:

```text
MCP_GATEWAY_OPERATOR_API_KEY
  -> reserved principal chronos-setup
  -> POST /internal/v1/opencode/control only
```

The three raw secrets must be distinct. ChronosGate's existing duplicate-key rejection remains authoritative.

Server-side provisioning in `MCP_GATEWAY_API_KEYS_JSON` therefore contains distinct principal/key entries, conceptually:

```json
{
  "claude-code": "<legacy-key-A>",
  "codex": "<legacy-key-B>",
  "opencode-ingestion": "<control-key-C>",
  "chronos-setup": "<operator-key-D>"
}
```

A deployment may have only the legacy principals it actually uses, but `opencode-ingestion` and `chronos-setup` may never reuse a legacy raw key.

### Path separation and session-bound Bearer authorization

Authentication success does not imply access to both protocol families.

The regular MCP transport is strengthened so both legs are authenticated. `session_id` possession alone is never authorization authority.

```text
GET /sse:
  require Bearer
  authenticate principal P
  reject reserved control principals opencode-ingestion / chronos-setup with 403
  apply existing intent/tool policy
  create regular MCP session S with immutable owner_principal = P

POST /messages?session_id=S:
  require Bearer
  authenticate principal Q
  lookup S
  require Q == S.owner_principal
  require Q is a regular MCP principal, not a reserved control principal
  then apply the existing session capability / tool-policy handling
```

Authorization/error ordering is fixed:

```text
POST /messages:

missing Bearer
  -> 401

invalid Bearer
  -> 401

valid Bearer + unknown/expired session_id
  -> 404

valid Bearer + existing session + Q != session.owner_principal
  -> 403

reserved control principal + any existing regular MCP session
  -> 403

matching regular principal + owned live session
  -> normal JSON-RPC handling
```

The Bearer is authenticated **before** session lookup, so an unauthenticated caller cannot use `/messages` as a session-id existence oracle. After successful Bearer authentication, an unknown/expired session remains the existing 404 condition.

Normative protocol-family matrix:

```text
legacy MCP agent principal:
  /sse + /messages only with its own Bearer and owned session
  /internal/v1/opencode/control -> 403

opencode-ingestion:
  /internal/v1/opencode/control according to control capabilities
  /sse -> 403
  /messages against any regular MCP session -> 403

chronos-setup:
  /internal/v1/opencode/control according to control capabilities
  /sse -> 403
  /messages against any regular MCP session -> 403
```

A session owner principal is immutable for the lifetime of that MCP session. Session refresh/touch/approval flow must not change its owner.

Supported regular MCP clients must repeat the same Bearer credential used for the SSE handshake on every `POST /messages`. The existing `scripts/agent_turn_hook.py` already follows this contract for its SSE handshake and subsequent `tools/call memory_save` POST.

This changes regular MCP `/messages` security semantics from session-id capability alone to **Bearer + session ownership**, while preserving the regression-protected Claude Code / Codex turn-end hook behavior.

### Control capability matrix

```text
opencode-ingestion:
  source.resolve
  receipt.list_roots
  receipt.list
  receipt.lookup
  receipt.validate
  turn.ingest

chronos-setup:
  source.resolve
  source.register
  source.authorize_alias_migration
  receipt.list_roots
  receipt.list
  receipt.lookup
  receipt.validate
```

Safe automatic alias migration proven by §5.6 is part of `source.resolve`; manual source-alias authorization remains setup-only.

The `chronos-setup` Bearer principal administers source enrollment/alias migration only. It has no keyring-secret or keyring-manifest administration capability.

Control capability is never inferred from `memory.ingest`, `developer_access`, or any allowed MCP tool. Legacy MCP intent authorization is never inferred from control capability.

Bearer credentials are never request-body fields and are never logged. Runtime/operator credential rotation is independent from receipt/keyring identity; authentication failure never advances a checkpoint.

## 8.6 ChronosGate -> ChronosGraph private transport

ChronosGate reaches the Graph control plane through a **second, private, long-lived local stdio subprocess**, distinct from the normal MCP subprocess:

```text
ChronosGate
  |
  +-- normal MCP upstream:
  |     context-store
  |     -> tools/list / tools/call
  |
  +-- private control upstream:
        context-store-control --stdio
        -> chronos.control.v1 JSON-RPC
```

The private wire protocol is newline/framed JSON-RPC 2.0 over stdio with method family:

```text
chronos.control.v1.source.resolve
chronos.control.v1.source.register
chronos.control.v1.source.authorize_alias_migration
chronos.control.v1.receipt.list_roots
chronos.control.v1.receipt.list
chronos.control.v1.receipt.lookup
chronos.control.v1.receipt.validate
chronos.control.v1.turn.ingest
```

No `chronos.control.v1.keyring.*` or manifest-administration method exists in this design.

These methods are implemented by a dedicated ChronosGraph control server/dispatcher and are **not registered as FastMCP tools/resources/prompts**. Consequently they cannot appear in `tools/list` and cannot be reached through regular external `tools/call`.

ChronosGate does not import `context_store`. The cross-repository wire schemas/error enums live in Graph-owned `chronos_shared` versioned protocol primitives, which ChronosGate may consume as it already consumes shared ingestion-mode primitives.

The control subprocess reads Graph-owned storage/keyring configuration itself. ChronosGate never receives or interprets identity/source-alias/source-binding HMAC key material.

## 8.7 Control error mapping

HTTP status is reserved for transport/auth/envelope failures:

```text
400:
  malformed/unsupported control envelope

401:
  missing/invalid Bearer credential

403:
  authenticated principal lacks requested control capability

413:
  request exceeds control-plane size limit

503:
  Graph control subprocess unavailable/timeout
```

A syntactically accepted domain request returns HTTP 200 and a versioned domain result.

For `turn.ingest`, the result kind is exactly:

```text
COMMITTED
ALREADY_COMMITTED
RETRYABLE_FAILED
TERMINAL_FAILED
IDEMPOTENCY_CONFLICT
IDEMPOTENCY_REBASE_UNAVAILABLE
```

Network/HTTP 5xx/control-process timeout is a transport-level retryable failure and is **not** rewritten into `TERMINAL_FAILED`. It leaves checkpoint unchanged.

Source/receipt operations return their fixed structured source-resolution/validation statuses. Unsupported protocol versions fail before mutation.

## 8.8 Repository ownership boundary

```text
chronos-gate:
  /internal/v1/opencode/control HTTP surface
  regular /sse + /messages Bearer authentication
  immutable MCP session owner-principal binding
  control capability authorization
  request size/schema gate
  audit/redaction
  private control-subprocess client
  HTTP <-> control wire error mapping

chronos-graph:
  context-store-control --stdio server
  chronos.control.v1 dispatcher
  context-store-admin ingestion-keyring {provision,verify,rotate}
  local keyring validation / manifest administration
  canonicalization / PREPARE / COMMIT orchestration
  IngestionCommitStore
  source-scope/alias/receipt registry
  keyring loading/rotation validation
  binding issue/verify
  backend migrations/RPCs
  domain result/error authority

chronos_shared (Graph-owned package surface):
  versioned control wire schemas
  operation/result/error enums
  no Gate policy implementation
```

ChronosGraph never depends on ChronosGate, preserving the repository separation constraint.

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

### Local recovery / cryptographic readiness

```text
LOCAL_STATE_CORRUPT
LOCAL_STATE_RECOVERY_RETRYABLE
LOCAL_STATE_RECOVERY_UNAVAILABLE
LOCAL_STATE_SOURCE_SCOPE_MISMATCH
INGESTION_KEYRING_NOT_READY
INGESTION_KEYRING_MISMATCH
INGESTION_KEYRING_MANIFEST_INCONSISTENT
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
- last successful durable commit;
- local ingestion keyring validity;
- authoritative keyring manifest generation;
- local-vs-manifest keyring match status.

`plugin loaded` alone is never sufficient to report ingestion healthy. Keyring/manifest mismatch makes durable-all NOT READY even when the control process is otherwise reachable.

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

Before source enrollment or smoke ingestion, an operator must execute the Graph-local administration flow in §2.5:

```text
operator/secret manager stages CHRONOS_INGESTION_KEYRING_PATH
context-store-admin ingestion-keyring provision   # first install only
context-store-admin ingestion-keyring verify
```

Rotation/retirement likewise uses only `context-store-admin ingestion-keyring rotate`. Setup automation may invoke this local Graph CLI on the Graph host, but it must not reimplement direct filesystem/database mutation and must not tunnel raw key material through ChronosGate.

Normal runtime is never allowed to bootstrap replacement cryptographic state implicitly.

Credential provisioning must also preserve §8.5 separation:

```text
legacy MCP agent key(s)
OpenCode control key
setup/operator key
```

must be distinct raw secrets mapped to their distinct principals.

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

Shared `scripts/agent_turn_hook.py` behavior for non-OpenCode consumers must remain regression-protected, including continued use of the legacy `MCP_GATEWAY_API_KEY` on the regular SSE/messages `memory.ingest -> memory_save` path. The same Bearer used to create the SSE session is required on the subsequent `POST /messages`, matching the existing hook behavior. OpenCode durable-all must not repurpose that credential.

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

## W. Stale dedupe plan rollback

Use deterministic fault injection around the PREPARE/COMMIT boundary:

```text
PREPARE
  -> destructive dedupe plan targets memory M
  -> PreparedTurn contains all required embeddings

concurrent transaction
  -> changes the dedupe-relevant state/version of M

COMMIT
  -> revalidation detects stale assumption
  -> RETRYABLE_FAILED(STALE_DEDUPE_PLAN)
```

Required assertions:

```text
external embedding/model/network calls inside COMMIT == 0
memory mutations from failed COMMIT == 0
graph/outbox mutations from failed COMMIT == 0
receipt mutations from failed COMMIT == 0
checkpoint advance == 0

fresh PREPARE
  -> current dedupe state
  -> later COMMIT may succeed normally
```

## X. Inter-process root-lock crash recovery

Exercise real inter-process lock ownership:

```text
process A acquires root reconciliation ownership
  -> A is hard-terminated before release

plugin/process restarts
  -> activation/periodic recovery rediscovers the root
  -> stale/dead ownership does not permanently block acquisition
  -> a live process reacquires root ownership
  -> pending root eventually reconciles
```

A leftover lock file by itself must not make the test remain blocked forever.

## Y. Control-plane isolation, credential separation, session ownership, and coexistence

Exercise one ChronosGate installation with distinct legacy/control/operator credentials and the real private Graph control subprocess.

Create at least two regular MCP principals, A and B, plus the reserved control principals.

Required assertions:

```text
legacy principal A:
  GET /sse with Bearer A + allowed memory.ingest intent
    -> succeeds
    -> creates session SA owned by A

Bearer A + SA:
  POST /messages tools/call memory_save
    -> existing behavior succeeds

missing Bearer + SA:
  POST /messages -> 401

invalid Bearer + SA:
  POST /messages -> 401

Bearer B + SA:
  POST /messages -> 403

Bearer A + unknown/expired session:
  POST /messages -> 404

legacy principal A:
  POST /internal/v1/opencode/control -> 403

OpenCode MCP/control credential separation:
  MCP_GATEWAY_CONTROL_API_KEY != MCP_GATEWAY_API_KEY

opencode-ingestion control credential:
  turn.ingest allowed
  receipt read/validate allowed
  source.register denied
  source.authorize_alias_migration denied
  GET /sse -> 403
  POST /messages with SA -> 403

chronos-setup operator credential:
  source.register allowed
  source.authorize_alias_migration allowed
  GET /sse -> 403
  POST /messages with SA -> 403

normal MCP/OpenCode agent principal:
  POST /internal/v1/opencode/control -> 403

tools/list:
  no control operations visible

tools/call(control-operation-name):
  unreachable/denied

private control subprocess unavailable:
  HTTP 503
  checkpoint advance == 0
```

The acceptance installation must run the regression-protected legacy Claude/Codex hook path and the OpenCode durable control path side-by-side. It must prove both credential separation and that a control/operator credential cannot successfully reuse a regular MCP session ID.

## Z. Backend atomic-COMMIT matrix

For SQLite, PostgreSQL, and Supabase, run a backend-specific deterministic failure after at least one proposed memory mutation but before receipt commit.

Required result for every backend:

```text
transaction abort
memory mutation == 0
graph/outbox mutation == 0
receipt mutation == 0
checkpoint advance == 0
```

Supabase acceptance must prove one `commit_ingested_turn_v1` transactional RPC/function is used; multiple PostgREST writes are release-blocking.

Also verify an `ingestion_revision` mismatch produces `RETRYABLE_FAILED(STALE_DEDUPE_PLAN)`.

## AA. Keyring provisioning, cross-instance consistency, rotation, and local binding

Acceptance must invoke the real Graph-local `context-store-admin` administration surface. Direct database inserts/updates or fixture-written manifest rows do not satisfy this scenario.

Exercise at least two ChronosGraph control instances against the same primary receipt namespace.

### Provisioning / whole-keyring failure

```text
missing CHRONOS_INGESTION_KEYRING_PATH:
  context-store-admin ingestion-keyring verify -> NOT READY/error
  normal durable-all runtime -> INGESTION_KEYRING_NOT_READY
  automatic key generation == 0
  source/receipt/turn mutation == 0

malformed/invalid/insecure keyring where enforceable:
  same fail-closed result

schema migration on fresh backend:
  manifest schema/constraints/singleton identity exist
  manifest value row == absent

manifest absent in normal runtime:
  durable-all NOT READY
  automatic manifest creation == 0

operator stages a valid local keyring
real admin command:
  context-store-admin ingestion-keyring provision
    -> INSERT initial manifest row create-if-absent
    -> verify committed manifest
    -> readiness becomes healthy only after verification

second provision:
  existing manifest overwrite == 0
  exact compatible manifest -> verify success
  incompatible manifest -> fail closed
```

### Secret-boundary assertion

Instrument Gate/control transports while admin provisioning/rotation runs:

```text
/internal/v1/opencode/control keyring operations == 0
chronos.control.v1 keyring operations == 0
normal MCP keyring operations == 0
raw key bytes observed by ChronosGate == 0
raw key bytes persisted in backend manifest == 0
```

### Cross-instance mismatch

Configure:

```text
instance A and B:
  same backend/receipt namespace
  same family/version names
  different raw key material for at least one required version
```

Expected:

```text
context-store-admin ingestion-keyring verify
  -> derived fingerprint mismatch detected mechanically

mismatched instance -> INGESTION_KEYRING_MISMATCH
mismatched instance durable-all NOT READY
turn.ingest mutation == 0
source alias mutation == 0
receipt mutation == 0
```

### Rotation / retirement through real admin command

```text
operator/secret manager stages new inactive key material on A and B
  -> current readiness remains valid

operator updates intended local active metadata
  -> local-active / manifest-active mismatch makes those instances NOT READY
  -> mutation disabled during transition

designated admin host:
  context-store-admin ingestion-keyring rotate
    -> reads generation G
    -> validates durable retention
    -> derives proposed non-secret fingerprints
    -> CAS updates to G+1
    -> verifies committed manifest

A and B reload:
  -> correctly staged instances READY
  -> mismatched/unstaged instances remain NOT READY

stale concurrent rotate using old generation G:
  -> CAS rejected
  -> manifest not overwritten

retirement proposal while receipt/alias/binding retention still requires key:
  -> rotate rejected
  -> manifest unchanged
```

### Rotation versus in-flight durable mutation

Use deterministic concurrency barriers around the real backend transaction fence.

Baseline:

```text
manifest generation = G
identity active = v1
identity required = {v1}
PreparedTurn T pins G / v1
operator has staged successor v2
```

Case A — turn COMMIT wins before promotion:

```text
T acquires manifest fence
T validates G / v1
T commits receipt(identity_key_version=v1)
T releases fence

promotion transaction acquires fence
re-reads authoritative state
commits G+1 only as:
  identity active = v2
  identity required = {v1, v2}

later retirement proposal G+1 -> G+2:
  acquires fence
  re-reads receipt references
  sees receipt(identity_key_version=v1)
  removal of v1 -> rejected
  manifest still requires v1
```

Case B — promotion wins before stale turn COMMIT:

```text
promotion acquires manifest fence
commits G+1:
  identity active = v2
  identity required = {v1, v2}
promotion releases fence

old T acquires fence
current generation != G
-> RETRYABLE_FAILED(KEYRING_GENERATION_CHANGED)
-> memory mutation == 0
-> graph/outbox mutation == 0
-> receipt mutation == 0
-> checkpoint advance == 0
-> fresh PREPARE
-> new receipt preparation uses active v2
```

Machine-check after both schedules:

```text
for every ingestion receipt:
  receipt.identity_key_version
    IN manifest.identity.required_versions
```

### Alias / binding concurrency

Run equivalent barriers for key-dependent source state:

```text
source-alias token creation/backfill prepared under G
vs alias-key promotion/retirement

binding issuance/refresh prepared under G
vs binding-key promotion/retirement
```

Required outcomes follow the same ordering:

```text
mutation/issuance wins first:
  rotate observes/obeys the committed/reference or retention state

rotate wins first:
  stale operation -> KEYRING_GENERATION_CHANGED
  alias/source mutation == 0
  stale binding token is not released for source.json replacement
  operation retries under the new generation
```

Binding retirement additionally proves the two-generation rule: successor promotion retains the previous key; final retirement is a later generation after fleet refresh policy.

Run these concurrency cases for SQLite, PostgreSQL, and Supabase integration backends using their backend-specific transaction implementation.

### Identity historical-key behavior

```text
identity old key:
  old receipt remains comparable while manifest-required

manifest-required identity key absent locally:
  -> instance NOT READY
  -> source/receipt/turn mutation == 0

defense-in-depth direct duplicate-validation fixture with receipt-pinned key unavailable:
  -> IDEMPOTENCY_REBASE_UNAVAILABLE
  -> no receipt rewrite
  -> no memory/outbox mutation

manifest incorrectly omits a receipt-referenced identity version:
  -> INGESTION_KEYRING_MANIFEST_INCONSISTENT
  -> durable-all NOT READY
  -> automatic manifest repair == 0
```

### Source alias / binding

```text
source-alias key rotation:
  old alias token resolves
  active-key token added to same alias_id
  canonical scope unchanged

binding token:
  valid token authenticates candidate S only
  tampered/unknown-key token fails closed
  full token/key material absent from logs
```

## AB. Post-terminal same-anchor continuation

Create a real FAILED or ABORTED root turn, let its user-only receipt commit, then resume OpenCode v1.18.34 against the same eligible user anchor and obtain a later successful assistant.

Required assertions:

```text
original turn_key unchanged
original receipt/hash unchanged
new same-anchor success receipt == 0
checkpoint does not roll back
divergence recorded:
  POST_TERMINAL_CONTINUATION /
  COMMITTED_TURN_SEMANTICS_CHANGED
```

Then create a new eligible user message and verify it receives a new normal `turn_key` and can commit successfully.

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

control plane:
  normal MCP/tool path cannot reach control operations
  legacy/control/operator credentials are distinct
  regular /messages requires Bearer == immutable MCP session owner
  cross-principal /messages reuse is rejected
  legacy MCP hook and OpenCode control path coexist
  reserved control principals cannot open or reuse regular MCP sessions

storage:
  SQLite/PostgreSQL/Supabase atomic COMMIT matrix green
  ingestion_revision stale-plan CAS green

crypto/binding:
  real context-store-admin provision/verify/rotate acceptance green
  no keyring administration through Gate/control/MCP transports
  explicit keyring/manifest provisioning green
  multi-instance manifest fingerprint consistency green
  missing/malformed/mismatched keyring fails readiness with zero mutation
  retained-key rebase/rotation green
  rotation-vs-turn/source/alias/binding serialization race green
  successful receipts always reference manifest-required identity keys
  invalid binding fails closed

post-terminal lineage:
  same-anchor continuation does not rewrite immutable receipt
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
28. COMMIT performs no external embedding/model/network work; destructive dedupe is transactionally revalidated using prepared embeddings and stale plans roll back as `RETRYABLE_FAILED(STALE_DEDUPE_PLAN)`.
29. Inter-process root ownership is crash-recoverable; persistent lock-file existence alone can never permanently suppress reconciliation.
30. OpenCode control-plane operations are carried over a dedicated authenticated HTTP control protocol and a private non-MCP Graph stdio control protocol; regular `tools/list` / `tools/call` cannot reach them.
31. ChronosGraph `IngestionCommitStore` owns one backend transaction per turn COMMIT; operation-oriented `StorageAdapter` calls cannot emulate that transaction.
32. `ingestion_revision` is the authoritative destructive dedupe concurrency token; timestamps are not CAS authority.
33. SQLite, PostgreSQL, and Supabase all-mode support requires the backend-specific atomic COMMIT strategy fixed in §1.9.
34. Identity/source-alias/source-binding key material is Graph-owned, versioned, and loaded from the Graph-owned ingestion keyring; it never becomes plugin/Gate policy state.
35. Canonical source scope / alias / receipt registries are primary durable storage owned by ChronosGraph migrations.
36. A Graph-issued local binding authenticates a candidate scope only; invalid/stale bindings fail closed and never authorize source mutation.
37. FAILED/ABORTED commit permanently closes that user-anchor receipt; same-anchor later success is divergence, while only a new eligible user anchor creates a later durable increment.
38. Legacy MCP ingestion, OpenCode durable control, and setup/operator control use distinct raw Bearer credentials and distinct principals; a control credential is never valid for regular SSE/messages MCP access.
39. Regular MCP `POST /messages` requires a valid Bearer whose authenticated principal exactly matches the immutable owner principal of the referenced live MCP session; missing/invalid Bearer is 401, owner mismatch is 403, and authenticated unknown/expired session is 404.
40. Existing non-OpenCode hooks retain `MCP_GATEWAY_API_KEY`; OpenCode durable-all uses `MCP_GATEWAY_CONTROL_API_KEY` and must not repurpose the legacy credential.
41. Every shared receipt namespace has one authoritative non-secret `ingestion_keyring_manifest`; each control instance must mechanically verify manifest-required key fingerprints before durable-all mutation.
42. Migrations create only manifest schema/constraints/singleton identity; only Graph-local `context-store-admin ingestion-keyring provision` may create the initial manifest value row.
43. The authoritative manifest must cover every identity key version still referenced by receipts and every alias key version still required by alias-retirement rules; missing durable-reference coverage is a fail-closed manifest inconsistency.
44. Runtime never auto-generates/replaces a missing or malformed ingestion keyring or missing manifest; initial provisioning and rotation are explicit operator actions.
45. Keyring manifest updates are generation-CAS protected, and local inactive staging keys may not become active authority until represented by the committed manifest.
46. Keyring/manifest provision, verify, rotation, and retirement are owned exclusively by the Graph-local `context-store-admin` administration surface; no Gate HTTP, `chronos.control.v1`, or MCP operation may administer them.
47. Raw ingestion key material is generated/distributed/staged by the operator or secret manager and is consumed locally by ChronosGraph only; ChronosGraph does not provide a fleet secret-distribution transport.
48. Setup automation may invoke the Graph-local admin CLI but may not bypass it with direct manifest/database mutation or transport raw key material through ChronosGate.
49. The singleton keyring manifest row is the common transaction serialization fence for every key-dependent durable mutation and every keyring promotion/retirement.
50. Prepared key-dependent mutations pin manifest generation and key authority; a changed generation yields zero mutation and the stable retryable reason `KEYRING_GENERATION_CHANGED`.
51. Retirement validation and manifest update occur in one primary-store transaction under the same fence used by turn/source/alias/binding mutations.
52. Active-key promotion always retains the previous active key; retirement is a separate later manifest generation after the candidate key is inactive and retention rules permit removal.
53. The serialization ordering is deterministic: mutation-first makes retirement observe the new reference/state; rotate-first makes the stale mutation rollback/retry.
54. No successful state may contain a receipt whose `identity_key_version` is absent from `manifest.identity.required_versions`; equivalent manifest-authority guarantees apply to keyed alias state and newly issued binding tokens.

## Implementation-order constraint

Implementation planning begins only after this design spec passes its own review gate.

Until then, production source/test/CI/config behavior must not be changed as part of the design phase.
