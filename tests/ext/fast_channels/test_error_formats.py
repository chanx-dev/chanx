"""Both error formats, driven through a real ASGI connection."""

from typing import Any, ClassVar, Literal, cast

import pytest
from chanx.core.decorators import ws_handler
from chanx.core.topic import Topic
from chanx.fast_channels.testing import WebsocketCommunicator
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer
from chanx.messages.base import BaseMessage
from fastapi import FastAPI
from pydantic import BaseModel, Field

from fast_channels.layers import InMemoryChannelLayer, register_channel_layer

LAYER_ALIAS = "standard_errors_memory"


class PostPayload(BaseModel):
    reply_text: str = Field(min_length=2)
    likes: int = 0


class PostMessage(BaseMessage):
    action: Literal["post"] = "post"
    payload: PostPayload


class Circle(BaseModel):
    radius: float


class Square(BaseModel):
    side: float


class ShapePayload(BaseModel):
    value: int | str = 0
    shape: Circle | Square | None = None


class ShapeMessage(BaseMessage):
    action: Literal["shape"] = "shape"
    payload: ShapePayload


class PostedMessage(BaseMessage):
    action: Literal["posted"] = "posted"
    payload: PostPayload


class PingMessage(BaseMessage):
    action: Literal["ping"] = "ping"
    payload: None = None


class PongMessage(BaseMessage):
    action: Literal["pong"] = "pong"
    payload: None = None


class FailMessage(BaseMessage):
    action: Literal["fail"] = "fail"
    payload: None = None


class RoomTopic(Topic[PostMessage]):
    pattern = "room:{room_id}"
    channel_layer_alias = LAYER_ALIAS

    async def authorize(self, **params: str) -> bool:
        return params["room_id"] != "secret"

    @ws_handler
    async def handle_post(self, message: PostMessage) -> PostedMessage:
        return PostedMessage(payload=message.payload)


class StandardConsumer(AsyncJsonWebsocketConsumer[PostMessage]):
    channel_layer_alias = LAYER_ALIAS
    topics: ClassVar[list[type[Topic[Any]]]] = [RoomTopic]

    @ws_handler
    async def handle_post(self, message: PostMessage) -> PostedMessage:
        return PostedMessage(payload=message.payload)

    @ws_handler
    async def handle_ping(self, _message: PingMessage) -> PongMessage:
        return PongMessage()

    @ws_handler
    async def handle_shape(self, _message: ShapeMessage) -> None:
        pass

    @ws_handler
    async def handle_fail(self, _message: FailMessage) -> None:
        raise RuntimeError("boom")


class CamelConsumer(StandardConsumer):
    camelize = True


class PydanticConsumer(StandardConsumer):
    error_format = "pydantic"


app = FastAPI()
app.router.add_websocket_route("/ws/standard", StandardConsumer.as_asgi())
app.router.add_websocket_route("/ws/camel", CamelConsumer.as_asgi())
app.router.add_websocket_route("/ws/pydantic", PydanticConsumer.as_asgi())


@pytest.fixture(autouse=True)
def memory_layer() -> None:
    register_channel_layer(LAYER_ALIAS, InMemoryChannelLayer())


async def _send(comm: Any, frame: dict[str, Any]) -> dict[str, Any]:
    await comm.send_json_to(frame)
    return cast(dict[str, Any], await comm.receive_json_from(timeout=2))


def _validation(*errors: dict[str, Any]) -> dict[str, Any]:
    """Expected payload, leaving out the human-readable text."""
    return {
        "type": "https://chanx.dev/errors/validation-failed",
        "title": "Message failed validation",
        "errors": list(errors),
    }


def _without_text(payload: dict[str, Any]) -> dict[str, Any]:
    assert all(isinstance(e["detail"], str) for e in payload["errors"])
    return {k: v for k, v in payload.items() if k != "detail"} | {
        "errors": [
            {k: v for k, v in e.items() if k != "detail"} for e in payload["errors"]
        ]
    }


def _err(keyword: str, pointer: str, **extra: str) -> dict[str, Any]:
    return {"keyword": keyword, "pointer": pointer, **extra}


@pytest.mark.parametrize(
    "frame, errors",
    [
        ({"payload": None}, [_err("required", "", property="action")]),
        ({"action": "nope"}, [_err("enum", "/action")]),
        ({"action": "post"}, [_err("required", "", property="payload")]),
        (
            {"action": "post", "payload": {}},
            [_err("required", "/payload", property="reply_text")],
        ),
        (
            {"action": "post", "payload": {"reply_text": "x", "likes": "many"}},
            [_err("minLength", "/payload/reply_text"), _err("type", "/payload/likes")],
        ),
        ({"action": "ping", "payload": 1}, [_err("type", "/payload")]),
        ({"action": "ping", "ref": 5}, [_err("type", "/ref")]),
        # Union member labels in Pydantic's loc never reach the pointer.
        (
            {"action": "shape", "payload": {"value": []}},
            [_err("type", "/payload/value"), _err("type", "/payload/value")],
        ),
        (
            {"action": "shape", "payload": {"shape": {"radius": "x"}}},
            [
                _err("type", "/payload/shape/radius"),
                _err("required", "/payload/shape", property="side"),
            ],
        ),
    ],
)
@pytest.mark.asyncio
async def test_validation_errors_carry_keyword_and_pointer(
    frame: dict[str, Any], errors: list[dict[str, Any]]
) -> None:
    async with WebsocketCommunicator(
        app, "/ws/standard", consumer=StandardConsumer
    ) as comm:
        reply = await _send(comm, frame)

        assert reply["action"] == "error"
        assert _without_text(reply["payload"]) == _validation(*errors)
        count = len(errors)
        assert reply["payload"]["detail"] == (
            f"{count} validation error{'' if count == 1 else 's'}"
        )


@pytest.mark.asyncio
async def test_pointers_follow_camelized_keys() -> None:
    async with WebsocketCommunicator(app, "/ws/camel", consumer=CamelConsumer) as comm:
        short = await _send(comm, {"action": "post", "payload": {"replyText": "x"}})
        missing = await _send(comm, {"action": "post", "payload": {}})

        assert _without_text(short["payload"]) == _validation(
            _err("minLength", "/payload/replyText")
        )
        assert _without_text(missing["payload"]) == _validation(
            _err("required", "/payload", property="replyText")
        )


@pytest.mark.asyncio
async def test_invalid_json_has_no_errors_list() -> None:
    async with WebsocketCommunicator(
        app, "/ws/standard", consumer=StandardConsumer
    ) as comm:
        await comm.send_input({"type": "websocket.receive", "bytes": b"\x01"})
        reply = await comm.receive_json_from(timeout=2)

        assert reply["payload"] == {
            "type": "https://chanx.dev/errors/invalid-json",
            "title": "Frame is not valid JSON",
            "detail": "Invalid JSON: binary frames are not supported",
        }


@pytest.mark.asyncio
async def test_handler_failure() -> None:
    async with WebsocketCommunicator(
        app, "/ws/standard", consumer=StandardConsumer
    ) as comm:
        reply = await _send(comm, {"action": "fail", "ref": "f1"})

        assert reply == {
            "action": "error",
            "payload": {
                "type": "https://chanx.dev/errors/handler-failed",
                "title": "Message handler failed",
                "detail": "Failed to process message for fail",
            },
            "version": 1,
            "ref": "f1",
        }


@pytest.mark.asyncio
async def test_topic_errors_use_the_reason_as_type() -> None:
    async with WebsocketCommunicator(
        app, "/ws/standard", consumer=StandardConsumer
    ) as comm:
        unknown = await _send(comm, {"topic": "nope:1", "action": "subscribe"})
        denied = await _send(comm, {"topic": "room:secret", "action": "subscribe"})
        unsubscribed = await _send(
            comm, {"topic": "room:1", "action": "post", "payload": {"reply_text": "hi"}}
        )

        assert unknown["payload"] == {
            "type": "https://chanx.dev/errors/unknown-topic",
            "title": "Unknown topic",
            "detail": "Unknown topic 'nope:1'",
        }
        assert denied["payload"]["type"] == "https://chanx.dev/errors/unauthorized"
        assert (
            unsubscribed["payload"]["type"] == "https://chanx.dev/errors/not-subscribed"
        )


@pytest.mark.asyncio
async def test_topic_validation_errors_use_the_consumer_format() -> None:
    async with WebsocketCommunicator(
        app, "/ws/standard", consumer=StandardConsumer
    ) as comm:
        await _send(comm, {"topic": "room:1", "action": "subscribe"})
        reply = await _send(
            comm, {"topic": "room:1", "action": "post", "payload": {"likes": 1}}
        )

        assert reply["topic"] == "room:1"
        assert _without_text(reply["payload"]) == _validation(
            _err("required", "/payload", property="reply_text")
        )


@pytest.mark.asyncio
async def test_pydantic_format_keeps_the_raw_error_list() -> None:
    async with WebsocketCommunicator(
        app, "/ws/pydantic", consumer=PydanticConsumer
    ) as comm:
        invalid = await _send(comm, {"action": "post", "payload": {}})
        failed = await _send(comm, {"action": "fail"})
        unknown = await _send(comm, {"topic": "nope:1", "action": "subscribe"})

        assert invalid["payload"] == [
            {
                "type": "missing",
                "loc": ["post", "payload", "reply_text"],
                "msg": "Field required",
            }
        ]
        assert failed["payload"] == {"detail": "Failed to process message for fail"}
        assert unknown["payload"] == {
            "reason": "unknown_topic",
            "detail": "Unknown topic 'nope:1'",
        }
