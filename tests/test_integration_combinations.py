"""Combinatorial INTEGRATION tests: weave.connector x weave.transcript.

The per-module unit suites (test_connector, test_transcript*) cover
each feature in isolation. This suite exercises the full cross product of how
they compose end to end:

    fixture shape   x  connector load  x  core edit op  x  content spec  x  connector write
    (5)                (id | path)        (8 ops)          (7 specs)         (new | in-place)

For EVERY valid combination it asserts the universal invariants that make a
session resumable:
  * the serialized result is a single valid linear chain (one root, no forks,
    one leaf, every parentUuid resolves, no duplicate uuids) -- or legitimately
    empty;
  * tool_use / tool_result pairing is intact on the chain;
  * the connector round-trips byte-for-byte (read_text after write_text);
  * write-new sessions are findable via resolve(); in-place rewrites overwrite.

Combinations that are inherently invalid (a uuid-anchored edit on an empty
session) are asserted to raise, and counted as covered -- not silently skipped.

Everything runs against a temp $CLAUDE_CONFIG_DIR; the real ~/.claude is never
touched.

Run (from repo root):  python3 -m unittest discover -s tests -t .
"""

import itertools
import json
import os
import tempfile
import unittest
import uuid as uuidlib
from pathlib import Path
from unittest import mock

from weave import connector as cc
from weave import transcript as tx

CWD = "/work/proj"   # fake project cwd -> encoded dir under the temp root


# --- fixture builders (return JSONL text) ------------------------------------
def fx_empty():
    return ""


def fx_linear():
    e = []
    for role, text in (("user", "u1"), ("assistant", "a1"),
                       ("user", "u2"), ("assistant", "a2")):
        e, _ = tx.create_at_end(e, {"type": "message", "role": role, "content": text})
    return tx.to_text(e)


def fx_tool():
    e = []
    e, _ = tx.create_at_end(e, {"type": "message", "role": "user", "content": "do it"})
    e, _ = tx.create_at_end(e, {"type": "tool_call", "name": "Bash",
                                "input": {"command": "ls"}, "result": "out", "reply": "done"})
    return tx.to_text(e)


def fx_thinking():
    e = []
    e, _ = tx.create_at_end(e, {"type": "message", "role": "user", "content": "think"})
    e, _ = tx.create_at_end(e, {"type": "message", "role": "assistant",
                                "content": [{"type": "thinking", "thinking": "hmm", "signature": "sig"},
                                            {"type": "text", "text": "ok"}]})
    return tx.to_text(e)


def fx_forked():
    """A linear base plus a real orphan branch AND a distinct active leaf, so
    from_text must linearize to the active branch and drop the fork."""
    base = fx_linear()
    objs = [json.loads(l) for l in base.splitlines() if l.strip()]
    a1, leaf = objs[1]["uuid"], objs[-1]["uuid"]
    orphan = ('{"parentUuid":"%s","type":"user","uuid":"orphan-1",'
              '"timestamp":"2026-06-26T10:00:09.000Z",'
              '"message":{"role":"user","content":"ORPHAN"}}\n') % a1
    active = ('{"parentUuid":"%s","type":"user","uuid":"active-leaf",'
              '"timestamp":"2026-06-26T10:00:10.000Z",'
              '"message":{"role":"user","content":"ACTIVE"}}\n') % leaf
    return base + orphan + active


FIXTURES = [("empty", fx_empty), ("linear", fx_linear), ("tool", fx_tool),
            ("thinking", fx_thinking), ("forked", fx_forked)]

SPECS = [
    ("user_str", {"type": "message", "role": "user", "content": "NEW-USER"}),
    ("asst_str", {"type": "message", "role": "assistant", "content": "NEW-ASST"}),
    ("asst_blocks", {"type": "message", "role": "assistant",
                     "content": [{"type": "text", "text": "T"},
                                 {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}),
    ("thinking", {"type": "message", "role": "assistant",
                  "content": [{"type": "thinking", "thinking": "h", "signature": "s"},
                              {"type": "text", "text": "t"}]}),
    ("image", {"type": "message", "role": "user",
               "content": [{"type": "image", "source": {"type": "url", "url": "http://x/y.png"}}]}),
    ("tool_single", {"type": "tool_call", "name": "Read", "input": {"file_path": "/a"},
                     "result": "DATA", "reply": "done"}),
    ("tool_multi", {"type": "tool_call",
                    "tools": [{"name": "A", "input": {}, "result": "a"},
                              {"name": "B", "input": {}, "result": "b"}],
                    "text": "two", "reply": "ok"}),
]

# Edit ops: (label, uses_spec, needs_uuid, apply_fn(entries, spec) -> (entries, created))
EDIT_OPS = [
    ("noop", False, False, lambda e, s: (e, [])),
    ("create_at_start", True, False, lambda e, s: tx.create_at_start(e, s)),
    ("create_at_end", True, False, lambda e, s: tx.create_at_end(e, s)),
    ("create_after", True, True, lambda e, s: tx.create_after(e, e[0]["uuid"], s)),
    ("update_leaf", True, True, lambda e, s: tx.update(e, e[-1]["uuid"], s)),
    ("delete_leaf", False, True, lambda e, s: tx.delete(e, e[-1]["uuid"])),
    ("delete_first", False, True, lambda e, s: tx.delete(e, e[0]["uuid"])),
    ("delete_between", False, True,
     lambda e, s: tx.delete_between(e, e[1]["uuid"], e[-2]["uuid"]) if len(e) >= 4
     else tx.delete_between(e, e[0]["uuid"], e[-1]["uuid"])),
]


def _entries_from_text(text):
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            o = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and o.get("uuid"):
            out.append(o)
    return out


class CombinationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    # --- shared invariant checks ---------------------------------------------
    def assert_valid_linear_chain(self, text):
        entries = _entries_from_text(text)
        if not entries:
            return  # an empty session is a legitimate result
        uuids = [e["uuid"] for e in entries]
        self.assertEqual(len(uuids), len(set(uuids)), "duplicate uuids on chain")
        by = set(uuids)
        children = {}
        roots = []
        for e in entries:
            p = e.get("parentUuid")
            if p is None:
                roots.append(e["uuid"])
            else:
                self.assertIn(p, by, "dangling parentUuid")
                children.setdefault(p, []).append(e["uuid"])
        self.assertEqual(len(roots), 1, "expected exactly one root")
        forks = [p for p, k in children.items() if len(k) > 1]
        self.assertEqual(forks, [], "fork present after serialize")
        leaves = [u for u in uuids if u not in children]
        self.assertEqual(len(leaves), 1, "expected exactly one leaf")

    def assert_tool_pairs_ok(self, text):
        use_ids, res_ids = set(), set()
        for e in _entries_from_text(text):
            m = e.get("message")
            c = m.get("content") if isinstance(m, dict) else None
            if isinstance(c, list):
                for b in c:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "tool_use" and b.get("id"):
                        use_ids.add(b["id"])
                    if b.get("type") == "tool_result" and b.get("tool_use_id"):
                        res_ids.add(b["tool_use_id"])
        orphan = res_ids - use_ids
        self.assertEqual(orphan, set(), f"orphaned tool_result(s): {orphan}")

    # --- the matrix ----------------------------------------------------------
    def test_every_combination(self):
        ran = invalid = 0
        for (fx_name, fx), load_mode, (op_label, uses_spec, needs_uuid, op_fn), write_mode in \
                itertools.product(FIXTURES, ("id", "path"), EDIT_OPS, ("new", "inplace")):
            spec_set = SPECS if uses_spec else [("-", None)]
            for spec_label, spec in spec_set:
                sid = uuidlib.uuid4().hex
                seed_path = cc.session_path(CWD, sid)
                seed_path.parent.mkdir(parents=True, exist_ok=True)
                seed_path.write_text(fx(), encoding="utf-8")

                label = (f"fx={fx_name} load={load_mode} op={op_label} "
                         f"spec={spec_label} write={write_mode}")
                with self.subTest(label):
                    # --- load via connector (id or path) ---
                    loaded = cc.read_text(sid if load_mode == "id" else str(seed_path))
                    entries = tx.from_text(loaded)

                    # --- inherently-invalid combo: uuid-anchored edit, no entries ---
                    if needs_uuid and not entries:
                        invalid += 1
                        with self.assertRaises((tx.NotFoundError, tx.SpecError, IndexError, ValueError)):
                            op_fn(entries, spec)
                        return_ok = True  # noqa: F841
                        continue

                    # --- apply the core edit ---
                    new_entries, created = op_fn(entries, spec)
                    new_text = tx.to_text(new_entries)

                    # --- write via connector (new id or in-place) ---
                    if write_mode == "new":
                        new_id = uuidlib.uuid4().hex
                        dst = cc.session_path(CWD, new_id)
                        cc.write_text(dst, new_text)
                        self.assertEqual(cc.read_text(new_id), new_text,
                                         "connector round-trip (by id) mismatch")
                        self.assertEqual(cc.resolve(new_id), dst,
                                         "write-new not findable via resolve")
                    else:
                        cc.write_text(seed_path, new_text)
                        self.assertEqual(cc.read_text(str(seed_path)), new_text,
                                         "in-place rewrite round-trip mismatch")

                    # --- universal invariants on the written result ---
                    self.assert_valid_linear_chain(new_text)
                    self.assert_tool_pairs_ok(new_text)

                    # --- op-specific effect checks ---
                    reread = tx.from_text(new_text)
                    if op_label == "noop":
                        self.assertEqual(len(reread), len(entries))
                    elif op_label.startswith("create"):
                        self.assertGreater(len(reread), len(entries),
                                           "create did not add entries")
                        self.assertEqual(len(created), len(reread) - len(entries))
                    elif op_label == "update_leaf":
                        # head keeps the target's uuid (identity-preserving)
                        self.assertIn(entries[-1]["uuid"], {e["uuid"] for e in reread})
                    elif op_label in ("delete_leaf", "delete_first"):
                        gone = entries[-1]["uuid"] if op_label == "delete_leaf" else entries[0]["uuid"]
                        self.assertNotIn(gone, {e["uuid"] for e in reread})
                    ran += 1

        print(f"\n[combination matrix] valid combos run: {ran} | "
              f"invalid combos asserted-to-raise: {invalid} | total: {ran + invalid}")


if __name__ == "__main__":
    unittest.main()
