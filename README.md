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
- **Strict Type Safety**: Public type contracts are checked by `pyright`/`mypy`, with result-type validation at handler registration.

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
`Mediator` is created are visible to that mediator. Configure registries during
application startup; concurrent registry mutation is not guaranteed to be
thread-safe. Separate registries are isolated, while sharing a registry
explicitly shares its handler mappings.

## Error behavior

- Sending an unregistered request raises `HandlerNotFoundError` when the
  returned `AwaitableResult` is awaited.
- Registering a second handler for the same request type raises
  `DuplicateHandlerError`. Use `replace()` for an intentional replacement;
  the request type must already be registered.
- Handler lookup uses the exact `type(request)`. A handler registered for a
  base request class does not handle its subclasses.
- Exceptions raised by `Injector` or a handler propagate unchanged. They are
  not converted into an `Err`; handlers must return an `Err` explicitly when
  failure is part of the request's `Result` contract.

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

## Requirements

- Python 3.13 or higher.
- [flow-res](https://github.com/aiagate/flow-res)
- [injector](https://github.com/alecthomas/injector)

## License

MIT License
