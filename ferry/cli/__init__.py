"""argparse CLI for ferry: push / pull / remote add / ls.

A thin marshalling layer over :mod:`ferry.core`. Implementation lives in
:mod:`ferry.cli.cli`; run as ``python -m ferry.cli``.
"""

from ferry.cli.cli import main

__all__ = ["main"]
