"""Local HTTP folder hub. Implementation lives in :mod:`weave.hub.hub`.

Start with ``python -m weave.hub --dir <folder>`` (set ``WEAVE_HUB_PASSWORD``).
"""

from weave.hub.hub import main, make_server, normalize_name

__all__ = ["main", "make_server", "normalize_name"]
