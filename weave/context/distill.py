"""Tolerant JSONL → :class:`ChatContext` distillation for merge."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from weave.context.types import (
    ChatContext,
    CommandRef,
    CommandOutcome,
    FailedAttempt,
    FileRef,
    TestOutcome,
    TestRef,
)

_MAX_SUMMARY_CHARS = 16_000
_MAX_HIGHLIGHTS = 15
_MAX_HIGHLIGHT_CHARS = 800
_MAX_TOOL_RESULT_SNIPPET = 400
_MAX_GOAL_CHARS = 300

_FILE_TOOL_NAMES = frozenset({"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"})
_BASH_TOOL_NAMES = frozenset({"Bash", "Shell"})

_TEST_COMMAND_RE = re.compile(
    r"\b(pytest|npm test|pnpm test|yarn test|go test|cargo test|make test)\b",
    re.IGNORECASE,
)
_FAILURE_HINT_RE = re.compile(
    r"(error|failed|failure|traceback|exit code [1-9]|command not found|exception)",
    re.IGNORECASE,
)


@dataclass
class DistillResult:
    context: ChatContext
    warnings: list[str]


def distill_from_jsonl(
    text: str,
    *,
    source_label: str,
    source_path: str,
    max_summary_messages: int = 20,
) -> DistillResult:
    """Parse Claude Code JSONL into a :class:`ChatContext` with transcript signal."""
    warnings: list[str] = []
    entries_with_uuid: list[dict] = []

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            entry = json.loads(stripped)
        except json.JSONDecodeError:
            warnings.append(f"line {line_no}: invalid JSON, skipped")
            continue
        if not isinstance(entry, dict):
            warnings.append(f"line {line_no}: expected JSON object, skipped")
            continue
        if entry.get("uuid"):
            entries_with_uuid.append(entry)

    branch = _linearize_active_branch(entries_with_uuid)
    if not branch:
        raise ValueError(f"no uuid-bearing chat history in {source_path!r}")

    leaf = branch[-1]
    session_id = leaf.get("sessionId") or Path(source_path).stem
    leaf_uuid = leaf["uuid"]
    git_branch = leaf.get("gitBranch")
    cwd = leaf.get("cwd")

    tool_results = _index_tool_results(branch)
    thinking_highlights = _extract_thinking_highlights(branch)
    file_refs = _extract_file_refs(branch, tool_results)
    commands = _extract_commands(branch, tool_results)
    tests = _extract_tests(branch, commands)
    failed_attempts = _extract_failed_attempts(branch, tool_results)
    goal = _extract_goal(branch)
    model, claude_version = _extract_model_metadata(branch)

    summary = _build_summary(
        branch,
        goal=goal,
        max_messages=max_summary_messages,
        tool_results=tool_results,
    )

    context = ChatContext(
        session_id=session_id,
        source_label=source_label,
        leaf_uuid=leaf_uuid,
        git_branch=git_branch,
        summary=summary,
        file_refs=file_refs,
        commands=commands,
        tests=tests,
        failed_attempts=failed_attempts,
        thinking_highlights=thinking_highlights,
        goal=goal,
        cwd=cwd,
        entry_count=len(branch),
        model=model,
        claude_version=claude_version,
        source_path=source_path,
    )
    return DistillResult(context=context, warnings=warnings)


def _linearize_active_branch(entries_with_uuid: list[dict]) -> list[dict]:
    """Active branch: last-appended uuid entry is leaf, walk parentUuid to root."""
    if not entries_with_uuid:
        return []

    by_uuid = {entry["uuid"]: entry for entry in entries_with_uuid}
    leaf = entries_with_uuid[-1]
    path: list[dict] = []
    seen: set[str] = set()
    cur: dict | None = leaf
    while cur is not None and cur.get("uuid") not in seen:
        seen.add(cur["uuid"])
        path.append(cur)
        parent_uuid = cur.get("parentUuid")
        cur = by_uuid.get(parent_uuid) if parent_uuid else None
    path.reverse()
    return path


def _content_blocks(content: object) -> list[dict]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _truncate(text: str, max_len: int) -> str:
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _index_tool_results(branch: list[dict]) -> dict[str, str]:
    """Map tool_use id → tool_result content text across the active branch."""
    results: dict[str, str] = {}
    for entry in branch:
        msg = entry.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        for block in _content_blocks(msg.get("content")):
            if block.get("type") != "tool_result":
                continue
            tool_id = block.get("tool_use_id")
            if not isinstance(tool_id, str):
                continue
            content = block.get("content")
            if isinstance(content, str):
                results[tool_id] = content
            elif isinstance(content, list):
                results[tool_id] = _message_text(content)
    return results


def _classify_outcome(result_text: str | None) -> CommandOutcome:
    if not result_text:
        return "unknown"
    if _FAILURE_HINT_RE.search(result_text):
        return "failure"
    return "success"


def _message_text(content: object) -> str:
    parts: list[str] = []
    for block in _content_blocks(content):
        if block.get("type") == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
    return " ".join(parts)


def _extract_goal(branch: list[dict]) -> str | None:
    for entry in branch:
        msg = entry.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        text = _message_text(msg.get("content"))
        if text.strip():
            return _truncate(text.strip(), _MAX_GOAL_CHARS)
    return None


def _extract_model_metadata(branch: list[dict]) -> tuple[str | None, str | None]:
    model: str | None = None
    claude_version: str | None = None
    for entry in reversed(branch):
        if model is None and isinstance(entry.get("model"), str):
            model = entry["model"]
        if claude_version is None and isinstance(entry.get("version"), str):
            claude_version = entry["version"]
        if model and claude_version:
            break
    return model, claude_version


def _extract_thinking_highlights(branch: list[dict]) -> list[str]:
    highlights: list[str] = []
    for entry in branch:
        msg = entry.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for block in _content_blocks(msg.get("content")):
            if block.get("type") != "thinking":
                continue
            thinking = block.get("thinking")
            if isinstance(thinking, str) and thinking.strip():
                highlights.append(_truncate(thinking.strip(), _MAX_HIGHLIGHT_CHARS))
                if len(highlights) >= _MAX_HIGHLIGHTS:
                    return highlights
    return highlights


def _format_tool_use(block: dict, tool_results: dict[str, str]) -> str:
    name = block.get("name", "tool")
    tool_id = block.get("id")
    inp = block.get("input")
    detail = ""
    if isinstance(inp, dict):
        if name in _BASH_TOOL_NAMES:
            detail = inp.get("command", "")
        elif name in _FILE_TOOL_NAMES:
            detail = inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""
        else:
            detail = json.dumps(inp, ensure_ascii=False, separators=(",", ":"))
    line = f"  [tool {name}] {_truncate(str(detail), 300)}"
    if isinstance(tool_id, str) and tool_id in tool_results:
        snippet = _truncate(tool_results[tool_id], _MAX_TOOL_RESULT_SNIPPET)
        line += f"\n  [tool_result] {snippet}"
    return line


def _format_entry_excerpt(entry: dict, tool_results: dict[str, str]) -> list[str]:
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return []

    role = msg.get("role", "?")
    uuid = entry.get("uuid", "?")
    lines: list[str] = [f"[{role}|{uuid}]"]

    if role == "user":
        tool_only = True
        for block in _content_blocks(msg.get("content")):
            if block.get("type") == "tool_result":
                tool_id = block.get("tool_use_id", "?")
                snippet = _truncate(
                    tool_results.get(tool_id, str(block.get("content", ""))),
                    _MAX_TOOL_RESULT_SNIPPET,
                )
                lines.append(f"  [tool_result|{tool_id}] {snippet}")
            elif block.get("type") == "text":
                tool_only = False
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    lines.append(f"  {_truncate(text.strip(), 500)}")
        if tool_only and len(lines) == 1:
            return []
        return lines

    if role != "assistant":
        return []

    text = _message_text(msg.get("content"))
    if text.strip():
        lines.append(f"  {_truncate(text.strip(), 500)}")

    for block in _content_blocks(msg.get("content")):
        if block.get("type") == "thinking":
            thinking = block.get("thinking")
            if isinstance(thinking, str) and thinking.strip():
                lines.append(f"  [thinking] {_truncate(thinking.strip(), 400)}")
        elif block.get("type") == "tool_use":
            lines.append(_format_tool_use(block, tool_results))

    return lines


def _build_summary(
    branch: list[dict],
    *,
    goal: str | None,
    max_messages: int,
    tool_results: dict[str, str],
) -> str:
    """Structured transcript excerpt: roles, thinking, tools, and results."""
    sections: list[str] = []
    if goal:
        sections.append(f"Goal: {goal}")

    excerpt_lines: list[str] = []
    for entry in branch:
        excerpt_lines.extend(_format_entry_excerpt(entry, tool_results))

    if max_messages > 0 and len(excerpt_lines) > max_messages * 4:
        head = excerpt_lines[: max_messages * 2]
        tail = excerpt_lines[-max_messages * 2 :]
        excerpt_lines = head + ["  ...", "  [transcript truncated for length]"] + tail

    if excerpt_lines:
        sections.append("Transcript excerpt:")
        sections.extend(excerpt_lines)

    summary = "\n".join(sections).strip()
    if len(summary) > _MAX_SUMMARY_CHARS:
        summary = summary[: _MAX_SUMMARY_CHARS - 3] + "..."
    return summary or "(no message content in active branch)"


def _extract_file_refs(
    branch: list[dict], tool_results: dict[str, str]
) -> list[FileRef]:
    seen: set[str] = set()
    refs: list[FileRef] = []
    for entry in branch:
        msg = entry.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for block in _content_blocks(msg.get("content")):
            if block.get("type") != "tool_use":
                continue
            name = block.get("name")
            if name not in _FILE_TOOL_NAMES:
                continue
            inp = block.get("input")
            if not isinstance(inp, dict):
                continue
            path = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
            if not isinstance(path, str) or not path or path in seen:
                continue
            seen.add(path)
            if name == "Read":
                action = "read"
            elif name == "Write":
                action = "create" if inp.get("content") else "edit"
            else:
                action = "edit"
            note: str | None = None
            tool_id = block.get("id")
            if isinstance(tool_id, str) and tool_id in tool_results:
                note = _truncate(tool_results[tool_id], 200)
            refs.append(FileRef(path=path, action=action, note=note))
    return refs


def _extract_commands(
    branch: list[dict], tool_results: dict[str, str]
) -> list[CommandRef]:
    seen: set[str] = set()
    commands: list[CommandRef] = []
    for entry in branch:
        msg = entry.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for block in _content_blocks(msg.get("content")):
            if block.get("type") != "tool_use":
                continue
            if block.get("name") not in _BASH_TOOL_NAMES:
                continue
            inp = block.get("input")
            if not isinstance(inp, dict):
                continue
            command = inp.get("command")
            if not isinstance(command, str) or not command or command in seen:
                continue
            seen.add(command)
            tool_id = block.get("id")
            result_text = tool_results.get(tool_id) if isinstance(tool_id, str) else None
            outcome = _classify_outcome(result_text)
            note = _truncate(result_text, 200) if result_text else None
            commands.append(CommandRef(command=command, outcome=outcome, note=note))
    return commands


def _extract_tests(
    branch: list[dict], commands: list[CommandRef]
) -> list[TestRef]:
    seen: set[str] = set()
    tests: list[TestRef] = []
    for cmd in commands:
        if not _TEST_COMMAND_RE.search(cmd.command):
            continue
        name = cmd.command.strip().split()[-1] if cmd.command.strip() else cmd.command
        if name in seen:
            continue
        seen.add(name)
        outcome: TestOutcome = "unknown"
        if cmd.outcome == "success":
            outcome = "pass"
        elif cmd.outcome == "failure":
            outcome = "fail"
        tests.append(TestRef(name=name, command=cmd.command, outcome=outcome))
    return tests


def _extract_failed_attempts(
    branch: list[dict], tool_results: dict[str, str]
) -> list[FailedAttempt]:
    attempts: list[FailedAttempt] = []
    seen: set[str] = set()
    for entry in branch:
        msg = entry.get("message")
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for block in _content_blocks(msg.get("content")):
            if block.get("type") != "tool_use":
                continue
            tool_id = block.get("id")
            if not isinstance(tool_id, str):
                continue
            result_text = tool_results.get(tool_id)
            if not result_text or not _FAILURE_HINT_RE.search(result_text):
                continue
            name = block.get("name", "tool")
            inp = block.get("input") if isinstance(block.get("input"), dict) else {}
            detail = inp.get("command") or inp.get("file_path") or inp.get("path") or name
            summary = f"{name}: {_truncate(str(detail), 120)}"
            key = summary.casefold()
            if key in seen:
                continue
            seen.add(key)
            attempts.append(
                FailedAttempt(
                    summary=summary,
                    reason=_truncate(result_text, 300),
                )
            )
    return attempts
