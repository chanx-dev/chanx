"""
Core WebSocket testing utilities for chanx.

This module provides fundamental testing infrastructure for WebSocket consumers,
including an enhanced WebsocketCommunicator mixin with structured message handling,
automatic message collection, completion signal tracking, and message validation.

The mixin provides framework-agnostic testing functionality that can be combined
with framework-specific WebSocket communicator implementations (Django Channels,
fast-channels, etc.) to create concrete testing utilities.
"""

import asyncio
from collections.abc import Collection, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self, cast

import humps
from asgiref.timeout import timeout as async_timeout

from chanx.constants import (
    COMPLETE_ACTIONS,
    COMPLETE_ACTIONS_TYPE,
    ENVELOPE_FIELDS,
    ENVELOPE_VERSION,
    MESSAGE_ACTION_COMPLETE,
)
from chanx.core.config import config
from chanx.core.websocket import ChanxWebsocketConsumerMixin
from chanx.messages.base import BaseMessage

INNER_RECEIVE_MARGIN = 5
"""Seconds by which a collection's inner receive outlives the collection itself.

``receive_all_json`` and ``receive_all_messages`` wrap their own timeout around
``receive_json_from``. Handing the inner receive the same value puts both
deadlines in the same event-loop iteration, so a late wake-up - a loaded test
suite is enough - expires them together. asgiref reacts to the inner one by
cancelling the ASGI application task
(``ApplicationCommunicator.receive_output``), which kills the connection: the
collection still returns what it had, but every later send on that
communicator raises ``CancelledError`` from a stack that says nothing about
why. Giving the inner receive a later deadline keeps the collection's own
timeout the one that fires.
"""


@dataclass
class CapturedTopicBroadcast:
    """One publish recorded by :func:`capture_topic_broadcasts`."""

    topic: str
    event: BaseMessage
    seq: int | None


@contextmanager
def capture_topic_broadcasts(
    topic_class: Any, *, suppress: bool = True
) -> Generator[list[CapturedTopicBroadcast]]:
    """
    Record what a topic published, rather than observing it on a second connection.

    Asserting on a broadcast usually means opening another client and reading its
    messages, which conflates what was *published* with what got *delivered*. This
    checks the publish side directly.

    Suppressed by default, so the broadcast is recorded and not delivered. Pass
    ``suppress=False`` to keep delivery working, which also makes the assertion
    deterministic: reading the delivered message proves the publish already happened.

    Args:
        topic_class: The Topic whose broadcasts to record
        suppress: Whether to swallow the broadcast instead of delivering it
    """
    captured: list[CapturedTopicBroadcast] = []
    original = topic_class.broadcast
    owned = "broadcast" in topic_class.__dict__

    # a classmethod, so an instance calling self.broadcast() still binds the class
    async def spy(_cls: Any, topic: str, event: Any, *, seq: int | None = None) -> None:
        """Record the publish, then forward it unless suppressed."""
        captured.append(CapturedTopicBroadcast(topic=topic, event=event, seq=seq))
        if not suppress:
            await original(topic, event, seq=seq)

    topic_class.broadcast = classmethod(spy)
    try:
        yield captured
    finally:
        if owned:
            topic_class.broadcast = original
        else:
            del topic_class.broadcast


@dataclass
class CapturedBroadcastEvent:
    """Structure of a captured broadcast event."""

    event: BaseMessage
    groups: Collection[str] | str | None


class WebsocketCommunicatorMixin:
    """
    Mixin providing enhanced WebSocket testing functionality for chanx consumers.

    This mixin provides chanx-specific features that work across different WebSocket
    frameworks (Django Channels, fast-channels, etc.):

    - Structured message sending and receiving with BaseMessage objects
    - Automatic message collection until completion signals
    - Message validation using consumer's type adapters
    - Connection state tracking
    - Async context manager support for automatic cleanup

    Key methods:

    - send_message(): Send BaseMessage objects directly
    - receive_all_json(): Collect all messages until timeout
    - receive_all_messages(): Collect and validate messages until stop action
    - connect()/disconnect(): Enhanced connection management

    The mixin automatically handles message serialization/deserialization and integrates
    with chanx's completion signal system for reliable testing.

    Concrete implementations should inherit from both this mixin and a framework-specific
    WebSocket communicator class (e.g., channels.testing.WebsocketCommunicator).
    """

    # These will be set by concrete implementations or during initialization
    application: Any
    action_key: str = "action"
    consumer: type[ChanxWebsocketConsumerMixin]  # Consumer class for message validation
    _connected: bool

    # Framework-provided methods (redefined for type checking)
    async def receive_json_from(self, timeout: float = 1) -> Any:
        """
        Receive and parse JSON data from the WebSocket.

        Provided by the framework testing communicator (Channels/fast-channels).

        Args:
            timeout: Maximum time to wait for data (seconds)

        Returns:
            Parsed JSON data as dictionary
        """
        return await super().receive_json_from(timeout)  # type: ignore[misc]

    async def send_json_to(self, data: dict[str, Any]) -> None:
        """
        Send JSON data to the WebSocket.

        Provided by the framework testing communicator (Channels/fast-channels).

        Args:
            data: Dictionary to serialize and send as JSON
        """
        await super().send_json_to(data)  # type: ignore[misc]

    async def receive_output(self, timeout: float = 1) -> Any:
        """
        Receive raw output from the WebSocket.

        Provided by the framework testing communicator (Channels/fast-channels).

        Args:
            timeout: Maximum time to wait for output (seconds)

        Returns:
            Raw output dictionary
        """
        return await super().receive_output(timeout)  # type: ignore[misc]

    def __init__(
        self,
        application: Any,
        path: str,
        headers: list[tuple[bytes, bytes]] | None = None,
        subprotocols: list[str] | None = None,
        spec_version: int | None = None,
        *,
        consumer: type[ChanxWebsocketConsumerMixin[Any]],
    ) -> None:
        """
        Initialize the WebSocket communicator for testing.

        Sets up the communicator with the specified application and path,
        and initializes connection tracking.

        Args:
            application: The ASGI application (usually a consumer)
            path: The WebSocket path to connect to
            headers: Optional HTTP headers for the connection
            subprotocols: Optional WebSocket subprotocols
            spec_version: Optional WebSocket spec version
        """
        super().__init__(application, path, headers, subprotocols, spec_version)  # type: ignore
        self._connected = False

        self.consumer = consumer

    async def receive_all_json(self, timeout: float = 1) -> list[dict[str, Any]]:
        """
        Receives and collects all JSON messages until an ACTION_COMPLETE message
        is received or timeout occurs.

        Args:
            timeout: Maximum time to wait for messages (in seconds)

        Returns:
            List of received JSON messages
        """
        json_list: list[dict[str, Any]] = []
        try:
            async with async_timeout(timeout):
                while True:
                    raw_message = await self.receive_json_from(
                        timeout + INNER_RECEIVE_MARGIN
                    )
                    json_list.append(raw_message)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

        return json_list

    async def receive_all_messages(
        self,
        stop_action: COMPLETE_ACTIONS_TYPE | str = MESSAGE_ACTION_COMPLETE,
        timeout: float = 1,
    ) -> list[BaseMessage]:
        """
        Receives and collects JSON messages until a specific action is received.

        Automatically filters out completion messages (ACTION_COMPLETE and GROUP_ACTION_COMPLETE).

        Args:
            stop_action: The action type to stop collecting at
            timeout: Maximum time to wait for messages (in seconds)

        Returns:
            List of received JSON messages (excluding completion messages)
        """
        if not self.consumer:
            raise ValueError("consumer must be initialized to use this method")

        messages: list[BaseMessage] = []

        try:
            async with async_timeout(timeout):
                while True:
                    raw_message = await self.receive_json_from(
                        timeout + INNER_RECEIVE_MARGIN
                    )

                    if self._should_camelize:
                        raw_message = humps.decamelize(raw_message)

                    message_action = raw_message.get(self.action_key)

                    if message_action not in COMPLETE_ACTIONS:
                        message = (
                            self.consumer.outgoing_message_adapter.validate_python(
                                raw_message
                            )
                        )
                        messages.append(message)

                    if message_action == stop_action:
                        break
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
        return messages

    @property
    def _should_camelize(self) -> bool:
        """Whether the consumer under test speaks camelCase on the wire."""
        return getattr(self.consumer, "camelize", False) or config.camelize

    async def send_message(
        self, message: BaseMessage, *, topic: str | None = None, ref: str | None = None
    ) -> None:
        """
        Sends a Message object as JSON to the WebSocket.

        Args:
            message: The Message instance to send
            topic: Address the message to a topic instead of the consumer
            ref: Correlate the reply with this request
        """
        content = message.model_dump()
        if self._should_camelize:
            content = humps.camelize(content)
        if topic is not None:
            content |= {"version": ENVELOPE_VERSION, "topic": topic}
        if ref is not None:
            content["ref"] = ref
        await self.send_json_to(content)

    async def subscribe(self, topic: str, ref: str = "1") -> dict[str, Any]:
        """
        Subscribe to a topic and return the reply frame.

        Args:
            topic: The topic to subscribe to
            ref: Ref to correlate the reply with
        """
        await self.send_json_to(
            {
                "version": ENVELOPE_VERSION,
                "topic": topic,
                "ref": ref,
                "action": "subscribe",
            }
        )
        return cast(dict[str, Any], await self.receive_json_from())

    async def unsubscribe(self, topic: str, ref: str = "1") -> dict[str, Any]:
        """
        Unsubscribe from a topic and return the reply frame.

        Args:
            topic: The topic to unsubscribe from
            ref: Ref to correlate the reply with
        """
        await self.send_json_to(
            {
                "version": ENVELOPE_VERSION,
                "topic": topic,
                "ref": ref,
                "action": "unsubscribe",
            }
        )
        return cast(dict[str, Any], await self.receive_json_from())

    async def receive_topic_message(
        self, topic_class: Any, timeout: float = 1
    ) -> BaseMessage:
        """
        Receive one frame and validate it against a topic's own messages.

        Args:
            topic_class: The Topic whose messages the frame should match
            timeout: Maximum time to wait
        """
        raw = await self.receive_json_from(timeout)
        if self._should_camelize:
            raw = humps.decamelize(raw)
        return cast(
            BaseMessage,
            topic_class.outgoing_message_adapter.validate_python(
                {k: v for k, v in raw.items() if k not in ENVELOPE_FIELDS}
            ),
        )

    async def assert_closed(self, code: int | None = None) -> None:
        """Asserts that the WebSocket has been closed, with `code` when given."""
        closed_status = await self.receive_output()
        assert closed_status["type"] == "websocket.close"
        if code is not None:
            assert closed_status.get("code") == code

    async def connect(self, timeout: float = 1) -> tuple[bool, int | str | None]:
        """
        Connects to the WebSocket and tracks connection state.

        Args:
            timeout: Maximum time to wait for connection (in seconds)

        Returns:
            Tuple of (connected, status_code)
        """
        try:
            res = await super().connect(timeout)  # type: ignore
            self._connected = True
            return cast(tuple[bool, int | str | None], res)
        except:
            raise

    async def disconnect(self, code: int = 1000, timeout: float = 1) -> None:
        """
        Closes the socket

        Args:
            code: Optional code to disconnect
            timeout: Maximum time to wait for connection (in seconds)
        """
        try:
            await super().disconnect(code, timeout)  # type: ignore
        except asyncio.CancelledError:
            pass

    async def __aenter__(self) -> Self:
        """Async context manager entry - connects to WebSocket."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async context manager exit - disconnects from WebSocket."""
        await self.disconnect()


@contextmanager
def capture_broadcast_events(
    consumer: type[ChanxWebsocketConsumerMixin],
    suppress: bool = True,
) -> Generator[list[CapturedBroadcastEvent], None, None]:
    """
    Capture broadcast events sent via broadcast_event() for testing purposes.

    Similar to structlog's capture_logs(), this context manager captures calls to
    broadcast_event() by monkey-patching the broadcast_event method to spy on events.

    Args:
        consumer: The consumer class to capture broadcast events from.
        suppress: If True (default), suppress actual broadcast event calls.
                  If False, capture events and still call the original broadcast_event.

    Returns:
        A list that will be populated with captured broadcast events.
    """
    captured_events: list[CapturedBroadcastEvent] = []

    # Save the original broadcast_event method
    original_broadcast_event = consumer.broadcast_event

    # Create wrapper that captures events
    async def capture_wrapper(
        _cls: type[ChanxWebsocketConsumerMixin],
        event: BaseMessage,
        groups: Collection[str] | str | None = None,
    ) -> None:
        """Wrapper that captures the event before calling original."""

        # Capture the event directly
        captured_events.append(
            CapturedBroadcastEvent(
                event=event,
                groups=groups,
            )
        )

        # Only call original if not suppressing
        if not suppress:
            await original_broadcast_event(event, groups)

    # Monkey-patch the method
    consumer.broadcast_event = classmethod(capture_wrapper)  # type: ignore[method-assign, assignment]

    try:
        yield captured_events
    finally:
        # Restore original method
        consumer.broadcast_event = original_broadcast_event  # type: ignore[method-assign]
