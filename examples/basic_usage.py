import asyncio
from typing import override

from flow_res import Ok, Result
from injector import Injector

from flow_med import Mediator, Request, RequestHandler


# 1. Define Request and Result
class GetUserRequest(Request[Result[str, Exception]]):
    def __init__(self, user_id: int):
        self.user_id = user_id


# 2. Implement Handler
# Handlers are automatically registered when defined.
class GetUserHandler(RequestHandler[GetUserRequest, Result[str, Exception]]):
    @override
    async def handle(self, request: GetUserRequest) -> Result[str, Exception]:
        # Logic to get user (e.g., from a database)
        return Ok(f"User {request.user_id}")


async def main():
    # 3. Initialize with an Injector
    # In a real app, you would configure your modules here.
    Mediator.initialize(Injector())

    print("--- Basic Usage Example ---")

    # 4. Send request and chain results using flow-res
    # Mediator.send_async returns an AwaitableResult,
    # allowing you to chain operations before awaiting.
    result = await (
        Mediator.send_async(GetUserRequest(user_id=42))
        .map(lambda name: f"Hello, {name}!")
        .unwrap()
    )

    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
