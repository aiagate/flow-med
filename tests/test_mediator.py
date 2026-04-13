"""Tests for the Mediator."""

from typing import override

import pytest
from flow_res import Ok, Result
from injector import Injector

from flow_med import HandlerNotFoundError, Mediator, Request, RequestHandler

# Initialize Mediator for tests
Mediator.initialize(Injector())


class MyQuery(Request[Result[str, Exception]]):
    pass


class MyQueryHandler(RequestHandler[MyQuery, Result[str, Exception]]):
    @override
    async def handle(self, request: MyQuery) -> Result[str, Exception]:
        return Ok("Handled")


class AnotherQuery(Request[Result[int, Exception]]):
    pass


@pytest.mark.anyio
async def test_mediator_send_registered_request() -> None:
    """Test that a request with an auto-registered handler can be sent."""
    # The MyQueryHandler should be auto-registered via __init_subclass__
    result = await Mediator.send_async(MyQuery()).unwrap()
    assert result == "Handled"


@pytest.mark.anyio
async def test_mediator_send_unregistered_raises_error() -> None:
    """Test that sending an unregistered request raises HandlerNotFoundError."""
    with pytest.raises(
        HandlerNotFoundError, match="Handler not found for request type"
    ):
        await Mediator.send_async(AnotherQuery())


@pytest.mark.anyio
async def test_mediator_not_initialized_raises_error() -> None:
    """Test that calling send_async before initialization raises RuntimeError."""
    original_injector = Mediator._injector
    Mediator._injector = None
    try:
        with pytest.raises(RuntimeError, match="Mediator not initialized"):
            await Mediator.send_async(MyQuery())
    finally:
        Mediator._injector = original_injector
