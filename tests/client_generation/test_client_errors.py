"""Error frames reach clients as typed problems."""

from typing import Any, Literal

import pytest
from chanx.client_generator.base.client import BaseClient
from chanx.client_generator.base.errors import ErrorType, ProblemDetails, parse_problem
from chanx.client_generator.base.topic_client import BaseTopicHandle, ProtocolMessage
from pydantic import BaseModel

VALIDATION = {
    "type": "https://chanx.dev/errors/validation-failed",
    "title": "Message failed validation",
    "detail": "1 validation error",
    "errors": [
        {
            "keyword": "required",
            "pointer": "/payload",
            "detail": "Field required",
            "property": "message",
        }
    ],
}


class Pong(BaseModel):
    action: Literal["pong"] = "pong"
    payload: None = None


class Client(BaseClient):
    path = "/ws"
    incoming_message = Pong

    def __init__(self) -> None:
        super().__init__("localhost:8000")
        self.errors: list[tuple[ProblemDetails | None, dict[str, Any]]] = []
        self.invalid: list[Any] = []

    async def handle_error_message(
        self, problem: ProblemDetails | None, frame: dict[str, Any]
    ) -> None:
        self.errors.append((problem, frame))

    async def handle_invalid_message(self, invalid_message: Any) -> None:
        self.invalid.append(invalid_message)


@pytest.mark.asyncio
async def test_an_error_frame_reaches_handle_error_message_typed() -> None:
    client = Client()
    await client.dispatch_frame({"action": "error", "payload": VALIDATION})

    [(problem, frame)] = client.errors
    assert problem is not None
    assert problem.type == ErrorType.VALIDATION_FAILED
    assert problem.errors is not None
    assert problem.errors[0].property == "message"
    assert frame["payload"] == VALIDATION
    assert client.invalid == []


@pytest.mark.asyncio
async def test_a_pydantic_format_error_arrives_without_a_problem() -> None:
    client = Client()
    payload = [{"type": "missing", "loc": ["payload"], "msg": "Field required"}]
    await client.dispatch_frame({"action": "error", "payload": payload})

    assert client.errors == [(None, {"action": "error", "payload": payload})]


def test_unknown_members_are_kept_as_rfc_9457_asks() -> None:
    problem = parse_problem({**VALIDATION, "data": {"statusCode": 403}})
    assert problem is not None
    assert problem.model_extra == {"data": {"statusCode": 403}}


def test_a_topic_reply_exposes_its_problem() -> None:
    error = ProtocolMessage(action="error", payload=VALIDATION)
    assert error.problem is not None
    assert error.problem.title == "Message failed validation"
    assert ProtocolMessage(action="subscribed").problem is None


class Handle(BaseTopicHandle):
    pattern = "room:{name}"
    incoming_message = Pong

    def __init__(self) -> None:
        self.errors: list[ProblemDetails | None] = []

    async def handle_error_message(
        self, problem: ProblemDetails | None, frame: dict[str, Any]
    ) -> None:
        self.errors.append(problem)


@pytest.mark.asyncio
async def test_an_error_pushed_on_a_topic_reaches_its_handle() -> None:
    handle = Handle()
    payload = {
        "type": "https://chanx.dev/errors/not-subscribed",
        "title": "Not subscribed to topic",
        "detail": "Not subscribed to 'room:a'",
    }
    await handle.dispatch_frame(
        {"action": "error", "payload": payload, "topic": "room:a"}
    )

    [problem] = handle.errors
    assert problem is not None and problem.type == ErrorType.NOT_SUBSCRIBED
