"""Behavioral regression tests for scoped handler registries."""

from abc import abstractmethod
from typing import Any, Generic, TypeVar, cast, override

import flow_med
import flow_med.mediator
import pytest
from flow_res import Ok, Result
from injector import Injector, Module, inject

from flow_med import (
    DuplicateHandlerError,
    HandlerNotFoundError,
    HandlerRegistry,
    InvalidHandlerError,
    Mediator,
    MediatorError,
    Request,
    RequestHandler,
)
from flow_med.mediator import _find_generic_base, _resolve_type


def test_mediator_error_is_part_of_the_public_api() -> None:
    assert flow_med.MediatorError is MediatorError
    assert "MediatorError" in flow_med.__all__
    assert "MediatorError" in flow_med.mediator.__all__
    assert issubclass(HandlerNotFoundError, MediatorError)
    assert issubclass(DuplicateHandlerError, MediatorError)


class MyQuery(Request[Result[str, Exception]]):
    pass


class MyQueryHandler(RequestHandler[MyQuery, Result[str, Exception]]):
    @override
    async def handle(self, request: MyQuery) -> Result[str, Exception]:
        return Ok("Handled")


class AnotherQuery(Request[Result[int, Exception]]):
    pass


@pytest.mark.anyio
async def test_registry_decorator_registers_and_sends() -> None:
    registry = HandlerRegistry()

    assert registry.handler(MyQueryHandler) is MyQueryHandler

    mediator = Mediator(Injector(), registry)
    assert await mediator.send_async(MyQuery()).unwrap() == "Handled"


@pytest.mark.anyio
async def test_mediator_reports_an_unregistered_request(
    mediator: Mediator,
) -> None:
    with pytest.raises(
        HandlerNotFoundError, match="Handler not found for request type"
    ):
        await mediator.send_async(AnotherQuery())


class AbstractQuery(Request[Result[str, Exception]]):
    pass


class AbstractQueryHandler(RequestHandler[AbstractQuery, Result[str, Exception]]):
    @abstractmethod
    def required_dependency(self) -> str:
        """Keep this handler abstract even though handle has a body."""

    @override
    async def handle(self, request: AbstractQuery) -> Result[str, Exception]:
        return Ok(self.required_dependency())


RequestT = TypeVar("RequestT", bound=Request[Any])


class GenericHandler(
    RequestHandler[RequestT, Result[str, Exception]], Generic[RequestT]
):
    @abstractmethod
    async def handle(self, request: RequestT) -> Result[str, Exception]:
        pass


class GenericQuery(Request[Result[str, Exception]]):
    pass


class ConcreteGenericHandler(GenericHandler[GenericQuery]):
    @override
    async def handle(self, request: GenericQuery) -> Result[str, Exception]:
        return Ok("Concrete generic handler")


@pytest.mark.anyio
async def test_decorator_resolves_a_concrete_intermediate_generic_handler() -> None:
    registry = HandlerRegistry()
    registry.handler(ConcreteGenericHandler)

    mediator = Mediator(Injector(), registry)
    assert (
        await mediator.send_async(GenericQuery()).unwrap() == "Concrete generic handler"
    )


def test_decorator_rejects_handlers_without_a_concrete_contract() -> None:
    registry = HandlerRegistry()

    with pytest.raises(InvalidHandlerError, match="concrete RequestHandler"):
        registry.handler(cast(Any, object))

    with pytest.raises(InvalidHandlerError, match="abstract"):
        registry.handler(AbstractQueryHandler)

    HandlerResultT = TypeVar("HandlerResultT", bound=Result[Any, Any])

    class GenericResultHandler(
        RequestHandler[AnotherQuery, HandlerResultT], Generic[HandlerResultT]
    ):
        @override
        async def handle(self, request: AnotherQuery) -> HandlerResultT:
            raise NotImplementedError

    with pytest.raises(InvalidHandlerError, match="concrete RequestHandler"):
        registry.handler(cast(Any, GenericResultHandler))


def test_duplicate_registration_is_rejected_at_registration_time() -> None:
    class DuplicateQuery(Request[Result[str, Exception]]):
        pass

    class FirstHandler(RequestHandler[DuplicateQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: DuplicateQuery) -> Result[str, Exception]:
            return Ok("first")

    class SecondHandler(RequestHandler[DuplicateQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: DuplicateQuery) -> Result[str, Exception]:
            return Ok("second")

    registry = HandlerRegistry()
    registry.handler(FirstHandler)

    with pytest.raises(DuplicateHandlerError, match="Multiple handlers"):
        registry.handler(SecondHandler)


def test_registration_validation_and_explicit_replacement(mediator: Mediator) -> None:
    class Query(Request[Result[str, Exception]]):
        pass

    class QueryHandler(RequestHandler[Query, Result[str, Exception]]):
        @override
        async def handle(self, request: Query) -> Result[str, Exception]:
            return Ok("first")

    class OtherQuery(Request[Result[str, Exception]]):
        pass

    class OtherHandler(RequestHandler[OtherQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: OtherQuery) -> Result[str, Exception]:
            return Ok("other")

    with pytest.raises(InvalidHandlerError, match="request_type"):
        mediator.register(cast(Any, object), QueryHandler)
    with pytest.raises(InvalidHandlerError, match="RequestHandler"):
        mediator.register(Query, cast(Any, object))
    with pytest.raises(InvalidHandlerError, match="declared"):
        mediator.register(Query, cast(Any, OtherHandler))
    with pytest.raises(InvalidHandlerError, match="abstract"):
        mediator.register(AbstractQuery, AbstractQueryHandler)
    with pytest.raises(HandlerNotFoundError):
        mediator.replace(Query, QueryHandler)

    mediator.register(Query, QueryHandler)

    with pytest.raises(DuplicateHandlerError):
        mediator.register(Query, QueryHandler)

    class ReplacementHandler(RequestHandler[Query, Result[str, Exception]]):
        @override
        async def handle(self, request: Query) -> Result[str, Exception]:
            return Ok("replacement")

    mediator.replace(Query, ReplacementHandler)


def test_inconsistent_result_type_is_rejected(mediator: Mediator) -> None:
    class NumberQuery(Request[Result[int, Exception]]):
        pass

    class WrongResultHandler(RequestHandler[NumberQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: NumberQuery) -> Result[str, Exception]:
            return Ok("wrong")

    with pytest.raises(InvalidHandlerError, match="result type"):
        mediator.register(NumberQuery, WrongResultHandler)


def test_non_result_handler_contract_is_rejected_at_registration() -> None:
    class Query(Request[Result[str, Exception]]):
        pass

    class PlainHandler(RequestHandler[Query, Any]):
        @override
        async def handle(self, request: Query) -> Any:
            return "plain value"

    with pytest.raises(InvalidHandlerError, match="flow_res.Result"):
        HandlerRegistry().handler(PlainHandler)


def test_non_result_request_contract_is_rejected_at_registration() -> None:
    class Query(Request[Any]):
        pass

    class QueryHandler(RequestHandler[Query, Result[str, Exception]]):
        @override
        async def handle(self, request: Query) -> Result[str, Exception]:
            return Ok("result")

    with pytest.raises(InvalidHandlerError, match="flow_res.Result"):
        HandlerRegistry().handler(QueryHandler)


@pytest.mark.anyio
async def test_separate_registries_isolate_handlers_for_the_same_request() -> None:
    class SharedQuery(Request[Result[str, Exception]]):
        pass

    class FirstHandler(RequestHandler[SharedQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: SharedQuery) -> Result[str, Exception]:
            return Ok("first")

    class SecondHandler(RequestHandler[SharedQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: SharedQuery) -> Result[str, Exception]:
            return Ok("second")

    first_registry = HandlerRegistry()
    first_registry.handler(FirstHandler)
    second_registry = HandlerRegistry()
    second_registry.handler(SecondHandler)

    first = Mediator(Injector(), first_registry)
    second = Mediator(Injector(), second_registry)

    assert await first.send_async(SharedQuery()).unwrap() == "first"
    assert await second.send_async(SharedQuery()).unwrap() == "second"


@pytest.mark.anyio
async def test_registry_is_a_live_reference() -> None:
    class LateQuery(Request[Result[str, Exception]]):
        pass

    class FirstHandler(RequestHandler[LateQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: LateQuery) -> Result[str, Exception]:
            return Ok("first")

    class SecondHandler(RequestHandler[LateQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: LateQuery) -> Result[str, Exception]:
            return Ok("second")

    registry = HandlerRegistry()
    mediator = Mediator(Injector(), registry)

    registry.handler(FirstHandler)
    assert await mediator.send_async(LateQuery()).unwrap() == "first"

    registry.replace(LateQuery, SecondHandler)
    assert await mediator.send_async(LateQuery()).unwrap() == "second"


@pytest.mark.anyio
async def test_default_registries_are_private_to_each_mediator() -> None:
    first = Mediator(Injector())
    second = Mediator(Injector())
    first.register(MyQuery, MyQueryHandler)

    assert await first.send_async(MyQuery()).unwrap() == "Handled"
    with pytest.raises(HandlerNotFoundError):
        await second.send_async(MyQuery())


class Dependency:
    def __init__(self, value: str) -> None:
        self.value = value


class DependencyModule(Module):
    def __init__(self, value: str) -> None:
        self.value = value

    def configure(self, binder: Any) -> None:
        binder.bind(Dependency, to=Dependency(self.value))


class LifecycleQuery(Request[Result[str, Exception]]):
    pass


class LifecycleHandler(RequestHandler[LifecycleQuery, Result[str, Exception]]):
    @inject
    def __init__(self, dependency: Dependency) -> None:
        self.dependency = dependency

    @override
    async def handle(self, request: LifecycleQuery) -> Result[str, Exception]:
        return Ok(self.dependency.value)


@pytest.mark.anyio
async def test_pending_send_uses_its_mediator_instance() -> None:
    registry = HandlerRegistry()
    registry.handler(LifecycleHandler)
    first = Mediator(Injector([DependencyModule("first")]), registry)
    second = Mediator(Injector([DependencyModule("second")]), registry)

    pending = first.send_async(LifecycleQuery())
    del second

    assert await pending.unwrap() == "first"


@pytest.mark.anyio
async def test_mediator_register_and_replace_delegate_to_its_registry(
    mediator: Mediator,
) -> None:
    class Query(Request[Result[str, Exception]]):
        pass

    class FirstHandler(RequestHandler[Query, Result[str, Exception]]):
        @override
        async def handle(self, request: Query) -> Result[str, Exception]:
            return Ok("first")

    class SecondHandler(RequestHandler[Query, Result[str, Exception]]):
        @override
        async def handle(self, request: Query) -> Result[str, Exception]:
            return Ok("second")

    mediator.register(Query, FirstHandler)
    assert await mediator.send_async(Query()).unwrap() == "first"

    mediator.replace(Query, SecondHandler)
    assert await mediator.send_async(Query()).unwrap() == "second"


def test_generic_introspection_handles_non_matching_and_nested_types() -> None:
    assert _find_generic_base(object, RequestHandler) is None

    NestedTypeT = cast(Any, TypeVar("NestedTypeT"))
    assert _resolve_type(list[NestedTypeT], {NestedTypeT: str}) == list[str]
