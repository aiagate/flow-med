"""Behavioral regression tests for scoped handler registries."""

import asyncio
from abc import abstractmethod
from concurrent.futures import ThreadPoolExecutor
import threading
from typing import Any, Generic, TypeVar, cast, override

import flow_med
import flow_med.mediator
import pytest
from flow_res import Err, Ok, Result
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


@pytest.mark.anyio
async def test_base_handler_handles_subclass_request() -> None:
    class BaseQuery(Request[Result[str, Exception]]):
        pass

    class ChildQuery(BaseQuery):
        pass

    class BaseQueryHandler(RequestHandler[BaseQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: BaseQuery) -> Result[str, Exception]:
            return Ok("base")

    registry = HandlerRegistry()
    registry.handler(BaseQueryHandler)

    mediator = Mediator(Injector(), registry)
    assert await mediator.send_async(ChildQuery()).unwrap() == "base"


@pytest.mark.anyio
async def test_exact_handler_takes_precedence_over_base_handler() -> None:
    class BaseQuery(Request[Result[str, Exception]]):
        pass

    class ChildQuery(BaseQuery):
        pass

    class BaseQueryHandler(RequestHandler[BaseQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: BaseQuery) -> Result[str, Exception]:
            return Ok("base")

    class ChildQueryHandler(RequestHandler[ChildQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: ChildQuery) -> Result[str, Exception]:
            return Ok("exact")

    registry = HandlerRegistry()
    registry.handler(BaseQueryHandler)
    registry.handler(ChildQueryHandler)

    mediator = Mediator(Injector(), registry)
    assert await mediator.send_async(ChildQuery()).unwrap() == "exact"


@pytest.mark.anyio
async def test_unregistered_request_hierarchy_raises_handler_not_found() -> None:
    class BaseQuery(Request[Result[str, Exception]]):
        pass

    class ChildQuery(BaseQuery):
        pass

    with pytest.raises(HandlerNotFoundError, match="ChildQuery"):
        await Mediator(Injector()).send_async(ChildQuery())


@pytest.mark.anyio
async def test_multiple_inheritance_uses_python_mro_for_handler_selection() -> None:
    class LeftQuery(Request[Result[str, Exception]]):
        pass

    class RightQuery(Request[Result[str, Exception]]):
        pass

    class CombinedQuery(LeftQuery, RightQuery):
        pass

    class LeftQueryHandler(RequestHandler[LeftQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: LeftQuery) -> Result[str, Exception]:
            return Ok("left")

    class RightQueryHandler(RequestHandler[RightQuery, Result[str, Exception]]):
        @override
        async def handle(self, request: RightQuery) -> Result[str, Exception]:
            return Ok("right")

    registry = HandlerRegistry()
    registry.handler(RightQueryHandler)
    registry.handler(LeftQueryHandler)

    mediator = Mediator(Injector(), registry)
    assert await mediator.send_async(CombinedQuery()).unwrap() == "left"


@pytest.mark.anyio
async def test_inheritance_dispatch_rejects_incompatible_result_contract() -> None:
    class TextQuery(Request[Result[str, Exception]]):
        pass

    class NumberQuery(Request[Result[int, Exception]]):
        pass

    class NumberQueryHandler(RequestHandler[NumberQuery, Result[int, Exception]]):
        @override
        async def handle(self, request: NumberQuery) -> Result[int, Exception]:
            return Ok(1)

    registry = HandlerRegistry()
    registry.handler(NumberQueryHandler)
    mediator = Mediator(Injector(), registry)

    ConflictingQuery = cast(
        type[Request[Result[str, Exception]]],
        type("ConflictingQuery", (TextQuery, NumberQuery), {}),
    )

    with pytest.raises(InvalidHandlerError, match="result type"):
        await mediator.send_async(ConflictingQuery())


@pytest.mark.anyio
async def test_handler_exception_propagates_without_exception_mapper() -> None:
    class HandlerFailure(Exception):
        pass

    class Query(Request[Result[str, HandlerFailure]]):
        pass

    class Handler(RequestHandler[Query, Result[str, HandlerFailure]]):
        @override
        async def handle(self, request: Query) -> Result[str, HandlerFailure]:
            raise RuntimeError("handler failed")

    mediator = Mediator(Injector())
    mediator.register(Query, Handler)

    with pytest.raises(RuntimeError, match="handler failed"):
        await mediator.send_async(Query())


@pytest.mark.anyio
async def test_handler_exception_can_be_mapped_to_err() -> None:
    class HandlerFailure(Exception):
        pass

    class Query(Request[Result[str, HandlerFailure]]):
        pass

    class Handler(RequestHandler[Query, Result[str, HandlerFailure]]):
        @override
        async def handle(self, request: Query) -> Result[str, HandlerFailure]:
            raise RuntimeError("handler failed")

    mediator = Mediator(Injector())
    mediator.register(Query, Handler)

    result = await mediator.send_async(
        Query(),
        exception_mapper=lambda exc: HandlerFailure(str(exc)),
    )

    assert isinstance(result, Err)
    assert isinstance(result.error, HandlerFailure)
    assert str(result.error) == "handler failed"


@pytest.mark.anyio
async def test_injector_exception_can_be_mapped_to_err() -> None:
    class InjectorFailure(Exception):
        pass

    class Query(Request[Result[str, InjectorFailure]]):
        pass

    class Handler(RequestHandler[Query, Result[str, InjectorFailure]]):
        def __init__(self) -> None:
            raise RuntimeError("injector failed")

        @override
        async def handle(self, request: Query) -> Result[str, InjectorFailure]:
            return Ok("unreachable")

    mediator = Mediator(Injector())
    mediator.register(Query, Handler)

    result = await mediator.send_async(
        Query(),
        exception_mapper=lambda exc: InjectorFailure(str(exc)),
    )

    assert isinstance(result, Err)
    assert isinstance(result.error, InjectorFailure)
    assert str(result.error) == "injector failed"


@pytest.mark.anyio
async def test_exception_mapper_exception_propagates() -> None:
    class MapperFailure(Exception):
        pass

    class Query(Request[Result[str, MapperFailure]]):
        pass

    class Handler(RequestHandler[Query, Result[str, MapperFailure]]):
        @override
        async def handle(self, request: Query) -> Result[str, MapperFailure]:
            raise RuntimeError("handler failed")

    def mapper(exc: Exception) -> MapperFailure:
        raise MapperFailure(f"could not map: {exc}")

    mediator = Mediator(Injector())
    mediator.register(Query, Handler)

    with pytest.raises(MapperFailure, match="could not map: handler failed"):
        await mediator.send_async(Query(), exception_mapper=mapper)


@pytest.mark.anyio
async def test_existing_err_is_returned_unchanged_with_exception_mapper() -> None:
    class ExistingFailure(Exception):
        pass

    existing_error = ExistingFailure("already an Err")

    class Query(Request[Result[str, ExistingFailure]]):
        pass

    class Handler(RequestHandler[Query, Result[str, ExistingFailure]]):
        @override
        async def handle(self, request: Query) -> Result[str, ExistingFailure]:
            return Err(existing_error)

    def mapper(exc: Exception) -> ExistingFailure:
        raise AssertionError("the mapper must not run for an existing Err")

    mediator = Mediator(Injector())
    mediator.register(Query, Handler)

    result = await mediator.send_async(Query(), exception_mapper=mapper)

    assert isinstance(result, Err)
    assert result.error is existing_error


@pytest.mark.anyio
async def test_unregistered_request_is_not_mapped() -> None:
    def mapper(exc: Exception) -> Exception:
        raise AssertionError("the mapper must not run for an unregistered request")

    with pytest.raises(HandlerNotFoundError):
        await Mediator(Injector()).send_async(AnotherQuery(), exception_mapper=mapper)


@pytest.mark.anyio
async def test_cancelled_error_is_not_mapped() -> None:
    class Query(Request[Result[str, Exception]]):
        pass

    class Handler(RequestHandler[Query, Result[str, Exception]]):
        @override
        async def handle(self, request: Query) -> Result[str, Exception]:
            raise asyncio.CancelledError

    def mapper(exc: Exception) -> Exception:
        raise AssertionError("CancelledError must not be mapped")

    mediator = Mediator(Injector())
    mediator.register(Query, Handler)

    with pytest.raises(asyncio.CancelledError):
        await mediator.send_async(Query(), exception_mapper=mapper)


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


def test_decorator_rejects_ambiguous_handler_contract() -> None:
    class TextHandlerBase(
        Generic[RequestT], RequestHandler[RequestT, Result[str, Exception]]
    ):
        async def handle(self, request: RequestT) -> Result[str, Exception]:
            return Ok("text")

    class NumberHandlerBase(
        Generic[RequestT], RequestHandler[RequestT, Result[int, Exception]]
    ):
        async def handle(self, request: RequestT) -> Result[int, Exception]:
            return Ok(1)

    class AmbiguousHandler(  # pyright: ignore[reportGeneralTypeIssues, reportIncompatibleMethodOverride]
        TextHandlerBase[GenericQuery], NumberHandlerBase[GenericQuery]
    ):
        pass

    with pytest.raises(InvalidHandlerError, match="concrete RequestHandler"):
        HandlerRegistry().handler(cast(Any, AmbiguousHandler))


def test_decorator_allows_duplicate_handler_contract_paths() -> None:
    class FirstHandlerBase(
        Generic[RequestT], RequestHandler[RequestT, Result[str, Exception]]
    ):
        async def handle(self, request: RequestT) -> Result[str, Exception]:
            return Ok("first")

    class SecondHandlerBase(
        Generic[RequestT], RequestHandler[RequestT, Result[str, Exception]]
    ):
        async def handle(self, request: RequestT) -> Result[str, Exception]:
            return Ok("second")

    class DuplicateContractHandler(
        FirstHandlerBase[GenericQuery], SecondHandlerBase[GenericQuery]
    ):
        pass

    registry = HandlerRegistry()
    registry.handler(cast(Any, DuplicateContractHandler))


def test_decorator_rejects_ambiguous_request_contract() -> None:
    BranchT = TypeVar("BranchT")

    class TextRequestBase(Generic[BranchT], Request[Result[str, Exception]]):
        pass

    class NumberRequestBase(Generic[BranchT], Request[Result[int, Exception]]):
        pass

    class AmbiguousRequest(  # pyright: ignore[reportGeneralTypeIssues]
        TextRequestBase[object], NumberRequestBase[object]
    ):
        pass

    class AmbiguousRequestHandler(
        RequestHandler[AmbiguousRequest, Result[str, Exception]]
    ):
        @override
        async def handle(self, request: AmbiguousRequest) -> Result[str, Exception]:
            return Ok("text")

    with pytest.raises(InvalidHandlerError, match="request must declare"):
        HandlerRegistry().handler(AmbiguousRequestHandler)


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


def test_concurrent_unique_registrations_are_safe() -> None:
    worker_count = 16
    start = threading.Barrier(worker_count)
    registry = HandlerRegistry()
    pairs: list[
        tuple[
            type[Request[Any]],
            type[RequestHandler[Any, Result[int, Exception]]],
        ]
    ] = []

    for index in range(worker_count):

        class Query(Request[Result[int, Exception]]):
            pass

        class Handler(RequestHandler[Query, Result[int, Exception]]):
            @override
            async def handle(self, request: Query) -> Result[int, Exception]:
                return Ok(index)

        pairs.append((Query, Handler))

    def register(
        pair: tuple[
            type[Request[Any]],
            type[RequestHandler[Any, Result[int, Exception]]],
        ],
    ) -> None:
        start.wait()
        registry.register(*pair)

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(register, pair) for pair in pairs]
        for future in futures:
            future.result()

    assert all(registry._handler_for(query) is handler for query, handler in pairs)


def test_concurrent_duplicate_registrations_allow_only_one_success() -> None:
    worker_count = 16
    start = threading.Barrier(worker_count)
    registry = HandlerRegistry()

    class Query(Request[Result[int, Exception]]):
        pass

    handlers: list[type[RequestHandler[Query, Result[int, Exception]]]] = []
    for index in range(worker_count):

        class Handler(RequestHandler[Query, Result[int, Exception]]):
            @override
            async def handle(self, request: Query) -> Result[int, Exception]:
                return Ok(index)

        handlers.append(Handler)

    def register(handler: type[RequestHandler[Query, Result[int, Exception]]]) -> bool:
        start.wait()
        try:
            registry.register(Query, handler)
        except DuplicateHandlerError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(register, handler) for handler in handlers]
        successes = [future.result() for future in futures]

    assert sum(successes) == 1
    assert registry._handler_for(Query) in handlers


def test_concurrent_replace_and_lookup_are_safe() -> None:
    registry = HandlerRegistry()
    start = threading.Barrier(2)
    lookup_ready = threading.Event()
    stop = threading.Event()

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

    registry.register(Query, FirstHandler)
    observed: list[type[RequestHandler[Query, Result[str, Exception]]] | None] = []

    def replace() -> None:
        start.wait()
        lookup_ready.wait()
        for index in range(500):
            registry.replace(Query, SecondHandler if index % 2 else FirstHandler)
        stop.set()

    def lookup() -> None:
        start.wait()
        observed.append(registry._handler_for(Query))
        lookup_ready.set()
        while not stop.is_set():
            observed.append(registry._handler_for(Query))

    with ThreadPoolExecutor(max_workers=2) as executor:
        replace_future = executor.submit(replace)
        lookup_future = executor.submit(lookup)
        replace_future.result()
        lookup_future.result()

    assert observed
    assert set(observed) <= {FirstHandler, SecondHandler}


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
    assert _resolve_type(NestedTypeT, {}) is None
    assert _resolve_type(NestedTypeT, {NestedTypeT: NestedTypeT}) is None
    assert _resolve_type(list[NestedTypeT], {}) is None
