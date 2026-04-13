import logging
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from flow_res import AwaitableResult, Result
from injector import Injector

logger = logging.getLogger(__name__)


class Request[R]:
    """Base class for all requests."""

    pass


class RequestHandler[T: Request[Any], R](ABC):
    """Base class for request handlers.

    Subclasses are automatically registered with the Mediator.
    """

    @abstractmethod
    async def handle(self, request: T) -> R:
        """Handle the given request."""
        pass

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Automatically register the handler with the Mediator."""
        super().__init_subclass__(**kwargs)

        # 抽象クラス（実装を持たないクラス）は登録しない
        if getattr(cls, "__abstractmethods__", None):
            return

        # RequestHandler[RequestType, ReturnType] から RequestType を取得
        for base in getattr(cls, "__orig_bases__", []):
            if getattr(base, "__origin__", None) is RequestHandler:
                request_type = base.__args__[0]
                logger.debug("Registering handler: %s -> %s", request_type, cls)
                Mediator.register(request_type, cls)
                break


class Mediator:
    """Mediator for sending requests to their respective handlers."""

    _request_handlers: ClassVar[dict[type[Any], type[Any]]] = {}
    _injector: ClassVar[Injector | None] = None

    @classmethod
    def initialize(cls, injector: Injector) -> None:
        """Initialize mediator with injector.

        This method should be called once at application startup.
        """
        cls._injector = injector

    @classmethod
    def send_async[T, E: Exception](
        cls, request: Request[Result[T, E]]
    ) -> AwaitableResult[T, E]:
        """
        Send a request to its handler.

        Returns AwaitableResult for method chaining.
        """

        async def execute() -> Result[T, E]:
            logger.debug("Mediator.send_async: %s", request)
            if cls._injector is None:
                raise RuntimeError(
                    "Mediator not initialized. Call Mediator.initialize() first."
                )

            handler_type = cls._request_handlers.get(type(request))
            if not handler_type:
                raise HandlerNotFoundError(request)

            handler = cls._injector.get(handler_type)
            return await handler.handle(request)  # type: ignore[no-any-return]

        return AwaitableResult(execute())

    @classmethod
    def register(cls, request_type: type[Any], handler_type: type[Any]) -> None:
        """Manually register a handler for a request type."""
        logger.debug("Mediator.register: %s -> %s", request_type, handler_type)
        cls._request_handlers[request_type] = handler_type


class MediatorError(Exception):
    """Base error for Mediator."""

    pass


class HandlerNotFoundError(MediatorError):
    """Raised when no handler is found for a request."""

    def __init__(self, target: Any) -> None:
        super().__init__(
            f"Handler not found for request type: {type(target)}",
        )


__all__ = [
    "HandlerNotFoundError",
    "Mediator",
    "Request",
    "RequestHandler",
]
