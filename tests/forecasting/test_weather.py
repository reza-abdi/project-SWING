"""Weather archive response validation and atomic-write regressions."""

import requests
import pytest

import modules.forecasting.fetch_weather as weather


def valid_payload():
    return [
        {"hourly": {"time": ["2024-01-01T00:00", "2024-01-01T01:00"], "temperature_2m": [1.0, 4.0]}},
        {"hourly": {"time": ["2024-01-01T00:00", "2024-01-01T01:00"], "temperature_2m": [2.0, 5.0]}},
        {"hourly": {"time": ["2024-01-01T00:00", "2024-01-01T01:00"], "temperature_2m": [3.0, 6.0]}},
    ]


class FakeResponse:
    status_error = None

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def json(self):
        return valid_payload()


def test_fetch_requests_three_locations_and_writes_regional_mean(monkeypatch, tmp_path) -> None:
    captured = {}

    def get(url, *, params, timeout):
        captured.update(url=url, params=params, timeout=timeout)
        return FakeResponse()

    monkeypatch.setattr(weather.requests, "get", get)
    destination = tmp_path / "weather.csv"
    frame = weather.fetch_northern_region_weather(destination)
    assert captured["params"]["timezone"] == "Asia/Kolkata"
    assert captured["params"]["hourly"] == "temperature_2m"
    assert len(captured["params"]["latitude"].split(",")) == 3
    assert frame["Northern_Region_Avg_T2M"].tolist() == [2.0, 5.0]
    assert destination.read_text().startswith("Datetime,Delhi_T2M,Lucknow_T2M,Jaipur_T2M,Northern_Region_Avg_T2M")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: [],
        lambda payload: payload[:2],
        lambda payload: [{"hourly": {"time": [], "temperature_2m": []}}] * 3,
        lambda payload: [payload[0], {"hourly": {"time": ["2024-01-01T00:00"], "temperature_2m": [2.0]}}, payload[2]],
        lambda payload: [payload[0], {"hourly": {"time": payload[1]["hourly"]["time"], "temperature_2m": [None, 5.0]}}, payload[2]],
    ],
)
def test_invalid_or_missing_hourly_data_preserves_existing_csv(monkeypatch, tmp_path, mutate) -> None:
    destination = tmp_path / "weather.csv"
    destination.write_text("prior-data\n")
    response = FakeResponse()
    response.json = lambda: mutate(valid_payload())
    monkeypatch.setattr(weather.requests, "get", lambda *args, **kwargs: response)
    with pytest.raises(ValueError):
        weather.fetch_northern_region_weather(destination)
    assert destination.read_text() == "prior-data\n"


@pytest.mark.parametrize("error", [requests.Timeout("timeout"), requests.HTTPError("bad status")])
def test_network_failures_preserve_existing_csv(monkeypatch, tmp_path, error) -> None:
    destination = tmp_path / "weather.csv"
    destination.write_text("prior-data\n")

    def get(*args, **kwargs):
        if isinstance(error, requests.Timeout):
            raise error
        response = FakeResponse()
        response.status_error = error
        return response

    monkeypatch.setattr(weather.requests, "get", get)
    with pytest.raises((requests.Timeout, requests.HTTPError)):
        weather.fetch_northern_region_weather(destination)
    assert destination.read_text() == "prior-data\n"
