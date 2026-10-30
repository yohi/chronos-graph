# OpenCode V2 Migration Evidence

## Scope

- Target: OpenCode `2.1.4`, source commit
  `68bc26b7da1990ce10ffecfbc1e09eb13aa5d824`.
- Package: `@yohi/opencode-plugin-chronos-turn-end@2.0.0-alpha.1`.
- Workspace: branch `feat/opencode-v2`, based on `6eaf561a36cb80d6b57d7d18a2ddfacb16abf70b`.
- Verification policy: the user directed that OpenSandbox be ignored. Commands
  below ran directly in the current workspace, not an isolated sandbox.
- Evidence source: current local command output; no production credentials or
  conversation data were used.

## Verified

- **Public API:** Compared installed `@opencode/plugin@2.1.4` and
  `@opencode/client@2.1.4` declarations with upstream `v2.1.4` source.
  Confirmed Promise setup, events, session lookup, and paginated messages.
- **Host binary:** `./node_modules/.bin/opencode --version` and `--help`.
  Result: `opencode v2.1.4`; CLI help returned successfully.
- **Type checking:** `npm run typecheck` — PASS.
- **Plugin tests:** `npm test` — PASS, 14 tests.
- **Python tests:** `uv run --frozen pytest tests/unit/ -q` — PASS, 1193 tests.
- **Python lint:** `uv run --frozen ruff check src/ tests/ scripts/` — PASS.
- **Python format:** Ruff format check on changed Python files — PASS. The
  repository-wide format check reports an existing difference in
  `scripts/agent_assets/transaction_journal.py`, which this migration did not
  modify.
- **Python types:** `uv run --frozen mypy src/` and changed agent-asset/hook
  modules — PASS.
- **Package contents:** `npm pack --dry-run --json` — PASS; the V2 entrypoint
  and five runtime modules are included.
- **Package tarball import:** Packed, extracted under a temporary path, linked
  to workspace dependencies, imported the extracted entrypoint, and removed
  temporary artifacts — PASS; stable ID and setup function are present.
  A clean `npm install` of that tarball was also attempted, but dependency
  resolution failed because the configured registry returned no version for
  `@smithy/core@^3.38.0`.
- **Registration:** Temporary-home sync tests — PASS; native `plugins`
  registration, idempotency, unrelated options retention, and old-version
  conflict.
- **Strict delivery:** Python unit tests — PASS; missing credentials, transport
  failures, JSON-RPC tool errors, and non-2xx responses are not recorded as
  success. Strict diagnostics redact error details.

## Not verified / blocked

- **Clean tarball dependency installation: BLOCKED.** The configured npm registry
  did not resolve `@smithy/core@^3.38.0`, a transitive package dependency.
  Extraction and import using already-installed workspace dependencies passed.
- **Installed-host plugin execution: NOT RUN.** The host binary was installed,
  but the plugin was not loaded by a running OpenCode server. CLI help/version
  and importing the packed package are not host-conformance evidence.
- **Gateway persistence readback: NOT RUN.** No fixture gateway with a connected
  ChronosGraph memory backend was available; HTTP acceptance alone is not proof
  of persistence.
- **Reconnect and missed events: PASS (fixture).** Stream closure triggers
  reconnect with bounded exponential delay and session reconciliation. Initial
  sessions establish an idle baseline; saved checkpoints reconcile newer idle
  messages. See `test_opencode_runtime.cjs`. Real-host behavior remains NOT RUN.
- **Full shutdown lifecycle stress: PARTIAL.** Basic cancellation-before-spawn,
  per-session serial processing, duplicate suppression, and checkpoint tests
  pass. Platform-specific child termination escalation and unload-during-every
  I/O phase were not exercised.
- **G1–G21 migration gates: PARTIAL / NOT RUN.** The user guide's complete
  capability inventory and gate matrix have not been established. No
  `PORT COMPLETE` claim is made.
- **Repository-wide Markdown lint: NOT CLEAN.** Focused lint on the new evidence,
  migration, README, design, and plan documents passes. Existing setup,
  configuration, Japanese README, and `SPEC.md` files report historical
  line-length/format findings; no broad formatting rewrite was made here.

## Result

`PARTIAL`. Source/type/fixture checks and local package tarball import passed.
Real-host plugin execution, clean dependency installation, durable memory
readback, and the complete migration-gate inventory remain outstanding.

## Alpha follow-up TODOs

Track these in `feat/opencode-v2`; do not mark the migration `PORT COMPLETE`
until the applicable items have evidence.

- [ ] **OpenCode host test:** Load the packed plugin in OpenCode `2.1.4` and
  exercise selective mode, all-mode, turns, compaction, restart/reconnect, and
  shutdown without modifying the user's global OpenCode configuration.
- [ ] **Clean package install:** Resolve the npm registry failure for
  `@smithy/core@^3.38.0`, then prove a clean consumer install of
  `2.0.0-alpha.1` and retain the install output/digest.
- [ ] **Memory persistence:** Submit a fixture turn through a test gateway
  connected to a controlled ChronosGraph backend, then retrieve the saved memory
  through `memory_search`. HTTP acceptance alone is insufficient.
- [ ] **Migration gates:** Inventory and map G1–G21 and applicable T214 cases
  from `MIGRATION.md`; mark each PASS, FAIL, NOT_RUN, BLOCKED, or reasoned N/A
  with reproducible evidence.
- [ ] **Lifecycle stress:** Exercise stream failure, unload during each I/O
  phase, child termination escalation, and platform-specific cleanup on a
  running V2 host.
- [ ] **Stable release gate:** Complete the applicable host, persistence,
  security, and migration-gate checks before removing the prerelease suffix or
  claiming `PORT COMPLETE`.

## Release status

- Requested alpha: `@yohi/opencode-plugin-chronos-turn-end@2.0.0-alpha.1`.
- GitHub Packages dist-tag: `alpha`.
- Status: published and verified with `npm view` and `npm dist-tag ls`.
- Published tarball integrity: `sha512-FvAb729J+f7KJ[...]AJouOatTaK1qQ==`.
- Commit: `9b22b93` on `feat/opencode-v2`; branch pushed to `origin`.
- The dist-tag `latest` was not changed. The ChronosGraph Python package remains
  at `3.2.1`; no Python package or GitHub Release tag was created.
