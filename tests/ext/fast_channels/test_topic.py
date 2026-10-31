"""Topics multiplexed over one connection, driven through a real ASGI connection."""

from typing import Any, ClassVar, Literal, cast

import pytest
from chanx.core.decorators import event_handler, ws_handler
from chanx.core.topic import Topic
from chanx.fast_channels.testing import WebsocketCommunicator
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer
from chanx.messages.base import BaseMessage
from fastapi import FastAPI
from pydantic import BaseModel

from fast_channels.layers import InMemoryChannelLayer, register_channel_layer

LAYER_ALIAS = "topic_memory"


class CancelMessage(BaseMessage):
    action: Literal["cancel"] = "cancel"
    payload: None = None


class CancelledMessage(BaseMessage):
    action: Literal["cancelled"] = "cancelled"
    payload: str


class NewReplyEvent(BaseMessage):
    action: Literal["new_reply"] = "new_reply"
    payload: str


class ReplyCreatedMessage(BaseMessage):
    action: Literal["reply_created"] = "reply_created"
    payload: str


class DiscussionTopic(Topic[NewReplyEvent]):
    pattern = "discussion:{pk}"
    channel_layer_alias = LAYER_ALIAS

    @ws_handler
    async def handle_cancel(self, _message: CancelMessage) -> CancelledMessage:
        return CancelledMessage(payload=f"discussion-{self.params['pk']}")

    @event_handler
    async def handle_new_reply(self, event: NewReplyEvent) -> ReplyCreatedMessage:
        return ReplyCreatedMessage(payload=event.payload)


class RoomTopic(Topic[NewReplyEvent]):
    pattern = "room:{room_id}"
    channel_layer_alias = LAYER_ALIAS

    # Same action name as DiscussionTopic - scoping makes this legal.
    @ws_handler
    async def handle_cancel(self, _message: CancelMessage) -> CancelledMessage:
        return CancelledMessage(payload=f"room-{self.params['room_id']}")


class PrivateTopic(Topic[NewReplyEvent]):
    pattern = "private:{pk}"
    channel_layer_alias = LAYER_ALIAS

    async def authorize(self, **params: str) -> bool:
        return params["pk"] == "allowed"

    @event_handler
    async def handle_new_reply(self, event: NewReplyEvent) -> ReplyCreatedMessage:
        return ReplyCreatedMessage(payload=event.payload)


class PingMessage(BaseMessage):
    action: Literal["ping"] = "ping"
    payload: None = None


class PongMessage(BaseMessage):
    action: Literal["pong"] = "pong"
    payload: None = None


class MainConsumer(AsyncJsonWebsocketConsumer[NewReplyEvent]):
    channel_layer_alias = LAYER_ALIAS
    topics: ClassVar[list[type[Topic[Any]]]] = [
        DiscussionTopic,
        RoomTopic,
        PrivateTopic,
    ]

    @ws_handler
    async def handle_ping(self, _message: PingMessage) -> PongMessage:
        return PongMessage()


app = FastAPI()
app.router.add_websocket_route("/ws/hub", MainConsumer.as_asgi())


@pytest.fixture(autouse=True)
def memory_layer() -> None:
    register_channel_layer(LAYER_ALIAS, InMemoryChannelLayer())


async def _send(comm: Any, frame: dict[str, Any]) -> dict[str, Any]:
    await comm.send_json_to(frame)
    return cast(dict[str, Any], await comm.receive_json_from(timeout=2))


@pytest.mark.asyncio
async def test_subscribe_confirms_with_the_ref() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        reply = await _send(
            comm, {"topic": "discussion:5", "ref": "1", "action": "subscribe"}
        )
        assert reply == {
            "action": "subscribed",
            "payload": None,
            "version": 1,
            "topic": "discussion:5",
            "ref": "1",
        }


@pytest.mark.asyncio
async def test_two_topics_share_an_action_name() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        await _send(comm, {"topic": "discussion:5", "ref": "1", "action": "subscribe"})
        await _send(comm, {"topic": "room:9", "ref": "2", "action": "subscribe"})

        discussion = await _send(
            comm, {"topic": "discussion:5", "ref": "3", "action": "cancel"}
        )
        room = await _send(comm, {"topic": "room:9", "ref": "4", "action": "cancel"})

        assert discussion["payload"] == "discussion-5"
        assert discussion["ref"] == "3"
        assert room["payload"] == "room-9"
        assert room["ref"] == "4"


@pytest.mark.asyncio
async def test_authorize_denies_per_topic() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        denied = await _send(
            comm, {"topic": "private:secret", "ref": "1", "action": "subscribe"}
        )
        assert denied["action"] == "error"
        assert denied["topic"] == "private:secret"
        assert denied["ref"] == "1"

        allowed = await _send(
            comm, {"topic": "private:allowed", "ref": "2", "action": "subscribe"}
        )
        assert allowed["action"] == "subscribed"


@pytest.mark.asyncio
async def test_group_event_routes_to_its_topic() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        await _send(comm, {"topic": "discussion:5", "ref": "1", "action": "subscribe"})

        await DiscussionTopic.broadcast("discussion:5", NewReplyEvent(payload="hello"))

        pushed = await comm.receive_json_from(timeout=2)
        assert pushed["action"] == "reply_created"
        assert pushed["payload"] == "hello"
        assert pushed["topic"] == "discussion:5"
        assert "ref" not in pushed


@pytest.mark.asyncio
async def test_untopiced_frame_falls_through_to_the_consumer() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        await comm.send_json_to({"action": "ping", "payload": None})
        reply = await comm.receive_json_from(timeout=2)
        assert reply["action"] == "pong"
        assert "topic" not in reply


@pytest.mark.asyncio
async def test_untopiced_reply_echoes_the_ref() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        reply = await _send(comm, {"version": 1, "ref": "3", "action": "ping"})
        assert reply == {"action": "pong", "payload": None, "version": 1, "ref": "3"}


@pytest.mark.asyncio
async def test_untopiced_reply_without_a_ref_is_unchanged() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        reply = await _send(comm, {"action": "ping", "payload": None})
        assert reply == {"action": "pong", "payload": None}


@pytest.mark.asyncio
async def test_untopiced_validation_error_echoes_the_ref() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        error = await _send(comm, {"version": 1, "ref": "4", "action": "unknown"})
        assert error["action"] == "error"
        assert error["ref"] == "4"


@pytest.mark.asyncio
async def test_untopiced_ref_does_not_leak_into_a_later_push() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        await _send(comm, {"topic": "discussion:5", "ref": "1", "action": "subscribe"})
        await _send(comm, {"version": 1, "ref": "3", "action": "ping"})

        await DiscussionTopic.broadcast("discussion:5", NewReplyEvent(payload="hello"))

        pushed = await comm.receive_json_from(timeout=2)
        assert pushed["action"] == "reply_created"
        assert "ref" not in pushed


@pytest.mark.asyncio
async def test_unknown_topic_and_unsubscribed_topic_report_errors() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        unknown = await _send(
            comm, {"topic": "nope:1", "ref": "1", "action": "subscribe"}
        )
        assert unknown["action"] == "error"

        not_subscribed = await _send(
            comm, {"topic": "discussion:5", "ref": "2", "action": "cancel"}
        )
        assert not_subscribed["action"] == "error"


@pytest.mark.asyncio
async def test_unsubscribe_stops_group_delivery() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        await _send(comm, {"topic": "discussion:5", "ref": "1", "action": "subscribe"})
        await _send(
            comm, {"topic": "discussion:5", "ref": "2", "action": "unsubscribe"}
        )

        await DiscussionTopic.broadcast("discussion:5", NewReplyEvent(payload="gone"))
        assert await comm.receive_nothing(timeout=0.3) is True


def test_asyncapi_documents_one_channel_per_topic() -> None:
    """Topics share the route address and are told apart by the extension."""
    from chanx.asyncapi.generator import AsyncAPIGenerator
    from chanx.fast_channels.discovery import FastAPIRouteDiscovery

    routes = FastAPIRouteDiscovery(app).discover_routes()
    channels = AsyncAPIGenerator(routes=routes, title="t", version="1").generate()[
        "channels"
    ]

    assert {name: channel["address"] for name, channel in channels.items()} == {
        "main": "/ws/hub",
        "main_discussion_topic": "/ws/hub",
        "main_room_topic": "/ws/hub",
        "main_private_topic": "/ws/hub",
    }
    assert channels["main_discussion_topic"]["x-topic"] == {
        "name": "discussion_topic",
        "pattern": "discussion:{pk}",
        "parameters": ["pk"],
    }
    # The consumer's own channel owns the connection, so it carries no topic.
    assert "x-topic" not in channels["main"]


standalone_app = FastAPI()
standalone_app.router.add_websocket_route(
    "/ws/discussion/{pk}", DiscussionTopic.as_consumer().as_asgi()
)


@pytest.mark.asyncio
async def test_standalone_route_subscribes_without_an_envelope() -> None:
    """The same Topic class on its own path: connect is the subscription."""
    consumer = DiscussionTopic.as_consumer()
    async with WebsocketCommunicator(
        standalone_app, "/ws/discussion/5", consumer=consumer
    ) as comm:
        # subscribed on connect, so the confirmation arrives unprompted
        assert (await comm.receive_json_from(timeout=2))["action"] == "subscribed"

        # no topic on the frame - the route serves exactly one
        await comm.send_json_to({"action": "cancel", "ref": "1"})
        reply = await comm.receive_json_from(timeout=2)
        assert reply["payload"] == "discussion-5"
        assert reply["topic"] == "discussion:5"

        # and it is the same group as the multiplexed route uses
        await DiscussionTopic.broadcast("discussion:5", NewReplyEvent(payload="hi"))
        pushed = await comm.receive_json_from(timeout=2)
        assert pushed["action"] == "reply_created"


misrouted_app = FastAPI()
misrouted_app.router.add_websocket_route(
    "/ws/misrouted", DiscussionTopic.as_consumer().as_asgi()
)


@pytest.mark.asyncio
async def test_default_topic_missing_url_param_fails_with_a_clear_error() -> None:
    """A route that lacks the pattern's parameters is a configuration error."""
    consumer = DiscussionTopic.as_consumer()
    comm = WebsocketCommunicator(misrouted_app, "/ws/misrouted", consumer=consumer)
    await comm.connect()
    with pytest.raises(ValueError, match=r"needs URL parameters \['pk'\]"):
        await comm.wait(timeout=1)


@pytest.mark.asyncio
async def test_broadcast_seq_reaches_the_client() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        await _send(comm, {"topic": "discussion:5", "ref": "1", "action": "subscribe"})

        await DiscussionTopic.broadcast(
            "discussion:5", NewReplyEvent(payload="a"), seq=142
        )
        assert (await comm.receive_json_from(timeout=2))["seq"] == 142

        # unset by default, so a multi-writer topic promises nothing
        await DiscussionTopic.broadcast("discussion:5", NewReplyEvent(payload="b"))
        assert "seq" not in await comm.receive_json_from(timeout=2)


def test_long_topics_stay_within_the_group_name_limit() -> None:
    """Channel layers cap group names, so a long topic is truncated with a digest."""

    class LongTopic(Topic[NewReplyEvent]):
        pattern = "org:{org}:project:{project}:run:{run}"

    long_topic = (
        "org:acme-corporation-holdings:project:platform-infrastructure"
        ":run:01HXQ2M9Z8K7J6H5G4F3D2S1A0"
    )
    name = LongTopic.group_name(long_topic)

    assert len(name) < 100
    InMemoryChannelLayer().require_valid_group_name(name)
    # deterministic, and still distinguishes topics that share a prefix
    assert name == LongTopic.group_name(long_topic)
    assert name != LongTopic.group_name(long_topic.replace("01HX", "02HX"))


class LifecycleTopic(Topic[NewReplyEvent]):
    pattern = "lifecycle:{name}"
    channel_layer_alias = LAYER_ALIAS
    events: ClassVar[list[str]] = []

    async def on_subscribe(self) -> None:
        type(self).events.append(f"subscribe:{self.params['name']}")
        await self.send_message(HealthRes(payload="state"))

    async def on_unsubscribe(self) -> None:
        type(self).events.append(f"unsubscribe:{self.params['name']}")


class HealthRes(BaseMessage):
    action: Literal["state"] = "state"
    payload: str


class LifecycleConsumer(AsyncJsonWebsocketConsumer[NewReplyEvent]):
    channel_layer_alias = LAYER_ALIAS
    topics: ClassVar[list[type[Topic[Any]]]] = [LifecycleTopic]


lifecycle_app = FastAPI()
lifecycle_app.router.add_websocket_route("/ws/lifecycle", LifecycleConsumer.as_asgi())


@pytest.mark.asyncio
async def test_subscribe_hooks_run_and_state_is_not_a_reply() -> None:
    LifecycleTopic.events.clear()
    async with WebsocketCommunicator(
        lifecycle_app, "/ws/lifecycle", consumer=LifecycleConsumer
    ) as comm:
        confirmed = await _send(
            comm, {"topic": "lifecycle:a", "ref": "1", "action": "subscribe"}
        )
        assert confirmed["action"] == "subscribed"
        assert confirmed["ref"] == "1"

        # pushed by on_subscribe, so it must not look like a reply to the request
        state = await comm.receive_json_from(timeout=2)
        assert state["action"] == "state"
        assert "ref" not in state

        await _send(comm, {"topic": "lifecycle:a", "ref": "2", "action": "unsubscribe"})

    assert LifecycleTopic.events == ["subscribe:a", "unsubscribe:a"]


@pytest.mark.asyncio
async def test_disconnect_runs_the_unsubscribe_hook() -> None:
    LifecycleTopic.events.clear()
    async with WebsocketCommunicator(
        lifecycle_app, "/ws/lifecycle", consumer=LifecycleConsumer
    ) as comm:
        await _send(comm, {"topic": "lifecycle:b", "ref": "1", "action": "subscribe"})
        await comm.receive_json_from(timeout=2)

    assert LifecycleTopic.events == ["subscribe:b", "unsubscribe:b"]


class ReplyPayload(BaseModel):
    reply_text: str


class PostReplyMessage(BaseMessage):
    action: Literal["post_reply"] = "post_reply"
    payload: ReplyPayload


class ReplyPostedMessage(BaseMessage):
    action: Literal["reply_posted"] = "reply_posted"
    payload: ReplyPayload


class CamelTopic(Topic[NewReplyEvent]):
    pattern = "camel:{pk}"
    channel_layer_alias = LAYER_ALIAS

    @ws_handler
    async def handle_post_reply(self, message: PostReplyMessage) -> ReplyPostedMessage:
        return ReplyPostedMessage(payload=message.payload)

    @event_handler
    async def handle_new_reply(self, event: NewReplyEvent) -> ReplyPostedMessage:
        return ReplyPostedMessage(payload=ReplyPayload(reply_text=event.payload))


class CamelConsumer(AsyncJsonWebsocketConsumer[NewReplyEvent]):
    camelize = True
    channel_layer_alias = LAYER_ALIAS
    topics: ClassVar[list[type[Topic[Any]]]] = [CamelTopic]


camel_app = FastAPI()
camel_app.router.add_websocket_route("/ws/camel", CamelConsumer.as_asgi())


@pytest.mark.asyncio
async def test_camelized_consumer_round_trips_topic_frames() -> None:
    """Topic frames follow the consumer's camelize setting in both directions."""
    async with WebsocketCommunicator(
        camel_app, "/ws/camel", consumer=CamelConsumer
    ) as comm:
        confirmed = await _send(
            comm, {"topic": "camel:1", "ref": "1", "action": "subscribe"}
        )
        assert confirmed["action"] == "subscribed"

        # a camelized client sends camelCase keys and gets them back
        reply = await _send(
            comm,
            {
                "topic": "camel:1",
                "ref": "2",
                "action": "post_reply",
                "payload": {"replyText": "hello"},
            },
        )
        assert reply == {
            "action": "reply_posted",
            "payload": {"replyText": "hello"},
            "version": 1,
            "topic": "camel:1",
            "ref": "2",
        }

        # the communicator helper camelizes the same way a generated client does
        await comm.send_message(
            PostReplyMessage(payload=ReplyPayload(reply_text="via helper")),
            topic="camel:1",
            ref="3",
        )
        helper_reply = await comm.receive_json_from(timeout=2)
        assert helper_reply["payload"] == {"replyText": "via helper"}
        assert helper_reply["ref"] == "3"


@pytest.mark.asyncio
async def test_camelized_consumer_broadcasts_camelcase_frames() -> None:
    async with WebsocketCommunicator(
        camel_app, "/ws/camel", consumer=CamelConsumer
    ) as comm:
        await _send(comm, {"topic": "camel:7", "ref": "1", "action": "subscribe"})

        await CamelTopic.broadcast("camel:7", NewReplyEvent(payload="from-broadcast"))

        pushed = await comm.receive_json_from(timeout=2)
        assert pushed == {
            "action": "reply_posted",
            "payload": {"replyText": "from-broadcast"},
            "version": 1,
            "topic": "camel:7",
        }


@pytest.mark.asyncio
async def test_malformed_envelope_reports_a_validation_error() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        # topic must be a string; a list cannot be an envelope
        reply = await _send(
            comm, {"topic": ["not", "a", "topic"], "action": "subscribe"}
        )

        assert reply["action"] == "error"


@pytest.mark.parametrize(
    "frame, detail",
    [
        ({"text": "not json"}, "Invalid JSON: Expecting value"),
        ({"text": ""}, "Invalid JSON: Expecting value"),
        ({"bytes": b"\x01"}, "Invalid JSON: binary frames are not supported"),
    ],
)
@pytest.mark.asyncio
async def test_a_frame_that_is_not_json_gets_an_error_and_keeps_the_socket(
    frame: dict[str, Any], detail: str
) -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        # Raw input, since send_to() refuses an empty text frame
        await comm.send_input({"type": "websocket.receive", **frame})
        reply = await comm.receive_json_from(timeout=2)

        assert reply["action"] == "error"
        assert reply["payload"]["type"] == "https://chanx.dev/errors/invalid-json"
        assert reply["payload"]["detail"].startswith(detail)

        pong = await _send(comm, {"action": "ping"})
        assert pong["action"] == "pong"


@pytest.mark.asyncio
async def test_event_for_an_unsubscribed_topic_is_dropped() -> None:
    """A broadcast racing an unsubscribe is dropped rather than blowing up."""
    consumer = MainConsumer()

    # delivered by the layer after the local unsubscribe already happened
    await consumer.handle_topic_event(
        {
            "type": "handle_topic_event",
            "topic": "discussion:5",
            "seq": None,
            "event_data": NewReplyEvent(payload="late").model_dump(mode="json"),
        }
    )

    assert consumer.subscriptions == {}


def test_a_topic_base_without_a_pattern_is_allowed() -> None:
    """Shared bases declare no pattern; only concrete topics need one."""

    class SharedBase(Topic[NewReplyEvent]):
        pass

    class Concrete(SharedBase):
        pattern = "concrete:{pk}"

    assert Concrete.parse("concrete:5") == {"pk": "5"}


@pytest.mark.asyncio
async def test_subscribing_twice_just_confirms_again() -> None:
    async with WebsocketCommunicator(app, "/ws/hub", consumer=MainConsumer) as comm:
        await _send(comm, {"topic": "discussion:5", "ref": "1", "action": "subscribe"})
        again = await _send(
            comm, {"topic": "discussion:5", "ref": "2", "action": "subscribe"}
        )

        assert again["action"] == "subscribed"
        assert again["ref"] == "2"


@pytest.mark.asyncio
async def test_a_topic_can_close_its_connection() -> None:
    class ByeMessage(BaseMessage):
        action: Literal["bye"] = "bye"
        payload: None = None

    class ClosingTopic(Topic[NewReplyEvent]):
        pattern = "closing:{pk}"
        channel_layer_alias = LAYER_ALIAS

        @ws_handler
        async def handle_bye(self, _message: ByeMessage) -> None:
            await self.send_json({"action": "bye", "payload": None}, close=True)

    class ClosingConsumer(AsyncJsonWebsocketConsumer[NewReplyEvent]):
        channel_layer_alias = LAYER_ALIAS
        topics: ClassVar[list[type[Topic[Any]]]] = [ClosingTopic]

    closing_app = FastAPI()
    closing_app.router.add_websocket_route("/ws/closing", ClosingConsumer.as_asgi())

    async with WebsocketCommunicator(
        closing_app, "/ws/closing", consumer=ClosingConsumer
    ) as comm:
        await _send(comm, {"topic": "closing:1", "ref": "1", "action": "subscribe"})
        farewell = await _send(
            comm, {"topic": "closing:1", "ref": "2", "action": "bye"}
        )

        assert farewell["action"] == "bye"
        closed = await comm.receive_output(timeout=2)
        assert closed["type"] == "websocket.close"
