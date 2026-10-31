"""
Topic subscriptions multiplexed over a single WebSocket connection.

A topic is a pattern plus its own handlers and authorization. Consumers mount
topics and clients address them per frame, so one connection serves many
resources without a route for each.
"""

import re
from typing import Any, ClassVar

from chanx.core.envelope import TOPIC_EVENT_TYPE
from chanx.core.websocket import ChanxWebsocketConsumerMixin, ReceiveEvent
from chanx.messages.base import BaseMessage
from chanx.utils.framework import channel_layer, consumer_base, detect_framework
from chanx.utils.groups import safe_group_name

_PARAM_RE = re.compile(r"\{(\w+)\}")


class Topic(ChanxWebsocketConsumerMixin[ReceiveEvent]):
    """
    A subscribable stream on a consumer's connection.

    Reuses the consumer machinery for handler discovery, validation and error
    handling, but borrows the connection: outgoing frames are stamped with this
    topic and written through the consumer that hosts it.
    """

    pattern: ClassVar[str]
    # Both frameworks name their default layer "default".
    channel_layer_alias: str = "default"
    # Copied per instance by the consumer mixin's __init__.
    groups: list[str] = []

    param_names: ClassVar[tuple[str, ...]] = ()
    _regex: ClassVar[re.Pattern[str]]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Compile the subclass's pattern into a matcher for its parameters."""
        super().__init_subclass__(**kwargs)

        pattern = cls.__dict__.get("pattern")
        if pattern is None:
            return

        cls.param_names = tuple(_PARAM_RE.findall(pattern))
        # split() alternates literal, param, literal; params stop at ':' so
        # "run:{id}" cannot swallow a following segment.
        parts = _PARAM_RE.split(pattern)
        cls._regex = re.compile(
            "^"
            + "".join(
                re.escape(part) if index % 2 == 0 else f"(?P<{part}>[^:]+)"
                for index, part in enumerate(parts)
            )
            + "$"
        )

    def __init__(self, consumer: ChanxWebsocketConsumerMixin[Any], topic: str) -> None:
        super().__init__()
        self.consumer = consumer
        self.topic = topic
        self.params = self.parse(topic) or {}
        self.scope = consumer.scope
        self.channel_name = consumer.channel_name
        self.channel_layer = consumer.channel_layer
        self.channel_layer_alias = consumer.channel_layer_alias

    @classmethod
    def parse(cls, topic: str) -> dict[str, str] | None:
        """Return the topic's parameters, or None when it does not match."""
        match = cls._regex.match(topic)
        return match.groupdict() if match else None

    @property
    def should_camelize(self) -> bool:
        """Frames share the consumer's connection, so follow its wire format."""
        return self.consumer.should_camelize

    @property
    def uses_standard_errors(self) -> bool:
        """Errors share the consumer's connection, so follow its format."""
        return self.consumer.uses_standard_errors

    @classmethod
    def group_name(cls, topic: str) -> str:
        """
        Map a topic to a channel layer group name.

        The class name prefix keeps two topic classes from colliding once the
        unsupported characters have been replaced.
        """
        return safe_group_name(topic, namespace=cls.__name__)

    async def authorize(self, **params: str) -> bool:
        """Decide whether this connection may subscribe. Override to restrict."""
        return True

    async def on_subscribe(self) -> None:
        """Run once this connection has joined. Override to send initial state."""

    async def on_unsubscribe(self) -> None:
        """Run before this connection leaves, on unsubscribe or disconnect."""

    async def send_json(self, content: dict[str, Any], close: bool = False) -> None:
        """Stamp this topic on an outgoing frame and hand it to the consumer."""
        await self.consumer.send_topic_json(self.topic, content)
        if close:
            await self.consumer.close()

    @classmethod
    def as_consumer(cls) -> Any:
        """
        Build a consumer serving this topic on its own route.

        Connecting subscribes the topic from the URL parameters and un-addressed
        frames belong to it, so the same class works on a dedicated route and on a
        multiplexed connection without the client knowing which it reached.
        """
        return type(
            f"{cls.__name__.removesuffix('Topic')}Consumer",
            (consumer_base(),),
            {
                "topics": [cls],
                "default_topic": cls,
                "channel_layer_alias": cls.channel_layer_alias,
                "__doc__": cls.__doc__,
            },
        )

    @classmethod
    def get_channel_layer(cls, alias: str) -> Any:
        """Resolve the channel layer without binding the topic to a framework."""
        return channel_layer(alias)

    @classmethod
    async def broadcast(
        cls, topic: str, event: BaseMessage, *, seq: int | None = None
    ) -> None:
        """
        Push an event to everyone subscribed to a topic.

        The topic travels on the event, which is what lets a receiving consumer
        route it back without ambiguity. ``seq`` is caller-assigned and only
        supports gap detection, so a topic with several writers leaves it unset.
        """
        channel_layer = cls.get_channel_layer(cls.channel_layer_alias)
        if channel_layer is None:
            raise LookupError(
                f"No channel layer registered under alias"
                f" {cls.channel_layer_alias!r} for the {detect_framework()!r}"
                " integration. chanx resolves the integration once per process from"
                " DJANGO_SETTINGS_MODULE, so a single process cannot serve both"
                " channels and fast_channels."
            )
        await channel_layer.group_send(
            cls.group_name(topic),
            {
                "type": TOPIC_EVENT_TYPE,
                "topic": topic,
                "seq": seq,
                "event_data": event.model_dump(mode="json"),
            },
        )
