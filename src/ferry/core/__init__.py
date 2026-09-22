"""Ferry orchestrator core: push/pull Claude Code sessions, plus remote/ls.

Owns all ferry-layer policy (id choice, cwd/sessionId rewrite, config
resolution, validation). Implementation lives in :mod:`ferry.core.core`; import
from this package (``from ferry import core``) for the stable surface.
"""

from ferry.core.core import (
    FerryError,
    log,
    ls,
    pull,
    push,
    remote_add,
    rm,
)

__all__ = [
    "FerryError",
    "log",
    "ls",
    "pull",
    "push",
    "remote_add",
    "rm",
]
