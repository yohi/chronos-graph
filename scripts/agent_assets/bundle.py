from __future__ import annotations

import hashlib
import stat
from pathlib import Path

from agent_assets.models import AssetBundle, IngestionMode


class AssetValidationError(RuntimeError):
    """Raised when the repository-owned Agent asset tree is malformed."""


def compute_bundle_digest(asset_root: Path) -> str:
    """Return the deterministic digest for all validated regular SSOT files."""
    digest = hashlib.sha256()
    candidates = sorted(
        asset_root.rglob("*"),
        key=lambda candidate: candidate.relative_to(asset_root).as_posix(),
    )
    for candidate in candidates:
        metadata = candidate.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise AssetValidationError(candidate, "symlink")
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise AssetValidationError(candidate, "unsupported-file-type")
        relative_path = candidate.relative_to(asset_root).as_posix().encode("utf-8")
        content = candidate.read_bytes()
        digest.update(len(relative_path).to_bytes(8, "big"))
        digest.update(relative_path)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def build_bundle(asset_root: Path) -> AssetBundle:
    """Validate the repository-owned asset tree and return its bundle."""
    digest = compute_bundle_digest(asset_root)
    template = (asset_root / "minimal-instructions.md").read_bytes()
    recall_root = asset_root / "skills" / "chronos-memory-recall"
    save_root = asset_root / "skills" / "chronos-memory-save"
    return AssetBundle(
        root=asset_root,
        digest=digest,
        minimal_template=template,
        skill_roots=(recall_root, save_root),
    )


_MODE_RULES: dict[IngestionMode, bytes] = {
    IngestionMode.SELECTIVE: (
        b"In selective mode, load and follow `chronos-memory-save` when its save trigger applies."
    ),
    IngestionMode.ALL: (
        b"In all mode, do not call `memory_save` or `session_flush`; "
        b"turn-end ingestion owns saving."
    ),
}


def render_managed_block(bundle: AssetBundle, mode: IngestionMode) -> bytes:
    """Render the managed instruction block with the current bundle digest."""
    rule = _MODE_RULES[mode]
    rendered: bytes = (
        bundle.minimal_template.replace(b"{{BUNDLE_SHA256}}", bundle.digest.encode("ascii"))
        .replace(b"{{INGESTION_MODE}}", mode.value.encode("ascii"))
        .replace(b"{{SAVE_MODE_RULE}}", rule)
    )
    return rendered
