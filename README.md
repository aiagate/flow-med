# flow-med

[![PyPI version](https://badge.fury.io/py/flow-med.svg)](https://badge.fury.io/py/flow-med)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/release/python-3130/)

A high-performance, type-safe Mediator pattern implementation for Python 3.13+, built on top of [flow-res](https://github.com/aiagate/flow-res) and [injector](https://github.com/alecthomas/injector).

## Features

- **Result-Driven Development**: Built-in support for `flow-res` Result types, making error handling explicit and type-safe.
- **Auto-Registration**: Handlers are automatically registered using Python 3.13's `__init_subclass__` and generic introspection.
- **Dependency Injection**: Seamless integration with the `injector` library for robust dependency management.
- **Native Async Support**: Designed from the ground up for `asyncio` with `AwaitableResult` support for elegant method chaining.
- **Strict Type Safety**: Fully compatible with `pyright` and `mypy` using modern Python 3.13 type parameters.

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

Handlers are automatically registered when defined. Use `@override` to ensure correct implementation.

```python
from typing import override
from flow_res import Ok, Result
from flow_med import RequestHandler

class GetUserHandler(RequestHandler[GetUserRequest, Result[str, Exception]]):
    @override
    async def handle(self, request: GetUserRequest) -> Result[str, Exception]:
        # Logic to get user
        return Ok(f"User {request.user_id}")
```

### 3. Initialize and Send

```python
import asyncio
from injector import Injector
from flow_med import Mediator

async def main():
    # Initialize with an Injector
    Mediator.initialize(Injector())

    # Send request and chain results using flow-res
    result = await (
        Mediator.send_async(GetUserRequest(user_id=1))
        .map(lambda name: f"Hello, {name}!")
        .unwrap()
    )
    
    print(result) # Hello, User 1!

if __name__ == "__main__":
    asyncio.run(main())
```

## Requirements

- Python 3.13 or higher.
- [flow-res](https://github.com/aiagate/flow-res)
- [injector](https://github.com/alecthomas/injector)

## License

MIT License
