"""Behavioral regression tests for the instance-based Mediator API."""

from abc import abstractmethod
from typing import Any, Generic, TypeVar, cast, override

import pytest
from flow_res import Ok, Result
from injector import Injector, Module, inject

from flow_med import (
    DuplicateHandlerError,
    HandlerNotFoundError,
    InvalidHandlerError,
    Mediator,
    Request,
    RequestHandler,
)
from flow_med.mediator import _find_generic_base, _resolve_type


class MyQuery(Request[Result[str, Exception]]):
    pass


class MyQueryHandler(RequestHandler[MyQuery, Result[str, Exception]]):
    @override
    async def handle(self, request: MyQuery) -> Result[str, Exception]:
        return Ok("Handled")


class AnotherQuery(Request[Result[int, Exception]]):
    pass


@pytest.mark.anyio
async def test_mediator_sends_to_an_auto_registered_handler(
    mediator: Mediator,
) -> None:
    result = await mediator.send_async(MyQuery()).unwrap()

    assert result == "Handled"


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


@pytest.mark.anyio
async def test_abstract_handler_is_not_auto_registered(
    mediator: Mediator,
) -> None:
    with pytest.raises(HandlerNotFoundError):
        await mediator.send_async(AbstractQuery())


RequestT = TypeVar("RequestT", bound=Request[Any])


class GenericHandler(
    RequestHandler[RequestT, Result[str, Exception]], Generic[RequestT]
):
    """Intermediate generic handler; it must not be registered by its TypeVar."""

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
async def test_concrete_handler_through_generic_base_is_auto_registered(
    mediator: Mediator,
) -> None:
    result = await mediator.send_async(GenericQuery()).unwrap()

    assert result == "Concrete generic handler"


@pytest.mark.anyio
async def test_duplicate_manual_registration_is_rejected(
    mediator: Mediator,
) -> None:
    """A second registration must not silently change the selected handler."""

    class DuplicateQuery(Request[Result[str, Exception]]):
        pass

    class DuplicateQueryHandler(RequestHandler[DuplicateQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: DuplicateQuery) -> Result[str, Exception]:
            return Ok("first")

    mediator.register(DuplicateQuery, DuplicateQueryHandler)

    with pytest.raises(DuplicateHandlerError, match="Multiple handlers"):
        mediator.register(DuplicateQuery, DuplicateQueryHandler)

    assert await mediator.send_async(DuplicateQuery()).unwrap() == "first"


def test_registration_validation_and_explicit_replacement(mediator: Mediator) -> None:
    class DuplicateQuery(Request[Result[str, Exception]]):
        pass

    class DuplicateQueryHandler(RequestHandler[DuplicateQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: DuplicateQuery) -> Result[str, Exception]:
            return Ok("first")

    class OtherQuery(Request[Result[str, Exception]]):
        pass

    class OtherHandler(RequestHandler[OtherQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: OtherQuery) -> Result[str, Exception]:
            return Ok("other")

    with pytest.raises(InvalidHandlerError, match="request_type"):
        mediator.register(cast(Any, object), DuplicateQueryHandler)
    with pytest.raises(InvalidHandlerError, match="RequestHandler"):
        mediator.register(DuplicateQuery, cast(Any, object))
    with pytest.raises(InvalidHandlerError, match="declared"):
        mediator.register(DuplicateQuery, cast(Any, OtherHandler))
    with pytest.raises(InvalidHandlerError, match="abstract"):
        mediator.register(AbstractQuery, AbstractQueryHandler)
    with pytest.raises(HandlerNotFoundError):
        mediator.replace(DuplicateQuery, DuplicateQueryHandler)

    mediator.register(DuplicateQuery, DuplicateQueryHandler)

    class ReplacementHandler(RequestHandler[DuplicateQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: DuplicateQuery) -> Result[str, Exception]:
            return Ok("replacement")

    mediator.replace(DuplicateQuery, ReplacementHandler)


@pytest.mark.anyio
async def test_duplicate_auto_handlers_are_rejected(mediator: Mediator) -> None:
    class AutoDuplicateQuery(Request[Result[str, Exception]]):
        pass

    class FirstHandler(RequestHandler[AutoDuplicateQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: AutoDuplicateQuery) -> Result[str, Exception]:
            return Ok("first")

    class SecondHandler(RequestHandler[AutoDuplicateQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: AutoDuplicateQuery) -> Result[str, Exception]:
            return Ok("second")

    class MalformedHandler(RequestHandler):
        async def handle(self, request: Any) -> Any:
            return None

    class InvalidRequestHandler(RequestHandler[Any, Any]):
        async def handle(self, request: Any) -> Any:
            return None

    ResultT = TypeVar("ResultT")

    class GenericResultHandler(
        RequestHandler[AutoDuplicateQuery, ResultT], Generic[ResultT]
    ):
        async def handle(self, request: AutoDuplicateQuery) -> ResultT:
            raise NotImplementedError

    with pytest.raises(DuplicateHandlerError, match="Multiple handlers"):
        await mediator.send_async(AutoDuplicateQuery())


@pytest.mark.anyio
async def test_inconsistent_result_type_is_rejected_on_manual_registration(
    mediator: Mediator,
) -> None:
    class NumberQuery(Request[Result[int, Exception]]):
        pass

    class WrongResultHandler(RequestHandler[NumberQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: NumberQuery) -> Result[str, Exception]:
            return Ok("wrong")

    with pytest.raises(InvalidHandlerError, match="result type"):
        mediator.register(NumberQuery, WrongResultHandler)


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


def test_mediators_have_independent_injectors_and_registries() -> None:
    first = Mediator(Injector([DependencyModule("first")]))
    second = Mediator(Injector([DependencyModule("second")]))

    assert first is not second


@pytest.mark.anyio
async def test_pending_send_uses_its_mediator_instance(
    mediator: Mediator,
) -> None:
    first = Mediator(Injector([DependencyModule("first")]))
    second = Mediator(Injector([DependencyModule("second")]))

    pending = first.send_async(LifecycleQuery())
    del second

    assert await pending.unwrap() == "first"


@pytest.mark.anyio
async def test_manual_registration_and_explicit_replace(
    mediator: Mediator,
) -> None:
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

    mediator.register(LateQuery, FirstHandler)
    assert await mediator.send_async(LateQuery()).unwrap() == "first"

    mediator.replace(LateQuery, SecondHandler)
    assert await mediator.send_async(LateQuery()).unwrap() == "second"


def test_invalid_manual_registration_is_rejected(mediator: Mediator) -> None:
    with pytest.raises(InvalidHandlerError, match="Request subclass"):
        mediator.register(cast(Any, object), cast(Any, object))

    with pytest.raises(InvalidHandlerError, match="RequestHandler subclass"):
        mediator.register(AnotherQuery, cast(Any, object))

    class AbstractManualHandler(RequestHandler[AnotherQuery, Result[int, Exception]]):
        @abstractmethod
        def dependency(self) -> None:
            pass

        @override
        async def handle(self, request: AnotherQuery) -> Result[int, Exception]:
            return Ok(1)

    with pytest.raises(InvalidHandlerError, match="abstract"):
        mediator.register(AnotherQuery, AbstractManualHandler)

    class OtherQuery(Request[Result[int, Exception]]):
        pass

    class OtherHandler(RequestHandler[OtherQuery, Result[int, Exception]]):
        @override
        async def handle(self, request: OtherQuery) -> Result[int, Exception]:
            return Ok(1)

    with pytest.raises(InvalidHandlerError, match="declared for"):
        mediator.register(AnotherQuery, cast(Any, OtherHandler))


@pytest.mark.anyio
async def test_handlers_without_concrete_generic_contract_are_ignored(
    mediator: Mediator,
) -> None:
    class IncompleteHandler(RequestHandler):
        @override
        async def handle(self, request: Any) -> Any:
            return None

    HandlerResultT = TypeVar("HandlerResultT")

    class TypeVarResultHandler(RequestHandler[AnotherQuery, HandlerResultT]):
        @override
        async def handle(self, request: AnotherQuery) -> HandlerResultT:
            raise NotImplementedError

    with pytest.raises(HandlerNotFoundError):
        await mediator.send_async(AnotherQuery())


def test_generic_introspection_handles_non_matching_and_nested_types() -> None:
    assert _find_generic_base(object, RequestHandler) is None

    NestedTypeT = cast(Any, TypeVar("NestedTypeT"))
    assert _resolve_type(list[NestedTypeT], {NestedTypeT: str}) == list[str]
