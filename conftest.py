"""Pytest bootstrap.

Registers ``src/`` as the installed ``ferry`` package so ``import ferry`` works
when the suite runs from the repo without ``pip install``.
"""

import importlib.util
import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_ROOT, "src")
_INIT = os.path.join(_SRC, "__init__.py")

if "ferry" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "ferry",
        _INIT,
        submodule_search_locations=[_SRC],
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["ferry"] = module
    spec.loader.exec_module(module)

if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
