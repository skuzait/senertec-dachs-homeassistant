"""Shared fixtures for the Dachs integration tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make custom_components and the test fakes importable.
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading the dachs integration from custom_components."""
    yield


@pytest.fixture(autouse=True)
def auto_enable_sockets(socket_enabled):
    """The fakes serve real HTTP on 127.0.0.1; unblock sockets.

    Newer pytest-homeassistant-custom-component versions block all
    sockets by default (mirroring the HA core conftest).
    """
    yield
