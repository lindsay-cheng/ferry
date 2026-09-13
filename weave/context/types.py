"""Distilled session context produced by the parser/distiller.

The parser/distiller owns JSONL parsing and normalization into :class:`ChatContext`.
Downstream merge and synthesizer code must not depend on raw Claude JSONL.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Literal

SCHEMA_VERSION = "1"

Side = Literal["a", "b"]
FileAction = Literal["read", "edit", "create", "delete", "mention"]
CommandOutcome = Literal["success", "failure", "unknown"]
TestOutcome = Literal["pass", "fail", "skip", "unknown"]
TodoStatus = Literal["open", "done", "blocked"]


def _omit_none(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _from_dict(cls: type, data: dict[str, Any]) -> Any:
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass
class Decision:
    id: str
    text: str
    evidence_uuids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {
                "id": self.id,
                "text": self.text,
                "evidence_uuids": self.evidence_uuids or None,
            }
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Decision:
        return _from_dict(cls, data)


@dataclass
class FileRef:
    path: str
    action: FileAction
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _omit_none({"path": self.path, "action": self.action, "note": self.note})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileRef:
        return _from_dict(cls, data)


@dataclass
class CommandRef:
    command: str
    outcome: CommandOutcome = "unknown"
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {"command": self.command, "outcome": self.outcome, "note": self.note}
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CommandRef:
        return _from_dict(cls, data)


@dataclass
class TestRef:
    name: str
    command: str | None = None
    outcome: TestOutcome = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return _omit_none(
            {"name": self.name, "command": self.command, "outcome": self.outcome}
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestRef:
        return _from_dict(cls, data)


@dataclass
class FailedAttempt:
    summary: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return _omit_none({"summary": self.summary, "reason": self.reason})

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FailedAttempt:
        return _from_dict(cls, data)


@dataclass
class TodoItem:
    text: str
    status: TodoStatus = "open"

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "status": self.status}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TodoItem:
        return _from_dict(cls, data)


@dataclass
class ChatContext:
    """Semantic snapshot of one Claude session's active branch."""

    session_id: str
    source_label: str
    leaf_uuid: str
    git_branch: str | None
    summary: str
    decisions: list[Decision] = field(default_factory=list)
    file_refs: list[FileRef] = field(default_factory=list)
    commands: list[CommandRef] = field(default_factory=list)
    tests: list[TestRef] = field(default_factory=list)
    failed_attempts: list[FailedAttempt] = field(default_factory=list)
    todos: list[TodoItem] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    cwd: str | None = None
    goal: str | None = None
    thinking_highlights: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    entry_count: int | None = None
    distilled_at: str | None = None
    model: str | None = None
    claude_version: str | None = None
    parent_session_id: str | None = None
    source_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = _omit_none(
            {
                "schema_version": self.schema_version,
                "session_id": self.session_id,
                "source_label": self.source_label,
                "leaf_uuid": self.leaf_uuid,
                "summary": self.summary,
                "decisions": [d.to_dict() for d in self.decisions],
                "file_refs": [f.to_dict() for f in self.file_refs],
                "commands": [c.to_dict() for c in self.commands],
                "tests": [t.to_dict() for t in self.tests],
                "failed_attempts": [f.to_dict() for f in self.failed_attempts],
                "todos": [t.to_dict() for t in self.todos],
                "cwd": self.cwd,
                "goal": self.goal,
                "thinking_highlights": self.thinking_highlights or None,
                "assumptions": self.assumptions or None,
                "entry_count": self.entry_count,
                "distilled_at": self.distilled_at,
                "model": self.model,
                "claude_version": self.claude_version,
                "parent_session_id": self.parent_session_id,
                "source_path": self.source_path,
            }
        )
        d["git_branch"] = self.git_branch
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatContext:
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            session_id=data["session_id"],
            source_label=data["source_label"],
            leaf_uuid=data["leaf_uuid"],
            git_branch=data.get("git_branch"),
            summary=data["summary"],
            decisions=[Decision.from_dict(d) for d in data.get("decisions", [])],
            file_refs=[FileRef.from_dict(f) for f in data.get("file_refs", [])],
            commands=[CommandRef.from_dict(c) for c in data.get("commands", [])],
            tests=[TestRef.from_dict(t) for t in data.get("tests", [])],
            failed_attempts=[
                FailedAttempt.from_dict(f) for f in data.get("failed_attempts", [])
            ],
            todos=[TodoItem.from_dict(t) for t in data.get("todos", [])],
            cwd=data.get("cwd"),
            goal=data.get("goal"),
            thinking_highlights=list(data.get("thinking_highlights", [])),
            assumptions=list(data.get("assumptions", [])),
            entry_count=data.get("entry_count"),
            distilled_at=data.get("distilled_at"),
            model=data.get("model"),
            claude_version=data.get("claude_version"),
            parent_session_id=data.get("parent_session_id"),
            source_path=data.get("source_path"),
        )
