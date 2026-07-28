"""Shared fixtures for mediator tests."""

import pytest
from injector import Injector

from flow_med import Mediator


@pytest.fixture
def mediator() -> Mediator:
    """Return a fresh mediator so tests do not share registry or DI state."""
    return Mediator(Injector())
