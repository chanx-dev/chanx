"""
Enhanced WebSocket consumer with automatic type generation and message routing.

This module provides the core AsyncJsonWebsocketConsumer class that extends
the base WebSocket consumer with automatic message type discovery, validation,
authentication, group broadcasting, and channel event handling capabilities.
"""

import asyncio
import inspect
import uuid
from collections.abc import Awaitable, Callable, Collection, Mapping, MutableMapping
from functools import reduce
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    ClassVar,
    Generic,
    cast,
    get_args,
    get_origin,
)

import humps
import structlog
from asgiref.sync import async_to_sync
from pydantic import Field, TypeAdapter, ValidationError
from typing_extensions import TypeVar

from chanx.constants import COMPLETE_ACTIONS, ENVELOPE_VERSION
from chanx.core.authenticator import BaseAuthenticator
from chanx.core.config import config
from chanx.core.decorators import event_handler
from chanx.core.envelope import (
    Envelope,
    TopicErrorReason,
    current_ref,
    current_seq,
    strip_envelope,
)
from chanx.core.errors import (
    ErrorFormat,
    ErrorType,
    current_input,
    problem,
    validation_problem,
)
from chanx.core.registry import message_registry
from chanx.messages.base import BaseMessage
from chanx.messages.outgoing import (
    CompleteMessage,
    ErrorMessage,
    EventCompleteMessage,
    GroupCompleteMessage,
)
from chanx.messages.topic import (
    SubscribedMessage,
    SubscribeMessage,
    UnsubscribedMessage,
    UnsubscribeMessage,
)
from chanx.type_defs import AsyncAPIHandlerInfo, EventPayload, GroupMessageEvent
from chanx.utils.asyncio import create_task
from chanx.utils.logging import logger
from chanx.utils.scope import path_params

if TYPE_CHECKING:
    from chanx.core.topic import Topic

ReceiveEvent = TypeVar("ReceiveEvent", bound=BaseMessage, default=BaseMessage)

_TOPIC_ERROR_TYPES = {
    TopicErrorReason.UNKNOWN_TOPIC: ErrorType.UNKNOWN_TOPIC,
    TopicErrorReason.UNAUTHORIZED: ErrorType.UNAUTHORIZED,
    TopicErrorReason.NOT_SUBSCRIBED: ErrorType.NOT_SUBSCRIBED,
}


class ChanxWebsocketConsumerMixin(Generic[ReceiveEvent]):
    """
    Mixin providing enhanced WebSocket consumer functionality with automatic message routing.

    Provides automatic message type discovery from @ws_handler and @event_handler decorators,
    type-safe message validation using Pydantic discriminated unions, built-in authentication,
    group broadcasting, channel event system, and comprehensive error handling.
    """

    # Configuration attributes - can be overridden in subclasses
    send_completion: bool
    send_message_immediately: bool | None = config.send_message_immediately
    log_websocket_message: bool | None = config.log_websocket_message
    log_ignored_actions: Collection[str] = config.log_ignored_actions

    # Class-level configuration
    camelize: ClassVar[bool]
    error_format: ClassVar[ErrorFormat]
    discriminator_field: ClassVar[str] = (
        "action"  # Field used for message type discrimination
    )

    # Passthrough events - list of BaseMessage subclasses that are automatically
    # forwarded to the WebSocket client without any processing.
    passthrough_events: ClassVar[list[type[BaseMessage]]] = []
    passthrough_method_prefix: ClassVar[str] = "handle_passthrough_"

    # Messages the consumer sends outside any handler, such as a welcome from
    # post_authentication. Documented and validated like handler output.
    emits: ClassVar[list[type[BaseMessage]]] = []
    _merged_emits: ClassVar[list[type[BaseMessage]]] = []

    # Topics this connection serves. Empty means the consumer behaves exactly as a
    # consumer without topics.
    topics: ClassVar[list[type["Topic[Any]"]]] = []

    # Subscribed from the URL parameters on connect; un-addressed frames are its.
    default_topic: ClassVar[type["Topic[Any]"] | None] = None

    # Cancel in-flight handlers on disconnect, for long work only the caller wants.
    cancel_handlers_on_disconnect: ClassVar[bool] = False

    # Groups contributed by mixins, merged across the MRO. Kept separate from
    # ``groups``, which the underlying framework owns and shadows as usual.
    extra_groups: ClassVar[list[str]] = []
    _merged_extra_groups: ClassVar[list[str]] = []

    # Internal handler registries - populated automatically by metaclass
    _MESSAGE_HANDLER_INFO_MAP: dict[str, AsyncAPIHandlerInfo] = (
        {}
    )  # WebSocket message handlers
    _EVENT_HANDLER_INFO_MAP: dict[str, AsyncAPIHandlerInfo] = (
        {}
    )  # Channel event handlers

    # Authentication
    authenticator: BaseAuthenticator | None = None  # Active authenticator instance
    authenticator_class: type[BaseAuthenticator] | None = (
        None  # Authenticator class to instantiate
    )

    # Framework attributes (set by channels/fast-channels)
    scope: MutableMapping[str, Any]
    groups: list[str]  # Channel groups this consumer belongs to
    channel_layer: (
        Any  # Channel layer instance for group operations (framework-provided)
    )
    channel_name: str  # Unique channel name for this consumer instance
    channel_layer_alias: str

    # Auto-generated type adapters (built by metaclass)
    # None when no handlers are registered for that direction
    incoming_message_adapter: ClassVar[
        TypeAdapter[BaseMessage] | None
    ]  # Validates incoming messages
    incoming_event_adapter: ClassVar[
        TypeAdapter[BaseMessage] | None
    ]  # Validates incoming events
    outgoing_message_adapter: ClassVar[
        TypeAdapter[BaseMessage]
    ]  # Validates outgoing messages

    # Consumer identification (auto-generated from class name)
    name: ClassVar[str]  # Consumer name without "Consumer" suffix
    snake_name: ClassVar[str]  # Snake case version of consumer name

    get_channel_layer: Callable[[Any], Any]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """
        Automatically build discriminated union from @ws_handler and @event_handler decorated methods.

        Called when a class inherits from AsyncJsonWebsocketConsumer. Scans for decorated methods,
        extracts message types, and builds type adapters for validation and routing.
        """
        super().__init_subclass__(**kwargs)

        cls.name = cls.__name__.removesuffix("Consumer")
        cls.snake_name = humps.decamelize(cls.name)

        # Skip if this is the abstract base class itself
        if cls.__name__ == "AbstractAsyncJsonWebsocketConsumer":
            return

        # Initialize handler info maps
        cls._MESSAGE_HANDLER_INFO_MAP = {}
        cls._EVENT_HANDLER_INFO_MAP = {}

        cls._merged_extra_groups = cls._collect_from_mro("extra_groups")
        cls._merged_emits = cls._collect_messages("emits")

        # Process all handlers
        cls._process_handlers()

    @classmethod
    def _process_handlers(cls) -> None:
        """
        Scan all methods in the class for handler decorators and process them.

        Also processes passthrough_events to create synthetic event handlers.
        """
        # Scan all methods in the class (skip private/special attributes)
        for attr_name in dir(cls):
            # Skip private attributes and known problematic ones
            if attr_name.startswith("_") or attr_name in ("__abstractmethods__",):
                continue

            try:
                attr = getattr(cls, attr_name)
            except AttributeError:
                # Skip attributes that can't be accessed
                continue

            # Process WebSocket handlers
            if hasattr(attr, "_ws_handler_info"):
                ws_handler_info: AsyncAPIHandlerInfo = attr._ws_handler_info
                cls._register_handler_info(
                    cls._MESSAGE_HANDLER_INFO_MAP, ws_handler_info, "message"
                )

            # Process event handlers
            if hasattr(attr, "_event_handler_info"):
                event_handler_info: AsyncAPIHandlerInfo = attr._event_handler_info
                cls._register_handler_info(
                    cls._EVENT_HANDLER_INFO_MAP, event_handler_info, "event"
                )

        # Process passthrough events
        cls._process_passthrough_events()

        # Register handler messages and build adapters
        cls._register_handler_messages()
        cls._build_adapters()

    @classmethod
    def _register_handler_info(
        cls,
        handler_info_map: dict[str, AsyncAPIHandlerInfo],
        handler_info: AsyncAPIHandlerInfo,
        kind: str,
    ) -> None:
        """
        Register a handler under its action, rejecting duplicates.

        Compares method names so overriding stays legal: an overridden handler
        resolves to a single attribute and so registers under one name.
        """
        action = handler_info["message_action"]
        existing = handler_info_map.get(action)
        if existing and existing["method_name"] != handler_info["method_name"]:
            first, second = sorted(
                [existing["method_name"], handler_info["method_name"]]
            )
            raise TypeError(
                f"{cls.__name__} has two {kind} handlers for action {action!r}: "
                f"{first}() and {second}(). Actions must be unique within a consumer."
            )
        handler_info_map[action] = handler_info

    @classmethod
    def _collect_from_mro(cls, name: str) -> list[Any]:
        """
        Merge a list attribute across the entire MRO, deduplicated.

        Each class in the inheritance chain (mixins included) may declare its own
        list. Plain attribute access would only return the most derived definition
        and shadow the rest, so we walk the MRO and merge every class's own list.
        Order follows the MRO (most derived first); duplicates keep their first
        occurrence.
        """
        merged: list[Any] = []
        for klass in cls.__mro__:
            for item in klass.__dict__.get(name, []):
                if item not in merged:
                    merged.append(item)
        return merged

    @classmethod
    def _collect_messages(cls, name: str) -> list[type[BaseMessage]]:
        """Merge a list of message types across the MRO, rejecting non-messages."""
        messages = cls._collect_from_mro(name)
        for msg_type in messages:
            if not (inspect.isclass(msg_type) and issubclass(msg_type, BaseMessage)):
                raise TypeError(
                    f"{name} item {msg_type} must be a BaseMessage subclass."
                )
        return messages

    @classmethod
    def _default_groups(cls) -> list[str]:
        """Groups a consumer joins by default: declared ``groups`` plus extras."""
        # getattr: fast-channels only annotates ``groups``, leaving it unset.
        groups = list(getattr(cls, "groups", None) or [])
        groups.extend(g for g in cls._merged_extra_groups if g not in groups)
        return groups

    @classmethod
    def _process_passthrough_events(cls) -> None:
        """
        Process passthrough_events to create synthetic event handlers.

        For each message type in passthrough_events, creates a handler method
        decorated with @event_handler that simply returns the event (forwarding
        it to the WebSocket client).
        Explicit @event_handler definitions take priority over passthrough.
        """
        for msg_type in cls._collect_messages("passthrough_events"):
            message_action = msg_type.model_fields["action"].default
            # Explicit @event_handler takes priority
            if message_action in cls._EVENT_HANDLER_INFO_MAP:
                continue

            method_name = (
                f"{cls.passthrough_method_prefix}{humps.decamelize(msg_type.__name__)}"
            )

            async def method(self: Any, event: BaseMessage) -> BaseMessage:
                """Passthrough handler that forwards the event unchanged."""
                return event

            method.__name__ = method_name
            method.__qualname__ = f"{cls.__qualname__}.{method_name}"

            decorated = event_handler(
                method,
                input_type=msg_type,
                output_type=msg_type,
                description=f"Passthrough handler for {msg_type.__name__}",
            )
            setattr(cls, method_name, decorated)
            handler_info: AsyncAPIHandlerInfo = decorated._event_handler_info  # type: ignore[attr-defined]
            cls._EVENT_HANDLER_INFO_MAP[message_action] = handler_info

    @classmethod
    def _register_handler_messages(cls) -> None:
        """Register all handler message types under this consumer's name."""
        for handler_info in cls._MESSAGE_HANDLER_INFO_MAP.values():
            input_type = handler_info["input_type"]
            if input_type:
                message_registry.add(input_type, cls.__name__)
            output_type = handler_info["output_type"]
            if output_type:
                message_registry.add(output_type, cls.__name__)

        for handler_info in cls._EVENT_HANDLER_INFO_MAP.values():
            output_type = handler_info["output_type"]
            if output_type:
                message_registry.add(output_type, cls.__name__)

        for msg_type in cls._merged_emits:
            message_registry.add(msg_type, cls.__name__)

    @classmethod
    def _extract_types_from_handlers(
        cls, handler_info_map: dict[str, AsyncAPIHandlerInfo]
    ) -> tuple[list[type[BaseMessage]], list[type[BaseMessage]]]:
        """
        Extract input and output types from handler info map.

        Handles expansion of list/tuple/union types into individual types.

        Args:
            handler_info_map: Map of action -> AsyncAPIHandlerInfo

        Returns:
            Tuple of (input_types, output_types)
        """
        input_types: list[type[BaseMessage]] = []
        output_types: list[type[BaseMessage]] = []
        infos = sorted(handler_info_map.values(), key=lambda i: i["message_action"])
        for info in infos:
            if info["input_type"]:
                input_types.append(info["input_type"])
            if info["output_type"]:
                output_type = info["output_type"]

                # Handle list/tuple of types - expand them
                if isinstance(output_type, list | tuple):
                    for msg_type in output_type:
                        output_types.append(msg_type)
                # Handle UnionType - expand into individual types
                elif get_origin(output_type) in (UnionType, type(None)):
                    for arg in get_args(output_type):
                        if isinstance(arg, type) and issubclass(arg, BaseMessage):
                            output_types.append(arg)
                # Handle single type
                else:
                    output_types.append(cast(type[BaseMessage], output_type))
        return input_types, output_types

    @classmethod
    def _create_adapter(
        cls, union_type: BaseMessage, discriminator_field: str
    ) -> TypeAdapter[BaseMessage]:
        """
        Create TypeAdapter for a discriminated union type.

        Args:
            union_type: The discriminated union type
            discriminator_field: Field name for discrimination

        Returns:
            TypeAdapter for message validation
        """
        return TypeAdapter(
            Annotated[
                union_type,
                Field(discriminator=discriminator_field),
            ]
        )

    @classmethod
    def _build_adapters(cls) -> None:
        """
        Extract input/output types from handlers and build unions and adapters.
        """
        # Extract types from both handler maps
        message_input_types, message_output_types = cls._extract_types_from_handlers(
            cls._MESSAGE_HANDLER_INFO_MAP
        )
        event_input_types, event_output_types = cls._extract_types_from_handlers(
            cls._EVENT_HANDLER_INFO_MAP
        )

        incoming_message_union = cls._create_discriminated_union(
            message_input_types, cls.discriminator_field
        )
        cls.incoming_message_adapter = (
            cls._create_adapter(incoming_message_union, cls.discriminator_field)
            if incoming_message_union is not None
            else None
        )

        incoming_event_union = cls._create_discriminated_union(
            event_input_types, cls.discriminator_field
        )
        cls.incoming_event_adapter = (
            cls._create_adapter(incoming_event_union, cls.discriminator_field)
            if incoming_event_union is not None
            else None
        )

        all_output_types = set(
            message_output_types + event_output_types + cls._merged_emits
        )
        all_output_types |= {
            CompleteMessage,
            GroupCompleteMessage,
            EventCompleteMessage,
            ErrorMessage,
        }

        outgoing_union = cls._create_discriminated_union(
            sorted(
                all_output_types,
                key=lambda t: str(t.model_fields[cls.discriminator_field].default),
            ),
            cls.discriminator_field,
        )
        cls.outgoing_message_adapter = cls._create_adapter(
            outgoing_union, cls.discriminator_field
        )

    @classmethod
    def _create_discriminated_union(
        cls, message_types: list[type[BaseMessage]] | None, discriminator_field: str
    ) -> Any:
        """
        Create a discriminated union from a list of message types.

        Args:
            message_types: List of BaseMessage subclasses to union
            discriminator_field: The field name to use for discrimination

        Returns:
            A discriminated union type that can validate any of the input message types
        """
        if not message_types:
            return None

        if len(message_types) == 1:
            # If only one message type, return it directly
            return message_types[0]

        # Create annotated type with configurable discriminator field
        # Convert list to Union type for proper type annotation
        union_type = (
            reduce(lambda a, b: a | b, message_types) if message_types else None  # type: ignore
        )
        discriminated_union = Annotated[
            union_type, Field(discriminator=discriminator_field)  # type: ignore[valid-type]
        ]

        return discriminated_union

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        self.subscriptions: dict[str, Topic[Any]] = {}
        self._handler_tasks: set[asyncio.Task[Any]] = set()
        self._closed = False
        self._default_topic_value: str | None = None

        # Copy: a class-level ``groups`` list is shared by every instance.
        groups = list(self.groups)
        groups.extend(g for g in self._merged_extra_groups if g not in groups)
        self.groups = groups

        if self.authenticator_class:
            self.authenticator = self.authenticator_class(self.send_message)

    @property
    def should_send_completion(self) -> bool:
        """
        Determine whether completion messages should be sent after handling requests.

        Checks for instance-level send_completion attribute first, then falls back
        to global configuration setting.

        Returns:
            True if completion messages should be sent, False otherwise
        """
        if hasattr(self, "send_completion"):
            return self.send_completion
        return config.send_completion

    @property
    def should_camelize(self) -> bool:
        """
        Determine whether message field names should be camelized.

        Checks for instance-level camelize attribute first, then falls back
        to global configuration setting. When True, snake_case field names
        are converted to camelCase in outgoing messages.

        Returns:
            True if field names should be camelized, False otherwise
        """
        if hasattr(self, "camelize"):
            return self.camelize
        return config.camelize

    @property
    def uses_standard_errors(self) -> bool:
        """Whether error payloads follow the standard format (``error_format``)."""
        if hasattr(self, "error_format"):
            return self.error_format != "pydantic"
        return config.error_format != "pydantic"

    @property
    def all_log_ignored_actions(self) -> set[str]:
        """
        Get the complete set of actions that should be ignored during logging.

        Combines instance-specific log_ignored_actions with system-level
        COMPLETE_ACTIONS to create the full set of actions to exclude
        from logging.

        Returns:
            Set of action names that should not be logged
        """
        return set(self.log_ignored_actions) | COMPLETE_ACTIONS

    async def websocket_connect(self, message: Any) -> None:
        """
        Handle WebSocket connection request with authentication.

        Accepts the connection, authenticates the user, and either
        adds the user to appropriate groups or closes the connection.

        Args:
            message: The connection message from the framework
        """
        await self.accept()  # type: ignore

        # Authenticate the connection
        if self.authenticator:
            auth_result = await self.authenticator.authenticate(self.scope)

            if not auth_result:
                await self.close(self.authenticator.close_code)
                return

        try:
            for group in self.groups:
                channel_layer = self.__class__.get_channel_layer(
                    self.channel_layer_alias
                )
                if channel_layer:
                    await channel_layer.group_add(group, self.channel_name)
        except AttributeError:
            raise ValueError(
                "BACKEND is unconfigured or doesn't support groups"
            ) from None

        await self.post_authentication()

        # A route dedicated to one topic subscribes it from the URL parameters.
        if not self._closed and self.default_topic is not None:
            await self._subscribe(self._resolve_default_topic())

    async def websocket_disconnect(self, message: Any) -> None:
        """
        Handle WebSocket disconnection.

        Leaves every subscribed topic, cleans up context variables and logs it.

        Args:
            message: The disconnection message from the framework
        """
        # A join_group still awaiting its add sees this and undoes it.
        self._closed = True
        for task in list(self._handler_tasks):
            task.cancel()
        for topic, subscription in list(self.subscriptions.items()):
            await subscription.on_unsubscribe()
            await self._leave_topic_group(topic, subscription)
        self.subscriptions.clear()

        await logger.ainfo("Disconnecting websocket")
        structlog.contextvars.clear_contextvars()
        await super().websocket_disconnect(message)  # type: ignore

    async def join_group(self, group: str) -> None:
        """Join a group at run time; disconnect leaves it like the connect groups."""
        await self.channel_layer.group_add(group, self.channel_name)
        if self._closed:
            # Disconnect may have run during the add and would not discard it.
            await self.channel_layer.group_discard(group, self.channel_name)
            return
        if group not in self.groups:
            self.groups.append(group)

    async def leave_group(self, group: str) -> None:
        """Leave a group joined on connect or with ``join_group``."""
        await self.channel_layer.group_discard(group, self.channel_name)
        if group in self.groups:
            self.groups.remove(group)

    async def post_authentication(self) -> None:
        """
        Hook for additional actions after successful authentication.

        Subclasses can override this method to perform custom actions
        after a successful authentication.
        """
        pass

    async def _receive_own_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        """
        Receive and process JSON data addressed to this consumer.

        Creates task for async processing. When message logging is enabled, also assigns a
        message id and enhances the asyncio context with it and the message action.

        Args:
            content: The JSON content received from the client
            **kwargs: Additional keyword arguments
        """
        if self.should_camelize:
            content = humps.decamelize(content)

        message_action = content.get(self.discriminator_field)

        token = None
        if self.log_websocket_message:
            token = structlog.contextvars.bind_contextvars(
                message_id=str(uuid.uuid4())[:8], received_action=message_action
            )
            if message_action not in self.all_log_ignored_actions:
                await logger.ainfo("Websocket received")

        self._track_handler(create_task(self.handle_json(content, **kwargs)))

        if token is not None:
            structlog.contextvars.reset_contextvars(**token)

    def _track_handler(self, task: asyncio.Task[Any]) -> None:
        """Track a handler task so disconnect can cancel it."""
        if not self.cancel_handlers_on_disconnect:
            return
        self._handler_tasks.add(task)
        task.add_done_callback(self._handler_tasks.discard)

    async def handle_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        """
        Handle received JSON message with validation and routing.

        Validates incoming messages using auto-generated discriminated union,
        routes to appropriate handlers, and sends error responses on failure.

        Args:
            content: The JSON content to handle
            **kwargs: Additional keyword arguments
        """
        try:
            if self.incoming_message_adapter is None:
                await self.handle_json_processing_error(
                    RuntimeError("No message handlers registered on this consumer")
                )
                return
            current_input.set(content)
            message = self.incoming_message_adapter.validate_python(content)
            await self.receive_message(message)

        except ValidationError as e:
            await self.handle_validation_error(e)
        except Exception as e:
            await self.handle_json_processing_error(e)

        # Send completion signal if configured
        if self.should_send_completion:
            await self.send_message(CompleteMessage())

    async def receive_message(self, message: BaseMessage) -> None:
        """
        Process a validated received message and route it to the appropriate handler.

        Args:
            message: The validated message object (BaseMessage instance)
        """
        # Extract the action from the discriminator field
        message_action = getattr(message, self.discriminator_field)

        # Find the handler for this message_action
        handler_info = self.__class__._MESSAGE_HANDLER_INFO_MAP[message_action]

        # Get the handler method by name
        method_name = handler_info["method_name"]
        handler_method = getattr(self, method_name)

        try:
            # Call the handler method with the validated message
            result = await handler_method(message)

            # If handler returns something, we could send it back (optional)
            if result is not None:
                await self.handle_result(result)

        except Exception as e:
            await self.handle_message_handler_error(e, message_action, message)

    async def handle_result(self, result: BaseMessage) -> None:
        """
        Process and send the result returned by a message handler.

        Args:
            result: The result returned by the handler (BaseMessage)
        """
        # Convert result to JSON-serializable format
        await self.send_message(result)

    async def send_message(
        self, message: BaseMessage, *, validate: bool = False
    ) -> None:
        """
        Send a BaseMessage to the client.

        Args:
            message: The BaseMessage instance to send
            validate: Whether to validate the message against the outgoing adapter
        """
        # Optionally validate outgoing message
        if validate and self.__class__.outgoing_message_adapter:
            try:
                self.__class__.outgoing_message_adapter.validate_python(
                    message.model_dump(mode="json")
                )
            except ValidationError as e:
                await logger.aexception(f"Outgoing message validation failed: {e}")
                raise

        # Convert message to JSON and send
        await self.send_json(message.model_dump(mode="json"))

    async def send_json(self, content: dict[str, Any], close: bool = False) -> None:
        """
        Send JSON data to the client.

        Args:
            content: The JSON data to send
            close: Whether to close the connection after sending
        """
        if self.should_camelize:
            content = humps.camelize(content)

        ref = current_ref.get()
        if ref is not None:
            content = content | {"version": ENVELOPE_VERSION, "ref": ref}
        await super().send_json(content, close)  # type: ignore

        message_action = content.get(self.discriminator_field)
        if (
            self.log_websocket_message
            and message_action not in self.all_log_ignored_actions
        ):
            await logger.ainfo("Websocket sent", sent_action=message_action)
        if self.send_message_immediately:
            await asyncio.sleep(0)

    async def handle_message_handler_error(
        self, error: Exception, action: str, message: BaseMessage
    ) -> None:
        """
        Handle errors that occur in message handlers.

        Args:
            error: The exception that occurred
            action: The action that was being handled
            message: The message that caused the error
        """
        # Default implementation - subclasses can override
        detail = f"Failed to process message for {action}"
        payload: Any = {"detail": detail}
        if self.uses_standard_errors:
            payload = problem(ErrorType.HANDLER_FAILED, detail)
        await self.send_message(ErrorMessage(payload=payload))
        await logger.aexception(f"Handler error for action '{action}': {error}")

    # Group operations methods
    async def broadcast_message(
        self,
        message: BaseMessage | dict[str, Any],
        groups: list[str] | None = None,
        *,
        exclude_current: bool = False,
    ) -> None:
        """
        Send a BaseMessage object to one or more channel groups.

        Broadcasts a message to all consumers in the specified groups.
        This is useful for implementing pub/sub patterns where messages
        need to be distributed to multiple connected clients.

        Args:
            message: Message object to send to the groups.
            groups: Group names to send to (defaults to self.groups)

            exclude_current: Whether to exclude the sending consumer from receiving
                            the broadcast (prevents echo effects)
        """
        channel_layer = self.__class__.get_channel_layer(self.channel_layer_alias)
        assert channel_layer

        if groups is None:
            groups = self.groups or []

        if isinstance(message, BaseMessage):
            message = message.model_dump(mode="json")

        for group in groups:
            await channel_layer.group_send(
                group,
                {
                    "type": "handle_group_message",
                    "message": message,
                    "exclude_current": exclude_current,
                    "from_channel": self.channel_name,
                },
            )

    async def handle_group_message(self, event: GroupMessageEvent) -> None:
        """
        Handle incoming group message and relay to client.

        Processes group messages from the channel layer, adds metadata (is_current),
        and forwards to the client. Respects exclude_current flag to prevent echo effects.

        Args:
            event: Group message event containing message data and metadata
        """
        message = event["message"]
        exclude_current = event["exclude_current"]
        from_channel = event["from_channel"]

        if exclude_current and self.channel_name == from_channel:
            return

        await self.send_json(message)

        if self.should_send_completion:
            await self.send_message(GroupCompleteMessage())

    # Channel event system methods
    @classmethod
    async def send_event(
        cls,
        event: ReceiveEvent,
        channel_name: str,
    ) -> None:
        """
        Send a typed channel event to a specific channel.

        Args:
            event: The typed event to send (BaseMessage subclass)
            channel_name: Channel name to send the event to
        """
        channel_layer = cls.get_channel_layer(cls.channel_layer_alias)
        assert channel_layer is not None

        await channel_layer.send(
            channel_name,
            {
                "type": "handle_channel_event",
                "event_data": event.model_dump(mode="json"),
            },
        )

    @classmethod
    def send_event_sync(
        cls,
        event: ReceiveEvent,
        channel_name: str,
    ) -> None:
        """
        Synchronous version of send_event for use in sync contexts.

        Args:
            event: The typed event to send (BaseMessage subclass)
            channel_name: Channel name to send to
        """
        async_to_sync(cls.send_event)(event, channel_name)

    @classmethod
    async def broadcast_event(
        cls,
        event: ReceiveEvent,
        groups: Collection[str] | str | None = None,
    ) -> None:
        """
        Broadcast a typed channel event to channel groups.

        Args:
            event: The typed event to broadcast (BaseMessage subclass)
            groups: Groups to broadcast the event to
        """
        channel_layer = cls.get_channel_layer(cls.channel_layer_alias)
        assert channel_layer is not None
        group_list: list[str]
        if groups is None:
            group_list = cls._default_groups()
        elif isinstance(groups, str):
            group_list = [groups]
        else:
            group_list = list(groups)

        for group in group_list:
            await channel_layer.group_send(
                group,
                {
                    "type": "handle_channel_event",
                    "event_data": event.model_dump(mode="json"),
                },
            )

    @classmethod
    def broadcast_event_sync(
        cls,
        event: ReceiveEvent,
        groups: Collection[str] | str | None = None,
    ) -> None:
        """
        Synchronous version of broadcast_event for use in sync contexts.

        Args:
            event: The typed event to broadcast (BaseMessage subclass)
            groups: Groups to broadcast to
        """
        async_to_sync(cls.broadcast_event)(event, groups)

    async def handle_channel_event(self, event_payload: EventPayload) -> None:
        """
        Internal dispatcher for typed channel events with completion signal.

        This method is called by the channel layer when an event is sent to a group
        this consumer belongs to. It validates the event data and routes it to
        the appropriate @event_handler decorated method.

        Args:
            event_payload: The message from the channel layer containing event data
        """
        try:
            if self.incoming_event_adapter is None:
                await logger.aexception("No event handlers registered on this consumer")
                return
            event_data_dict: dict[str, Any] = event_payload.get("event_data", {})
            event = self.incoming_event_adapter.validate_python(event_data_dict)

            assert event is not None

            await self.receive_event(event)

        except ValidationError as e:
            # Log validation error for channel events
            await logger.aexception(f"Channel event validation failed: {e}")
        except Exception:
            await logger.aexception("Failed to process channel event")

    async def receive_event(self, event: BaseMessage) -> None:
        """
        Process channel events received through the channel layer.

        Routes events to @event_handler decorated methods based on action field.

        Args:
            event: The validated event object
        """

        # Extract the action from the event
        action = getattr(event, "action", None)

        if not action:
            await logger.aerror("Event missing action field")
            return

        # Find the handler for this action
        event_handler_info = self.__class__._EVENT_HANDLER_INFO_MAP[action]

        # Get the handler method by name
        method_name = event_handler_info["method_name"]
        handler_method = getattr(self, method_name)

        try:
            # Call the handler method with the validated event
            result = await handler_method(event)

            # Events are received through channel system, so send event completion
            if result is not None:
                await self.send_message(result)

        except Exception as e:
            await self.handle_event_handler_error(e, action, event)

        if self.should_send_completion:
            await self.send_message(EventCompleteMessage())

    @property
    def url_params(self) -> Mapping[str, Any]:
        """Path parameters, however the framework exposes them."""
        return path_params(self.scope)

    def _resolve_default_topic(self) -> str:
        """Fill the default topic's pattern from the URL, once per connection."""
        if self._default_topic_value is None:
            default_topic = cast("type[Topic[Any]]", self.default_topic)
            params = self.url_params
            missing = [name for name in default_topic.param_names if name not in params]
            if missing:
                raise ValueError(
                    f"default_topic pattern '{default_topic.pattern}' needs URL "
                    f"parameters {missing} that this route does not provide "
                    f"(got {sorted(params)})"
                )
            self._default_topic_value = default_topic.pattern.format(**params)
        return self._default_topic_value

    async def close(self, code: int | None = None, reason: str | None = None) -> None:
        """Close the connection, recording that it is gone."""
        self._closed = True
        await super().close(code, reason)  # type: ignore[misc]

    async def receive(
        self,
        text_data: str | None = None,
        bytes_data: bytes | None = None,
        **kwargs: Any,
    ) -> None:
        """Decode a frame, answering one that is not JSON text with an error frame."""
        if text_data is None:
            await self._reject_frame(text_data, "binary frames are not supported")
            return
        decode_json = cast(
            Callable[[str], Awaitable[Any]],
            self.decode_json,  # type: ignore[attr-defined]
        )
        try:
            content = await decode_json(text_data)
        except Exception as e:
            await self._reject_frame(text_data, str(e))
            return
        await self.receive_json(content, **kwargs)

    async def _reject_frame(self, text_data: str | None, reason: str) -> None:
        """Report a frame that is not JSON, keeping the connection open."""
        await logger.awarning("Malformed frame", reason=reason)
        await self.handle_validation_error(
            ValidationError.from_exception_data(
                "Envelope",
                [
                    {
                        "type": "json_invalid",
                        "loc": (),
                        "input": text_data,
                        "ctx": {"error": reason},
                    }
                ],
            )
        )

    async def receive_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        """Route a frame to its topic, or to this consumer's own handlers."""
        try:
            envelope = Envelope.model_validate(content)
        except ValidationError as e:
            token = current_input.set(content)
            try:
                await self.handle_validation_error(e)
            finally:
                current_input.reset(token)
            return

        message_data = strip_envelope(content)
        topic = envelope.topic

        if topic is None and self.default_topic is not None:
            # A standalone route serves one topic, so clients need no envelope.
            topic = self._resolve_default_topic()
            envelope = envelope.model_copy(update={"topic": topic})

        if topic is None:
            # The handler task copies this context, so its replies carry the ref.
            token = current_ref.set(envelope.ref)
            try:
                await self._receive_own_json(message_data, **kwargs)
            finally:
                current_ref.reset(token)
            return

        if self.should_camelize:
            message_data = humps.decamelize(message_data)
        self._track_handler(create_task(self._route_to_topic(envelope, message_data)))

    async def _route_to_topic(
        self, envelope: Envelope, message_data: dict[str, Any]
    ) -> None:
        """Dispatch one topic-addressed frame, with its ref bound for replies."""
        topic = cast(str, envelope.topic)
        token = current_ref.set(envelope.ref)
        try:
            action = message_data.get("action")
            if action == SubscribeMessage.model_fields["action"].default:
                await self._subscribe(topic)
            elif action == UnsubscribeMessage.model_fields["action"].default:
                await self._unsubscribe(topic)
            else:
                await self._dispatch(topic, message_data)
        finally:
            current_ref.reset(token)

    async def _dispatch(self, topic: str, message_data: dict[str, Any]) -> None:
        """Hand a frame to a subscribed topic."""
        subscription = self.subscriptions.get(topic)
        if subscription is None:
            await self.send_topic_error(
                topic,
                TopicErrorReason.NOT_SUBSCRIBED,
                f"Not subscribed to '{topic}'",
            )
            return
        await subscription.handle_json(message_data)

    async def _subscribe(self, topic: str) -> None:
        """Authorize a topic, join its group, and confirm."""
        if topic in self.subscriptions:
            await self.send_topic_message(topic, SubscribedMessage())
            return

        topic_class = self._match(topic)
        if topic_class is None:
            await self.send_topic_error(
                topic, TopicErrorReason.UNKNOWN_TOPIC, f"Unknown topic '{topic}'"
            )
            return

        subscription = topic_class(self, topic)
        if not await subscription.authorize(**subscription.params):
            await self.send_topic_error(
                topic,
                TopicErrorReason.UNAUTHORIZED,
                f"Not allowed to subscribe to '{topic}'",
            )
            return

        await self.join_group(topic_class.group_name(topic))
        if self._closed:
            return
        self.subscriptions[topic] = subscription
        await self.send_topic_message(topic, SubscribedMessage())

        # Anything the topic pushes now is state, not a reply to the request.
        token = current_ref.set(None)
        try:
            await subscription.on_subscribe()
        finally:
            current_ref.reset(token)

    async def _unsubscribe(self, topic: str) -> None:
        """Leave a topic's group and confirm."""
        subscription = self.subscriptions.pop(topic, None)
        if subscription is not None:
            await subscription.on_unsubscribe()
            await self._leave_topic_group(topic, subscription)
        await self.send_topic_message(topic, UnsubscribedMessage())

    async def _leave_topic_group(self, topic: str, subscription: "Topic[Any]") -> None:
        """Drop a subscription's group, both in the layer and on this consumer."""
        await self.leave_group(type(subscription).group_name(topic))

    @classmethod
    def _match(cls, topic: str) -> type["Topic[Any]"] | None:
        """Find the mounted topic class whose pattern matches."""
        for topic_class in cls.topics:
            if topic_class.parse(topic) is not None:
                return topic_class
        return None

    async def handle_topic_event(self, event: dict[str, Any]) -> None:
        """Route a channel layer event to the topic it was published to."""
        topic = event.get("topic")
        subscription = self.subscriptions.get(cast(str, topic))
        if subscription is None:
            return

        ref_token = current_ref.set(None)
        seq_token = current_seq.set(event.get("seq"))
        try:
            await subscription.handle_channel_event(event)  # type: ignore[arg-type]
        finally:
            current_ref.reset(ref_token)
            current_seq.reset(seq_token)

    async def send_topic_json(self, topic: str, content: dict[str, Any]) -> None:
        """Write a frame stamped with its topic, plus the ref or seq in flight."""
        envelope: dict[str, Any] = {
            "version": ENVELOPE_VERSION,
            "topic": topic,
        }
        ref = current_ref.get()
        if ref is not None:
            envelope["ref"] = ref
        seq = current_seq.get()
        if seq is not None:
            envelope["seq"] = seq
        if self.should_camelize:
            content = humps.camelize(content)
        await super().send_json(content | envelope)  # type: ignore[misc]

    async def send_topic_message(self, topic: str, message: BaseMessage) -> None:
        """Send a chanx message on a topic."""
        await self.send_topic_json(topic, message.model_dump(mode="json"))

    async def send_topic_error(
        self, topic: str, reason: TopicErrorReason, detail: str
    ) -> None:
        """Report a topic-level failure, with a reason the client can branch on."""
        await logger.awarning("Topic error", topic=topic, reason=reason, detail=detail)
        payload: Any = {"reason": reason, "detail": detail}
        if self.uses_standard_errors:
            payload = problem(_TOPIC_ERROR_TYPES[reason], detail)
        await self.send_topic_message(topic, ErrorMessage(payload=payload))

    async def handle_validation_error(self, error: ValidationError) -> None:
        """
        Handle ValidationError exceptions during message processing.

        Subclasses can override this method to customize validation error responses.

        Args:
            error: The ValidationError that occurred
        """
        if self.uses_standard_errors:
            payload: Any = validation_problem(
                error,
                discriminator=self.discriminator_field,
                camelize=self.should_camelize,
            )
        else:
            payload = error.errors(
                include_url=False, include_context=False, include_input=False
            )
        await self.send_message(ErrorMessage(payload=payload))

    async def handle_json_processing_error(self, error: Exception) -> None:
        """
        Handle general exceptions during JSON message processing.

        Subclasses can override this method to customize error responses.

        Args:
            error: The exception that occurred
        """
        detail = "Failed to process message"
        payload: Any = {"detail": detail}
        if self.uses_standard_errors:
            payload = problem(ErrorType.INTERNAL_ERROR, detail)
        await self.send_message(ErrorMessage(payload=payload))
        # Log the actual error for debugging
        await logger.aexception(f"Failed to process message: {str(error)}")

    async def handle_event_handler_error(
        self, error: Exception, action: str, event: BaseMessage
    ) -> None:
        """
        Handle errors that occur in event handlers.

        Args:
            error: The exception that occurred
            action: The action that was being processed
            event: The event that caused the error
        """
        await logger.aexception(f"Event handler error for action '{action}': {error}")
