"""Pytest bootstrap.

Ensures the repository root is importable so ``import weave`` resolves when the
suite is run from anywhere. Test modules live under ``tests/``.
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
