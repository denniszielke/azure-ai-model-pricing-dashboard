"""
logging.py – Structured logging configuration for the dashboard project.

Call ``configure_logging()`` once at application startup.  All loggers in the
``src`` package will emit structured lines via the root handler.
"""

from __future__ import annotations

import logging
import sys
from typing import Literal

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

LevelName = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def configure_logging(level: LevelName = "INFO") -> None:
    """Configure root logger with a consistent format.

    Parameters
    ----------
    level:
        Logging level name (``DEBUG``, ``INFO``, etc.).
    """
    numeric = logging.getLevelName(level)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root = logging.getLogger()
    # Remove any existing handlers to avoid duplicate output
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric)

    # Quiet noisy third-party loggers
    for noisy in ("azure.core.pipeline", "urllib3", "requests", "botocore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger("src").setLevel(numeric)
