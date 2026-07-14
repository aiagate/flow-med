"""This fixture must be rejected: handler result does not match its request."""

from typing import override

from flow_res import Result

from flow_med import Request, RequestHandler


class NumberQuery(Request[Result[int, Exception]]):
    pass


class WrongResultHandler(RequestHandler[NumberQuery, Result[int, Exception]]):
    @override
    async def handle(self, request: NumberQuery) -> Result[str, Exception]:
        raise NotImplementedError
