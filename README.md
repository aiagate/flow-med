# flow-med

[![PyPI version](https://badge.fury.io/py/flow-med.svg)](https://badge.fury.io/py/flow-med)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/release/python-3130/)

A high-performance, type-safe Mediator pattern implementation for Python 3.13+, built on top of [flow-res](https://github.com/aiagate/flow-res) and [injector](https://github.com/alecthomas/injector).

## Features

- **Result-Driven Development**: Built-in support for `flow-res` Result types, making error handling explicit and type-safe.
- **Scoped Registration**: Application-owned registries keep handler discovery explicit and isolated.
- **Dependency Injection**: Seamless integration with the `injector` library for robust dependency management.
- **Native Async Support**: Designed from the ground up for `asyncio` with `AwaitableResult` support for elegant method chaining.
- **Strict Type Safety**: Public type contracts are checked by `pyright`, with result-type validation at handler registration.

## Installation

```bash
pip install flow-med
```

## Quick Start

### 1. Define Request and Result

```python
from flow_res import Result
from flow_med import Request

class GetUserRequest(Request[Result[str, Exception]]):
    def __init__(self, user_id: int):
        self.user_id = user_id
```

### 2. Implement Handler

Register concrete handlers with an application-owned `HandlerRegistry`. Use
`@override` to ensure correct implementation.

```python
from typing import override
from flow_res import Ok, Result
from flow_med import HandlerRegistry, RequestHandler

registry = HandlerRegistry()

@registry.handler
class GetUserHandler(RequestHandler[GetUserRequest, Result[str, Exception]]):
    @override
    async def handle(self, request: GetUserRequest) -> Result[str, Exception]:
        # Logic to get user
        return Ok(f"User {request.user_id}")
```

### 3. Create a Mediator and Send

```python
import asyncio
from injector import Injector
from flow_med import Mediator

async def main():
    # Each application owns its Registry, Mediator, and Injector.
    mediator = Mediator(Injector(), registry)

    # Send request and chain results using flow-res
    result = await (
        mediator.send_async(GetUserRequest(user_id=1))
        .map(lambda name: f"Hello, {name}!")
        .unwrap()
    )
    
    print(result) # Hello, User 1!

if __name__ == "__main__":
    asyncio.run(main())
```

Registries are live references. Handlers added or explicitly replaced after a
`Mediator` is created are visible to that mediator. The registry synchronizes
its handler-map operations, so concurrent registration, replacement, and lookup
cannot corrupt the mapping or bypass duplicate/existence checks. Separate
registries are isolated, while sharing a registry explicitly shares its handler
mappings.

## Registration API

`HandlerRegistry` and `Mediator` expose explicit registration operations:

- `registry.handler(Handler)` infers the request type from the concrete
  `RequestHandler[RequestType, ResultType]` contract. It can be used as
  `@registry.handler` or called directly.
- `registry.register(RequestType, Handler)` is useful when the request type
  should be explicit. `mediator.register(...)` delegates to the mediator's
  registry.
- `registry.replace(RequestType, Handler)` intentionally changes an existing
  mapping. `mediator.replace(...)` delegates to the same operation. Replacement
  fails if no mapping exists, while either registration form fails if one
  already exists.

Registration validates that the handler is concrete, is declared for the given
request type, declares the same generic result type as the request, and uses a
`flow_res.Result[T, E]` result contract. Plain result values are rejected by
Pyright and raise `InvalidHandlerError` during dynamic registration. This is a
declaration-level check: `flow-med` does not inspect or validate the value
returned by `handle()` at runtime. Static type checking and the handler
implementation remain responsible for honoring the declared result contract.

When sending a request, `Mediator` asks its `Injector` for the registered
handler type. The injector therefore controls handler construction, dependency
injection, and lifetime according to its bindings and scopes; `Mediator` does
not cache handler instances.

Treat registry setup and mutation as an application-startup concern even though
the individual handler-map operations are synchronized. The lock does not
freeze the live registry or provide a dispatch snapshot: a request may use the
handler selected before a concurrent `replace()`. It also does not make
resolved handlers or their dependencies thread-safe; that remains determined
by those objects and their injector scopes.

## Error behavior

- Sending an unregistered request raises `HandlerNotFoundError` when the
  returned `AwaitableResult` is awaited.
- Registering a second handler for the same request type raises
  `DuplicateHandlerError`. Use `replace()` for an intentional replacement;
  the request type must already be registered.
- Handler lookup first checks the exact `type(request)`. If no exact handler is
  registered, it walks that request class's Python MRO from the concrete class
  toward its bases and uses the first registered request handler. Therefore an
  exact handler always wins over a base handler. For multiple inheritance,
  Python's MRO is the selection rule: for `class Combined(Left, Right)`, a
  handler registered for `Left` wins over one registered for `Right` when no
  exact `Combined` handler exists. Registration order does not affect this
  choice. If no class in the MRO has a handler, `HandlerNotFoundError` is
  raised.
- A base handler can handle subclasses that preserve the request's
  `flow_res.Result[T, E]` contract. Dispatch validates the selected handler's
  result contract against the concrete request and raises `InvalidHandlerError`
  rather than returning a mismatched result for an incompatible hierarchy.
- By default, exceptions raised by `Injector` or a handler propagate unchanged.
  To opt into Result-based handling at this boundary, pass the keyword-only
  `exception_mapper`; exceptions from handler resolution or execution are then
  returned as `Err` values:

  ```python
  class RequestFailure(Exception):
      pass

  result = await mediator.send_async(
      GetUserRequest(user_id=1),
      exception_mapper=lambda exc: RequestFailure(str(exc)),
  )
  ```

  The mapper is not called for an already-returned `Err`, an unregistered
  request still raises `HandlerNotFoundError`, and cancellation/system-level
  exceptions are not converted. If no mapper is supplied, the existing
  propagation behavior is preserved.

## Migrating from v0.1

v0.2 replaces the process-wide class API with instance-owned mediators and
scoped registries:

```python
# v0.1
Mediator.initialize(Injector())
result = await Mediator.send_async(GetUserRequest(user_id=1)).unwrap()

# v0.2
registry = HandlerRegistry()
registry.handler(GetUserHandler)
mediator = Mediator(Injector(), registry)
result = await mediator.send_async(GetUserRequest(user_id=1)).unwrap()
```

For test-specific overrides, create a separate registry or call
`mediator.register(...)` and `mediator.replace(...)`.

See the
[changelog](https://github.com/aiagate/flow-med/blob/main/CHANGELOG.md) for the
complete v0.2 change summary.

## Requirements

- Python 3.13 or higher.
- [flow-res](https://github.com/aiagate/flow-res)
- [injector](https://github.com/alecthomas/injector)

## License

MIT License
