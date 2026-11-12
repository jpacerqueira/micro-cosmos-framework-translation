"""Micro-Cosmos — neurosymbolic code modernisation pipeline.

On import, this module configures structured logging for the
`micro_cosmos.diagnostics` logger so unhandled errors land in stderr with a
consistent format. Application code emits via that logger; user code can
override the handler set-up by configuring `logging.getLogger("micro_cosmos")`
before importing this package."""

import logging
import os

__version__ = "0.1.0"


def _configure_default_logging() -> None:
    root = logging.getLogger("micro_cosmos")
    if root.handlers:
        # Caller has already configured logging — respect their setup
        return
    level_name = os.environ.get("MICRO_COSMOS_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s · %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False


_configure_default_logging()
