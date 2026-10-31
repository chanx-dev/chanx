"""Base classes for clients that address topics over one shared connection."""

import asyncio
from types import UnionType
from typing import Annotated, Any, Self, TypeVar

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from .client import BaseClient
from .errors import ERROR_ACTION, ProblemDetails, parse_problem

ENVELOPE_VERSION = 1

HandleT = TypeVar("HandleT", bound="BaseTopicHandle")


class ProtocolMessage(BaseModel):
    """A subscribe/unsubscribe confirmation or an error, not a topic's own message."""

    action: str
    payload: Any = None

    @property
    def problem(self) -> ProblemDetails | None:
        """The error's payload as a ProblemDetails; None for other frames or shapes."""
        if self.action != ERROR_ACTION:
            return None
        return parse_problem(self.payload)


class BaseTopicHandle:
    """
    A typed view of one topic on a shared connection.

    Subclasses set ``pattern`` and ``incoming_message``; the generator derives
    both from the channel's ``x-topic`` extension.
    """

    pattern: str
    incoming_message: type[BaseModel] | UnionType

    def __init__(self, connection: "BaseTopicConnection", **params: Any) -> None:
        """
        Bind a handle to a connection.

        Args:
            connection: The connection owning the socket
            **params: Values for the topic pattern's parameters
        """
        self.connection = connection
        self.topic = self.pattern.format(**params)
        self.params = params
        self.incoming_message_adapter = TypeAdapter[BaseModel](
            Annotated[self.incoming_message, Field(discriminator="action")]
        )

    async def subscribe(self) -> BaseModel:
        """Subscribe, returning the server's reply."""
        return self.validate(
            await self.connection.request(self.topic, {"action": "subscribe"})
        )

    async def unsubscribe(self) -> BaseModel:
        """Unsubscribe, returning the server's reply."""
        return self.validate(
            await self.connection.request(self.topic, {"action": "unsubscribe"})
        )

    async def send_message(self, message: Any) -> None:
        """Send a message on this topic without waiting for a reply."""
        await self.connection.send_topic(self.topic, message.model_dump())

    async def request(self, message: Any) -> BaseModel:
        """Send a message on this topic and wait for the reply carrying its ref."""
        return self.validate(
            await self.connection.request(self.topic, message.model_dump())
        )

    def validate(self, frame: dict[str, Any]) -> BaseModel:
        """
        Parse a reply against this topic's messages.

        Subscription confirmations and errors are protocol frames rather than one of
        the topic's own messages, so they come back as-is.

        Args:
            frame: The decoded reply frame
        """
        try:
            return self.incoming_message_adapter.validate_python(frame)
        except ValidationError:
            return ProtocolMessage.model_validate(frame)

    async def dispatch_frame(self, py_object: dict[str, Any]) -> None:
        """Validate a frame addressed to this topic and hand it to the handler."""
        if py_object.get("action") == ERROR_ACTION:
            await self.handle_error_message(
                parse_problem(py_object.get("payload")), py_object
            )
            return
        try:
            message = self.incoming_message_adapter.validate_python(py_object)
        except ValidationError:
            await self.handle_invalid_message(py_object)
            return
        await self.handle_message(message)

    async def handle_message(self, message: Any) -> None:
        """Handle a message pushed on this topic. Override in subclasses."""

    async def handle_error_message(
        self, problem: ProblemDetails | None, frame: dict[str, Any]
    ) -> None:
        """Handle an error pushed on this topic, such as not-subscribed."""

    async def handle_invalid_message(self, py_object: dict[str, Any]) -> None:
        """Handle a frame that did not match this topic's messages."""


class BaseTopicConnection(BaseClient):
    """
    Owns the socket and fans frames out to topic handles.

    Frames answering a request are matched by ``ref``; the rest are routed by
    ``topic``. Frames with neither belong to the connection's own handlers.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.handles: dict[str, BaseTopicHandle] = {}
        self._pending: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._ref = 0

    def topic(self, handle_class: type[HandleT], **params: Any) -> HandleT:
        """
        Build a handle for a topic and remember it for routing.

        Args:
            handle_class: The generated handle class for the topic
            **params: Values for the topic pattern's parameters
        """
        handle = handle_class(self, **params)
        self.handles[handle.topic] = handle
        return handle

    def _next_ref(self) -> str:
        """Allocate a ref for correlating a reply."""
        self._ref += 1
        return str(self._ref)

    async def send_topic(
        self, topic: str, data: dict[str, Any], ref: str | None = None
    ) -> None:
        """Send a frame stamped with its topic, and a ref when one is expected."""
        frame = dict(data)
        frame["version"] = ENVELOPE_VERSION
        frame["topic"] = topic
        if ref is not None:
            frame["ref"] = ref
        await self.send_json(frame)

    async def request(
        self, topic: str, data: dict[str, Any], timeout: float = 10.0
    ) -> dict[str, Any]:
        """
        Send a frame on a topic and wait for the reply carrying the same ref.

        Args:
            topic: The topic to address
            data: The message body
            timeout: Seconds to wait for the reply
        """
        ref = self._next_ref()
        future: asyncio.Future[dict[str, Any]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[ref] = future
        try:
            await self.send_topic(topic, data, ref=ref)
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(ref, None)

    async def dispatch_frame(self, py_object: dict[str, Any]) -> None:
        """Resolve a pending request, route to a topic, or fall back to the connection."""
        ref = py_object.get("ref")
        if ref is not None:
            future = self._pending.pop(str(ref), None)
            if future is not None and not future.done():
                future.set_result(py_object)
                return

        topic = py_object.get("topic")
        if topic is not None:
            handle = self.handles.get(str(topic))
            if handle is not None:
                await handle.dispatch_frame(py_object)
            return

        await super().dispatch_frame(py_object)

    async def resubscribe(self) -> None:
        """Re-subscribe every handle, for use after a reconnect."""
        for handle in self.handles.values():
            await handle.subscribe()

    async def __aenter__(self) -> Self:
        """Enter a context managing this connection."""
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Close the connection on leaving the context."""
        await self.disconnect()
