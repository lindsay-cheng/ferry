"""Boundary test: weave must reach the private transcript engine only via the
public weave.transcript surface.

Run (from repo root):  PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_merge_pipeline.py -q
"""

import ast
import unittest
from pathlib import Path

_WEAVE_ROOT = Path(__file__).resolve().parent.parent / "weave"


class WeaveImportBoundaryTests(unittest.TestCase):
    def test_only_transcript_package_imports_private_engine(self):
        """The private transcript engine is reachable only through the public
        ``weave.transcript`` surface -- no other weave module may import
        ``weave.transcript.engine`` (nor the legacy top-level ``transcript``)."""
        private = "weave.transcript.engine"
        legacy = "transcript"

        def is_private(name):
            return (
                name == private
                or name == legacy
                or name.startswith(legacy + ".")
            )

        offenders: list[str] = []
        for path in _WEAVE_ROOT.rglob("*.py"):
            # weave/transcript/* legitimately wires the engine to its façade.
            if path.parent.name == "transcript":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if is_private(alias.name):
                            offenders.append(f"{path}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    if is_private(node.module):
                        offenders.append(f"{path}: from {node.module}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
