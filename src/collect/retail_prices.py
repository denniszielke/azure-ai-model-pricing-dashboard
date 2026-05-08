"""
retail_prices.py – Public Azure Retail Prices API for list-price baseline.

Endpoint: https://prices.azure.com/api/retail/prices

Used to compute "discount vs list" when PayAsYouGoPrice is absent from Cost
Details data.  Responses are cached locally to avoid repeated API calls.

Only Azure OpenAI / Cognitive Services meters are fetched.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import requests

from src.common.cache import get_data_dir

logger = logging.getLogger(__name__)

RETAIL_PRICES_URL = "https://prices.azure.com/api/retail/prices"
CACHE_FILE_NAME = "retail_prices_openai.json"

# OData filter to narrow to Azure OpenAI meters
OPENAI_FILTER = (
    "serviceName eq 'Azure OpenAI' or "
    "serviceFamily eq 'AI + Machine Learning' and "
    "productName contains 'OpenAI'"
)


def fetch_retail_prices(use_cache: bool = True) -> dict[str, float]:
    """Fetch public retail (list) prices for Azure OpenAI meters.

    Parameters
    ----------
    use_cache:
        If ``True`` (default), use a locally cached response when available.

    Returns
    -------
    dict[str, float]
        Mapping of lower-cased meter name to retail unit price (per unit).
    """
    cache_path = get_data_dir() / CACHE_FILE_NAME
    if use_cache and cache_path.exists():
        logger.debug("Loading retail prices from cache: %s", cache_path)
        return _parse_prices(json.loads(cache_path.read_text(encoding="utf-8")))

    prices_raw: list[dict[str, Any]] = []
    url = RETAIL_PRICES_URL
    params: dict[str, str] = {
        "$filter": "serviceName eq 'Azure OpenAI'",
        "api-version": "2023-01-01-preview",
    }

    page = 0
    while url:
        logger.debug("Fetching retail prices page %d", page)
        try:
            resp = requests.get(url, params=params if page == 0 else None, timeout=30)
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to fetch retail prices: %s", exc)
            break

        body = resp.json()
        prices_raw.extend(body.get("Items", []))
        url = body.get("NextPageLink", "")
        params = {}  # NextPageLink already includes query params
        page += 1

    if prices_raw:
        cache_path.write_text(
            json.dumps(prices_raw, indent=2), encoding="utf-8"
        )
        logger.info("Cached %d retail price entries to %s", len(prices_raw), cache_path)

    return _parse_prices(prices_raw)


def _parse_prices(items: list[dict[str, Any]]) -> dict[str, float]:
    """Convert a list of retail price items into a meter-name → price dict."""
    prices: dict[str, float] = {}
    for item in items:
        meter_name = (item.get("meterName") or item.get("MeterName") or "").lower()
        retail_price = item.get("retailPrice") or item.get("unitPrice") or 0.0
        if meter_name:
            try:
                # Keep the lowest (most common) price if duplicates
                existing = prices.get(meter_name, float("inf"))
                prices[meter_name] = min(existing, float(retail_price))
            except (ValueError, TypeError):
                pass
    logger.debug("Retail prices: %d unique meters", len(prices))
    return prices
