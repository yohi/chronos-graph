# Secure Setup and Migration Design

## Goal

Make the documented remote setup reproducible and verifiable, prevent dry-run
from requesting secrets, and ensure dimension mismatch recovery preserves data.

## Decisions

1. Remote setup uses a full commit SHA archive URL for both the bootstrap
   tarball and the generated `uvx --from` source. The generic `--uv-from`
   option remains flexible for local and development use.
2. The release workflow downloads the commit archive, publishes its SHA-256
   checksum as a release asset, and the setup protocol verifies that checksum
   before extraction and bootstrap execution.
3. The English and Japanese setup protocols explicitly gate Phase 6 to
   production. Dry-run proceeds directly to the existing Phase 7 plan, digest,
   and diagnostics checks.
4. Supabase setup writes the collected URL to `SUPABASE_URL` in `.env`, then
   regenerates `mcp_config.json` after `.env` values are complete when the
   generated file is registered with an MCP client.
5. Dimension mismatch recovery points to `docs/migration.md` and describes
   retaining the old column, re-embedding into a new column, validating all
   rows, and switching only after validation. The matching-dimension branch is
   unchanged.

## Scope

The implementation changes the English and Japanese setup protocols, both
README release examples, the release workflow, the orchestrator recovery
message, and its unit test. No storage schema or generic package-source
behavior changes.

## Verification

Run the focused orchestrator tests, the full unit test suite, Ruff checks and
format verification, Markdown checks if available, YAML syntax validation, and
shell syntax validation. Confirm the final diff contains no credentials and
that the branch is pushed successfully.
