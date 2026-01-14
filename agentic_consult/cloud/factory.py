"""
Factory for CloudProvider.

Tests inject a DummyCloudProvider via set_cloud_provider() before
invoking CLI commands. Production code calls get_cloud_provider()
and gets GCloudProvider by default.
"""
from typing import Optional
from .base import CloudProvider

_provider: Optional[CloudProvider] = None


def get_cloud_provider() -> CloudProvider:
    """Get the current cloud provider (GCloudProvider by default)."""
    global _provider
    if _provider is None:
        from .gcloud import GCloudProvider
        _provider = GCloudProvider()
    return _provider


def set_cloud_provider(provider: Optional[CloudProvider]) -> None:
    """
    Set the cloud provider for testing.

    Pass None to reset to default (GCloudProvider).
    """
    global _provider
    _provider = provider
