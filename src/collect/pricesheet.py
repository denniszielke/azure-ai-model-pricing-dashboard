"""
pricesheet.py – Optional: Retrieve the negotiated price sheet for a subscription.

Uses:
  GET https://management.azure.com/subscriptions/{id}/providers/
      Microsoft.Consumption/pricesheets/default?api-version=2024-08-01

The response contains ``pricesheets`` items with fields like:
  meterName, unitPrice, includedQuantity, currencyCode, partNumber, etc.

This is used to validate / cross-check the negotiated prices returned in the
Cost Details data.  If this call fails (e.g., the subscription is on an
incompatible billing model) the failure is logged and an empty dict is returned.
"""

from __future__ import annotations

import logging
from typing import Any

import requests

from src.common.auth import get_auth_headers

logger = logging.getLogger(__name__)

ARM_BASE = "https://management.azure.com"
PRICESHEET_API_VERSION = "2024-08-01"


def fetch_pricesheet(subscription_id: str) -> dict[str, float]:
    """Fetch the negotiated price sheet and return a meter-to-price mapping.

    Parameters
    ----------
    subscription_id:
        Azure subscription GUID.

    Returns
    -------
    dict[str, float]
        Mapping of meter name (lower-cased) to negotiated unit price.
        Returns an empty dict if the price sheet is unavailable.
    """
    url = (
        f"{ARM_BASE}/subscriptions/{subscription_id}/providers/"
        f"Microsoft.Consumption/pricesheets/default"
        f"?api-version={PRICESHEET_API_VERSION}"
        "&$expand=properties/meterDetails"
    )
    try:
        resp = requests.get(url, headers=get_auth_headers(), timeout=60)
        if resp.status_code in (404, 403, 422):
            logger.warning(
                "[%s] Price sheet unavailable (HTTP %d); skipping enrichment",
                subscription_id,
                resp.status_code,
            )
            return {}
        resp.raise_for_status()
        return _parse_pricesheet(resp.json())
    except Exception as exc:
        logger.warning(
            "[%s] Failed to fetch price sheet: %s", subscription_id, exc
        )
        return {}


def _parse_pricesheet(body: dict[str, Any]) -> dict[str, float]:
    """Extract meter-name → unit-price mappings from the price sheet response."""
    prices: dict[str, float] = {}
    properties = body.get("properties", body)
    items = properties.get("pricesheets", [])

    for item in items:
        # Meter details may be nested
        meter_details = item.get("meterDetails", {}) or {}
        meter_name = (
            meter_details.get("meterName")
            or item.get("meterName")
            or item.get("MeterName")
            or ""
        )
        unit_price = item.get("unitPrice") or item.get("UnitPrice") or 0.0
        if meter_name:
            try:
                prices[meter_name.lower()] = float(unit_price)
            except (ValueError, TypeError):
                pass

    logger.debug("Price sheet: extracted %d meter prices", len(prices))
    return prices
