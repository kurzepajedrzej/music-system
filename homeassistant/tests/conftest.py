"""Shared fixtures for the music_system integration test suite."""
from __future__ import annotations

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"

# Monkey-patch aioresponses to work with aiohttp 3.14+
import aiohttp.client_reqrep
from unittest.mock import Mock

_original_init = aiohttp.client_reqrep.ClientResponse.__init__

def _patched_init(self, method, url, *, stream_writer=None, **kwargs):
    """Patched ClientResponse.__init__ to accept stream_writer as optional."""
    _original_init(self, method, url, stream_writer=stream_writer or Mock(), **kwargs)

aiohttp.client_reqrep.ClientResponse.__init__ = _patched_init


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield
