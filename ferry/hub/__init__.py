"""Local HTTP folder hub. Implementation lives in :mod:`ferry.hub.hub`.

Start with ``python -m ferry.hub --dir <folder>`` (set ``FERRY_HUB_PASSWORD``).
"""

from ferry.hub.hub import main, make_server, normalize_name

__all__ = ["main", "make_server", "normalize_name"]
