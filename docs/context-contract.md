# Context contract handoff

Team contract for the merge pipeline. Types live in `weave/context/types.py`, `weave/merge/types.py`, and `weave/merge/protocols.py`.

## Data flow

```
Claude JSONL session A  ──► parser/distiller ──► ChatContext A ──┐
Claude JSONL session B  ──► parser/distiller ──► ChatContext B ──┤
                                                                  ├──► Cerebras merge ──► MergedContext
                                                                  │                              │
                                                                  │                              ▼
                                                                  │                    synthesizer/writer
                                                                  │                              │
                                                                  │                              ▼
                                                                  │                    transcript_api specs
                                                                  │                              │
                                                                  │                              ▼
                                                                  │                    target session JSONL
```

Each stage owns one transformation. Downstream code must not skip layers (e.g. merge must not read JSONL; synthesizer must not call Cerebras).

---

## Parser / distiller

**Owns:** JSONL → `ChatContext`

**Must do**

- Parse Claude JSONL (may use `transcript_api.from_text` / `linearize` for the active branch only).
- Emit one `ChatContext` per session via `ChatContext.to_dict()` or the dataclass directly.
- Distill signal, not raw noise: summaries, decisions, `file_refs`, commands, tests, failed attempts, todos.
- Set `leaf_uuid` to the active-branch leaf (abandoned forks excluded).
- Set `git_branch` explicitly (`null` if unknown — key must be present in JSON).

**Must not do**

- Call Cerebras or produce `MergedContext`.
- Write JSONL files.
- Import private `transcript` (use `transcript_api` if JSONL helpers are needed).

---

## Cerebras merge

**Owns:** `ChatContext` + `ChatContext` → `MergedContext`

**Must do**

- Implement `ContextMerger` (`weave/merge/protocols.py`).
- Return semantic merge output: summary, decisions, conflicts, assumptions, todos, `file_refs`, rerun lists, `bootstrap_prompt`, `sources`.
- Attribute decisions with `sources: ["a"]`, `["b"]`, or `["a", "b"]` — never `"both"`.
- Populate `SourceRef` with `side`, `source_label`, `session_id`, `git_branch`, `leaf_uuid`.
- Accept optional `feedback` for reprompt loops.

**Must not do**

- Write files or emit raw Claude JSONL.
- Import private `transcript`.
- Build `transcript_api` specs (that is synthesizer work).

---

## Synthesizer / writer

**Owns:** `MergedContext` → `transcript_api` specs → edited entry list

**Must do**

- Read `MergedContext` (including `bootstrap_prompt`, structured lists, and conflicts).
- Turn merged semantics into `transcript_api` create/update specs (`message`, `tool_call` grammar — see `transcript_api` docstring).
- Apply specs via `transcript_api` only (`create_at_end`, etc.).
- Handle `cwd` / session metadata rewrite at write time (outside merge layer).

**Must not do**

- Parse raw JSONL for merge logic or call Cerebras.
- Import private `transcript`.

---

## `ChatContext` guarantees

Parser output must satisfy:

| Guarantee | Detail |
|-----------|--------|
| Schema | `schema_version: "1"` |
| Required fields | `session_id`, `source_label`, `leaf_uuid`, `git_branch`, `summary`, `decisions`, `file_refs`, `commands`, `tests`, `failed_attempts`, `todos` |
| `git_branch` | Key always present; value may be `null` |
| Active branch only | `leaf_uuid` and evidence refer to the linearized active branch |
| No JSONL inside | Distilled records only |
| Serializable | `ChatContext.from_dict(ctx.to_dict())` round-trips |
| Deterministic | Same JSONL input → same context (except optional `distilled_at`) |

Reference: `weave/context/types.py`, tests in `test_context_types.py`.

---

## `MergedContext` guarantees

Merge output must satisfy:

| Guarantee | Detail |
|-----------|--------|
| Schema | `schema_version: "1"` |
| Required fields | `merged_summary`, `decisions`, `conflicts`, `assumptions`, `unresolved_todos`, `file_refs`, `commands_to_rerun`, `tests_to_rerun`, `bootstrap_prompt`, `sources` |
| Not JSONL | Semantic merge artifact only |
| Provenance | Each `SourceRef` identifies side `a` or `b` with session metadata |
| `bootstrap_prompt` | Non-empty seed text for the synthesizer's first user message(s) |
| Serializable | `MergedContext.from_dict(ctx.to_dict())` round-trips |

Reference: `weave/merge/types.py`, example fixture at `fixtures/merge/merged_context_minimal.json`, tests in `test_merge_types.py`.

---

## Example snippets

### Load `ChatContext`

```python
import json
from weave.context.types import ChatContext

with open("fixtures/context/chat_context_a.json") as f:
    context_a = ChatContext.from_dict(json.load(f))
```

### Call `ContextMerger.merge`

```python
from weave.context.types import ChatContext
from weave.merge.types import MergedContext

# cerebras_merger implements ContextMerger (future)
merged: MergedContext = cerebras_merger.merge(context_a, context_b)

# Reprompt after rejection
merged = cerebras_merger.merge(context_a, context_b, feedback="Keep session B's redirect URL.")
```

### Consume `bootstrap_prompt` (synthesizer)

```python
import transcript_api as tx
from weave.merge.types import MergedContext

def seed_transcript(entries: list, merged: MergedContext) -> tuple[list, list]:
    entries, created = tx.create_at_end(
        entries,
        {"type": "message", "role": "user", "content": merged.bootstrap_prompt},
    )
    return entries, created
```

The synthesizer may also use `merged_summary`, `decisions`, `conflicts`, and rerun lists to build additional specs — but always through `transcript_api`, never by writing JSONL strings directly from merge output.

---

## Non-goals

- **No direct `transcript.py` imports** — use `transcript_api` in synthesizer/CLI only.
- **No raw JSONL from Cerebras** — merge returns `MergedContext`, not Claude entry dicts.
- **No file writes from the merge layer** — Cerebras code is in-memory transform only; parser and synthesizer own I/O at their boundaries.
