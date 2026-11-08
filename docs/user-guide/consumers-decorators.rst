Consumers & Decorators
======================

In chanx, WebSocket code is built from decorator-based message handlers that automatically route messages, validate types, and generate documentation. This guide covers the core patterns you'll use to build WebSocket applications.

The AsyncJsonWebsocketConsumer Base Class
-----------------------------------------

All chanx consumers inherit from ``AsyncJsonWebsocketConsumer``, which provides the foundation for decorator-based message handling.

**Framework-Specific Imports:**

.. code-block:: python

    # For Django Channels
    from chanx.channels.websocket import AsyncJsonWebsocketConsumer

    # For FastAPI / other ASGI frameworks
    from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer

    # Decorators are framework-agnostic
    from chanx.core.decorators import ws_handler, event_handler, channel

    @channel(name="chat", description="Real-time chat system")
    class ChatConsumer(AsyncJsonWebsocketConsumer):
        # Your handlers go here
        pass

**Optional Generic Type Parameter:**

You can optionally specify an event type for better static type checking with mypy/pyright:

.. code-block:: python

    # Without generic type (perfectly fine)
    class ChatConsumer(AsyncJsonWebsocketConsumer):
        pass

    # With generic type for enhanced type checking
    class ChatConsumer(AsyncJsonWebsocketConsumer[SystemNotifyEvent]):
        pass

The generic type parameter helps with:

- **Type safety** for ``send_event()``, ``broadcast_event()`` methods
- **Better IDE support** with autocomplete and type hints
- **Static analysis** with mypy/pyright

**Note:** The generic type is purely optional and for developer convenience. It doesn't affect runtime behavior or functionality.

**Key features provided by the base class:**

- **Automatic message routing** based on decorators
- **Type validation** using Pydantic discriminated unions
- **Channel layer integration** for group messaging
- **Authentication handling** with configurable authenticators
- **Completion signals** for reliable testing
- **Configurable behavior** via class attributes

The @channel Decorator
----------------------

The ``@channel`` decorator marks consumer classes and provides metadata for AsyncAPI documentation generation:

.. code-block:: python

    @channel(
        name="notifications",
        description="User notification system",
        tags=["notifications", "real-time"]
    )
    class NotificationConsumer(AsyncJsonWebsocketConsumer):
        pass

**Parameters:**

- **name** (str, optional): Custom channel name (defaults to class name)
- **description** (str, optional): Channel description (overrides class docstring)
- **tags** (list[str], optional): Tags for AsyncAPI grouping

The @ws_handler Decorator
-------------------------

The ``@ws_handler`` decorator handles messages sent directly from WebSocket clients. Each handler method corresponds to a specific message type:

.. code-block:: python

    from chanx.messages.incoming import PingMessage
    from chanx.messages.outgoing import PongMessage

    @channel(name="example")
    class ExampleConsumer(AsyncJsonWebsocketConsumer):
        @ws_handler(summary="Handle ping requests")
        async def handle_ping(self, message: PingMessage) -> PongMessage:
            return PongMessage()

        @ws_handler(
            summary="Handle chat messages",
            description="Process chat messages and broadcast to room members",
            output_type=ChatNotificationMessage,
            tags=["chat", "messaging"]
        )
        async def handle_chat(self, message: ChatMessage) -> None:
            # Broadcast to group instead of direct response
            await self.broadcast_message(
                ChatNotificationMessage(
                    payload=ChatPayload(
                        message=f"User: {message.payload.message}"
                    )
                )
            )

**How Message Handlers Send Messages**

Understanding how messages are sent back to clients is important.

**Pattern 1: Return value sends to sender only**

.. code-block:: python

    @ws_handler
    async def handle_user_message(self, message: UserMessage) -> SystemEchoMessage:
        # What you return goes back to the sender only
        return SystemEchoMessage(payload=...)

The returned message is automatically sent to the client who sent the original message.

**Pattern 2: Broadcasting to multiple users**

.. code-block:: python

    @ws_handler(output_type=RoomNotificationMessage)
    async def handle_chat(self, message: ChatMessage) -> None:
        # Explicitly broadcast to send to multiple users
        await self.broadcast_message(
            RoomNotificationMessage(payload=...),
            groups=["room_general"]  # Can be omitted if groups defined as class attribute
        )

When broadcasting:

- Return type is ``None`` (not sending directly to sender)
- Use ``output_type`` parameter in ``@ws_handler`` for API documentation
- Call ``broadcast_message()`` explicitly
- ``groups`` parameter can be omitted if already defined as class attribute

**Pattern 3: No Response**

.. code-block:: python

    @ws_handler
    async def handle_log_event(self, message: LogMessage) -> None:
        logger.info(f"Received: {message.payload}")
        # No response sent

**@ws_handler parameters:**

- **func**: The handler function (when used without parentheses)
- **action** (str, optional): Action name (defaults to function name)
- **input_type** (type, optional): Expected input message type
- **output_type** (type, optional): Expected output message type for docs
- **summary** (str, optional): Brief description for AsyncAPI
- **description** (str, optional): Detailed description for AsyncAPI
- **tags** (list[str], optional): Tags for AsyncAPI grouping

The @event_handler Decorator
----------------------------

The ``@event_handler`` decorator handles events sent through the channel layer from other parts of your application (HTTP views, background tasks, management scripts, etc.). It enables server-to-server communication patterns.

**@ws_handler vs @event_handler:**

.. code-block:: python

    # Receives messages from WebSocket clients
    @ws_handler
    async def handle_user_message(self, message: UserMessage) -> Response:
        ...

    # Receives messages from channel layer (server-to-server)
    @event_handler
    async def handle_job_result(self, event: JobResult) -> Response:
        ...

**Key differences:**

+------------------+------------------------------------+--------------------------------------------+
|                  | @ws_handler                        | @event_handler                             |
+==================+====================================+============================================+
| **Source**       | WebSocket clients                  | Channel layer (server-side)                |
+------------------+------------------------------------+--------------------------------------------+
| **Triggered by** | Client sends JSON message          | ``send_event()`` or ``broadcast_event()``  |
+------------------+------------------------------------+--------------------------------------------+
| **Use case**     | Handle user interactions           | Handle background job results, external    |
|                  |                                    | triggers, cross-consumer messages          |
+------------------+------------------------------------+--------------------------------------------+

**How event handlers work:**

**Pattern 1: Return value sends to WebSocket client**

.. code-block:: python

    @event_handler
    async def handle_job_result(self, event: JobResult) -> JobStatusMessage:
        # What you return is sent to the WebSocket client
        return JobStatusMessage(payload={"status": "result", "message": event.payload})

Where the message goes depends on how the event was sent:

- ``send_event(message, channel_name)`` → goes to **one specific client**
- ``broadcast_event(message, groups=[...])`` → goes to **all clients in those groups**

**Pattern 2: Send multiple messages or complex logic**

.. code-block:: python

    @event_handler(output_type=Notification)
    async def handle_complex_event(self, event: ComplexEvent) -> None:
        # Send multiple messages
        await self.send_message(Notification(payload="Processing..."))
        await self.send_message(Notification(payload="Complete!"))

When using complex logic:

- Return type is ``None``
- Use ``output_type`` parameter for API documentation
- Call ``send_message()`` or ``broadcast_message()`` explicitly

**Why use event handlers?**

Event handlers enable server-to-server communication:

- **Background workers** can send results back to WebSocket clients
- **External scripts** can trigger WebSocket notifications
- **HTTP endpoints** can push messages to WebSocket connections
- **Different consumers** can send messages to each other

This is more powerful than ``@ws_handler`` which only handles client messages.

**@event_handler parameters:**

- **func**: The handler function (when used without parentheses)
- **input_type** (type, optional): Expected event type for validation
- **output_type** (type, optional): Expected output type for docs
- **summary** (str, optional): Brief description for AsyncAPI
- **description** (str, optional): Detailed description for AsyncAPI
- **tags** (list[str], optional): Tags for AsyncAPI grouping

Passthrough Events
------------------

When you have events that should be forwarded directly to WebSocket clients without any processing, you can use ``passthrough_events`` instead of writing repetitive no-op handlers:

**Before (repetitive):**

.. code-block:: python

    class ChatConsumer(AsyncJsonWebsocketConsumer):
        @event_handler
        async def handle_user_joined(self, event: UserJoinedNotification) -> UserJoinedNotification:
            return event

        @event_handler
        async def handle_user_left(self, event: UserLeftNotification) -> UserLeftNotification:
            return event

        @event_handler
        async def handle_message_updated(self, event: MessageUpdated) -> MessageUpdated:
            return event

**After (using passthrough_events):**

.. code-block:: python

    class ChatConsumer(AsyncJsonWebsocketConsumer):
        passthrough_events = [UserJoinedNotification, UserLeftNotification, MessageUpdated]

Each message type listed in ``passthrough_events`` automatically:

- Creates a handler method named ``handle_passthrough_{snake_case_class_name}``
- Registers the event type for incoming validation
- Registers the same type as output (forwarded to client)
- Generates an AsyncAPI ``send`` operation in the documentation

**Mixing with explicit handlers:**

You can combine ``passthrough_events`` with explicit ``@event_handler`` methods. Explicit handlers always take priority:

.. code-block:: python

    class ChatConsumer(AsyncJsonWebsocketConsumer):
        passthrough_events = [UserJoinedNotification, UserLeftNotification]

        # This explicit handler takes priority over passthrough for UserJoinedNotification
        @event_handler
        async def handle_user_joined(self, event: UserJoinedNotification) -> UserJoinedNotification:
            log_user_joined(event)
            return event

**Customizing the method prefix:**

By default, generated methods are named ``handle_passthrough_{snake_case_class_name}``. You can change this with ``passthrough_method_prefix``:

.. code-block:: python

    class ChatConsumer(AsyncJsonWebsocketConsumer):
        passthrough_events = [UserJoinedNotification, UserLeftNotification]
        passthrough_method_prefix = "forward_"

        # Generated methods will be:
        #   forward_user_joined_notification
        #   forward_user_left_notification

**Sharing passthrough events via mixins:**

``passthrough_events`` declared anywhere in the inheritance chain are merged together, just like ``@event_handler`` and ``@ws_handler`` methods. A mixin can contribute its own passthrough events, and the consumer's own list is added on top — the concrete class does **not** shadow the mixin's events:

.. code-block:: python

    class PresenceMixin:
        passthrough_events = [UserJoinedNotification, UserLeftNotification]

    class ChatConsumer(PresenceMixin, AsyncJsonWebsocketConsumer):
        passthrough_events = [MessageUpdated]

    # ChatConsumer forwards all three:
    #   UserJoinedNotification, UserLeftNotification (from the mixin)
    #   MessageUpdated (from the consumer)

Duplicate types across the chain are de-duplicated. Because the lists are merged additively, a subclass cannot *remove* a passthrough event contributed by a base class or mixin — this mirrors how inherited handler methods cannot be un-inherited.

**Note:** ``passthrough_events`` only applies to event handlers (channel layer events), not WebSocket message handlers (``@ws_handler``). WebSocket messages from clients typically require processing logic, so passthrough is not supported for them.

Messages Sent Outside Handlers
------------------------------

A handler's ``output_type`` documents what it sends. A message the consumer sends on its
own, such as a welcome from ``post_authentication``, belongs in ``emits``:

.. code-block:: python

    class ChatConsumer(AsyncJsonWebsocketConsumer):
        emits = [WelcomeMessage]

        async def post_authentication(self) -> None:
            await self.send_message(WelcomeMessage(payload="Connected"))

Each message type listed in ``emits``:

- Appears in the channel's messages, so generated clients get a type for it
- Is accepted by outgoing validation (``send_message(validate=True)`` and the test
  communicator)
- Is documented by one AsyncAPI ``send`` operation, ``<channel>_emits``

Like ``passthrough_events``, lists from mixins and base classes are merged. Events that
arrive through the channel layer, from a worker or a view, need no entry here: their
``@event_handler`` or ``passthrough_events`` entry already documents them.

AsyncAPI Documentation Mapping
-------------------------------

Understanding how chanx decorators map to AsyncAPI operations helps you write better documentation and understand the generated API specs.

**@ws_handler AsyncAPI Mapping:**

The ``@ws_handler`` decorator always generates documentation for the **input message** (from client) and optionally for the **output message** (to client):

.. code-block:: python

    # Generates: RECEIVE action with reply field
    @ws_handler
    async def handle_ping(self, message: PingMessage) -> PongMessage:
        return PongMessage()
    # AsyncAPI: "ping" action - receive (input_type=PingMessage) with reply field (output_type=PongMessage)

    # Generates: RECEIVE action with reply field
    @ws_handler(output_type=ChatNotificationMessage)
    async def handle_chat(self, message: ChatMessage) -> None:
        await self.broadcast_message(ChatNotificationMessage(...))
    # AsyncAPI: "chat" action - receive (input_type=ChatMessage) with reply field (output_type=ChatNotificationMessage)

    # Generates: RECEIVE action (no reply field)
    @ws_handler
    async def handle_log(self, message: LogMessage) -> None:
        logger.info(message.payload)
        # No response sent
    # AsyncAPI: "log" action - receive (input_type=LogMessage) with no reply

**AsyncAPI operation kinds for @ws_handler:**

- **RECEIVE with reply**: When handler has return type or ``output_type`` parameter (receive action has reply field describing response)
- **RECEIVE without reply**: When handler returns ``None`` and has no ``output_type``

**@event_handler AsyncAPI Mapping:**

The ``@event_handler`` decorator only generates documentation for the **output message** (sent to WebSocket client). The input event type is NOT documented because events come from internal sources (background workers, HTTP views, etc.), not from WebSocket clients:

.. code-block:: python

    # Generates: SEND operation (send only)
    @event_handler
    async def handle_job_result(self, event: JobResult) -> JobResult:
        return event
    # AsyncAPI: "job_result" action - send (output_type=JobResult)
    # Note: input_type (event parameter) is NOT in AsyncAPI docs

    # Generates: SEND operation (send only)
    @event_handler(output_type=SystemNotification)
    async def handle_system_notify(self, event: SystemNotifyEvent) -> None:
        await self.send_message(SystemNotification(...))
    # AsyncAPI: "system_notification" action - send (output_type=SystemNotification)
    # Note: SystemNotifyEvent is NOT in AsyncAPI docs (internal event)

**AsyncAPI operation kind for @event_handler:**

- **SEND** (send with no reply): Server-initiated message to WebSocket client

**Summary:**

+-------------------+-------------------------+---------------------------+--------------------------------+
|                   | Input Type              | Output Type               | AsyncAPI Operation             |
+===================+=========================+===========================+================================+
| ``@ws_handler``   | Always documented       | Documented if present     | RECEIVE (with or without       |
|                   | (from WebSocket client) | (reply field)             | reply field)                   |
+-------------------+-------------------------+---------------------------+--------------------------------+
| ``@event_handler``| NOT documented          | Always documented         | SEND                           |
|                   | (internal event)        | (to WebSocket client)     |                                |
+-------------------+-------------------------+---------------------------+--------------------------------+

This mapping ensures your AsyncAPI documentation accurately reflects the WebSocket protocol from the **client's perspective**, showing what messages clients can send and receive.

Message Types and Automatic Routing
-----------------------------------

**Discriminated unions** route both WebSocket messages and events to the correct handlers automatically. Messages and events are identified by their ``action`` field:

**WebSocket Message Example:**

.. code-block:: python

    from chanx.messages.base import BaseMessage
    from typing import Literal

    class ChatMessage(BaseMessage):
        action: Literal["chat"] = "chat"  # Discriminator field
        payload: ChatPayload

    class PingMessage(BaseMessage):
        action: Literal["ping"] = "ping"
        payload: None = None

**Event Message Example:**

.. code-block:: python

    class UserJoinedEvent(BaseMessage):
        action: Literal["user_joined"] = "user_joined"  # Discriminator field
        payload: UserPayload

    class SystemNotifyEvent(BaseMessage):
        action: Literal["system_notify"] = "system_notify"
        payload: NotificationPayload

**How routing works:**

**For WebSocket messages:**

1. Client sends: ``{"action": "chat", "payload": {"message": "Hello"}}``
2. Framework validates against discriminated union of all input messages
3. Routes to ``@ws_handler`` method based on message type
4. Handler receives properly typed message object

**For events:**

1. Application sends: ``Consumer.send_event(UserJoinedEvent(...))``
2. Framework validates against discriminated union of all event types
3. Routes to ``@event_handler`` method based on event type
4. Handler receives properly typed event object

**The framework automatically:**

- Builds separate discriminated unions for WebSocket messages and events
- Validates incoming JSON/events against the appropriate union
- Routes to the correct handler method (``@ws_handler`` or ``@event_handler``)
- Provides full type safety with IDE support for both message types

Output Messages and Broadcasting
---------------------------------

**Direct Response Messages:**

.. code-block:: python

    @ws_handler
    async def handle_get_status(self, message: GetStatusMessage) -> StatusMessage:
        return StatusMessage(
            payload=StatusPayload(
                status="online",
                timestamp=datetime.now()
            )
        )

**Broadcasting Messages:**

.. code-block:: python

    @ws_handler(output_type=ChatNotificationMessage)
    async def handle_chat(self, message: ChatMessage) -> None:
        # Broadcast to all connections in the same groups
        await self.broadcast_message(
            ChatNotificationMessage(payload=message.payload)
        )

        # Broadcast to specific groups
        await self.broadcast_message(
            ChatNotificationMessage(payload=message.payload),
            groups=["room_123", "moderators"]
        )

**Group Management:**

A consumer joins its ``groups`` on connect. To join or leave a group later, such as when
the user enters a room, use ``join_group()`` and ``leave_group()``. They update the
channel layer and ``self.groups`` together, so ``broadcast_message()`` without ``groups``
reaches the new group and disconnect leaves it.

.. code-block:: python

    class RoomChatConsumer(AsyncJsonWebsocketConsumer):
        async def post_authentication(self) -> None:
            """Called after successful authentication."""
            # Extract room from URL parameters
            room_id = self.scope["path_params"]["room_id"]
            group_name = f"room_{room_id}"

            # Join the room group; leave it with ``await self.leave_group(group_name)``
            await self.join_group(group_name)

            # Notify others about the join
            await self.broadcast_message(
                UserJoinedMessage(payload={"user_id": self.user.id}),
                groups=[group_name],
                exclude_current=True  # Don't send to self
            )

Event Broadcasting from Anywhere
---------------------------------

One of chanx's most powerful features is sending events to WebSocket consumers from anywhere in your application:

**From Django Views:**

.. code-block:: python

    # views.py
    from django.http import JsonResponse
    from myapp.consumers import NotificationConsumer
    from myapp.events import NewPostEvent

    def create_post(request):
        post = Post.objects.create(...)

        # Send event to WebSocket consumers
        NotificationConsumer.broadcast_event_sync(
            NewPostEvent(payload={"post_id": post.id, "title": post.title}),
            groups=["news_feed"]
        )

        return JsonResponse({"status": "created"})

**From Celery Tasks:**

.. code-block:: python

    # tasks.py
    from celery import shared_task
    from myapp.consumers import PaymentConsumer
    from myapp.events import PaymentCompleteEvent

    @shared_task
    def process_payment(payment_id):
        result = process_payment_logic(payment_id)

        # Notify specific user
        PaymentConsumer.send_event_sync(
            PaymentCompleteEvent(payload={"status": result}),
            channel_name=f"user_{payment.user_id}"
        )

**From Management Commands:**

.. code-block:: python

    # management/commands/send_announcement.py
    from django.core.management.base import BaseCommand
    from myapp.consumers import AnnouncementConsumer

    class Command(BaseCommand):
        def add_arguments(self, parser):
            parser.add_argument('message', type=str)

        def handle(self, *args, **options):
            AnnouncementConsumer.broadcast_event_sync(
                SystemAnnouncementEvent(payload=options['message']),
                groups=["all_users"]
            )

**Available event methods:**

- **send_event_sync()**: Send to specific channel name
- **broadcast_event_sync()**: Send to groups
- **send_event()**: Async version of send_event_sync
- **broadcast_event()**: Async version of broadcast_event_sync

**Note:** When using the optional generic type parameter (``AsyncJsonWebsocketConsumer[EventType]``), these methods will provide better type checking and IDE support for the event parameter.

Consumer Configuration
----------------------

Consumers can be configured via class attributes:

.. code-block:: python

    class MyConsumer(AsyncJsonWebsocketConsumer):
        # Message behavior
        send_completion = False  # Whether to send completion signals
        send_message_immediately = True  # Yield control after sending
        log_websocket_message = True  # Log messages
        log_ignored_actions = ["ping", "pong"]  # Skip logging these

        # Message formatting
        camelize = False  # Convert snake_case <-> camelCase
        discriminator_field = "action"  # Field for message routing

        # Channel layer (required for non-Django frameworks)
        channel_layer_alias = "default"

        # Authentication
        authenticator_class = MyAuthenticator

Handlers After Disconnect
~~~~~~~~~~~~~~~~~~~~~~~~~

Each incoming message runs its handler in a background task, and by default that task
finishes even if the client disconnects first: its sends to the closed socket are dropped,
while its other work (database writes, group broadcasts) still happens. For handlers doing
long work only the caller wants, such as streaming an LLM reply, cancel them instead:

.. code-block:: python

    class AssistantConsumer(AsyncJsonWebsocketConsumer):
        cancel_handlers_on_disconnect = True

On disconnect, every in-flight handler of that connection gets ``asyncio.CancelledError``
at its next ``await``. Use ``try/finally`` for any cleanup that must still run.

Authentication Integration
--------------------------

**Django Example:**

.. code-block:: python

    from chanx.channels.authenticator import DjangoAuthenticator
    from rest_framework.permissions import IsAuthenticated

    class ChatAuthenticator(DjangoAuthenticator):
        permission_classes = [IsAuthenticated]
        # Optional: object-level permissions
        queryset = ChatRoom.objects.all()
        obj: ChatRoom

    @channel(name="chat")
    class ChatConsumer(AsyncJsonWebsocketConsumer):
        authenticator_class = ChatAuthenticator
        authenticator: ChatAuthenticator  # Type hint

        async def post_authentication(self) -> None:
            """Called after successful authentication."""
            # Access authenticated user and object
            user = self.authenticator.user
            room = self.authenticator.obj  # If using object-level auth

            # Join room-specific group
            await self.join_group(f"room_{room.id}")

**FastAPI/Custom Example:**

.. code-block:: python

    from chanx.core.authenticator import BaseAuthenticator

    class TokenAuthenticator(BaseAuthenticator):
        async def authenticate(self) -> bool:
            token = self.get_query_param("token")
            if not token:
                return False

            # Validate token logic here
            self.user = await get_user_by_token(token)
            return self.user is not None

    class MyConsumer(AsyncJsonWebsocketConsumer):
        authenticator_class = TokenAuthenticator

Complete Example: Chat Consumer
-------------------------------

Here's a complete example that demonstrates all the concepts:

.. code-block:: python

    from chanx.core.decorators import ws_handler, event_handler, channel
    from chanx.channels.websocket import AsyncJsonWebsocketConsumer
    from chanx.channels.authenticator import DjangoAuthenticator
    from rest_framework.permissions import IsAuthenticated

    # Messages
    class ChatMessage(BaseMessage):
        action: Literal["chat"] = "chat"
        payload: ChatPayload

    class JoinRoomMessage(BaseMessage):
        action: Literal["join_room"] = "join_room"
        payload: JoinRoomPayload

    # Events
    class UserJoinedEvent(BaseChannelEvent):
        handler: Literal["user_joined"] = "user_joined"
        payload: UserPayload

    # Authenticator
    class RoomAuthenticator(DjangoAuthenticator):
        permission_classes = [IsAuthenticated]
        queryset = ChatRoom.objects.all()
        obj: ChatRoom

    # Consumer (generic type is optional - either approach works)
    @channel(
        name="room_chat",
        description="Real-time chat for specific rooms",
        tags=["chat", "rooms"]
    )
    class RoomChatConsumer(AsyncJsonWebsocketConsumer[UserJoinedEvent]):  # Optional generic for type hints
        authenticator_class = RoomAuthenticator
        authenticator: RoomAuthenticator

        # Configuration
        log_ignored_actions = ["ping", "pong"]

        async def post_authentication(self) -> None:
            """Join room group after authentication."""
            room_group = f"room_{self.authenticator.obj.id}"
            await self.join_group(room_group)

        @ws_handler(
            summary="Handle chat messages",
            output_type=ChatNotificationMessage
        )
        async def handle_chat(self, message: ChatMessage) -> None:
            """Process and broadcast chat messages."""
            await self.broadcast_message(
                ChatNotificationMessage(
                    payload=ChatNotificationPayload(
                        message=message.payload.message,
                        username=self.authenticator.user.username,
                        room_id=self.authenticator.obj.id
                    )
                )
            )

        @event_handler(output_type=UserJoinedMessage)
        async def user_joined(self, event: UserJoinedEvent) -> UserJoinedMessage:
            """Handle user join events from other parts of the app."""
            return UserJoinedMessage(
                payload=UserJoinedPayload(
                    username=event.payload.username,
                    message=f"{event.payload.username} joined the room"
                )
            )

Next Steps
----------

Now that you understand chanx's decorator-based approach, you can:

- Learn about :doc:`mixins` for reusable handler composition
- Learn about :doc:`asyncapi` documentation generation
- Explore :doc:`testing` patterns for WebSocket consumers
- Check out :doc:`framework-integration` for Django views and FastAPI API endpoints

The decorator pattern eliminates the complexity of manual message routing while providing full type safety and automatic documentation generation. This makes WebSocket development as straightforward as building REST APIs.
