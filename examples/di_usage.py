import asyncio
from typing import override

from flow_res import Ok, Result
from injector import Injector, Module, inject, provider, singleton

from flow_med import Mediator, Request, RequestHandler


# 1. External Service
class UserRepository:
    def get_name(self, user_id: int) -> str:
        return f"User_{user_id}_from_DB"


# 2. DI Module
class UserModule(Module):
    @singleton
    @provider
    def provide_user_repo(self) -> UserRepository:
        return UserRepository()


# 3. Define Request
class GetUserRequest(Request[Result[str, Exception]]):
    def __init__(self, user_id: int):
        self.user_id = user_id


# 4. Implement Handler with DI
# RequestHandler is automatically registered.
class GetUserHandler(RequestHandler[GetUserRequest, Result[str, Exception]]):
    # UserRepository is injected via the constructor
    @inject
    def __init__(self, repo: UserRepository):
        self.repo = repo

    @override
    async def handle(self, request: GetUserRequest) -> Result[str, Exception]:
        name = self.repo.get_name(request.user_id)
        return Ok(name)


async def main():
    # 5. Initialize with an Injector containing our Module
    injector = Injector([UserModule()])
    Mediator.initialize(injector)

    print("--- Dependency Injection Example ---")

    # 6. Send request
    result = await (
        Mediator.send_async(GetUserRequest(user_id=123))
        .map(lambda name: f"Retrieved: {name}")
        .unwrap()
    )

    print(f"Result: {result}")


if __name__ == "__main__":
    asyncio.run(main())
