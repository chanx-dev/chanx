"""
Tests for chanx.asyncapi.generator module.

Tests the AsyncAPI 3.0 specification generator functionality.
"""

from typing import Any, ClassVar, Literal
from unittest.mock import Mock

import pytest
from chanx.asyncapi.generator import AsyncAPIGenerator
from chanx.channels.websocket import AsyncJsonWebsocketConsumer
from chanx.core.decorators import channel, event_handler, ws_handler
from chanx.core.registry import message_registry
from chanx.messages.base import BaseMessage
from chanx.routing.discovery import RouteInfo
from pydantic import BaseModel


class DummyMessage(BaseMessage):
    action: Literal["test"] = "test"
    payload: str


class DummyResponse(BaseMessage):
    action: Literal["test_response"] = "test_response"
    payload: dict[str, Any]


class DummyEvent(BaseMessage):
    action: Literal["test_event"] = "test_event"
    payload: int


class SecondResponse(BaseMessage):
    action: Literal["second_response"] = "second_response"
    payload: str


class ThirdResponse(BaseMessage):
    action: Literal["third_response"] = "third_response"
    payload: bool


@channel(name="test_channel", description="Test channel for testing")
class DummyConsumer(AsyncJsonWebsocketConsumer):
    """Test consumer with documentation."""

    @ws_handler(description="Handle test messages", summary="Test handler")
    async def handle_test(self, message: DummyMessage) -> DummyResponse:
        return DummyResponse(payload={"result": "success"})

    @event_handler(description="Handle test events")
    async def handle_test_event(self, event: DummyEvent) -> None:
        pass


class UndocumentedConsumer(AsyncJsonWebsocketConsumer):
    """Consumer without explicit channel documentation."""

    @ws_handler
    async def handle_simple(self, message: DummyMessage) -> None:
        pass


class TestAsyncAPIGenerator:
    """Test the AsyncAPI generator class."""

    def test_generator_initialization(self) -> None:
        """Test generator initialization with default values."""
        routes: list[RouteInfo] = []
        generator = AsyncAPIGenerator(routes)

        assert generator.routes == []
        assert generator.title is not None
        assert generator.version is not None
        assert generator.server_url is not None
        assert generator.server_protocol is not None
        assert generator.channels == {}
        assert generator.operations == {}

    def test_generator_initialization_with_custom_values(self) -> None:
        """Test generator initialization with custom values."""
        routes: list[RouteInfo] = []
        generator = AsyncAPIGenerator(
            routes=routes,
            title="Custom API",
            version="2.0.0",
            description="Custom description",
            server_url="wss://example.com",
            server_protocol="wss",
        )

        assert generator.title == "Custom API"
        assert generator.version == "2.0.0"
        assert generator.description == "Custom description"
        assert generator.server_url == "wss://example.com"
        assert generator.server_protocol == "wss"

    def test_generate_empty_spec(self) -> None:
        """Test generating spec with no routes."""
        generator = AsyncAPIGenerator([])
        spec = generator.generate()

        # Should generate valid AsyncAPI spec structure
        assert spec["asyncapi"] == "3.0.0"
        assert "info" in spec
        assert "servers" in spec
        assert "channels" in spec
        assert "operations" in spec

        # With no routes, channels and operations should be empty
        assert spec["channels"] == {}
        assert spec["operations"] == {}

    def test_error_payload_schemas_follow_the_error_format(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The standard format lists its payload schemas; the Pydantic one does not."""
        schemas = AsyncAPIGenerator([]).generate()["components"]["schemas"]
        assert schemas["ProblemDetails"]["required"] == ["type", "title", "detail"]
        assert schemas["ValidationFailure"]["required"] == [
            "keyword",
            "pointer",
            "detail",
        ]

        monkeypatch.setattr(
            "chanx.asyncapi.generator.config", Mock(error_format="pydantic")
        )
        schemas = AsyncAPIGenerator([]).generate()["components"]["schemas"]
        assert "ProblemDetails" not in schemas

    def test_a_model_named_like_an_error_schema_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Error payload schemas never silently replace a user's model."""
        monkeypatch.setitem(
            message_registry.schema_objects, "ProblemDetails", {"type": "object"}
        )
        with pytest.raises(ValueError, match="'ProblemDetails'"):
            AsyncAPIGenerator([]).generate()

    def test_generate_with_single_route(self) -> None:
        """Test generating spec with single route."""
        route = RouteInfo(
            path="/ws/test",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=DummyConsumer,
        )

        generator = AsyncAPIGenerator([route])
        spec = generator.generate()

        # Should have channels and operations
        assert len(spec["channels"]) > 0
        assert len(spec["operations"]) > 0

        # Should have proper info
        assert spec["info"]["title"] is not None
        assert spec["info"]["version"] is not None

    def test_generate_with_multiple_routes(self) -> None:
        """Test generating spec with multiple routes."""
        routes = [
            RouteInfo(
                path="/ws/test1",
                handler=Mock(),
                base_url="ws://localhost:8000",
                consumer=DummyConsumer,
            ),
            RouteInfo(
                path="/ws/test2",
                handler=Mock(),
                base_url="ws://localhost:8000",
                consumer=UndocumentedConsumer,
            ),
        ]

        generator = AsyncAPIGenerator(routes)
        spec = generator.generate()

        # Should have multiple channels
        assert len(spec["channels"]) == 2

        # Each route should generate operations
        assert len(spec["operations"]) > 0

    def test_server_environment_name_localhost(self) -> None:
        """Test server environment name generation for localhost."""
        generator = AsyncAPIGenerator([], server_url="ws://localhost:8000")
        env_name = generator._get_server_environment_name()
        assert env_name == "development"

        generator = AsyncAPIGenerator([], server_url="ws://127.0.0.1:9000")
        env_name = generator._get_server_environment_name()
        assert env_name == "development"

    def test_server_environment_name_production(self) -> None:
        """Test server environment name generation for production."""
        generator = AsyncAPIGenerator([], server_url="wss://production.example.com:443")
        env_name = generator._get_server_environment_name()
        assert env_name == "production"

        generator = AsyncAPIGenerator([], server_url="wss://api.mysite.com")
        env_name = generator._get_server_environment_name()
        assert env_name == "production"

    def test_server_environment_name_no_url(self) -> None:
        """Test server environment name when no URL is provided."""
        generator = AsyncAPIGenerator([], server_url=None)
        env_name = generator._get_server_environment_name()
        assert env_name == "development"

    def test_parameter_type_description(self) -> None:
        """Test parameter type description generation."""
        generator = AsyncAPIGenerator([])

        # Test known converter types
        assert generator._get_parameter_type_description("int") == "int"
        assert generator._get_parameter_type_description("str") == "str"
        assert generator._get_parameter_type_description("slug") == "slug"
        assert generator._get_parameter_type_description("uuid") == "uuid"

        # Test regex patterns
        pattern = "[0-9]+"
        result = generator._get_parameter_type_description(pattern)
        assert result == f"regex: {pattern}"

    def test_get_channel_messages(self) -> None:
        """Test getting channel messages from consumer."""
        # First need to register the consumer's messages
        route = RouteInfo(
            path="/ws/test",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=DummyConsumer,
        )

        generator = AsyncAPIGenerator([route])
        generator.build_channels()  # This populates the message registry

        messages = generator.get_channel_messages(DummyConsumer)
        assert isinstance(messages, dict)
        # Should have message references
        for _msg_name, msg_ref in messages.items():
            assert "$ref" in msg_ref

    def test_build_output(self) -> None:
        """Test building output message reference."""
        generator = AsyncAPIGenerator([])

        # Build output reference for a message type
        output_ref = generator.build_output("test_channel", DummyResponse)

        assert "$ref" in output_ref
        assert "test_channel" in output_ref["$ref"]
        assert "messages" in output_ref["$ref"]

    def test_channel_with_decorator_metadata(self) -> None:
        """Test channel building with @channel decorator metadata."""
        route = RouteInfo(
            path="/ws/test",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=DummyConsumer,
        )

        generator = AsyncAPIGenerator([route])
        generator.build_channels()

        # Should use decorator name instead of class snake_name
        assert "test_channel" in generator.channels
        channel = generator.channels["test_channel"]
        assert channel["title"] == "test_channel"
        assert channel["description"] == "Test channel for testing"

    def test_build_channels_with_route_info(self) -> None:
        """Test building channels with route information."""
        route = RouteInfo(
            path="/ws/test/{user_id}",
            handler=Mock(),
            base_url="ws://localhost:8000",
            path_params={"user_id": "int"},
            consumer=DummyConsumer,
        )

        generator = AsyncAPIGenerator([route])
        generator.build_channels()

        # Should have created channel (using @channel decorator name)
        assert len(generator.channels) == 1
        assert "test_channel" in generator.channels

        channel = generator.channels["test_channel"]
        assert channel["address"] == "/ws/test/{user_id}"

        # Should have path parameters
        assert "parameters" in channel
        assert "user_id" in channel["parameters"]
        assert "description" in channel["parameters"]["user_id"]

    def test_build_operations_with_handlers(self) -> None:
        """Test building operations from consumer handlers."""
        route = RouteInfo(
            path="/ws/test",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=DummyConsumer,
        )

        generator = AsyncAPIGenerator([route])
        generator.build_channels()  # Build channels first
        generator.build_operations()

        # Should have created operations for each handler
        assert len(generator.operations) > 0

        # Operations should have proper structure
        for _op_name, operation in generator.operations.items():
            assert "action" in operation
            assert operation["action"] in ["send", "receive"]
            assert "channel" in operation
            assert "$ref" in operation["channel"]

    def test_channel_with_path_parameters(self) -> None:
        """Test channel creation with path parameters."""
        route = RouteInfo(
            path="/ws/room/{room_id}/user/{user_id}",
            handler=Mock(),
            base_url="ws://localhost:8000",
            path_params={"room_id": "str", "user_id": "int"},
            consumer=DummyConsumer,
        )

        generator = AsyncAPIGenerator([route])
        generator.build_channels()

        channel = generator.channels["test_channel"]
        assert "parameters" in channel
        assert "room_id" in channel["parameters"]
        assert "user_id" in channel["parameters"]

        # Check parameter descriptions contain type info
        room_param = channel["parameters"]["room_id"]
        user_param = channel["parameters"]["user_id"]
        assert "str" in room_param["description"]
        assert "int" in user_param["description"]

    def test_channel_without_decorator(self) -> None:
        """Test channel creation without @channel decorator."""
        route = RouteInfo(
            path="/ws/simple",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=UndocumentedConsumer,
        )

        generator = AsyncAPIGenerator([route])
        generator.build_channels()

        # Should use snake_name when no @channel decorator
        assert "undocumented" in generator.channels
        channel = generator.channels["undocumented"]
        assert channel["title"] == "undocumented"

    def test_operation_structure(self) -> None:
        """Test operation structure and content."""
        route = RouteInfo(
            path="/ws/test",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=DummyConsumer,
        )

        generator = AsyncAPIGenerator([route])
        generator.build_channels()
        generator.build_operations()

        # Check that operations have required fields
        assert len(generator.operations) > 0

        for operation in generator.operations.values():
            assert "action" in operation
            assert "channel" in operation
            assert "description" in operation
            assert "summary" in operation

    def test_operation_with_tags(self) -> None:
        """Test operation creation with tags metadata."""

        class TaggedMessage(BaseMessage):
            action: Literal["tagged"] = "tagged"
            payload: str

        class TaggedConsumer(AsyncJsonWebsocketConsumer):
            @ws_handler(tags=["important", "api"])
            async def handle_tagged(self, message: TaggedMessage) -> None:
                pass

        route = RouteInfo(
            path="/ws/tagged",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=TaggedConsumer,
        )

        generator = AsyncAPIGenerator([route])
        generator.build_channels()
        generator.build_operations()

        # Should have operation with tags
        operations = list(generator.operations.values())
        assert len(operations) > 0

        # Find operation with tags
        tagged_operation = None
        for op in operations:
            if "tags" in op:
                tagged_operation = op
                break

        assert tagged_operation is not None
        assert "tags" in tagged_operation
        assert len(tagged_operation["tags"]) == 2
        assert tagged_operation["tags"][0]["name"] == "important"
        assert tagged_operation["tags"][1]["name"] == "api"

    def test_operation_with_union_output_type(self) -> None:
        """Test operation creation with UnionType output."""

        class UnionMessage(BaseMessage):
            action: Literal["union_input"] = "union_input"
            payload: str

        class UnionConsumer(AsyncJsonWebsocketConsumer):
            @ws_handler(output_type=DummyResponse | SecondResponse)
            async def handle_union(self, message: UnionMessage) -> None:
                pass

        route = RouteInfo(
            path="/ws/union",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=UnionConsumer,
        )

        generator = AsyncAPIGenerator([route])
        generator.build_channels()
        generator.build_operations()

        # Should have operation
        assert len(generator.operations) > 0
        operation = list(generator.operations.values())[0]

        # Should have reply with multiple messages for UnionType
        assert "reply" in operation
        assert "messages" in operation["reply"]
        assert len(operation["reply"]["messages"]) == 2

        # Each message should be a $ref
        for msg in operation["reply"]["messages"]:
            assert "$ref" in msg

    def test_operation_with_optional_union_output_type(self) -> None:
        """A `X | None` reply must not reference a non-existent none_type message."""

        class OptionalMessage(BaseMessage):
            action: Literal["optional_input"] = "optional_input"
            payload: str

        class OptionalConsumer(AsyncJsonWebsocketConsumer):
            @ws_handler
            async def handle_optional(
                self, message: OptionalMessage
            ) -> DummyResponse | None:
                return None

        route = RouteInfo(
            path="/ws/optional",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=OptionalConsumer,
        )

        generator = AsyncAPIGenerator([route])
        spec = generator.generate()

        operation = spec["operations"]["handle_optional"]
        refs = [msg["$ref"] for msg in operation["reply"]["messages"]]

        # Only the message arm is referenced; None has no message definition.
        assert refs == ["#/channels/optional/messages/dummy_response"]

        # Every reference in the document must resolve.
        channel_messages = spec["channels"]["optional"]["messages"]
        assert "none_type" not in channel_messages
        for ref in refs:
            assert ref.rsplit("/", 1)[1] in channel_messages

    def test_operation_with_list_output_type(self) -> None:
        """Test operation creation with list output type."""

        class ListMessage(BaseMessage):
            action: Literal["list_input"] = "list_input"
            payload: str

        class ListConsumer(AsyncJsonWebsocketConsumer):
            @ws_handler(output_type=[DummyResponse, SecondResponse, ThirdResponse])
            async def handle_list(self, message: ListMessage) -> None:
                pass

        route = RouteInfo(
            path="/ws/list",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=ListConsumer,
        )

        generator = AsyncAPIGenerator([route])
        generator.build_channels()
        generator.build_operations()

        # Should have operation
        assert len(generator.operations) > 0
        operation = list(generator.operations.values())[0]

        # Should have reply with multiple messages for list output type
        assert "reply" in operation
        assert "messages" in operation["reply"]
        assert len(operation["reply"]["messages"]) == 3

        # Each message should be a $ref
        for msg in operation["reply"]["messages"]:
            assert "$ref" in msg

    def test_operation_with_tuple_output_type(self) -> None:
        """Test operation creation with tuple output type."""

        class TupleMessage(BaseMessage):
            action: Literal["tuple_input"] = "tuple_input"
            payload: str

        class TupleConsumer(AsyncJsonWebsocketConsumer):
            @ws_handler(output_type=(DummyResponse, SecondResponse))
            async def handle_tuple(self, message: TupleMessage) -> None:
                pass

        route = RouteInfo(
            path="/ws/tuple",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=TupleConsumer,
        )

        generator = AsyncAPIGenerator([route])
        generator.build_channels()
        generator.build_operations()

        # Should have operation
        assert len(generator.operations) > 0
        operation = list(generator.operations.values())[0]

        # Should have reply with multiple messages for tuple output type
        assert "reply" in operation
        assert "messages" in operation["reply"]
        assert len(operation["reply"]["messages"]) == 2

        # Each message should be a $ref
        for msg in operation["reply"]["messages"]:
            assert "$ref" in msg

    def test_event_handler_with_list_output_type(self) -> None:
        """Test event handler with list output type."""

        class EventConsumerWithList(AsyncJsonWebsocketConsumer):
            @ws_handler
            async def handle_test(self, message: DummyMessage) -> None:
                pass

            @event_handler(output_type=[DummyResponse, SecondResponse])
            async def handle_event_with_list(self, event: DummyEvent) -> None:
                pass

        route = RouteInfo(
            path="/ws/event_list",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=EventConsumerWithList,
        )

        generator = AsyncAPIGenerator([route])
        generator.build_channels()
        generator.build_operations()

        # Find the event handler operation (action: send)
        event_operation = None
        for op in generator.operations.values():
            if op["action"] == "send":
                event_operation = op
                break

        assert event_operation is not None

        # Should have messages for event handler with list output type
        assert "messages" in event_operation
        assert len(event_operation["messages"]) == 2

        # Each message should be a $ref
        for msg in event_operation["messages"]:
            assert "$ref" in msg

    def test_camelization_disabled_by_default(self) -> None:
        """Test that camelization is disabled by default and keeps snake_case."""

        @channel(name="test_channel")
        class DefaultConsumer(AsyncJsonWebsocketConsumer):
            @ws_handler
            async def handle_test(self, message: DummyMessage) -> None:
                pass

        route = RouteInfo(
            path="/ws/test",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=DefaultConsumer,
        )

        spec = AsyncAPIGenerator([route]).generate()

        # Should keep snake_case when disabled
        assert "test_channel" in spec["channels"]
        assert "testChannel" not in spec["channels"]

    def test_camelization_enabled(self) -> None:
        """Test comprehensive camelization when enabled."""

        # Create schema with snake_case properties
        class UserPayload(BaseModel):
            first_name: str
            last_name: str
            user_id: int

        class UserRegistrationMessage(BaseMessage):
            action: Literal["user_registration"] = "user_registration"
            payload: UserPayload

        class RegistrationCompleteMessage(BaseMessage):
            action: Literal["registration_complete"] = "registration_complete"
            payload: dict[str, Any]

        @channel(name="user_registration_channel", tags=["user_auth"])
        class UserRegistrationConsumer(AsyncJsonWebsocketConsumer):
            @ws_handler
            async def handle_user_registration(
                self, message: UserRegistrationMessage
            ) -> RegistrationCompleteMessage:
                return RegistrationCompleteMessage(payload={"success": True})

        route = RouteInfo(
            path="/ws/user_registration",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=UserRegistrationConsumer,
        )

        spec = AsyncAPIGenerator([route], camelize=True).generate()

        # Channel names camelized
        assert "userRegistrationChannel" in spec["channels"]
        assert all("_" not in name for name in spec["channels"].keys())

        # Channel message keys camelized
        channel_messages = spec["channels"]["userRegistrationChannel"]["messages"]
        assert all("_" not in key for key in channel_messages.keys())

        # Operation names camelized
        assert "handleUserRegistration" in spec["operations"]
        assert all("_" not in name for name in spec["operations"].keys())

        # Component message keys camelized
        assert all("_" not in key for key in spec["components"]["messages"].keys())

        # Schema keys should be preserved (class names in PascalCase)
        schema_keys = list(spec["components"]["schemas"].keys())
        assert "UserPayload" in schema_keys
        assert "UserRegistrationMessage" in schema_keys
        assert "RegistrationCompleteMessage" in schema_keys

        # Schema properties camelized
        for schema in spec["components"]["schemas"].values():
            if "properties" in schema:
                assert all("_" not in prop for prop in schema["properties"].keys())
                # Required fields camelized
                if "required" in schema:
                    assert all("_" not in field for field in schema["required"])

        # $ref paths camelized
        for channel_spec in spec["channels"].values():
            if "messages" in channel_spec:
                for msg_ref in channel_spec["messages"].values():
                    # Extract component names from ref (skip keywords)
                    parts = [
                        p
                        for p in msg_ref["$ref"].split("/")
                        if p
                        not in [
                            "#",
                            "channels",
                            "messages",
                            "components",
                            "schemas",
                            "",
                        ]
                    ]
                    assert all("_" not in part for part in parts)

        for operation in spec["operations"].values():
            if "channel" in operation:
                parts = [
                    p
                    for p in operation["channel"]["$ref"].split("/")
                    if p not in ["#", "channels", ""]
                ]
                assert all("_" not in p for p in parts)

    def test_passthrough_events_generate_operations(self) -> None:
        """Test that passthrough_events generate proper AsyncAPI operations."""

        class PassthroughEvent(BaseMessage):
            action: Literal["item_created"] = "item_created"
            payload: str

        class AnotherPassthroughEvent(BaseMessage):
            action: Literal["item_deleted"] = "item_deleted"
            payload: str

        @channel(name="passthrough_channel")
        class PassthroughConsumer(AsyncJsonWebsocketConsumer):
            passthrough_events = [PassthroughEvent, AnotherPassthroughEvent]

            @ws_handler
            async def handle_test(self, message: DummyMessage) -> None:
                pass

        route = RouteInfo(
            path="/ws/passthrough",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=PassthroughConsumer,
        )

        generator = AsyncAPIGenerator([route])
        spec = generator.generate()

        # Should have operations for passthrough events
        operations = spec["operations"]

        # Passthrough events generate send operations
        passthrough_ops = {
            name: op for name, op in operations.items() if op["action"] == "send"
        }
        assert len(passthrough_ops) == 2

        # Check each passthrough operation structure
        for op in passthrough_ops.values():
            assert op["action"] == "send"
            assert op["channel"] == {"$ref": "#/channels/passthrough_channel"}
            assert "messages" in op
            assert len(op["messages"]) == 1

        # Check operation names use handle_passthrough_ prefix
        assert "handle_passthrough_passthrough_event" in operations
        assert "handle_passthrough_another_passthrough_event" in operations

        # Check description
        op = operations["handle_passthrough_passthrough_event"]
        assert op["description"] == "Passthrough handler for PassthroughEvent"

        # Passthrough event messages should appear in channel messages
        channel_spec = spec["channels"]["passthrough_channel"]
        assert "passthrough_event" in channel_spec["messages"]
        assert "another_passthrough_event" in channel_spec["messages"]

        # Messages should be in components
        assert "passthrough_event" in spec["components"]["messages"]
        assert "another_passthrough_event" in spec["components"]["messages"]

    def test_emits_documents_what_the_consumer_pushes(self) -> None:
        class WelcomeMessage(BaseMessage):
            action: Literal["welcome"] = "welcome"
            payload: str

        class EmitsMixin:
            emits: ClassVar[list[type[BaseMessage]]] = [WelcomeMessage]

        @channel(name="news")
        class NewsConsumer(EmitsMixin, AsyncJsonWebsocketConsumer):  # type: ignore[misc]
            emits = [DummyResponse]

            @ws_handler
            async def handle_test(self, message: DummyMessage) -> None:
                pass

        route = RouteInfo(
            path="/ws/news",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=NewsConsumer,
        )
        spec = AsyncAPIGenerator([route]).generate()

        assert spec["operations"]["news_emits"] == {
            "action": "send",
            "channel": {"$ref": "#/channels/news"},
            "description": "",
            "summary": "Messages the server pushes",
            "messages": [
                {"$ref": "#/channels/news/messages/dummy_response"},
                {"$ref": "#/channels/news/messages/welcome_message"},
            ],
        }
        assert {"dummy_response", "welcome_message"} <= set(
            spec["channels"]["news"]["messages"]
        )
        assert NewsConsumer.outgoing_message_adapter.validate_python(
            {"action": "welcome", "payload": "hi"}
        ) == WelcomeMessage(payload="hi")

    def test_passthrough_events_with_explicit_handler_override(self) -> None:
        """Test that explicit @event_handler overrides passthrough in AsyncAPI."""

        class OverrideEvent(BaseMessage):
            action: Literal["override_event"] = "override_event"
            payload: str

        class OverrideResponse(BaseMessage):
            action: Literal["override_response"] = "override_response"
            payload: str

        class MixedConsumer(AsyncJsonWebsocketConsumer):
            passthrough_events = [OverrideEvent]

            @ws_handler
            async def handle_test(self, message: DummyMessage) -> None:
                pass

            @event_handler
            async def handle_override_event(
                self, event: OverrideEvent
            ) -> OverrideResponse:
                return OverrideResponse(payload="custom")

        route = RouteInfo(
            path="/ws/mixed",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=MixedConsumer,
        )

        generator = AsyncAPIGenerator([route])
        spec = generator.generate()

        # The explicit handler should win
        send_ops = {
            name: op
            for name, op in spec["operations"].items()
            if op["action"] == "send"
        }
        assert len(send_ops) == 1
        # Should use the explicit handler's action name, not passthrough
        assert "handle_override_event" in send_ops


class TestAsyncAPIGeneratorIntegration:
    """Test AsyncAPI generator integration with real consumers."""

    def test_full_generation_with_documented_consumer(self) -> None:
        """Test full spec generation with well-documented consumer."""
        route = RouteInfo(
            path="/ws/chat/{room_id}",
            handler=Mock(),
            base_url="wss://api.example.com",
            path_params={"room_id": "str"},
            consumer=DummyConsumer,
        )

        generator = AsyncAPIGenerator(
            routes=[route],
            title="Chat API",
            version="1.0.0",
            description="WebSocket API for chat functionality",
        )

        spec = generator.generate()

        # Validate overall structure
        assert spec["asyncapi"] == "3.0.0"
        assert spec["info"]["title"] == "Chat API"
        assert spec["info"]["version"] == "1.0.0"
        assert spec["info"]["description"] == "WebSocket API for chat functionality"

        # Should have server information
        assert "servers" in spec
        assert len(spec["servers"]) == 1

        # Should have channels with path parameters
        assert len(spec["channels"]) == 1
        channel_name = list(spec["channels"].keys())[0]
        channel = spec["channels"][channel_name]

        # Should have path parameters
        assert "room_id" in channel["parameters"]
        assert "description" in channel["parameters"]["room_id"]

        # Should have operations
        assert len(spec["operations"]) > 0

    def test_generation_with_multiple_consumers(self) -> None:
        """Test generation with multiple different consumers."""

        class ChatMessage(BaseMessage):
            action: Literal["chat"] = "chat"
            payload: str

        class NotificationMessage(BaseMessage):
            action: Literal["notification"] = "notification"
            payload: dict[str, Any]

        @channel(name="chat", description="Chat channel")
        class ChatConsumer(AsyncJsonWebsocketConsumer):
            @ws_handler
            async def handle_chat(self, message: ChatMessage) -> None:
                pass

        @channel(name="notifications", description="Notification channel")
        class NotificationConsumer(AsyncJsonWebsocketConsumer):
            @ws_handler
            async def handle_notification(self, message: NotificationMessage) -> None:
                pass

        routes = [
            RouteInfo(
                path="/ws/chat",
                handler=Mock(),
                base_url="ws://localhost:8000",
                consumer=ChatConsumer,
            ),
            RouteInfo(
                path="/ws/notifications",
                handler=Mock(),
                base_url="ws://localhost:8000",
                consumer=NotificationConsumer,
            ),
        ]

        generator = AsyncAPIGenerator(routes)
        spec = generator.generate()

        # Should have two channels
        assert len(spec["channels"]) == 2

        # Should have operations for both consumers
        assert len(spec["operations"]) > 0

        # Channel names should reflect the @channel decorator names
        channel_names = list(spec["channels"].keys())
        assert "chat" in channel_names
        assert "notifications" in channel_names

    def test_generation_with_event_handlers(self) -> None:
        """Test generation including event handlers."""

        class EventMessage(BaseMessage):
            action: Literal["user_joined"] = "user_joined"
            payload: dict[str, str]

        class EventConsumer(AsyncJsonWebsocketConsumer):
            @ws_handler
            async def handle_test(self, message: DummyMessage) -> None:
                pass

            @event_handler
            async def handle_user_joined(self, event: EventMessage) -> None:
                pass

        route = RouteInfo(
            path="/ws/events",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=EventConsumer,
        )

        generator = AsyncAPIGenerator([route])
        spec = generator.generate()

        # Should have operations for both ws_handler and event_handler
        operations = spec["operations"]
        operation_names = list(operations.keys())

        # Should have both send/receive for ws_handler and operations for event_handler
        assert len(operation_names) > 0

    def test_spec_serialization(self) -> None:
        """Test that generated spec can be JSON serialized."""
        import json

        route = RouteInfo(
            path="/ws/test",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=DummyConsumer,
        )

        generator = AsyncAPIGenerator([route])
        spec = generator.generate()

        # Should be JSON serializable without errors
        json_str = json.dumps(spec)
        assert isinstance(json_str, str)

        # Should be able to deserialize back
        deserialized = json.loads(json_str)
        assert deserialized["asyncapi"] == "3.0.0"


class TestAsyncAPIGeneratorErrorHandling:
    """Test error handling in AsyncAPI generator."""

    def test_generation_with_invalid_consumer(self) -> None:
        """Test generation with consumer that has no message handlers."""

        class EmptyConsumer(AsyncJsonWebsocketConsumer):
            """Consumer with no handlers."""

            pass

        route = RouteInfo(
            path="/ws/test",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=EmptyConsumer,
        )

        generator = AsyncAPIGenerator([route])

        # Should handle gracefully and not crash
        spec = generator.generate()
        assert isinstance(spec, dict)
        assert "asyncapi" in spec
        # Should still have channel but no operations
        assert len(spec["channels"]) == 1
        assert len(spec["operations"]) == 0

    def test_generation_with_minimal_route(self) -> None:
        """Test generation with minimal route information."""

        class MinimalConsumer(AsyncJsonWebsocketConsumer):
            """Consumer with minimal setup."""

            @ws_handler
            async def handle_minimal(self, message: DummyMessage) -> None:
                pass

        route = RouteInfo(
            path="/ws/minimal",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=MinimalConsumer,
        )

        generator = AsyncAPIGenerator([route])
        spec = generator.generate()

        # Should still generate spec
        assert spec["asyncapi"] == "3.0.0"
        assert len(spec["channels"]) >= 1  # Should have at least one channel

    def test_generation_with_malformed_route(self) -> None:
        """Test generation with malformed route information."""
        route = RouteInfo(
            path="", handler=None, base_url="", consumer=DummyConsumer  # Empty path
        )

        generator = AsyncAPIGenerator([route])

        # Should handle gracefully
        spec = generator.generate()
        assert isinstance(spec, dict)

    def test_reply_messages_carry_correlation_id(self) -> None:
        """Request and reply messages point at the shared `ref` correlation id."""
        route = RouteInfo(
            path="/ws/test",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=DummyConsumer,
        )

        for camelize in (False, True):
            spec = AsyncAPIGenerator([route], camelize=camelize).generate()
            components = spec["components"]
            assert components["correlationIds"] == {
                "ref": {
                    "description": (
                        "A reply carries the `ref` of the request it answers."
                    ),
                    "location": "$message.payload#/ref",
                }
            }
            correlated = {
                name
                for name, message in components["messages"].items()
                if message.get("correlationId")
                == {"$ref": "#/components/correlationIds/ref"}
            }
            assert correlated == (
                {"dummyMessage", "dummyResponse"}
                if camelize
                else {"dummy_message", "dummy_response"}
            )

    def test_no_correlation_ids_without_replies(self) -> None:
        """A spec without request/reply operations has no correlationIds."""
        route = RouteInfo(
            path="/ws/simple",
            handler=Mock(),
            base_url="ws://localhost:8000",
            consumer=UndocumentedConsumer,
        )
        spec = AsyncAPIGenerator([route]).generate()
        assert "correlationIds" not in spec["components"]
