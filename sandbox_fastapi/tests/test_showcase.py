from typing import cast

import pytest
from chanx.constants import EVENT_ACTION_COMPLETE, GROUP_ACTION_COMPLETE
from chanx.fast_channels.testing import WebsocketCommunicator
from chanx.messages.incoming import PingMessage
from chanx.messages.outgoing import PongMessage

from sandbox_fastapi.apps.mixins import (
    ExtraPassthroughMessage,
    ExtraRequestMessage,
    ExtraResponseMessage,
)
from sandbox_fastapi.apps.showcase.consumer import (
    AnalyticsConsumer,
    ChatConsumer,
    NotificationConsumer,
    ReliableChatConsumer,
)
from sandbox_fastapi.apps.showcase.messages import (
    AnalyticsMessage,
    AnalyticsNotificationMessage,
    AnalyticsPayload,
    ChatMessage,
    ChatNotificationMessage,
    ChatPayload,
    NotificationBroadcastMessage,
    NotificationMessage,
    NotificationPayload,
    ReliableChatMessage,
    ReliableChatNotificationMessage,
    ReliableChatPayload,
    UserJoinedNotification,
    UserLeftNotification,
)
from sandbox_fastapi.external_sender import (
    send_analytics_event,
    send_chat_message,
    send_notification,
    send_reliable_message,
)
from sandbox_fastapi.main import app


@pytest.mark.asyncio
async def test_chat_consumer_ping() -> None:
    """Test ping-pong functionality for ChatConsumer."""
    async with WebsocketCommunicator(app, "/ws/chat", consumer=ChatConsumer) as comm:
        # Skip join message
        await comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)

        await comm.send_message(PingMessage())
        replies = await comm.receive_all_messages()

        assert len(replies) == 1
        assert replies == [PongMessage()]


@pytest.mark.asyncio
async def test_chat_consumer_extra_handler_from_mixin() -> None:
    """Test extra handler provided by ExtraWsHandlerMixin on ChatConsumer."""
    async with WebsocketCommunicator(app, "/ws/chat", consumer=ChatConsumer) as comm:
        # Skip join message
        await comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)

        await comm.send_message(ExtraRequestMessage(payload="hello"))
        replies = await comm.receive_all_messages()

        assert len(replies) == 1
        assert replies == [ExtraResponseMessage(payload="hello any extra thing")]


@pytest.mark.asyncio
async def test_chat_consumer_messaging() -> None:
    """Test chat messaging and broadcasting."""
    async with WebsocketCommunicator(app, "/ws/chat", consumer=ChatConsumer) as comm:
        # Skip join message
        join_messages = await comm.receive_all_messages(
            stop_action=GROUP_ACTION_COMPLETE
        )
        assert len(join_messages) == 1
        join_message = cast(ChatNotificationMessage, join_messages[0])
        assert join_message.payload.message == "📢 Someone joined the chat"

        # Send chat message
        test_message = "Hello from chat!"
        await comm.send_message(ChatMessage(payload=ChatPayload(message=test_message)))

        replies = await comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)
        assert len(replies) == 1
        chat_reply = cast(ChatNotificationMessage, replies[0])
        assert chat_reply.payload.message == f"💬 {test_message}"


@pytest.mark.asyncio
async def test_reliable_chat_consumer_ping() -> None:
    """Test ping-pong functionality for ReliableChatConsumer."""
    async with WebsocketCommunicator(
        app, "/ws/reliable", consumer=ReliableChatConsumer
    ) as comm:
        # Assert connection message
        join_messages = await comm.receive_all_messages(
            stop_action=GROUP_ACTION_COMPLETE
        )
        assert len(join_messages) == 1
        join_message = cast(ReliableChatNotificationMessage, join_messages[0])
        assert (
            join_message.payload.message == "🔒 Reliable chat connection established!"
        )

        await comm.send_message(PingMessage())
        replies = await comm.receive_all_messages()

        assert len(replies) == 1
        assert replies == [PongMessage()]


@pytest.mark.asyncio
async def test_reliable_chat_consumer_messaging() -> None:
    """Test reliable chat messaging."""
    async with WebsocketCommunicator(
        app, "/ws/reliable", consumer=ReliableChatConsumer
    ) as comm:
        # Assert connection message
        connection_messages = await comm.receive_all_messages(
            stop_action=GROUP_ACTION_COMPLETE
        )
        assert len(connection_messages) == 1
        connection_message = cast(
            ReliableChatNotificationMessage, connection_messages[0]
        )
        assert (
            connection_message.payload.message
            == "🔒 Reliable chat connection established!"
        )

        # Send reliable chat message
        test_message = "Reliable message test"
        await comm.send_message(
            ReliableChatMessage(payload=ReliableChatPayload(message=test_message))
        )

        replies = await comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)
        assert len(replies) == 1
        reliable_reply = cast(ReliableChatNotificationMessage, replies[0])
        assert reliable_reply.payload.message == f"📨 {test_message}"


@pytest.mark.asyncio
async def test_notification_consumer_ping() -> None:
    """Test ping-pong functionality for NotificationConsumer."""
    async with WebsocketCommunicator(
        app, "/ws/notifications", consumer=NotificationConsumer
    ) as comm:
        # Skip connection notification
        await comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)

        await comm.send_message(PingMessage())
        replies = await comm.receive_all_messages()

        assert len(replies) == 1
        assert replies == [PongMessage()]


@pytest.mark.asyncio
async def test_notification_consumer_messaging() -> None:
    """Test notification broadcasting."""
    async with WebsocketCommunicator(
        app, "/ws/notifications", consumer=NotificationConsumer
    ) as comm:
        # assert connection notification
        connection_messages = await comm.receive_all_messages(
            stop_action=GROUP_ACTION_COMPLETE
        )
        assert len(connection_messages) == 1
        connection_message = cast(NotificationBroadcastMessage, connection_messages[0])
        assert connection_message.payload.message == "🔔 Connected to notifications!"
        assert connection_message.payload.type == "system"

        # Send notification
        test_message = "Test notification"
        await comm.send_message(
            NotificationMessage(payload=NotificationPayload(message=test_message))
        )

        replies = await comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)
        assert len(replies) == 1
        notification_reply = cast(NotificationBroadcastMessage, replies[0])
        assert notification_reply.payload.message == f"🔔 Notification: {test_message}"
        assert notification_reply.payload.type == "user"


@pytest.mark.asyncio
async def test_analytics_consumer_ping() -> None:
    """Test ping-pong functionality for AnalyticsConsumer."""
    async with WebsocketCommunicator(
        app, "/ws/analytics", consumer=AnalyticsConsumer
    ) as comm:
        await comm.send_message(PingMessage())
        replies = await comm.receive_all_messages()

        assert len(replies) == 1
        assert replies == [PongMessage()]


@pytest.mark.asyncio
async def test_analytics_consumer_events() -> None:
    """Test analytics event processing."""
    async with WebsocketCommunicator(
        app, "/ws/analytics", consumer=AnalyticsConsumer
    ) as comm:
        # Send analytics event
        test_event = "user_click"
        test_data = {"button": "submit", "page": "home"}
        await comm.send_message(
            AnalyticsMessage(payload=AnalyticsPayload(event=test_event, data=test_data))
        )

        replies = await comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)
        assert len(replies) == 1
        analytics_reply = cast(AnalyticsNotificationMessage, replies[0])
        assert analytics_reply.payload.event == f"📊 Analytics: {test_event}"
        assert analytics_reply.payload.data == test_data


@pytest.mark.asyncio
async def test_analytics_consumer_events_no_data() -> None:
    """Test analytics event processing without data."""
    async with WebsocketCommunicator(
        app, "/ws/analytics", consumer=AnalyticsConsumer
    ) as comm:
        # Send analytics event without data
        test_event = "page_view"
        await comm.send_message(
            AnalyticsMessage(payload=AnalyticsPayload(event=test_event))
        )

        replies = await comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)
        assert len(replies) == 1
        analytics_reply = cast(AnalyticsNotificationMessage, replies[0])
        assert analytics_reply.payload.event == f"📊 Analytics: {test_event}"
        assert analytics_reply.payload.data is None


@pytest.mark.asyncio
async def test_external_sender_broadcast() -> None:
    """Test external sender script broadcasts to all consumers."""
    # Setup all consumers
    chat_comm = WebsocketCommunicator(app, "/ws/chat", consumer=ChatConsumer)
    reliable_comm = WebsocketCommunicator(
        app, "/ws/reliable", consumer=ReliableChatConsumer
    )
    notification_comm = WebsocketCommunicator(
        app, "/ws/notifications", consumer=NotificationConsumer
    )
    analytics_comm = WebsocketCommunicator(
        app, "/ws/analytics", consumer=AnalyticsConsumer
    )

    # Connect all consumers
    await chat_comm.connect()
    await reliable_comm.connect()
    await notification_comm.connect()
    await analytics_comm.connect()

    # Clear initial connection messages
    await chat_comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)
    await reliable_comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)
    await notification_comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)
    # Analytics doesn't send connection messages

    # Import and call external sender functions

    # Test chat message broadcast
    await send_chat_message()
    chat_replies = await chat_comm.receive_all_messages(
        stop_action=GROUP_ACTION_COMPLETE
    )
    assert len(chat_replies) == 1
    chat_reply = cast(ChatNotificationMessage, chat_replies[0])
    assert chat_reply.payload.message == "🔔 System announcement: Welcome to the chat!"

    # Test reliable message broadcast
    await send_reliable_message()
    reliable_replies = await reliable_comm.receive_all_messages(
        stop_action=GROUP_ACTION_COMPLETE
    )
    assert len(reliable_replies) == 1
    reliable_reply = cast(ChatNotificationMessage, reliable_replies[0])
    assert (
        reliable_reply.payload.message
        == "🔒 Important: System maintenance scheduled for tonight"
    )

    # Test notification broadcast
    await send_notification()
    notification_replies = await notification_comm.receive_all_messages(
        stop_action=GROUP_ACTION_COMPLETE
    )
    assert len(notification_replies) == 1
    notification_reply = cast(NotificationBroadcastMessage, notification_replies[0])
    assert (
        notification_reply.payload.message
        == "🚨 Alert: High CPU usage detected on server"
    )

    # Test analytics events broadcast
    await send_analytics_event()
    analytics_replies = await analytics_comm.receive_all_messages(
        stop_action=GROUP_ACTION_COMPLETE
    )

    # Should receive 5 analytics events
    assert len(analytics_replies) == 5
    expected_events = [
        "user_login:john_doe",
        "page_view:/dashboard",
        "button_click:export_data",
        "session_duration:1234",
        "error:api_timeout",
    ]

    for i, reply in enumerate(analytics_replies):
        analytics_reply = cast(AnalyticsNotificationMessage, reply)
        assert analytics_reply.payload.event == expected_events[i]
    await chat_comm.disconnect()
    await reliable_comm.disconnect()
    await notification_comm.disconnect()
    await analytics_comm.disconnect()


@pytest.mark.asyncio
async def test_chat_consumer_passthrough_user_joined() -> None:
    """Test that UserJoinedNotification passthrough event is forwarded to client."""
    async with WebsocketCommunicator(app, "/ws/chat", consumer=ChatConsumer) as comm:
        # Skip join message
        await comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)

        # Broadcast a passthrough event from outside
        await ChatConsumer.broadcast_event(
            UserJoinedNotification(payload=ChatPayload(message="Alice joined"))
        )

        replies = await comm.receive_all_messages(stop_action=EVENT_ACTION_COMPLETE)
        assert len(replies) == 1
        reply = cast(UserJoinedNotification, replies[0])
        assert reply.action == "user_joined_notification"
        assert reply.payload.message == "Alice joined"


@pytest.mark.asyncio
async def test_chat_consumer_passthrough_user_left() -> None:
    """Test that UserLeftNotification passthrough event is forwarded to client."""
    async with WebsocketCommunicator(app, "/ws/chat", consumer=ChatConsumer) as comm:
        # Skip join message
        await comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)

        # Broadcast a passthrough event from outside
        await ChatConsumer.broadcast_event(
            UserLeftNotification(payload=ChatPayload(message="Bob left"))
        )

        replies = await comm.receive_all_messages(stop_action=EVENT_ACTION_COMPLETE)
        assert len(replies) == 1
        reply = cast(UserLeftNotification, replies[0])
        assert reply.action == "user_left_notification"
        assert reply.payload.message == "Bob left"


@pytest.mark.asyncio
async def test_chat_consumer_passthrough_multiple_events() -> None:
    """Test multiple passthrough events forwarded in sequence."""
    async with WebsocketCommunicator(app, "/ws/chat", consumer=ChatConsumer) as comm:
        # Skip join message
        await comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)

        # Send joined then left
        await ChatConsumer.broadcast_event(
            UserJoinedNotification(payload=ChatPayload(message="Alice joined"))
        )
        replies = await comm.receive_all_messages(stop_action=EVENT_ACTION_COMPLETE)
        assert len(replies) == 1
        assert (
            cast(UserJoinedNotification, replies[0]).payload.message == "Alice joined"
        )

        await ChatConsumer.broadcast_event(
            UserLeftNotification(payload=ChatPayload(message="Alice left"))
        )
        replies = await comm.receive_all_messages(stop_action=EVENT_ACTION_COMPLETE)
        assert len(replies) == 1
        assert cast(UserLeftNotification, replies[0]).payload.message == "Alice left"


@pytest.mark.asyncio
async def test_chat_consumer_passthrough_from_mixin() -> None:
    """Test that a passthrough event contributed by a mixin is forwarded to client."""
    async with WebsocketCommunicator(app, "/ws/chat", consumer=ChatConsumer) as comm:
        # Skip join message
        await comm.receive_all_messages(stop_action=GROUP_ACTION_COMPLETE)

        # ExtraPassthroughMessage comes from ExtraPassthroughMixin, not ChatConsumer's
        # own passthrough_events — proves the two lists are merged across the MRO.
        await ChatConsumer.broadcast_event(
            ExtraPassthroughMessage(payload="from mixin")
        )

        replies = await comm.receive_all_messages(stop_action=EVENT_ACTION_COMPLETE)
        assert len(replies) == 1
        reply = cast(ExtraPassthroughMessage, replies[0])
        assert reply.action == "extra_passthrough"
        assert reply.payload == "from mixin"
