"""Unit test configuration - isolates tests from real GCP.

CLOUD PROVIDER ISOLATION
========================

Unit tests should never call real gcloud commands. This conftest provides
fixtures for injecting DummyCloudProvider instances.

Usage in tests:

    def test_cloud_init_creates_bucket(cloud_provider):
        # cloud_provider is a fresh DummyCloudProvider instance
        cloud_provider.projects["my-proj"] = {"labels": {"agentic-consult": "default"}}
        # ... invoke CLI command ...
        assert "my-bucket" in cloud_provider.buckets

    def test_with_preset_config(cloud_config):
        # Load from tests/config/cloud/labeled-project.yaml
        provider = cloud_config("labeled-project")
        # ... test against pre-configured state ...

After each test, the global cloud provider is reset to None so subsequent
tests get fresh state (or the default GCloudProvider in non-test contexts).
"""
import pytest
from agentic_consult.cloud import set_cloud_provider
from agentic_consult.cloud.dummy import DummyCloudProvider


@pytest.fixture
def cloud_provider():
    """
    Provides a fresh DummyCloudProvider and injects it globally.

    The provider starts empty - tests can populate it as needed.
    Automatically resets global provider after test completes.
    """
    provider = DummyCloudProvider()
    set_cloud_provider(provider)
    yield provider
    set_cloud_provider(None)


@pytest.fixture
def cloud_config():
    """
    Factory fixture for loading pre-configured cloud state from YAML.

    Usage:
        def test_something(cloud_config):
            provider = cloud_config("full-setup")
            # provider is loaded from tests/config/cloud/full-setup.yaml
            # and injected globally

    Available configs (in tests/config/cloud/):
        - empty: No GCP resources
        - labeled-project: Project with label, no bucket
        - full-setup: Project + bucket + secrets + images + scheduler
        - missing-secrets: Project + bucket, no secrets
    """
    provider = None

    def _load(name: str) -> DummyCloudProvider:
        nonlocal provider
        provider = DummyCloudProvider.from_config(name)
        set_cloud_provider(provider)
        return provider

    yield _load
    set_cloud_provider(None)
