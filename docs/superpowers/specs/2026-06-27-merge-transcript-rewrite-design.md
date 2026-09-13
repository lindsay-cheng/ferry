# Weave merge: shared-prefix detection + transcript rewrite

**Date:** 2026-06-27
**Status:** Approved design, pending implementation plan
**Topic:** Replace the semantic-sidecar merge with a transcript-level merge that produces a resumable cloned session.

---

## Problem

`weave merge` today does not produce a resumable session. `core.merge_contexts(source_a, source_b)`:

1. Distills each JSONL independently into a `ChatContext` (a semantic snapshot; raw message/uuid structure is discarded).
2. Makes one Cerebras call that dumps both `ChatContext`s as JSON and asks for one `MergedContext` back.
3. Writes a sidecar JSON to `.weave/merged/<id>.json`, explicitly flagged `claude_jsonl_compatible: false`.

There is no shared-prefix detection, no A-branch / B-branch separation, and no JSONL rewrite. The output cannot be resumed with `claude --resume`.

## Goal

Merge two sessions at the **raw transcript level** into a new, resumable cloned session:

- Keep the **shared prefix** (the turns the two sessions have in common) verbatim.
- Send the shared prefix plus each session's divergent **branch** to Cerebras and get back a single **briefing document** unifying the two branches.
- On a **clone** of one source, **delete** the branch and **splice in** a synthetic `Read` tool cycle whose `tool_result` carries the briefing text.
- Write the clone as a new session JSONL under `~/.claude`, with a fresh id and machine-local `cwd`/`sessionId`, so it resumes immediately.

Both source sessions are left untouched (non-destructive).

## Non-goals (YAGNI)

- Reprompt / feedback loop (the `feedback` parameter is dropped from the new path).
- Structured conflict modeling or any output schema — the merge output is plain briefing text.
- The `--into <session-id>` flag.
- Writing files from the merge layer. The merge layer is pure and read-only.

---

## Decisions (resolved during brainstorming)

| # | Decision |
|---|----------|
| Match rule | **Longest common prefix on content equality.** Compare role + textual content (and tool name/input/result for tool cycles), ignoring `uuid`/`parentUuid`/`sessionId`/`cwd`/`timestamp`. Stop at the first mismatch; that is the branch point. |
| Payload form | **Branches raw, shared distilled.** A-branch and B-branch are sent as raw transcript turns; the shared prefix is sent as a compact distilled summary for background. |
| Output shape | **Single briefing document (text).** Cerebras returns one prose/markdown briefing. No schema, no validator. |
| Injection | The briefing text is passed **as the `result` parameter** of a `tool_call` spec to `weave.transcript`'s create function. No file is written; `transcript` builds the `tool_use` + `tool_result` pair with the briefing in the result. |
| Merge-layer boundary | **Cerebras is pure / read-only.** It receives the three context pieces and returns briefing text. All I/O and transcript editing live in `core`. |
| Clone base | **Either side works** (the shared prefix is content-identical). Default to `source_a` for identity. |
| Empty shared prefix | **Leave it empty.** When the two sessions never overlapped, the clone is just the spliced-in Read cycle. No synthetic seed turn, no error. |
| Integration | **Replace** (option A). The new transcript-rewriting path supersedes `merge_contexts` + the sidecar. The now-unused `MergedContext` schema, `validator`, `parse`, and JSON-schema prompt are retired. |

---

## Architecture

```
core.merge(source_a, source_b)
  │
  ├─ from_text(A), from_text(B)                         # weave.transcript → linear entry lists
  ├─ _split_at_branch(A, B) on CONTENT                  # role+text+tool name/input/result; ignore volatile fields
  │     → branch_point_uuid (or None), a_tail, b_tail
  │
  ├─ briefing = merger.merge(distill(shared), a_tail, b_tail)   # weave.merge — PURE, returns text
  │
  ├─ clone = A (in memory; disk untouched)              # core owns all I/O
  │     ├─ delete_between(a_tail[0].uuid, A[-1].uuid)   # drop A's branch (if a_tail non-empty)
  │     └─ create_after(branch_point_uuid, spec)        # or create_at_start when prefix empty
  │           spec = {"type":"tool_call","name":"Read",
  │                   "input":{"file_path":"weave-merged-context"},
  │                   "result": briefing}
  │
  ├─ new_id = _new_id();  entries = _rewrite_for_local(entries, new_id, cwd)
  └─ connector.write_text(session_path(cwd, new_id), to_text(entries))   # resumable session
```

### Component responsibilities

| Module | Change | Responsibility |
|--------|--------|----------------|
| `weave.merge` | Repurpose | `ContextMerger.merge(shared, a_branch, b_branch) -> str` returns briefing text. `CerebrasMerger` builds a briefing prompt, calls the client, returns prose. `StubMerger` returns deterministic briefing text. `prompt.build_merge_prompt` rewritten to request one briefing document. |
| `weave.core` | Replace | New `merge()` owns LCP detection, the clone + Read-cycle splice, identity rewrite, and the write. |
| `weave.transcript` | None | Consumed as-is: `from_text`, `read_all`, `delete_between`, `create_after` / `create_at_start`, `to_text`. |
| `weave.connector` | None | `read_text`, `session_path`, `write_text`. |
| `weave.cli` | Adjust | `merge` subcommand drops `--output-dir`; prints the new session id and a `claude --resume <id>` hint (mirrors `pull`). |

### Code retired (option A)

- `weave/merge/types.py`: `MergedContext`, `MergedDecision`, `Conflict`, `SourceRef` (the whole semantic-merge schema).
- `weave/merge/validator.py` (validates `MergedContext`).
- `weave/merge/parse.py` (parses the JSON merged response).
- `weave/merge/prompt.py`: the `_MERGE_OUTPUT_SCHEMA` block.
- `weave/core/core.py`: `merge_contexts`, `_write_merge_sidecar`, `_resolve_source_path` (if unused after), `_DEFAULT_MERGED_DIR`, `_WEAVE_MERGE_VERSION`, `_COMPATIBILITY_NOTE`, and the old sidecar `MergeResult` shape.

**Kept in `weave.merge`:** `client.py`, `env.py`, `factory.py`, `exceptions.py`.

### Affected files (for the implementation plan)

Runtime: `weave/merge/__init__.py`, `weave/merge/protocols.py`, `weave/merge/cerebras.py`, `weave/merge/stub.py`, `weave/merge/prompt.py`, `weave/merge/types.py`, `weave/merge/validator.py`, `weave/merge/parse.py`, `weave/core/__init__.py`, `weave/core/core.py`, `weave/cli/cli.py`.

Tests/fixtures: `tests/merge_test_fixtures.py`, `tests/test_merge_pipeline.py`, `tests/test_merge_types.py`, `tests/test_merge_e2e.py`, `tests/test_cerebras_integration.py`, `tests/test_weave_cli.py`.

---

## Detailed behavior

### `_split_at_branch(a_entries, b_entries) -> (branch_point_uuid | None, a_tail, b_tail)`

- Walk both entry lists from index 0. At each position compare `_entry_key(a[i]) == _entry_key(b[i])`. The longest run of equal entries is the shared prefix; the first unequal position (or the end of the shorter list) is the divergence point.
- `branch_point_uuid` = the uuid of the **last shared entry** in `a_entries` (None if the prefix is empty).
- `a_tail` = `a_entries` after the prefix; `b_tail` = `b_entries` after the prefix.
- **Cycle-boundary snap:** if the divergence point lands in the middle of a `tool_use`/`tool_result` cycle, back the prefix boundary off to the last complete cycle so a pair is never split across the prefix/tail line. (`delete_between` already keeps cycles atomic on the deletion side.)

### `_entry_key(entry) -> hashable`

Extracts the comparable content of an entry, ignoring volatile fields (`uuid`, `parentUuid`, `sessionId`, `cwd`, `timestamp`, and similar machine/identity fields):

- message entries: `(role, normalized message content)`.
- tool entries: `(role, tool name, tool input, tool result)`.

### Merge layer

```
ContextMerger.merge(shared_context: ChatContext | None,
                    a_branch: list[dict],
                    b_branch: list[dict]) -> str
```

- `CerebrasMerger`: `prompt = build_merge_prompt(shared_context, a_branch, b_branch)`; `text = client.complete(prompt)`; return `text` (stripped). No JSON parse, no validation. Raise `MergeResponseError` if the briefing is empty/blank.
- `StubMerger`: returns deterministic briefing text derived from the inputs (for tests).
- `build_merge_prompt`: instructs the model to write a single briefing document unifying the two branches — what each branch did, decisions, how conflicts reconcile, files touched, current state and next steps — given the shared background. Plain text out; no fences, no schema.

### `core.merge(source_a, source_b, *, cwd=None, merger=None, config_path=None) -> MergeResult`

Order of operations guarantees no partial writes: resolve + read + split + **merge call** all happen before the clone is written, so a merge-layer failure aborts cleanly.

- Resolve and read each source via `connector.read_text` (id or path); `transcript.from_text`.
- `_split_at_branch`.
- Distill the shared prefix sub-document into a `ChatContext` via `distill_from_jsonl` (background for the merge layer); pass `a_tail`, `b_tail` raw.
- `briefing = (merger or default_merger()).merge(shared_ctx, a_tail, b_tail)`.
- Clone editing on the in-memory `a` entries:
  - if `a_tail`: `entries, _ = delete_between(a, a_tail[0]["uuid"], a[-1]["uuid"])`.
  - splice: `create_after(entries, branch_point_uuid, spec)`; when `branch_point_uuid is None`, `create_at_start(entries, spec)`.
- `new_id = _new_id()`; `cwd = cwd or os.getcwd()`; `entries = _rewrite_for_local(entries, new_id, cwd)`.
- `connector.write_text(connector.session_path(cwd, new_id), transcript.to_text(entries))`.
- Return `MergeResult(session_id=new_id, jsonl_path=str(path), branch_point=branch_point_uuid, a_tail_len=len(a_tail), b_tail_len=len(b_tail))`.

### `MergeResult` (new shape)

```python
@dataclass(frozen=True)
class MergeResult:
    session_id: str
    jsonl_path: str
    branch_point: str | None
    a_tail_len: int
    b_tail_len: int
```

### CLI

`weave merge <source_a> <source_b>` → on success prints:

```
merged into <new_id>
  resume: claude --resume <new_id>
```

---

## Error handling

| Case | Behavior |
|------|----------|
| Source id/path missing or ambiguous | `connector` raises `SessionNotFound` / `AmbiguousSession` (subclass `ValueError`) → core wraps as `WeaveError`, before any write. |
| Both transcripts empty | `WeaveError("no chat history")`. |
| Identical transcripts (both tails empty) | `WeaveError("sessions are identical; nothing to merge")`. |
| Cerebras unreachable / no API key | merge-layer error (`MergeClientError`) propagates; nothing written. |
| Empty / blank briefing returned | `MergeResponseError`; nothing written. |
| Empty shared prefix | Allowed. Clone is just the Read cycle (`create_at_start`). |

The merge call precedes the clone write, so any failure leaves both originals and the local `~/.claude` untouched.

### Known caveat

When the shared prefix is empty, the merged transcript begins with an assistant `tool_use` cycle rather than a user turn. This may not be an ideal resume shape for Claude Code; accepted per the "leave it empty" decision. Documented here so a future change can revisit it without surprise.

---

## Testing

- **Unit — `_split_at_branch`:** shared-then-branch, no-shared (empty prefix), one side a strict prefix of the other, identical transcripts. Assert correct `branch_point_uuid`, `a_tail`, `b_tail`, and cycle-boundary snapping.
- **Unit — `_entry_key`:** the same logical turn captured on two machines (different `uuid`/`sessionId`/`cwd`/`timestamp`) compares equal; genuinely different content compares unequal.
- **End-to-end with `StubMerger`:** merge two fixture JSONLs and assert:
  - the shared prefix is preserved verbatim,
  - exactly one `Read` tool cycle is present, carrying the stub briefing in its `tool_result`,
  - every entry's `cwd` and `sessionId` are rewritten and a fresh `session_id` is used,
  - the output round-trips through `weave.transcript` as a single valid linear chain (resumable).
- **Cerebras path:** mocked client returns a canned briefing; assert it lands in the `tool_result`.
- **Edge — empty prefix:** merged file is just the Read cycle.
- **Integration:** keep the single real-Cerebras test gated behind `CEREBRAS_API_KEY`, adapted to assert briefing text instead of a `MergedContext`.

Fixtures referencing `MergedContext` (`tests/merge_test_fixtures.py`, `tests/test_merge_types.py`) are migrated to the new text-briefing shape or removed with the retired schema.

---

## Follow-up (out of this spec)

The README still documents the old SSH-based WeaveHub and the sidecar merge. After this lands, the README "Merge pipeline" / "Write" stage and error-handling rows should be updated to describe the resumable-clone behavior. Tracked separately from this implementation.
