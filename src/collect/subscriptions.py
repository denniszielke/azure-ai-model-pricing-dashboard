"""
subscriptions.py – List all Azure subscriptions accessible by the current identity.

Uses azure-mgmt-resource SubscriptionClient for clean SDK-based enumeration.
Falls back to a raw REST call if the SDK is unavailable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from src.common.auth import get_auth_headers

logger = logging.getLogger(__name__)

ARM_BASE = "https://management.azure.com"
SUBSCRIPTIONS_API_VERSION = "2022-12-01"


@dataclass
class Subscription:
    """Minimal representation of an Azure subscription."""

    subscription_id: str
    display_name: str
    state: str


def list_subscriptions() -> list[Subscription]:
    """Return all subscriptions accessible to the current credential.

    Tries the azure-mgmt-resource SDK first; falls back to raw REST if the
    package is not installed.

    Returns
    -------
    list[Subscription]
        Non-empty list of accessible subscriptions in the ``Enabled`` state.
    """
    try:
        return _list_via_sdk()
    except ImportError:
        logger.debug("azure-mgmt-resource not installed; falling back to REST")
        return _list_via_rest()


def _list_via_sdk() -> list[Subscription]:
    """Use azure-mgmt-resource SubscriptionClient."""
    from azure.mgmt.resource import SubscriptionClient  # type: ignore[import-untyped]

    from src.common.auth import get_credential

    client = SubscriptionClient(get_credential())
    subs: list[Subscription] = []
    for sub in client.subscriptions.list():
        if sub.state and sub.state.lower() != "enabled":
            logger.debug("Skipping subscription %s (state=%s)", sub.subscription_id, sub.state)
            continue
        subs.append(
            Subscription(
                subscription_id=sub.subscription_id or "",
                display_name=sub.display_name or sub.subscription_id or "",
                state=sub.state or "unknown",
            )
        )
    logger.info("Found %d enabled subscription(s) via SDK", len(subs))
    return subs


def _list_via_rest() -> list[Subscription]:
    """Enumerate subscriptions via raw ARM REST API."""
    url = f"{ARM_BASE}/subscriptions?api-version={SUBSCRIPTIONS_API_VERSION}"
    subs: list[Subscription] = []
    while url:
        resp = requests.get(url, headers=get_auth_headers(), timeout=30)
        resp.raise_for_status()
        body = resp.json()
        for item in body.get("value", []):
            state = item.get("state", "unknown")
            if state.lower() != "enabled":
                continue
            subs.append(
                Subscription(
                    subscription_id=item["subscriptionId"],
                    display_name=item.get("displayName", item["subscriptionId"]),
                    state=state,
                )
            )
        # Handle pagination
        url = body.get("nextLink", "")
    logger.info("Found %d enabled subscription(s) via REST", len(subs))
    return subs
