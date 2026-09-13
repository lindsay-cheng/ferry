"""argparse CLI for weave: push / pull / remote add / ls / merge.

A thin marshalling layer over :mod:`weave.core`. Implementation lives in
:mod:`weave.cli.cli`; run as ``python -m weave.cli``.
"""

from weave.cli.cli import main

__all__ = ["main"]
