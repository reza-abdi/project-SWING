"""Digital Twin HTTP route, payload, timeout and failure contracts."""

import requests
import pytest

from modules.ai_agents.twin_client import TwinClient, TwinClientError


class Response:
    def __init__(self, body=None, error=None):
        self.body = {"ok": True} if body is None else body
        self.error = error

    def raise_for_status(self):
        if self.error:
            raise self.error

    def json(self):
        return self.body


class Session:
    def __init__(self, response=None, error=None):
        self.response = response or Response()
        self.error = error
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error:
            raise self.error
        return self.response


@pytest.mark.parametrize(
    "method,args,path,params,body",
    [
        ("grid_status", ("39",), "/grid_status", {"grid": "39"}, None),
        ("topology", ("118",), "/topology", {"grid": "118"}, None),
        ("contingency", ("39",), "/contingency/39", None, None),
        ("optimize", ("39", {"action_type": "SHED_LOAD"}), "/optimize_action/39", None, {"action_type": "SHED_LOAD"}),
        ("validate", ("118", {"target_bus": 1}), "/validate_action/118", None, {"target_bus": 1}),
        ("redistribute_load", ("39", 1, 2, 5.0), "/redistribute_load/39", {"source_bus": 1, "destination_bus": 2, "mw_amount": 5.0}, None),
    ],
)
def test_read_and_optimizer_routes(method, args, path, params, body):
    session = Session()
    client = TwinClient("http://twin.local", session=session)
    assert getattr(client, method)(*args) == {"ok": True}
    request_args, kwargs = session.calls[0]
    assert request_args[:2] == (("GET" if method in {"grid_status", "topology", "contingency"} else "POST"), f"http://twin.local{path}")
    assert kwargs["params"] == params
    assert kwargs["json"] == body
    assert kwargs["timeout"] == 10.0


def test_mutation_route_mapping_is_exact():
    session = Session(); client = TwinClient("http://twin.local", session=session)
    client.change_load("118", 4, 75.5)
    client.redispatch_gen("39", 2, 1.25)
    client.inject_fault("39", 8)
    client.restore_line("118", 11)
    expected = [
        ("POST", "http://twin.local/change_load/4", {"new_mw": 75.5, "grid": "118"}),
        ("POST", "http://twin.local/redispatch_gen/2", {"delta_mw": 1.25, "grid": "39"}),
        ("POST", "http://twin.local/inject_fault/8", {"grid": "39"}),
        ("POST", "http://twin.local/restore_line/118/11", None),
    ]
    for (args, kwargs), (method, url, params) in zip(session.calls, expected):
        assert args[:2] == (method, url)
        assert kwargs["params"] == params


@pytest.mark.parametrize("failure", [requests.Timeout("timeout"), requests.HTTPError("server error")])
def test_http_and_timeout_errors_are_controlled(failure):
    session = Session(error=failure) if isinstance(failure, requests.Timeout) else Session(Response(error=failure))
    with pytest.raises(TwinClientError):
        TwinClient("http://twin.local", session=session).grid_status("39")


def test_invalid_grid_url_and_non_object_response_are_rejected():
    with pytest.raises(ValueError):
        TwinClient("file:///tmp/twin")
    with pytest.raises(ValueError):
        TwinClient("https://user:secret@twin.local")
    with pytest.raises(TwinClientError):
        TwinClient("http://twin.local", session=Session(Response(body=[]))).grid_status("39")
