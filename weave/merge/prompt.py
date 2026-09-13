"""Prompt construction for the text-briefing merge layer.

Branch turns are rendered as lean text -- role plus text/thinking plus tool
calls with truncated I/O -- rather than dumping the raw JSONL entries. The raw
entries carry a heavy envelope (uuid/parentUuid/sessionId/cwd/timestamp on every
turn, nested JSON, ``"``-escaping) that can be ~7x the actual conversation; for
a briefing the model only needs what was said and done, so we drop the plumbing
and trim bulky tool inputs/results to keep the prompt small.
"""

from __future__ import annotations

import json

from weave.context.types import ChatContext

# Tool inputs/results are evidence of actions, not data to reproduce -- cap them.
_TOOL_INPUT_CHAR_LIMIT = 200
_RESULT_CHAR_LIMIT = 200


def _truncate(value, limit: int) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...[+{len(text) - limit} chars elided]"


def _render_block(role: str, block: dict, lines: list[str]) -> None:
    ty = block.get("type")
    if ty == "text":
        lines.append(f"{role}: {block.get('text', '')}")
    elif ty == "thinking":
        lines.append(f"{role} (thinking): {block.get('thinking') or block.get('text', '')}")
    elif ty == "tool_use":
        args = _truncate(block.get("input", {}), _TOOL_INPUT_CHAR_LIMIT)
        lines.append(f"  > tool {block.get('name', '?')}({args})")
    elif ty == "tool_result":
        lines.append(f"  < result {_truncate(block.get('content', ''), _RESULT_CHAR_LIMIT)}")


def _render_turns(entries: list[dict]) -> str:
    """Render raw transcript entries as lean text, dropping the JSONL envelope."""
    lines: list[str] = []
    for entry in entries:
        msg = entry.get("message") or {}
        role = msg.get("role") or entry.get("type", "?")
        content = msg.get("content")
        if isinstance(content, str):
            lines.append(f"{role}: {content}")
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    _render_block(role, block, lines)
    return "\n".join(lines)


def build_merge_prompt(
    shared_context: ChatContext | None,
    a_branch: list[dict],
    b_branch: list[dict],
) -> str:
    """Serialize the shared background + both rendered branches into a briefing prompt."""
    shared_block = (
        json.dumps(shared_context.to_dict(), sort_keys=True)
        if shared_context is not None
        else "(none -- the two sessions share no history)"
    )
    sections = [
        "You are merging two Claude Code sessions into a single unified briefing.",
        "",
        "You will receive up to three inputs:",
        "  BASE: the shared context before the two sessions diverged (may be absent)",
        "  SESSION A: one branch of work",
        "  SESSION B: another branch of work",
        "",
        "Your output is plain text. It will be injected into a new Claude Code",
        "session as the content of a synthetic file read. The next engineer will",
        "resume from this context as their starting point.",
        "",
        "═══════════════════════════════════════",
        "YOUR OUTPUT MUST COVER IN ORDER",
        "═══════════════════════════════════════",
        "",
        "1. GOAL",
        "   What were both sessions trying to accomplish.",
        "   Use the base context if present. Be specific.",
        "",
        "2. SHARED CONTEXT",
        "   What was already known or established before the branches diverged.",
        "   Only include if base context is present.",
        "",
        "3. SESSION A — what happened",
        "   What was tried, in the order it happened.",
        "   What worked and why.",
        "   What failed and why.",
        "   What decisions were made and the reasoning behind them.",
        "",
        "4. SESSION B — what happened",
        "   Same structure as session A.",
        "",
        "5. CONFLICTS",
        "   Anywhere the two sessions reached different conclusions,",
        "   tried different approaches, or left the codebase in",
        "   different states. Name each conflict explicitly.",
        "   Do not resolve conflicts. Surface them.",
        "",
        "6. CURRENT STATE",
        "   What is the current understood state of each relevant file",
        "   or component based on the most recent work in either session.",
        "   If session B edited something session A read, use session B's",
        "   version as the current state.",
        "",
        "7. UNRESOLVED",
        "   Every open question from either session.",
        "   Do not answer them. List them exactly as they were left.",
        "",
        "8. NEXT STEPS",
        "   What the next engineer should do first based on everything above.",
        "   Be specific. Reference file names and line numbers where relevant.",
        "",
        "═══════════════════════════════════════",
        "RULES",
        "═══════════════════════════════════════",
        "",
        "THINKING BLOCKS",
        "When either session contains a thinking block, reproduce it verbatim",
        "under the relevant section. Do not summarize or paraphrase thinking.",
        "Label it clearly:",
        "  [THINKING - Session A] <exact text>",
        "",
        "FAILURES",
        "Every failed attempt must appear in the output.",
        "A dead end is not noise. It is critical context.",
        "The next engineer must know what not to try and why.",
        "",
        "CONFLICTS",
        "Do not silently resolve disagreements between sessions.",
        "Do not pick a side. Name the conflict explicitly:",
        "  CONFLICT: Session A did X because [reason].",
        "             Session B did Y because [reason].",
        "             Resolution needed.",
        "",
        "NO INVENTION",
        "Do not add context that is not in either session.",
        "Do not infer what probably happened.",
        "Do not fill gaps.",
        "Do not answer unresolved questions.",
        "Reproduce uncertainty as uncertainty.",
        "",
        "TOOL RESULTS",
        "If both sessions read the same file and got the same content,",
        "summarize it once. Do not repeat it twice.",
        "If the content differed between sessions, note the discrepancy",
        "and use the most recent version as current state.",
        "",
        "BASE:",
        shared_block,
        "",
        "SESSION A:",
        _render_turns(a_branch),
        "",
        "SESSION B:",
        _render_turns(b_branch),
    ]
    return "\n".join(sections)
