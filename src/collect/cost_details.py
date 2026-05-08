"""
cost_details.py – Azure Cost Management Generate Cost Details Report (async).

Implements the full lifecycle:
  1. POST to trigger async report generation
  2. Poll the ``Location`` header until the operation completes (status 200)
  3. Download each reported blob (CSV or zip of CSVs)
  4. Parse CSVs into a pandas DataFrame

API reference:
  POST {scope}/providers/Microsoft.CostManagement/generateCostDetailsReport
       ?api-version=2024-08-01

The operation returns 202 Accepted with a ``Location`` header.  Polling that
URL eventually returns 200 OK with a JSON body containing ``manifest.blobs``,
each of which has a ``blobLink`` pointing to a downloadable CSV.
"""

from __future__ import annotations

import csv
import io
import logging
import time
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.common.auth import get_auth_headers
from src.common.cache import get_raw_dir

logger = logging.getLogger(__name__)

ARM_BASE = "https://management.azure.com"
COST_DETAILS_API_VERSION = "2024-08-01"

# Polling configuration
MAX_POLL_ATTEMPTS = 60
DEFAULT_POLL_INTERVAL = 10  # seconds


def generate_cost_details_report(
    subscription_id: str,
    start_date: str,
    end_date: str,
    metric: str = "ActualCost",
) -> dict[str, Any]:
    """Trigger an async cost details report and return the completed manifest.

    Parameters
    ----------
    subscription_id:
        Azure subscription GUID.
    start_date:
        Start date in ``YYYY-MM-DD`` format.
    end_date:
        End date in ``YYYY-MM-DD`` format.
    metric:
        ``ActualCost`` (default) or ``AmortizedCost``.

    Returns
    -------
    dict
        The completed operation manifest body containing ``manifest.blobs``.

    Raises
    ------
    RuntimeError
        If the async operation fails or times out.
    """
    scope = f"/subscriptions/{subscription_id}"
    url = (
        f"{ARM_BASE}{scope}/providers/Microsoft.CostManagement/"
        f"generateCostDetailsReport?api-version={COST_DETAILS_API_VERSION}"
    )
    payload: dict[str, Any] = {
        "metric": metric,
        "timePeriod": {
            "start": start_date,
            "end": end_date,
        },
    }

    logger.info(
        "[%s] Submitting Cost Details report for %s – %s (metric=%s)",
        subscription_id,
        start_date,
        end_date,
        metric,
    )

    headers = get_auth_headers()
    response = requests.post(url, json=payload, headers=headers, timeout=60)

    if response.status_code == 200:
        # Synchronous response (rare but possible for small datasets)
        logger.info("[%s] Received synchronous response", subscription_id)
        return response.json()

    if response.status_code != 202:
        _raise_api_error(response, subscription_id, "generate cost details report")

    # Async – poll the Location header
    poll_url = response.headers.get("Location")
    if not poll_url:
        raise RuntimeError(
            f"[{subscription_id}] 202 response missing Location header"
        )

    logger.info("[%s] Polling operation at: %s", subscription_id, poll_url)
    return _poll_until_complete(subscription_id, poll_url)


def _poll_until_complete(subscription_id: str, poll_url: str) -> dict[str, Any]:
    """Poll *poll_url* until the async operation completes.

    Respects ``Retry-After`` headers from the service.
    """
    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        headers = get_auth_headers()
        resp = requests.get(poll_url, headers=headers, timeout=60)

        if resp.status_code == 200:
            logger.info(
                "[%s] Operation completed after %d poll(s)", subscription_id, attempt
            )
            return resp.json()

        if resp.status_code == 202:
            # Still in progress
            retry_after = int(resp.headers.get("Retry-After", DEFAULT_POLL_INTERVAL))
            logger.debug(
                "[%s] Still in progress (attempt %d/%d); waiting %ds",
                subscription_id,
                attempt,
                MAX_POLL_ATTEMPTS,
                retry_after,
            )
            time.sleep(retry_after)
            continue

        if resp.status_code == 429:
            # Rate limited
            retry_after = int(resp.headers.get("Retry-After", 30))
            logger.warning(
                "[%s] Rate limited (429); waiting %ds", subscription_id, retry_after
            )
            time.sleep(retry_after)
            continue

        _raise_api_error(resp, subscription_id, "poll cost details report")

    raise RuntimeError(
        f"[{subscription_id}] Cost details report did not complete after "
        f"{MAX_POLL_ATTEMPTS} attempts"
    )


def download_and_parse(
    subscription_id: str,
    manifest: dict[str, Any],
    raw_dir: Path | None = None,
) -> pd.DataFrame:
    """Download all blobs in *manifest* and parse them into a DataFrame.

    Parameters
    ----------
    subscription_id:
        Azure subscription GUID (used for the local cache path).
    manifest:
        The completed operation manifest returned by the API.
    raw_dir:
        Optional directory to store downloaded files.  Created automatically
        if *None*.

    Returns
    -------
    pd.DataFrame
        Combined DataFrame of all downloaded CSV rows.
    """
    if raw_dir is None:
        raw_dir = get_raw_dir(subscription_id)

    blobs = _extract_blob_links(manifest)
    if not blobs:
        logger.warning("[%s] No blobs found in manifest", subscription_id)
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for idx, blob_url in enumerate(blobs):
        logger.info("[%s] Downloading blob %d/%d", subscription_id, idx + 1, len(blobs))
        df = _download_blob(blob_url, raw_dir, idx)
        if not df.empty:
            frames.append(df)
            logger.info(
                "[%s] Blob %d: parsed %d row(s)", subscription_id, idx + 1, len(df)
            )

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    logger.info(
        "[%s] Total rows after combining all blobs: %d", subscription_id, len(combined)
    )
    return combined


def _extract_blob_links(manifest: dict[str, Any]) -> list[str]:
    """Extract download URLs from a completed manifest response."""
    links: list[str] = []

    # Common response shape: {"manifest": {"blobs": [{"blobLink": "..."}]}}
    manifest_inner = manifest.get("manifest", manifest)
    for blob in manifest_inner.get("blobs", []):
        link = blob.get("blobLink") or blob.get("downloadUrl") or blob.get("url")
        if link:
            links.append(link)

    # Alternative shape (direct "blobs" at top level)
    if not links:
        for blob in manifest.get("blobs", []):
            link = blob.get("blobLink") or blob.get("downloadUrl") or blob.get("url")
            if link:
                links.append(link)

    return links


def _download_blob(blob_url: str, raw_dir: Path, idx: int) -> pd.DataFrame:
    """Download a single blob URL and return its contents as a DataFrame."""
    resp = requests.get(blob_url, timeout=120)
    resp.raise_for_status()

    content_type = resp.headers.get("Content-Type", "")
    content = resp.content

    # Detect zip vs CSV by content-type or magic bytes
    if content[:2] == b"PK" or "zip" in content_type:
        return _parse_zip(content, raw_dir, idx)
    else:
        filename = raw_dir / f"blob_{idx:03d}.csv"
        filename.write_bytes(content)
        return _parse_csv_bytes(content, filename)


def _parse_zip(content: bytes, raw_dir: Path, idx: int) -> pd.DataFrame:
    """Extract CSV files from a zip archive and parse them."""
    frames: list[pd.DataFrame] = []
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        for name in zf.namelist():
            if not name.lower().endswith(".csv"):
                continue
            data = zf.read(name)
            dest = raw_dir / name.replace("/", "_")
            dest.write_bytes(data)
            df = _parse_csv_bytes(data, dest)
            if not df.empty:
                frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _parse_csv_bytes(content: bytes, path: Path) -> pd.DataFrame:
    """Parse CSV content bytes into a DataFrame, handling BOM and encoding."""
    try:
        text = content.decode("utf-8-sig")  # handle BOM
    except UnicodeDecodeError:
        text = content.decode("latin-1")

    if not text.strip():
        logger.debug("Empty CSV at %s", path)
        return pd.DataFrame()

    # Detect delimiter (some Cost Management exports use tab)
    sample = text[:2048]
    dialect = csv.Sniffer().sniff(sample, delimiters=",\t")

    df = pd.read_csv(
        io.StringIO(text),
        sep=dialect.delimiter,
        dtype=str,  # read everything as str; normalise downstream
        low_memory=False,
    )
    logger.debug("Parsed %d row(s) from %s", len(df), path)
    return df


def _raise_api_error(
    response: requests.Response,
    subscription_id: str,
    operation: str,
) -> None:
    """Raise a RuntimeError with details from an unexpected HTTP response."""
    try:
        body = response.json()
        message = body.get("error", {}).get("message", response.text[:500])
    except Exception:
        message = response.text[:500]

    raise RuntimeError(
        f"[{subscription_id}] Failed to {operation}: "
        f"HTTP {response.status_code} – {message}"
    )
