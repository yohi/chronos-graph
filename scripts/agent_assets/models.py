from __future__ import annotations

import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final, Literal


class AgentId(StrEnum):
    CLAUDECODE = "claudecode"
    CODEX = "codex"
    OPENCODE = "opencode"


class IngestionMode(StrEnum):
    SELECTIVE = "selective"
    ALL = "all"


class ExecutionMode(StrEnum):
    PRODUCTION = "production"
    DRY_RUN = "dry-run"


class PlannedAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    UNCHANGED = "unchanged"
    CONFLICT = "conflict"


class SnapshotKind(StrEnum):
    DIRECTORY = "directory"
    FILE = "file"
    SYMLINK = "symlink"


CANONICAL_AGENT_ORDER: Final = (
    AgentId.CLAUDECODE,
    AgentId.CODEX,
    AgentId.OPENCODE,
)


@dataclass(frozen=True, slots=True)
class AgentAdapter:
    agent_id: AgentId
    skills_root: Path
    instructions_path: Path
    instructions_root: Path


@dataclass(frozen=True, slots=True)
class SyncRequest:
    command: Literal["canonicalize", "sync"]
    repo_root: Path
    home: Path
    mode: ExecutionMode
    ingestion_mode: IngestionMode
    agent_ids: tuple[AgentId, ...]


@dataclass(frozen=True, slots=True)
class AssetBundle:
    root: Path
    digest: str
    minimal_template: bytes
    skill_roots: tuple[Path, Path]


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    path: Path
    kind: SnapshotKind
    fingerprint: str


@dataclass(frozen=True, slots=True)
class PlannedTarget:
    path: Path
    action: PlannedAction
    snapshots: tuple[TargetSnapshot, ...]
    content: bytes | None = None


@dataclass(frozen=True, slots=True)
class SafeDiagnostic:
    phase: str
    action: str
    path: Path
    mismatch: str

    def render(self) -> str:
        """Render a deterministic diagnostic without target content."""
        return f"{self.phase}:{self.action}:{self.path}:{self.mismatch}"


@dataclass(frozen=True, slots=True)
class SyncPlan:
    request: SyncRequest
    bundle: AssetBundle
    targets: tuple[PlannedTarget, ...]
    diagnostics: tuple[SafeDiagnostic, ...]
    snapshots: tuple[TargetSnapshot, ...] = ()


class AgentSelectionError(RuntimeError):
    """Raised when raw `--agents` input cannot become a supported canonical set."""


def validate_command(value: str) -> Literal["canonicalize", "sync"]:
    """Return the canonical command name or exit with a parser error."""
    if value in ("canonicalize", "sync"):
        return value  # type: ignore[return-value]
    print(f"unknown-command:{value}", file=sys.stderr)
    sys.exit(2)


def parse_agent_csv(raw: str) -> tuple[AgentId, ...]:
    """Parse one comma-separated CLI value into canonical supported Agent IDs."""
    values = tuple(piece.strip() for piece in raw.split(","))
    if not values or any(not value for value in values):
        raise AgentSelectionError("invalid-agent-selection")

    requested: set[AgentId] = set()
    for value in values:
        match value:
            case "claudecode":
                requested.add(AgentId.CLAUDECODE)
            case "codex":
                requested.add(AgentId.CODEX)
            case "opencode":
                requested.add(AgentId.OPENCODE)
            case _:
                raise AgentSelectionError("unsupported-agent")

    return tuple(agent for agent in CANONICAL_AGENT_ORDER if agent in requested)


def adapter_for(agent_id: AgentId, home: Path) -> AgentAdapter:
    """Return the canonical global paths for one supported Agent."""
    match agent_id:
        case AgentId.CLAUDECODE:
            instructions_root = home / ".claude"
            instructions_path = instructions_root / "CLAUDE.md"
        case AgentId.CODEX:
            instructions_root = home / ".agents"
            instructions_path = instructions_root / "AGENTS.md"
        case AgentId.OPENCODE:
            instructions_root = home / ".config" / "opencode"
            instructions_path = instructions_root / "AGENTS.md"

    skills_root = instructions_root / "skills"
    return AgentAdapter(
        agent_id=agent_id,
        skills_root=skills_root,
        instructions_path=instructions_path,
        instructions_root=instructions_root,
    )
