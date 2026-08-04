"""Type-safe request/response mediation with dependency injection."""

from abc import ABC, abstractmethod
from collections.abc import Callable
import inspect
import logging
import threading
from typing import Any, TypeVar, cast, get_args, get_origin

from flow_res import AwaitableResult, Err, Result
from injector import Injector

logger = logging.getLogger(__name__)


class Request[R: Result[Any, Any]]:
    """Base class for all requests.

    ``R`` is the exact :class:`flow_res.Result` type returned by the request's
    handler.
    """

    pass


class RequestHandler[T: Request[Any], R: Result[Any, Any]](ABC):
    """Base class for request handlers.

    ``R`` must be a :class:`flow_res.Result` type.
    Concrete subclasses are registered with an application-owned
    :class:`HandlerRegistry`.
    """

    @abstractmethod
    async def handle(self, request: T) -> R:
        """Handle the given request."""
        pass


class HandlerRegistry:
    """Store validated request-handler mappings for one application scope.

    Lookup prefers an exact request-type mapping and otherwise follows the
    request class's method resolution order (MRO).
    """

    def __init__(self) -> None:
        self._request_handlers: dict[
            type[Request[Any]], type[RequestHandler[Any, Any]]
        ] = {}
        self._request_handlers_lock = threading.RLock()

    def handler[
        T: Request[Any],
        R: Result[Any, Any],
    ](self, handler_type: type[RequestHandler[T, R]]) -> type[RequestHandler[T, R]]:
        """Register ``handler_type`` by inferring its concrete request contract."""

        contract = _handler_contract(handler_type)
        if contract is None:
            raise InvalidHandlerError(
                handler_type,
                "handler must declare a concrete RequestHandler request/result contract",
            )
        request_type, _ = contract
        self.register(cast(type[T], request_type), handler_type)
        return handler_type

    def register[
        T: Request[Any],
        R: Result[Any, Any],
    ](self, request_type: type[T], handler_type: type[RequestHandler[T, R]]) -> None:
        """Register a handler, rejecting invalid or duplicate contracts."""

        self._validate_request_type(request_type)
        self._validate_handler_type(request_type, handler_type)
        with self._request_handlers_lock:
            existing = self._request_handlers.get(request_type)
            if existing is not None:
                raise DuplicateHandlerError(request_type, existing, handler_type)
            self._request_handlers[request_type] = handler_type

        logger.debug("HandlerRegistry.register: %s -> %s", request_type, handler_type)

    def replace[
        T: Request[Any],
        R: Result[Any, Any],
    ](self, request_type: type[T], handler_type: type[RequestHandler[T, R]]) -> None:
        """Replace an existing handler mapping explicitly."""

        self._validate_request_type(request_type)
        self._validate_handler_type(request_type, handler_type)
        with self._request_handlers_lock:
            if request_type not in self._request_handlers:
                raise HandlerNotFoundError(request_type)
            self._request_handlers[request_type] = handler_type

        logger.debug("HandlerRegistry.replace: %s -> %s", request_type, handler_type)

    def _handler_for(
        self, request_type: type[Request[Any]]
    ) -> type[RequestHandler[Any, Any]] | None:
        """Find the exact handler or the first registered MRO base handler.

        The registry lock protects only the mapping read and is released
        before the mediator asks the injector to construct or invoke a
        handler.
        """
        request_result = _request_result_type(request_type)
        with self._request_handlers_lock:
            for candidate_type in request_type.__mro__:
                handler_type = self._request_handlers.get(candidate_type)
                if handler_type is None:
                    continue

                contract = _handler_contract(handler_type)
                if contract is None or contract[1] != request_result:
                    handler_result = None if contract is None else contract[1]
                    raise InvalidHandlerError(
                        handler_type,
                        f"handler result type {handler_result!r} does not match "
                        f"request result type {request_result!r} for {request_type!r}",
                    )
                return handler_type
        return None

    def _validate_request_type(self, request_type: type[Any]) -> None:
        if not isinstance(request_type, type) or not issubclass(request_type, Request):
            raise InvalidHandlerError(
                request_type, "request_type must be a Request subclass"
            )

    def _validate_handler_type(
        self,
        request_type: type[Request[Any]],
        handler_type: type[RequestHandler[Any, Any]],
    ) -> None:
        if not isinstance(handler_type, type) or not issubclass(
            handler_type, RequestHandler
        ):
            raise InvalidHandlerError(
                handler_type, "handler_type must be a RequestHandler subclass"
            )
        if inspect.isabstract(handler_type):
            raise InvalidHandlerError(
                handler_type, "abstract handlers cannot be registered"
            )

        contract = _handler_contract(handler_type)
        if contract is None or contract[0] is not request_type:
            raise InvalidHandlerError(
                handler_type,
                f"handler is declared for {contract[0] if contract else 'an unknown request'}",
            )
        self._validate_result_type(request_type, handler_type, contract[1])

    def _validate_result_type(
        self,
        request_type: type[Request[Any]],
        handler_type: type[RequestHandler[Any, Any]],
        handler_result: Any,
    ) -> None:
        request_result = _request_result_type(request_type)
        if not _is_result_type(request_result):
            raise InvalidHandlerError(
                handler_type,
                "request must declare a flow_res.Result result type",
            )
        if not _is_result_type(handler_result):
            raise InvalidHandlerError(
                handler_type,
                "handler must declare a flow_res.Result result type",
            )
        if request_result != handler_result:
            raise InvalidHandlerError(
                handler_type,
                f"result type {handler_result!r} does not match request result {request_result!r}",
            )


class Mediator:
    """Send requests to handlers resolved from an instance-owned registry."""

    def __init__(
        self, injector: Injector, registry: HandlerRegistry | None = None
    ) -> None:
        self._injector = injector
        self._registry = HandlerRegistry() if registry is None else registry

    def send_async[T, E: Exception](
        self,
        request: Request[Result[T, E]],
        *,
        exception_mapper: Callable[[Exception], E] | None = None,
    ) -> AwaitableResult[T, E]:
        """Send a request and return an awaitable result for method chaining.

        When ``exception_mapper`` is provided, exceptions raised while resolving
        or invoking the handler are returned as ``Err`` values. Without a
        mapper, those exceptions propagate unchanged.
        """

        injector = self._injector

        async def execute() -> Result[T, E]:
            logger.debug("Mediator.send_async: %s", request)
            handler_type = self._registry._handler_for(type(request))
            if handler_type is None:
                raise HandlerNotFoundError(request)

            try:
                handler = injector.get(handler_type)
                result = await handler.handle(request)
            except Exception as exc:
                if exception_mapper is None:
                    raise
                return Err(exception_mapper(exc))
            return cast(Result[T, E], result)

        return AwaitableResult(execute())

    def register[
        T: Request[Any],
        R: Result[Any, Any],
    ](self, request_type: type[T], handler_type: type[RequestHandler[T, R]]) -> None:
        """Register a handler in this mediator's live registry."""

        self._registry.register(request_type, handler_type)

    def replace[
        T: Request[Any],
        R: Result[Any, Any],
    ](self, request_type: type[T], handler_type: type[RequestHandler[T, R]]) -> None:
        """Replace a handler in this mediator's live registry."""

        self._registry.replace(request_type, handler_type)


def _handler_contract(
    handler_type: type[Any],
) -> tuple[type[Request[Any]], Any] | None:
    contract = _find_generic_base(handler_type, RequestHandler)
    if contract is None or len(contract) != 2:
        return None
    request_type, result_type = contract
    if not isinstance(request_type, type) or not issubclass(request_type, Request):
        return None
    if _contains_typevar(result_type):
        return None
    return cast(type[Request[Any]], request_type), result_type


def _request_result_type(request_type: type[Any]) -> Any | None:
    contract = _find_generic_base(request_type, Request)
    return None if contract is None else contract[0]


def _is_result_type(value: Any) -> bool:
    return get_origin(value) is Result


def _find_generic_base(cls: type[Any], target: type[Any]) -> tuple[Any, ...] | None:
    """Resolve a target generic base while substituting intermediate TypeVars."""

    contracts: list[tuple[Any, ...]] = []
    unresolved_path = False

    def visit(current: type[Any], substitutions: dict[TypeVar, Any]) -> None:
        nonlocal unresolved_path

        for base in getattr(current, "__orig_bases__", ()):
            origin = get_origin(base) or base
            is_target = origin is target
            is_target_subclass = isinstance(origin, type) and issubclass(origin, target)
            if not is_target and not is_target_subclass:
                continue

            args = get_args(base)
            parameters = getattr(origin, "__parameters__", ())
            local_substitutions = dict(substitutions)
            resolved_args: list[Any] = []
            path_is_resolved = True

            for argument in args:
                resolved_argument = _resolve_type(argument, substitutions)
                if resolved_argument is None:
                    unresolved_path = True
                    path_is_resolved = False
                    break
                resolved_args.append(resolved_argument)
            if not path_is_resolved:
                continue
            for parameter, resolved_argument in zip(
                parameters, resolved_args, strict=False
            ):
                local_substitutions[parameter] = resolved_argument

            if is_target:
                contracts.append(tuple(resolved_args))
            else:
                visit(origin, local_substitutions)

    visit(cls, {})
    if unresolved_path or not contracts:
        return None

    first_contract = contracts[0]
    if any(contract != first_contract for contract in contracts[1:]):
        return None
    return first_contract


def _resolve_type(value: Any, substitutions: dict[TypeVar, Any]) -> Any:
    seen_typevars: set[TypeVar] = set()
    while isinstance(value, TypeVar):
        if value not in substitutions or value in seen_typevars:
            return None
        seen_typevars.add(value)
        replacement = substitutions[value]
        value = replacement
    args = get_args(value)
    if not args:
        return value

    resolved_args_list: list[Any] = []
    for argument in args:
        resolved_argument = _resolve_type(argument, substitutions)
        if resolved_argument is None:
            return None
        resolved_args_list.append(resolved_argument)
    resolved_args = tuple(resolved_args_list)
    if resolved_args == args:
        return value

    origin = get_origin(value)
    if origin is None:
        return None
    try:
        return origin[resolved_args[0] if len(resolved_args) == 1 else resolved_args]
    except (AttributeError, TypeError):
        return None


def _contains_typevar(value: Any) -> bool:
    if isinstance(value, TypeVar):
        return True
    return any(_contains_typevar(argument) for argument in get_args(value))


class MediatorError(Exception):
    """Base error for Mediator."""


class HandlerNotFoundError(MediatorError):
    """Raised when no handler is found for a request."""

    def __init__(self, target: Any) -> None:
        request_type = target if isinstance(target, type) else type(target)
        super().__init__(f"Handler not found for request type: {request_type}")


class HandlerRegistrationError(MediatorError):
    """Raised when a handler registration violates the mediator contract."""


class InvalidHandlerError(HandlerRegistrationError):
    """Raised for an invalid, abstract, or type-inconsistent handler."""

    def __init__(self, handler_type: Any, reason: str) -> None:
        super().__init__(f"Invalid handler {handler_type!r}: {reason}")


class DuplicateHandlerError(HandlerRegistrationError):
    """Raised when more than one handler claims the same request type."""

    def __init__(
        self,
        request_type: type[Any],
        existing: type[Any],
        duplicate: type[Any] | None = None,
    ) -> None:
        duplicate_text = f" and {duplicate!r}" if duplicate is not None else ""
        super().__init__(
            f"Multiple handlers registered for {request_type!r}: {existing!r}{duplicate_text}"
        )


__all__ = [
    "DuplicateHandlerError",
    "HandlerRegistry",
    "HandlerNotFoundError",
    "HandlerRegistrationError",
    "InvalidHandlerError",
    "Mediator",
    "MediatorError",
    "Request",
    "RequestHandler",
]
