"""Topics driven through a real Django Channels connection."""

from typing import Any, ClassVar, Literal

from channels.routing import URLRouter

from chanx.channels.routing import path
from chanx.channels.testing import WebsocketTestCase
from chanx.channels.websocket import AsyncJsonWebsocketConsumer
from chanx.constants import COMPLETE_ACTIONS
from chanx.core.decorators import event_handler, ws_handler
from chanx.core.topic import Topic
from chanx.messages.base import BaseMessage
from chanx.messages.incoming import PingMessage
from chanx.messages.outgoing import PongMessage


class JoinMessage(BaseMessage):
    action: Literal["join"] = "join"
    payload: None = None


class JoinedMessage(BaseMessage):
    action: Literal["joined"] = "joined"
    payload: str


class RoomEvent(BaseMessage):
    action: Literal["room_event"] = "room_event"
    payload: str


class DjangoRoomTopic(Topic[RoomEvent]):
    """A room, addressed as room:<room_id>."""

    pattern = "room:{room_id}"

    @ws_handler
    async def handle_join(self, _message: JoinMessage) -> JoinedMessage:
        return JoinedMessage(payload=self.params["room_id"])

    @event_handler
    async def handle_room_event(self, event: RoomEvent) -> RoomEvent:
        return event


class DjangoPrivateTopic(Topic[RoomEvent]):
    """Only one room may be subscribed."""

    pattern = "private:{room_id}"

    async def authorize(self, **params: str) -> bool:
        return params["room_id"] == "open"

    @event_handler
    async def handle_room_event(self, event: RoomEvent) -> RoomEvent:
        return event


class DjangoHubConsumer(AsyncJsonWebsocketConsumer[RoomEvent]):
    """Hub serving topics over one Django Channels connection."""

    topics: ClassVar[list[type[Topic[Any]]]] = [DjangoRoomTopic, DjangoPrivateTopic]

    @ws_handler
    async def handle_ping(self, _message: PingMessage) -> PongMessage:
        return PongMessage()


DjangoRoomTopicConsumer = DjangoRoomTopic.as_consumer()


class TestTopicsOverChannels(WebsocketTestCase):
    ws_path = "/ws/hub"
    consumer = DjangoHubConsumer
    router = URLRouter(
        [
            path("ws/hub", DjangoHubConsumer.as_asgi()),
            path("ws/room/<str:room_id>", DjangoRoomTopicConsumer.as_asgi()),
        ]
    )

    async def test_subscribe_and_address_a_topic(self) -> None:
        await self.auth_communicator.connect()

        reply = await self.auth_communicator.subscribe("room:lobby")
        assert reply["action"] == "subscribed"
        assert reply["topic"] == "room:lobby"

        await self.auth_communicator.send_message(
            JoinMessage(), topic="room:lobby", ref="2"
        )
        joined = await self.auth_communicator.receive_json_from()
        assert joined["action"] == "joined"
        assert joined["payload"] == "lobby"
        assert joined["ref"] == "2"

    async def test_untopiced_reply_echoes_the_ref(self) -> None:
        await self.auth_communicator.connect()

        await self.auth_communicator.send_message(PingMessage(), ref="3")
        reply = await self.auth_communicator.receive_json_from()
        assert reply["action"] == "pong"
        assert reply["ref"] == "3"

    async def test_a_frame_that_is_not_json_gets_an_error_and_keeps_the_socket(
        self,
    ) -> None:
        await self.auth_communicator.connect()

        await self.auth_communicator.send_to(text_data="not json")
        reply = await self.auth_communicator.receive_json_from()
        assert reply["payload"]["type"] == "https://chanx.dev/errors/invalid-json"

        await self.auth_communicator.send_to(bytes_data=b"\x01")
        reply = await self.auth_communicator.receive_json_from()
        assert reply["payload"]["type"] == "https://chanx.dev/errors/invalid-json"

        await self.auth_communicator.send_message(PingMessage())
        reply = await self.auth_communicator.receive_json_from()
        assert reply["action"] == "pong"

    async def test_untopiced_reply_without_a_ref_is_unchanged(self) -> None:
        await self.auth_communicator.connect()

        await self.auth_communicator.send_message(PingMessage())
        reply = await self.auth_communicator.receive_json_from()
        assert reply == {"action": "pong", "payload": None}

    async def test_authorize_denies_per_topic(self) -> None:
        await self.auth_communicator.connect()

        denied = await self.auth_communicator.subscribe("private:secret")
        assert denied["action"] == "error"
        assert denied["payload"]["type"] == "https://chanx.dev/errors/unauthorized"

        allowed = await self.auth_communicator.subscribe("private:open", ref="2")
        assert allowed["action"] == "subscribed"

    async def test_unknown_topic_reports_a_reason(self) -> None:
        await self.auth_communicator.connect()

        unknown = await self.auth_communicator.subscribe("nope:1")
        assert unknown["payload"]["type"] == "https://chanx.dev/errors/unknown-topic"

    async def test_broadcast_reaches_the_subscribed_topic(self) -> None:
        await self.auth_communicator.connect()
        await self.auth_communicator.subscribe("room:lobby")

        await DjangoRoomTopic.broadcast("room:lobby", RoomEvent(payload="hi"), seq=3)

        pushed = await self.auth_communicator.receive_json_from()
        assert pushed["action"] == "room_event"
        assert pushed["topic"] == "room:lobby"
        assert pushed["seq"] == 3

    async def test_untopiced_frame_falls_through_to_the_consumer(self) -> None:
        await self.auth_communicator.connect()

        await self.auth_communicator.send_message(PingMessage())
        reply = await self.auth_communicator.receive_json_from()
        assert reply["action"] == "pong"
        assert "topic" not in reply

    async def test_unsubscribe_stops_delivery(self) -> None:
        await self.auth_communicator.connect()
        await self.auth_communicator.subscribe("room:lobby")
        left = await self.auth_communicator.unsubscribe("room:lobby", ref="2")
        assert left["action"] == "unsubscribed"

        await DjangoRoomTopic.broadcast("room:lobby", RoomEvent(payload="gone"))
        assert await self.auth_communicator.receive_nothing(timeout=0.3) is True


class TestStandaloneTopicRoute(WebsocketTestCase):
    """The same Topic class on its own path, sharing the group."""

    ws_path = "/ws/room/lobby"
    consumer = DjangoRoomTopicConsumer
    router = URLRouter(
        [
            path("ws/hub", DjangoHubConsumer.as_asgi()),
            path("ws/room/<str:room_id>", DjangoRoomTopicConsumer.as_asgi()),
        ]
    )

    async def test_connect_subscribes_and_shares_the_group(self) -> None:
        await self.auth_communicator.connect()

        subscribed = await self.auth_communicator.receive_json_from()
        assert subscribed["action"] == "subscribed"

        # no envelope needed on a dedicated route
        await self.auth_communicator.send_message(JoinMessage())
        joined = await self.auth_communicator.receive_json_from()
        assert joined["payload"] == "lobby"

        await DjangoRoomTopic.broadcast("room:lobby", RoomEvent(payload="from hub"))
        pushed = await self.auth_communicator.receive_json_from()
        while pushed["action"] in COMPLETE_ACTIONS:
            pushed = await self.auth_communicator.receive_json_from()
        assert pushed["payload"] == "from hub"
