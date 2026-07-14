"""This fixture must be rejected: object is not a request handler type."""

from flow_res import Result

from flow_med import Mediator, Request


class NumberQuery(Request[Result[int, Exception]]):
    pass


mediator = Mediator()
mediator.register(NumberQuery, object)
