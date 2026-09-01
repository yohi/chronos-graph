from __future__ import annotations

import hashlib
import stat
from pathlib import Path
from typing import Final

from agent_assets.models import (
    MANAGED_SKILL_SENTINEL,
    AssetBundle,
    IngestionMode,
    SafeDiagnostic,
)

_REQUIRED_TEMPLATE_TOKENS: Final = (
    b"{{BUNDLE_SHA256}}",
    b"{{INGESTION_MODE}}",
    b"{{SAVE_MODE_RULE}}",
)
_REQUIRED_SKILL_NAMES: Final = (
    "chronos-memory-recall",
    "chronos-memory-save",
)


class AssetValidationError(RuntimeError):
    """Raised when the repository-owned Agent asset tree is malformed."""

    path: Path
    code: str

    def __init__(self, path: Path, code: str) -> None:
        self.path = path
        self.code = code
        super().__init__(code)

    def diagnostic(self) -> SafeDiagnostic:
        return SafeDiagnostic("preflight", "reject", self.path, self.code)


def _require_directory(path: Path, code: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        raise AssetValidationError(path, f"{code}-missing") from None
    if stat.S_ISLNK(mode):
        raise AssetValidationError(path, f"{code}-symlink")
    if not stat.S_ISDIR(mode):
        raise AssetValidationError(path, f"{code}-not-directory")


def _read_required_regular_file(path: Path, code: str) -> bytes:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        raise AssetValidationError(path, f"{code}-missing") from None
    if stat.S_ISLNK(mode):
        raise AssetValidationError(path, f"{code}-symlink")
    if not stat.S_ISREG(mode):
        raise AssetValidationError(path, f"{code}-not-regular")
    return path.read_bytes()


def _validate_template(path: Path) -> bytes:
    template = _read_required_regular_file(path, "asset-template")
    for token in _REQUIRED_TEMPLATE_TOKENS:
        if template.count(token) != 1:
            raise AssetValidationError(path, "asset-template-render-token")
    without_tokens = template
    for token in _REQUIRED_TEMPLATE_TOKENS:
        without_tokens = without_tokens.replace(token, b"")
    if b"{{" in without_tokens or b"}}" in without_tokens:
        raise AssetValidationError(path, "asset-template-render-token")
    return template


def _validate_skill_frontmatter(document: bytes, path: Path, skill_name: str) -> None:
    lines = document.splitlines()
    if not lines or lines[0] != b"---":
        raise AssetValidationError(path, "asset-skill-frontmatter")
    try:
        end = lines.index(b"---", 1)
    except ValueError:
        raise AssetValidationError(path, "asset-skill-frontmatter") from None

    frontmatter = lines[1:end]
    expected_name = b"name: " + skill_name.encode("utf-8")
    descriptions = tuple(
        line.removeprefix(b"description: ").strip()
        for line in frontmatter
        if line.startswith(b"description: ")
    )
    if frontmatter.count(expected_name) != 1 or len(descriptions) != 1 or not descriptions[0]:
        raise AssetValidationError(path, "asset-skill-frontmatter")


def _validate_skill_source(root: Path, skill_name: str) -> None:
    _require_directory(root, "asset-skill")
    document_path = root / "SKILL.md"
    document = _read_required_regular_file(document_path, "asset-skill-document")
    _validate_skill_frontmatter(document, document_path, skill_name)
    sentinel = _read_required_regular_file(root / ".chronosgraph-managed", "asset-skill-sentinel")
    if sentinel != MANAGED_SKILL_SENTINEL:
        raise AssetValidationError(root / ".chronosgraph-managed", "asset-skill-sentinel-content")


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
    _require_directory(asset_root, "asset-root")
    skills_root = asset_root / "skills"
    _require_directory(skills_root, "asset-skills-root")
    template = _validate_template(asset_root / "minimal-instructions.md")
    recall_root = skills_root / _REQUIRED_SKILL_NAMES[0]
    save_root = skills_root / _REQUIRED_SKILL_NAMES[1]
    _validate_skill_source(recall_root, _REQUIRED_SKILL_NAMES[0])
    _validate_skill_source(save_root, _REQUIRED_SKILL_NAMES[1])
    digest = compute_bundle_digest(asset_root)
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
