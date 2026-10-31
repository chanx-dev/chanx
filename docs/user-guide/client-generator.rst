Client Generator
================

The chanx client generator automatically creates type-safe Python WebSocket clients from AsyncAPI 3.0 schemas. This eliminates the need to manually write and maintain client code, ensuring your client always stays in sync with your server's API.

.. tip::

   For JavaScript and TypeScript clients, use `chanx-js <https://js.chanx.dev/>`_. See :doc:`../ecosystem`.

Why Use the Client Generator?
------------------------------

**Without the Client Generator:**

.. code-block:: python

    # Manual WebSocket client - error-prone and tedious
    import websocket
    import json

    ws = websocket.create_connection("ws://localhost:8000/ws/chat")

    # No type safety, no validation
    ws.send(json.dumps({
        "action": "chat",
        "payload": {"message": "Hello"}  # Easy to make typos
    }))

    response = json.loads(ws.recv())
    # What fields does response have? Check the docs... if they exist

**With the Client Generator:**

.. code-block:: python

    # Generated type-safe client
    from my_client.chat import ChatClient, ChatMessage, ChatPayload

    client = ChatClient("localhost:8000")

    # Full type safety and IDE autocomplete
    message = ChatMessage(
        payload=ChatPayload(message="Hello")
    )

    async def main():
        await client.handle()  # Connects and handles messages

    # Type-safe message handling
    async def handle_message(self, message: IncomingMessage) -> None:
        if isinstance(message, ChatNotificationMessage):
            print(f"Received: {message.payload.message}")

Installation
------------

**For Generating Clients (CLI):**

.. code-block:: bash

    # Using pip
    pip install "chanx[cli]"

    # Using uv (install as dev dependency)
    uv add --group dev chanx[cli]

**For Using Generated Clients:**

.. code-block:: bash

    # Using pip
    pip install "chanx[client]"

    # Using uv (install as runtime dependency)
    uv add chanx[client]

This installs only Pydantic and websockets - everything needed to run generated client code without CLI tools or server dependencies.

**For Both CLI and Client (Common Setup):**

.. code-block:: bash

    # Using pip - install both extras
    pip install "chanx[cli,client]"

    # Using uv - separate runtime and dev dependencies
    uv add chanx[client]           # Runtime
    uv add --group dev chanx[cli]  # Development

Quick Start
-----------

1. **Get AsyncAPI Schema**

Your chanx server automatically generates an AsyncAPI schema (see :doc:`asyncapi` for details):

.. code-block:: bash

    # Django or FastAPI - schema available at:
    # http://localhost:8000/asyncapi.json
    # http://localhost:8000/asyncapi.yaml

You can use the URL directly or save it locally - both work!

2. **Generate Client**

Run the client generator with a local file or URL:

.. code-block:: bash

    # From local file (JSON or YAML)
    chanx generate-client --schema asyncapi.json --output ./my_client
    chanx generate-client --schema asyncapi.yaml --output ./my_client

    # Directly from URL (no download needed!)
    chanx generate-client --schema http://localhost:8000/asyncapi.json --output ./my_client

This creates a complete client package:

.. code-block:: text

    my_client/
    ├── __init__.py              # Main package exports
    ├── README.md                # Usage documentation
    ├── base/
    │   ├── __init__.py
    │   └── client.py            # Base client class
    ├── shared/
    │   ├── __init__.py
    │   └── messages.py          # Shared message types
    └── chat/                    # Channel-specific module
        ├── __init__.py
        ├── client.py            # ChatClient class
        └── messages.py          # Channel message types

3. **Install Client Dependencies**

In your client project (where you'll use the generated code):

.. code-block:: bash

    pip install "chanx[client]"

4. **Use the Generated Client**

Inherit from the generated client and override ``handle_message()`` to process incoming messages:

.. code-block:: python

    import asyncio
    from typing import assert_never
    from my_client.chat import (
        ChatClient,
        ChatMessage,
        ChatPayload,
        IncomingMessage,
        ChatNotificationMessage,
        PongMessage
    )

    class MyChatClient(ChatClient):
        async def send_init_message(self) -> None:
            """Send initial message after connection is established."""
            await self.send_message(
                ChatMessage(payload=ChatPayload(
                    message="Hello",
                    conversation_id=1,
                    user_id="user123"
                ))
            )

        async def handle_message(self, message: IncomingMessage) -> None:
            """Handle all incoming messages with exhaustive pattern matching."""
            match message:
                case ChatNotificationMessage(payload=payload):
                    print(f"Notification: {payload.message}")
                case PongMessage():
                    print("Received pong")
                case _:
                    assert_never(message)

    async def main():
        client = MyChatClient("localhost:8000")

        # Connect and start handling messages
        # Initial message sent automatically via send_init_message()
        await client.handle()

    asyncio.run(main())

CLI Reference
-------------

Basic Usage
~~~~~~~~~~~

.. code-block:: bash

    chanx generate-client --schema <schema-path-or-url> --output <output-dir>

**Required Options:**

``--schema, -s``
    Path or URL to AsyncAPI JSON or YAML schema file.
    Supports:

    - Local files: ``asyncapi.json``, ``asyncapi.yaml``
    - HTTP/HTTPS URLs: ``http://localhost:8000/asyncapi.json``
    - Both JSON and YAML formats

``--output, -o``
    Output directory for generated client code

**Optional Options:**

``--formatter, -f``
    Custom formatter command (e.g., ``"ruff format"``, ``"black"``).
    If not specified, auto-detects ruff.

``--no-format``
    Skip automatic formatting after generation

``--no-readme``
    Skip README.md generation

``--clear-output``
    Remove entire output directory before generation

``--override-base``
    Regenerate base files even if they already exist

``--no-clear-channels``
    Keep existing channel folders instead of clearing them

.. note::
   By default, regeneration keeps the ``base/`` folder (preserving customizations) and clears channel folders. Use ``--clear-output`` for a fresh start or ``--override-base`` to update base files.

Examples
~~~~~~~~

**From Local File:**

.. code-block:: bash

    # JSON format
    chanx generate-client --schema asyncapi.json --output ./myclient

    # YAML format
    chanx generate-client --schema asyncapi.yaml --output ./myclient

**From URL (No Download Needed):**

.. code-block:: bash

    # Development server
    chanx generate-client \
        --schema http://localhost:8000/asyncapi.json \
        --output ./myclient

    # Production API
    chanx generate-client \
        --schema https://api.example.com/asyncapi.yaml \
        --output ./myclient

**Custom Formatter:**

.. code-block:: bash

    chanx generate-client \
        --schema asyncapi.json \
        --output ./myclient \
        --formatter "black"

**Skip Formatting:**

.. code-block:: bash

    chanx generate-client \
        --schema asyncapi.json \
        --output ./myclient \
        --no-format

**Skip README:**

.. code-block:: bash

    chanx generate-client \
        --schema asyncapi.json \
        --output ./myclient \
        --no-readme

**Fresh Regeneration (Clear Everything):**

.. code-block:: bash

    chanx generate-client \
        --schema asyncapi.json \
        --output ./myclient \
        --clear-output

**Update Base Files:**

.. code-block:: bash

    chanx generate-client \
        --schema asyncapi.json \
        --output ./myclient \
        --override-base


Generated Client Structure
--------------------------

Base Client
~~~~~~~~~~~

The generated ``base/client.py`` provides the foundation for all channel clients:

.. code-block:: python

    from my_client.base import BaseClient

    class BaseClient:
        """Base WebSocket client class."""

        def __init__(
            self,
            base_url: str,
            /,
            protocol: str = "ws",
            headers: dict[str, str] | None = None,
            path_params: dict[str, Any] | None = None,
        ):
            """Initialize the base client."""

        async def handle(self) -> None:
            """Connect to WebSocket server and handle incoming messages."""

        async def send_message(self, message: BaseModel) -> None:
            """Send a Pydantic message model to the server."""

        async def handle_message(self, message: BaseModel) -> None:
            """Override this method in subclasses to process messages."""

        async def disconnect(self, code: int = 1000, reason: str = "") -> None:
            """Disconnect from the WebSocket server."""

**Hooks for Customization:**

- ``send_init_message()``: Send initial message after connection is established
- ``before_handle()``: Called before establishing connection
- ``after_handle()``: Called after connection closes
- ``handle_error(error)``: Handle general message processing errors
- ``handle_websocket_connection_error(error)``: Handle connection errors
- ``handle_raw_data(message)``: Handle non-JSON data
- ``handle_invalid_message(invalid_message)``: Handle validation errors
- ``handle_error_message(problem, frame)``: Handle an ``error`` frame from the server

Channel Clients
~~~~~~~~~~~~~~~

Each channel gets its own client class with typed message unions:

.. code-block:: python

    from my_client.chat import ChatClient, OutgoingMessage, IncomingMessage

    class ChatClient(BaseClient):
        """WebSocket client for chat channel."""

        path = "/ws/chat"

        async def send_message(self, message: OutgoingMessage) -> None:
            """Send outgoing message (type-safe union)."""

        async def handle_message(self, message: IncomingMessage) -> None:
            """Handle incoming message (type-safe union)."""

Message Types
~~~~~~~~~~~~~

All message types are generated as Pydantic models with full validation.

**Each channel module exports:**

- **Client class** - WebSocket client for that channel
- **Message classes** - Individual message models (e.g., ``ChatMessage``)
- **Payload classes** - Message payload models (e.g., ``ChatPayload``)
- **IncomingMessage** - Union type of all messages the client can receive
- **OutgoingMessage** - Union type of all messages the client can send

.. code-block:: python

    from typing import Literal
    from pydantic import BaseModel

    # Payload models
    class ChatPayload(BaseModel):
        """Payload for agent chat messages."""
        message: str
        conversation_id: int
        user_id: str
        allowed_tools: list[str] | None = None
        auto_use_tools: list[str] | None = None

    # Message models
    class ChatMessage(BaseModel):
        """Chat message."""
        action: Literal["chat"] = "chat"
        payload: ChatPayload

    # Type-safe unions for incoming/outgoing messages
    IncomingMessage = ChatNotificationMessage | PongMessage
    OutgoingMessage = ChatMessage | PingMessage

**Import from channel modules:**

.. code-block:: python

    from my_client.chat import ChatClient, IncomingMessage, OutgoingMessage
    from my_client.chat.messages import ChatMessage, ChatPayload

Shared Messages
~~~~~~~~~~~~~~~

Messages used across multiple channels are placed in ``shared/messages.py`` to avoid duplication:

.. code-block:: python

    from my_client.shared.messages import PingMessage, PongMessage

Advanced Message Handling
~~~~~~~~~~~~~~~~~~~~~~~~~

For more complex scenarios, extract message handlers into separate methods:

**Using Pattern Matching (Recommended - Python 3.10+):**

Pattern matching with ``match/case`` provides **exhaustive checking** - type checkers (pyright/mypy) will error if you forget to handle a message type:

.. code-block:: python

    from typing import assert_never
    from my_client.chat import ChatClient, IncomingMessage
    from my_client.chat.messages import (
        ChatNotificationMessage,
        AgentStreamingMessage,
        PongMessage
    )

    class MyChatClient(ChatClient):
        async def handle_message(self, message: IncomingMessage) -> None:
            """Handle incoming messages with exhaustive pattern matching."""
            match message:
                case ChatNotificationMessage(payload=payload):
                    print(f"Notification: {payload.message}")
                case AgentStreamingMessage(payload=payload):
                    print(f"Streaming: {payload.content}", end="", flush=True)
                case PongMessage():
                    print("Received pong")
                case _:
                    assert_never(message)

**Why use pattern matching?**

- **Type safety**: Pyright/mypy catch missing cases at development time
- **Exhaustive**: If you comment out a case, type checker will error
- **Refactor-safe**: Adding new message types shows exactly where to update handlers

Example type checker errors:

.. code-block:: text

    # Pyright error if you miss a case:
    error: Cases within match statement do not exhaustively handle all values
        Unhandled type: "PongMessage"
        Add the missing case or use "case _: pass"

    # Mypy error with assert_never:
    error: Argument 1 to "assert_never" has incompatible type "PongMessage"; expected "Never"

**Using isinstance() Checks (Alternative):**

For Python < 3.10 or if you prefer explicit checks:

.. code-block:: python

    from my_client.chat import ChatClient, IncomingMessage

    class MyChatClient(ChatClient):
        async def handle_message(self, message: IncomingMessage) -> None:
            """Handle incoming messages with type narrowing."""
            if isinstance(message, ChatNotificationMessage):
                print(f"Notification: {message.payload.message}")
            elif isinstance(message, AgentStreamingMessage):
                print(f"Streaming: {message.payload.content}", end="", flush=True)
            elif isinstance(message, PongMessage):
                print("Received pong")

.. note::
   Pattern matching is **recommended** for production code - type checkers ensure you never miss a message type when refactoring.

Connection Lifecycle Hooks
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Customize connection behavior with lifecycle hooks:

.. code-block:: python

    class MyChatClient(ChatClient):
        async def before_handle(self) -> None:
            """Called before connecting."""
            print("Connecting to server...")

        async def send_init_message(self) -> None:
            """Send initial message after connection."""
            await self.send_message(
                ChatMessage(payload=ChatPayload(
                    message="Hello!",
                    conversation_id=1,
                    user_id="user123"
                ))
            )

        async def after_handle(self) -> None:
            """Called after connection closes."""
            print("Connection closed")

Error Handling
~~~~~~~~~~~~~~

Override error handlers for custom error processing:

.. code-block:: python

    class MyChatClient(ChatClient):
        async def handle_error(self, error: Exception) -> None:
            """Handle message processing errors."""
            logger.error(f"Error processing message: {error}")

        async def handle_websocket_connection_error(self, error: Exception) -> None:
            """Handle connection errors."""
            logger.error(f"Connection error: {error}")
            # Optionally implement reconnection logic

        async def handle_invalid_message(self, invalid_message: Any) -> None:
            """Handle messages that fail validation."""
            logger.warning(f"Invalid message: {invalid_message}")
            # Default implementation prints traceback
            # Override to customize behavior

``error`` frames from the server go to ``handle_error_message`` instead, with the payload
parsed as a ``ProblemDetails`` (see :ref:`protocol-errors`). Branch on ``problem.type`` with the
``ErrorType`` constants; ``problem`` is ``None`` when the server sends another shape,
such as ``error_format = "pydantic"``:

.. code-block:: python

    from my_client.base.errors import ErrorType, ProblemDetails

    class MyChatClient(ChatClient):
        async def handle_error_message(
            self, problem: ProblemDetails | None, frame: dict[str, Any]
        ) -> None:
            if problem and problem.type == ErrorType.VALIDATION_FAILED:
                for error in problem.errors or []:
                    logger.warning(f"{error.pointer}: {error.keyword}")

Topic clients get the same hook on each topic handle, and a reply from ``request()`` or
``subscribe()`` that is an error carries the parsed payload as ``reply.problem``.

Advanced Features
-----------------

Path Parameters
~~~~~~~~~~~~~~~

For channels with path parameters:

.. code-block:: python

    # Channel with path: /ws/room/{room_id}
    from my_client.room_chat import RoomChatClient

    client = RoomChatClient(
        "localhost:8000",
        path_params={"room_id": "lobby"}
    )
    # Connects to: ws://localhost:8000/ws/room/lobby

Custom Headers
~~~~~~~~~~~~~~

Add custom headers for authentication:

.. code-block:: python

    client = ChatClient(
        "localhost:8000",
        headers={
            "Authorization": "Bearer your-token-here",
            "X-Custom-Header": "value"
        }
    )

WSS Protocol
~~~~~~~~~~~~

Use secure WebSocket connections:

.. code-block:: python

    client = ChatClient(
        "api.example.com",
        protocol="wss"
    )
    # Connects to: wss://api.example.com/ws/chat

Raw Data Handling
~~~~~~~~~~~~~~~~~

Handle non-JSON data (binary, plain text):

.. code-block:: python

    class MyChatClient(ChatClient):
        async def handle_raw_data(self, message: str | bytes) -> None:
            """Handle raw non-JSON data."""
            if isinstance(message, bytes):
                # Handle binary data
                print(f"Received binary: {len(message)} bytes")
            else:
                # Handle plain text
                print(f"Received text: {message}")

Type Safety Benefits
--------------------

The generated client provides full type safety with IDE support:

**IDE Autocomplete:**

.. code-block:: python

    # IDE autocompletes available fields
    message = ChatMessage(
        payload=ChatPayload(
            message="",      # ← IDE shows this field
            conversation_id= # ← IDE shows this field
        )
    )

**Type Checking:**

.. code-block:: python

    # mypy/pyright catch type errors at development time
    client.send_message("invalid")  # ❌ Type error!
    client.send_message(ChatMessage(...))  # ✅ Type safe!

**Runtime Validation:**

.. code-block:: python

    # Pydantic validates at runtime
    message = ChatMessage(
        payload=ChatPayload(
            message=123,  # ❌ ValidationError: message must be str
            conversation_id="invalid"  # ❌ ValidationError: must be int
        )
    )

Integration with chanx Server
------------------------------

The client generator is designed to work seamlessly with chanx servers:

1. **Auto-Generated from Server**

   Your AsyncAPI schema is automatically generated from your chanx decorators

2. **Type-Safe Communication**

   Client and server share the same message schemas via Pydantic

3. **Always in Sync**

   Regenerate client whenever server API changes

4. **Full Documentation**

   Generated README.md includes usage examples and API details

Workflow Example
~~~~~~~~~~~~~~~~

.. code-block:: bash

    # 1. Update server
    # Add new message type to your chanx consumer

    # 2. Regenerate client directly from server (no file needed!)
    chanx generate-client \
        --schema http://localhost:8000/asyncapi.json \
        --output ./my_client

    # 3. Update client code
    # Your IDE will show new message types and fields

    # Alternative: Save schema for version control
    curl http://localhost:8000/asyncapi.json > asyncapi.json
    chanx generate-client --schema asyncapi.json --output ./my_client

See Also
--------

- :doc:`asyncapi` - Generating AsyncAPI documentation
- :doc:`testing` - Testing WebSocket clients
- :doc:`framework-integration` - Server setup guides
