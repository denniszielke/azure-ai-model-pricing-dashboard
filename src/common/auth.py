"""
auth.py – DefaultAzureCredential helper for ARM API calls.

Uses DefaultAzureCredential which automatically tries:
  1. Environment variables (AZURE_TENANT_ID / AZURE_CLIENT_ID / AZURE_CLIENT_SECRET)
  2. Workload Identity (for AKS/container environments)
  3. Azure CLI credentials (az login)
  4. Managed Identity
"""

from __future__ import annotations

import logging

from azure.identity import DefaultAzureCredential

logger = logging.getLogger(__name__)

# ARM token scope required for all management.azure.com REST calls
ARM_SCOPE = "https://management.azure.com/.default"

_credential: DefaultAzureCredential | None = None


def get_credential() -> DefaultAzureCredential:
    """Return a cached DefaultAzureCredential instance."""
    global _credential
    if _credential is None:
        logger.debug("Initialising DefaultAzureCredential")
        _credential = DefaultAzureCredential()
    return _credential


def get_arm_token() -> str:
    """Acquire and return a bearer token for the Azure Resource Manager scope.

    Returns
    -------
    str
        A valid bearer token string (without the 'Bearer ' prefix).
    """
    credential = get_credential()
    token = credential.get_token(ARM_SCOPE)
    logger.debug("Acquired ARM token (expires at %s)", token.expires_on)
    return token.token


def get_auth_headers() -> dict[str, str]:
    """Return HTTP headers with a fresh Bearer token for ARM calls."""
    return {
        "Authorization": f"Bearer {get_arm_token()}",
        "Content-Type": "application/json",
    }
