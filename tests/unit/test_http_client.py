"""Timeout, retry com backoff, Retry-After e intervalo mínimo entre requisições."""

from __future__ import annotations

import httpx
import pytest

from ufabc_science.collectors.base import CollectorError, RateLimitedClient


def _client(handler, sleeps: list[float], **kwargs) -> RateLimitedClient:
    params = {"timeout": 1.0, "max_retries": 2, "backoff_seconds": 0.5, "min_interval": 0.0}
    params.update(kwargs)
    return RateLimitedClient(
        source="teste",
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **params,
    )


def test_transient_errors_are_retried_with_backoff() -> None:
    statuses = [503, 429, 200]
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(statuses.pop(0), text="ok")

    with _client(handler, sleeps) as client:
        response = client.get("https://api.example.org/x")

    assert response.status_code == 200
    assert client.requests == 3
    assert sleeps == [0.5, 1.0]  # backoff exponencial


def test_retry_after_header_is_respected() -> None:
    statuses = [429, 200]
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        status = statuses.pop(0)
        return httpx.Response(status, headers={"Retry-After": "7"} if status == 429 else {})

    with _client(handler, sleeps) as client:
        client.get("https://api.example.org/x")

    assert sleeps == [7.0]


def test_retries_are_limited() -> None:
    sleeps: list[float] = []

    with (
        _client(lambda r: httpx.Response(503), sleeps) as client,
        pytest.raises(CollectorError, match="3 tentativa"),
    ):
        client.get("https://api.example.org/x")
    assert client.requests == 3


def test_client_errors_are_not_retried() -> None:
    sleeps: list[float] = []
    with (
        _client(lambda r: httpx.Response(404), sleeps) as client,
        pytest.raises(CollectorError, match="HTTP 404"),
    ):
        client.get("https://api.example.org/x")
    assert client.requests == 1
    assert sleeps == []


def test_connection_failures_are_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("sem rede", request=request)
        return httpx.Response(200)

    with _client(handler, []) as client:
        assert client.get("https://api.example.org/x").status_code == 200


def test_minimum_interval_between_requests() -> None:
    sleeps: list[float] = []
    with _client(lambda r: httpx.Response(200), sleeps, min_interval=10.0) as client:
        client.get("https://api.example.org/a")
        client.get("https://api.example.org/b")
    assert len(sleeps) == 1 and 9.0 < sleeps[0] <= 10.0


def test_user_agent_identifies_project_without_email_by_default() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200)

    with _client(handler, []) as client:
        client.get("https://api.example.org/x")
    assert seen[0].startswith("UFABC-Science/")
    assert "mailto" not in seen[0]
