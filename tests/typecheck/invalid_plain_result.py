"""This fixture must be rejected: handler result is not flow_res.Result."""

from typing import override

from flow_res import Result

from flow_med import Request, RequestHandler


class Query(Request[Result[str, Exception]]):
    pass


class PlainHandler(RequestHandler[Query, str]):
    @override
    async def handle(self, request: Query) -> str:
        return "plain value"
