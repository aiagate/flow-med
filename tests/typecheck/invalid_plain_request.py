"""This fixture must be rejected: request result is not flow_res.Result."""

from flow_med import Request


class PlainRequest(Request[str]):
    pass
