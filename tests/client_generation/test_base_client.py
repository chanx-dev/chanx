"""Simple tests for BaseClient initialization."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal
from unittest.mock import patch

import pytest
from chanx.client_generator.base.client import BaseClient
from pydantic import BaseModel


class SimpleTestMessage(BaseModel):
    """Test message model."""

    action: Literal["test"] = "test"
    payload: dict[str, Any]


def test_init_with_host_port() -> None:
    """Test initialization with host:port format."""

    class TestClient(BaseClient):
        path = "/ws/test"
        incoming_message = SimpleTestMessage

    client = TestClient("localhost:8000")

    assert client.url == "ws://localhost:8000/ws/test"


def test_init_with_full_url() -> None:
    """Test initialization with full WebSocket URL."""

    class TestClient(BaseClient):
        path = "/ws/test"
        incoming_message = SimpleTestMessage

    client = TestClient("ws://example.com:9000")

    assert client.url == "ws://example.com:9000/ws/test"


def test_init_with_wss_protocol() -> None:
    """Test initialization with WSS protocol."""

    class TestClient(BaseClient):
        path = "/ws/test"
        incoming_message = SimpleTestMessage

    client = TestClient("localhost:8000", protocol="wss")

    assert client.url == "wss://localhost:8000/ws/test"


def test_init_with_headers() -> None:
    """Test initialization with custom headers."""

    class TestClient(BaseClient):
        path = "/ws/test"
        incoming_message = SimpleTestMessage

    headers = {"Authorization": "Bearer token"}
    client = TestClient("localhost:8000", headers=headers)

    assert client.headers == headers


def test_init_with_path_params() -> None:
    """Test initialization with path parameters."""

    class RoomClient(BaseClient):
        path = "/ws/room/{room_id}/chat/{chat_id}"
        incoming_message = SimpleTestMessage

    client = RoomClient("localhost:8000", path_params={"room_id": 123, "chat_id": 456})

    assert client.url == "ws://localhost:8000/ws/room/123/chat/456"


def test_init_path_params_with_string() -> None:
    """Test that path parameters are converted to strings."""

    class RoomClient(BaseClient):
        path = "/ws/{room_name}"
        incoming_message = SimpleTestMessage

    client = RoomClient("localhost:8000", path_params={"room_name": "lobby"})

    assert client.url == "ws://localhost:8000/ws/lobby"


class _FakeConnection:
    """Closes immediately, so `handle()` just establishes and returns."""

    def __aiter__(self) -> AsyncIterator[str]:
        return self._no_frames()

    async def _no_frames(self) -> AsyncIterator[str]:
        return
        yield


def _capturing_connect(calls: list[dict[str, Any]]) -> Any:
    @asynccontextmanager
    async def fake_connect(url: str, **kwargs: Any) -> AsyncIterator[_FakeConnection]:
        calls.append({"url": url, **kwargs})
        yield _FakeConnection()

    return fake_connect


@pytest.mark.asyncio
async def test_headers_are_sent_on_the_handshake() -> None:
    """They were accepted and stored but never passed to connect(), so a client
    given an auth header was rejected by the server."""

    class TestClient(BaseClient):
        path = "/ws/test"
        incoming_message = SimpleTestMessage

    calls: list[dict[str, Any]] = []
    client = TestClient("localhost:8000", headers={"x-token": "s3cret"})

    with patch("chanx.client_generator.base.client.connect", _capturing_connect(calls)):
        await client.handle()

    assert calls[0]["additional_headers"] == {"x-token": "s3cret"}


@pytest.mark.asyncio
async def test_no_headers_sends_none_rather_than_an_empty_dict() -> None:
    class TestClient(BaseClient):
        path = "/ws/test"
        incoming_message = SimpleTestMessage

    calls: list[dict[str, Any]] = []

    with patch("chanx.client_generator.base.client.connect", _capturing_connect(calls)):
        await TestClient("localhost:8000").handle()

    assert calls[0]["additional_headers"] is None


async def test_default_handlers_log_instead_of_printing(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    client = object.__new__(BaseClient)

    with caplog.at_level(logging.WARNING, logger="chanx.client"):
        await client.handle_invalid_message({"action": "nope"})
        await client.handle_error_message(None, {"payload": "boom"})

    assert capsys.readouterr().out == ""
    assert [r.getMessage() for r in caplog.records] == [
        "Received invalid message that failed validation: {'action': 'nope'}",
        "Server error: boom",
    ]
