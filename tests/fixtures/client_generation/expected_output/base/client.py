"""Base WebSocket client for AsyncAPI."""

import asyncio
import json
from contextlib import suppress
from traceback import print_exc
from types import UnionType
from typing import Annotated, Any

from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from websockets.asyncio.client import ClientConnection, connect

from .errors import ERROR_ACTION, ProblemDetails, parse_problem


class BaseClient:
    """Base WebSocket client class."""

    path: str
    websocket: ClientConnection
    incoming_message: type[BaseModel] | UnionType
    discriminator_field: str = "action"

    def __init__(
        self,
        base_url: str,
        /,
        protocol: str = "ws",
        headers: dict[str, str] | None = None,
        path_params: dict[str, Any] | None = None,
    ):
        """
        Initialize the base client.

        Args:
            base_url: WebSocket server URL (host:port or full URL)
            protocol: Protocol (ws or wss)
            headers: Optional headers for WebSocket connection
            path_params: Path parameters to replace in URL (e.g., {"room_id": 123, "room_name": "lobby"})
        """
        # Handle both full URLs and host:port
        if not base_url.startswith(("ws://", "wss://")):
            base_url = f"{protocol}://{base_url}"

        self.headers = headers or {}

        # Replace path parameters in the path
        path = self.path
        if path_params:
            for param_name, param_value in path_params.items():
                path = path.replace(f"{{{param_name}}}", str(param_value))

        self.url = base_url + path

        self.incoming_message_adapter = TypeAdapter[BaseModel](
            Annotated[
                self.incoming_message,
                Field(discriminator=self.discriminator_field),
            ]
        )

    async def send_init_message(self) -> None:
        """Send initial message after connection is established."""
        pass

    async def before_handle(self) -> None:
        """
        Hook called before establishing WebSocket connection.

        Override this method to perform setup operations before connecting,
        such as authentication, validation, or resource initialization.
        """
        pass

    async def handle(self) -> None:  # noqa
        """
        Connect to WebSocket server and handle incoming messages.

        This method establishes a WebSocket connection and continuously listens
        for incoming messages, dispatching them to the appropriate handlers.
        """

        await self.before_handle()
        init: asyncio.Future[None] | None = None

        try:
            # Create new WebSocket connection for this request
            async with connect(
                self.url, additional_headers=self.headers or None
            ) as websocket:
                self.websocket = websocket
                # Not awaited here: a subscribe sent from `send_init_message`
                # waits for a reply that arrives through the loop below.
                init = asyncio.ensure_future(self.send_init_message())

                # Stream responses back to channel layer
                async for data in websocket:
                    try:
                        decoded_data = (
                            data.decode("utf-8") if isinstance(data, bytes) else data
                        )
                        py_object = json.loads(decoded_data)
                        await self.dispatch_frame(py_object)
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        # Not JSON, handle as raw
                        await self.handle_raw_data(data)
                    except Exception as e:
                        # Log and continue processing other messages
                        await self.handle_error(e)
                        continue

        except Exception as e:
            await self.handle_websocket_connection_error(e)
            return
        finally:
            await _settle(init)

        await self.after_handle()

    async def dispatch_frame(self, py_object: dict[str, Any]) -> None:
        """
        Validate one decoded frame and route it.

        Args:
            py_object: The decoded JSON frame
        """
        if py_object.get(self.discriminator_field) == ERROR_ACTION:
            await self.handle_error_message(
                parse_problem(py_object.get("payload")), py_object
            )
            return
        try:
            message = self.incoming_message_adapter.validate_python(py_object)
            await self.handle_message(message)
        except ValidationError:
            # Valid JSON but doesn't match schema
            await self.handle_invalid_message(py_object)

    async def disconnect(self, code: int = 1000, reason: str = "") -> None:
        """
        Disconnect from the WebSocket server.

        Args:
            code: WebSocket close code (default: 1000 for normal closure)
            reason: Optional reason for closing the connection
        """
        await self.websocket.close(code, reason)

    async def send_raw(self, data: str | bytes) -> None:
        """
        Send raw data to the server.

        Args:
            data: Raw data to send
        """
        if not self.websocket:
            raise RuntimeError("Not connected to WebSocket server")

        await self.websocket.send(data)

    async def send_json(self, data: dict[str, Any]) -> None:
        """
        Send JSON data to the server.

        Args:
            data: Dictionary to serialize and send as JSON
        """
        await self.send_raw(json.dumps(data))

    async def send_message(self, message: Any) -> None:
        """
        Send a Pydantic message model to the server.

        Note:
            In concrete client implementations, the message parameter type will be
            overridden with a specific union type of outgoing messages for that channel.

        Args:
            message: Pydantic BaseModel instance to serialize and send.
                     In subclasses, this will be a typed union of valid outgoing messages.
        """
        await self.send_json(message.model_dump())

    async def handle_message(self, message: Any) -> None:
        """
        Handle incoming messages from the server.

        Override this method in subclasses to process messages.

        Note:
            In concrete client implementations, the message parameter type will be
            overridden with a specific union type of incoming messages for that channel.

        Args:
            message: Validated Pydantic message model received from the server.
                     In subclasses, this will be a typed union of valid incoming messages.
        """
        pass

    async def handle_error_message(
        self, problem: ProblemDetails | None, frame: dict[str, Any]
    ) -> None:
        """
        Handle an error frame from the server. Override it and branch on ``problem.type``.

        Args:
            problem: The payload as a ProblemDetails, or None when the server sent
                another shape (``error_format = "pydantic"`` or a custom hook)
            frame: The whole error frame
        """
        if problem is None:
            print(f"Server error: {frame.get('payload')}")
        else:
            print(f"Server error: {problem.title}: {problem.detail}")

    async def handle_raw_data(self, message: str | bytes) -> None:
        """
        Handle raw non-JSON data from the server.

        Override this method to process binary or non-JSON text data.

        Args:
            message: Raw data received from the server
        """
        pass

    async def handle_error(self, error: Exception) -> None:
        """
        Handle errors that occur during message processing.

        Override this method to implement custom error handling.

        Args:
            error: Exception that occurred during message processing
        """
        raise error

    async def handle_websocket_connection_error(self, e: Exception) -> None:
        """
        Handle WebSocket connection errors.

        Override this method to implement custom error handling for connection issues.

        Args:
            e: Exception that occurred during WebSocket connection
        """
        pass

    async def after_handle(self) -> None:
        """
        Hook called after WebSocket connection closes.

        Override this method to perform cleanup operations after disconnection,
        such as releasing resources, logging, or state cleanup.
        """
        pass

    async def handle_invalid_message(self, invalid_message: Any) -> None:
        """
        Handle messages that fail Pydantic validation.

        Override this method to implement custom validation error handling.

        Args:
            invalid_message: The parsed JSON object that failed validation
        """
        print(f"Received invalid message that failed validation: {invalid_message}")
        print_exc()


async def _settle(task: "asyncio.Future[None] | None") -> None:
    """Let the init message finish, or stop waiting for it.

    Its exception is retrieved either way, so asyncio does not report it later
    at garbage collection.
    """
    if task is None or task.done():
        if task is not None:
            with suppress(Exception, asyncio.CancelledError):
                task.result()
        return
    task.cancel()
    # CancelledError is not an Exception, so it needs naming separately.
    with suppress(Exception, asyncio.CancelledError):
        await task
