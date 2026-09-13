# Weave transcript engine — linear simplification

- **Date:** 2026-06-27
- **Status:** Approved design, pre-implementation
- **Scope:** Rewrite `transcript.py` (private editing engine) and `transcipt_api.py`
  (public façade) around a single linear branch. Replaces the fork-aware graph model.
- **Out of scope:** Persistence (new-file creation, `sessionId` rewrite, lineage).
  That stays a future, separate module.

---

## 1. Context & problem

`transcript.py` is the CRUD engine behind weave's `edit <session>` capability: it
edits a Claude Code transcript (JSONL, one entry per line, entries linked into a
**tree** by `parentUuid → uuid`). `transcipt_api.py` is a thin public façade over it.

Claude Code transcripts are append-only. When a user rewinds/edits and re-sends, the
new branch is **appended at the end of the file**, so a node gains multiple children
(a fork); the active conversation is the branch ending at the **last-appended** entry.

The current engine tries to operate on this forked tree directly, which causes two
problems:

1. **A correctness bug.** `_main_path` reconstructs "the conversation" by walking
   from the root and taking the **first** child at each fork (`kids[0]`). The first
   child is the *oldest/abandoned* branch. Verified against 1,635 real transcripts:
   1,078 contain forks; in **735** the first-child walk diverges from the active
   branch, and in **733** of those it picks the older sibling — silently truncating
   the conversation (e.g. returning 39 of 86 turns) and making the default `at_end`
   insert land on a dead branch.
2. **Complexity.** Most of the module — `_main_path`, `_resolve_position`,
   successor re-pointing, `_set_parent`, `_warn_orphaned_tool_partner`, graph
   navigation — exists only to keep a forked tree valid under edits.

## 2. Decision

Stop editing the tree. **Linearize to the active branch once on input, edit it as a
plain list, and re-derive links on output.** Forks are never created (the output is
always a single chain) and the only fork-aware code in the system is one input
function. The persistence model (if/when added) is copy-on-write at the file level:
treat source files as immutable and write a new session file — so editing never needs
to preserve in-file forks.

### Goals

- Output JSONL is **always a single linear chain** — no branches, no forks — by
  construction, not by careful bookkeeping.
- Collapse the fork-handling surface to one function (`linearize`).
- A small, obvious public CRUD surface other engineers iterate against.
- Tool-use/tool-result pairs are handled automatically as atomic units.

### Non-goals

- No filesystem, network, or session-identity logic in these modules (pure,
  in-memory).
- No preservation of input forks in the output. Linearize keeps the active branch
  only; abandoned branches and non-chain meta lines are dropped.
- No `raw` spec mode, no `thinking` lint warnings.

## 3. Module split

| Module | Role | Visibility |
|---|---|---|
| `transcript.py` | The editing engine: linear model, builder, tool-cycle logic. | All functions/helpers `_`-private; free to change. |
| `transcipt_api.py` | The **stable public interface**. Thin delegates to `transcript.py`, carrying the authoritative docstrings + exception classes. | Public names; what other code imports. |

(Aside: `transcipt_api.py` is misspelled; renaming to `transcript_api.py` is an
optional later cleanup, out of scope here.)

## 4. Data model & boundary

The working representation is a **Python `list` of entry dicts in conversation
order**. List order is the single source of truth; `parentUuid` is ignored while
editing and recomputed on output. All CRUD is **pure** — input list never mutated,
mutators return a new list.

Boundary functions convert to/from JSONL:

```
linearize(raw_lines) -> list[dict]   # walk active leaf → root, reverse. ONLY fork-aware code.
serialize(entries)   -> list[str]    # recompute parentUuid from order; head parent = null.
from_text(text)      -> list[dict]   # split + linearize
to_text(entries)     -> str          # serialize + join
```

- **`linearize`** finds the **active leaf = the last-appended entry that has a uuid**
  (the bug fix), walks `parentUuid` to the root with a cycle guard, and reverses.
  Input forks and non-chain meta lines (`mode`, `last-prompt`,
  `file-history-snapshot`, `ai-title`, …) are not carried over. Entries on the chain
  of any type (user/assistant/system/attachment) are kept.
- **`serialize`** sets `entry[0].parentUuid = null` and `entry[i].parentUuid =
  entry[i-1].uuid`. uuids are preserved; only links are rewritten.

### Output guarantee (why there can be no fork)

After `serialize`, a node `e[i]`'s children are exactly the entries whose
`parentUuid == e[i].uuid`. Since `parentUuid[j] = e[j-1].uuid`, that holds only when
`j = i+1`. So every node has exactly one child (except the leaf) and one parent
(except the root): a singly-linked list. A fork is **unrepresentable** in the output,
given unique uuids (guaranteed: a linearized path can't revisit a node, and new
entries get fresh uuids). This is asserted as a property test.

## 5. Public operation set (`transcipt_api.py`)

All operate on `entries` (a list); mutators return `(entries, uuids)`.

```
# boundary
linearize(raw_lines) -> list[dict]
serialize(entries)   -> list[str]
from_text(text)      -> list[dict]
to_text(entries)     -> str

# create  -> (entries, created_uuids)
create_at_start(entries, spec)
create_after(entries, uuid, spec)
create_at_end(entries, spec)

# read  (pure; no mutation)
read_all(entries)                                -> list[dict]
read_from(entries, uuid, n=None, reverse=False)  -> list[dict]   # ascending output always
read_between(entries, uuid_a, uuid_b)            -> list[dict]   # inclusive, order-agnostic
read_one(entries, uuid)                          -> dict | None  # lenient

# update  -> (entries, affected_uuids)
update(entries, uuid, spec)

# delete  -> (entries, deleted_uuids)
delete(entries, uuid)
delete_between(entries, uuid_a, uuid_b)          # inclusive, order-agnostic

# exceptions
NotFoundError   # uuid-anchored op targets a uuid not on the branch (ValueError subclass)
SpecError       # malformed spec (ValueError subclass)
```

### Semantics

- **`create_at_start`** — new root (becomes `entries[0]`).
- **`create_after(uuid)`** — inserts immediately after the target's tool-cycle span.
- **`create_at_end`** — new leaf.
- **`read_from(uuid, n, reverse)`** — `reverse=False` walks toward the leaf (newer),
  `reverse=True` toward the root (older); `n=None` means "to the end" that way.
  Output is **always conversation order (ascending)**; `reverse` only selects which
  window, not the output ordering.
- **`read_between(a, b)`** — inclusive both ends, ascending; inputs auto-ordered;
  `a == b` yields a single entry.
- **`delete_between(a, b)`** — inclusive, order-agnostic; endpoints expand to their
  tool-cycle spans. Rewind = delete from a point's successor to the leaf.

### Error handling

- uuid-anchored ops (`create_after`, `update`, `delete`, `delete_between`,
  `read_from`, `read_between`) **raise `NotFoundError`** if the uuid is absent.
- `read_one` / `read_all` are **lenient** (`None` / `[]`).
- Malformed spec → **`SpecError`**.
- Both exceptions subclass `ValueError` (catch `ValueError` for "any edit error").

## 6. Spec grammar (slim builder)

Shared by `create_*` and `update`:

```python
{"type": "message", "role": "user"|"assistant", "content": str | [block, ...]}

{"type": "tool_call",                       # builds the atomic assistant+user pair
 "tools": [{"name", "input", "result", "is_error"?, "id"?}, ...],
 "text"?: str, "reply"?: str}               # single-tool shorthand: name/input/result at top level
```

- `tool_call` always builds `[assistant(text? + tool_use…), user(tool_result…)]`
  (+ optional `reply` assistant). Tool ids are auto-filled and must be unique.
- Validation kept minimal: role must be `user`/`assistant`; `tool_use` needs a
  `name`; tool ids unique.
- **Removed:** `raw` mode; `thinking` signature/order warnings.
- New entries get a fresh uuid + timestamp and inherit context fields (`cwd`,
  `gitBranch`, `version`, `model`) from neighbors so they remain valid-looking.

## 7. Tool-cycle atomicity

A tool cycle is two adjacent entries: assistant with a `tool_use` block, then the
user entry with the matching `tool_result`. One helper, `_cycle_span(entries, i) ->
(start, end)`:

- a normal entry → `(i, i)`;
- an entry inside a cycle → expands to cover both adjacent entries.

`update`, `delete`, and the endpoints of `delete_between` operate on the **span**;
`create_after` inserts past the span's end. Orphaned `tool_use`/`tool_result` become
structurally impossible — eliminating today's `_warn_orphaned_tool_partner` path.

## 8. What is removed from today's code

`_main_path`, `_find_main_leaf`, `_resolve_position`, `_build_segment` positioning,
`_set_parent`, successor re-pointing, `_warn_orphaned_tool_partner`, `_block_ids`,
graph navigation (`_root`/`_parent`/`_children`/`_ancestors`/`_read_blocks`), the
`raw` spec, and `thinking` warnings. The fork-handling surface collapses to
`linearize`. Expected ~40–50% size reduction.

The old façade exports (`read` with `types`/`roles`/`start`/`end`, `read_by_uuid`,
`read_blocks`, `leaf`, `root`, `parent`, `children`, `ancestors`, `create`'s
`position` modes) are replaced by the operation set in §5.

## 9. Testing

Rewrite `test_transcript.py` and `test_transcipt_api.py` around the linear model,
stdlib `unittest`:

- **Linearize:** selects the **last-appended** leaf; drops forks + non-chain meta
  lines (regression coverage for the bug, using real-fork-shaped fixtures where a
  node has an older first child and a newer later child).
- **Serialize / property:** output has **no node with >1 child**; round-trip
  `linearize(serialize(x))` is stable. Shared helper `assert_linear(entries)`.
- **Create / Update / Delete:** correct list effect + serialized-chain validity for
  each position/op.
- **Tool-cycle atomicity:** delete/update either half removes/rebuilds both; no
  orphaned tool blocks remain.
- **Read variants:** forward/backward windows, inclusive range, lenient `read_one`,
  `read_all` on empty.
- **Errors:** missing uuid raises `NotFoundError`; bad spec raises `SpecError`.
- **API façade:** every public name delegates to the engine and re-exports the
  exception classes.

## 10. Migration note

Callers of the old façade must move to the new surface. There is no `position`
argument (replaced by `create_at_start`/`create_after`/`create_at_end`), no
`types`/`roles` read filtering (read returns raw entries; filter in the caller), and
no graph navigation (the branch is a list — index it). `read`/`leaf` no longer return
an abandoned-branch view, so existing callers silently affected by the `_main_path`
bug will start seeing the correct active conversation.
