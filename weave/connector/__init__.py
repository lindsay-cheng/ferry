"""Local-filesystem connector: Claude Code session id <-> JSONL file path I/O.

A dumb byte boundary over a unix ``~/.claude``. Implementation lives in
:mod:`weave.connector.connector`; import from this package for the stable surface.
"""

from weave.connector.connector import (
    AmbiguousSession,
    SessionNotFound,
    encode_cwd,
    latest_session,
    list_sessions,
    projects_root,
    read_text,
    resolve,
    session_path,
    write_text,
)

__all__ = [
    "AmbiguousSession",
    "SessionNotFound",
    "encode_cwd",
    "latest_session",
    "list_sessions",
    "projects_root",
    "read_text",
    "resolve",
    "session_path",
    "write_text",
]
