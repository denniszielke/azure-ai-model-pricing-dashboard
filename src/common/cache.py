"""
cache.py – Local file-system caching helpers.

Raw CSV downloads are stored under:
  <data_dir>/raw/<subscription_id>/<timestamp>/

Normalised parquet is stored under:
  <data_dir>/normalized/

The data directory defaults to ./data but can be overridden via the
COST_DASHBOARD_DATA_DIR environment variable.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Root data directory (can be overridden by env var)
DATA_DIR = Path(os.environ.get("COST_DASHBOARD_DATA_DIR", "data"))


def get_data_dir() -> Path:
    """Return the root data directory, creating it if necessary."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def get_raw_dir(subscription_id: str, timestamp: str | None = None) -> Path:
    """Return (and create) the raw download directory for a subscription.

    Parameters
    ----------
    subscription_id:
        Azure subscription GUID.
    timestamp:
        Optional ISO-ish timestamp string used as the sub-folder name.
        Defaults to the current UTC time formatted as ``YYYYMMDD_HHMMSS``.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = DATA_DIR / "raw" / subscription_id / timestamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_normalized_dir() -> Path:
    """Return (and create) the normalized output directory."""
    path = DATA_DIR / "normalized"
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data: Any) -> None:
    """Write *data* as pretty-printed JSON to *path*."""
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    logger.debug("Wrote JSON cache: %s", path)


def read_json(path: Path) -> Any:
    """Read and return a JSON file, or ``None`` if it doesn't exist."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
