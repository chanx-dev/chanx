"""Tests for FastAPI route discovery functionality."""

from unittest.mock import Mock

from chanx.fast_channels.discovery import FastAPIRouteDiscovery
from chanx.routing.discovery import RouteInfo
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.websockets import WebSocket


class TestFastAPIRouteDiscovery:
    """Test FastAPI route discovery implementation."""

    def test_init(self) -> None:
        """Test FastAPIRouteDiscovery initialization."""
        app = Starlette()
        discovery = FastAPIRouteDiscovery(app)
        assert discovery.app is app

    def test_discover_routes_empty_app(self) -> None:
        """Test route discovery with empty app."""
        app = Starlette()
        discovery = FastAPIRouteDiscovery(app)
        routes = discovery.discover_routes("ws://localhost:8000")
        assert routes == []

    def test_discover_websocket_routes(self) -> None:
        """Test discovery of WebSocket routes."""

        async def websocket_endpoint(websocket: WebSocket) -> None:
            pass

        app = Starlette(
            routes=[
                WebSocketRoute("/ws", websocket_endpoint),
                WebSocketRoute("/chat/{room_id}", websocket_endpoint),
            ]
        )

        discovery = FastAPIRouteDiscovery(app)
        routes = discovery.discover_routes("ws://localhost:8000")

        assert len(routes) == 2

        # Check first route
        route1 = routes[0]
        assert isinstance(route1, RouteInfo)
        assert route1.path == "/ws"
        assert route1.handler is websocket_endpoint
        assert route1.base_url == "ws://localhost:8000"
        assert route1.path_params is None

        # Check second route with path parameters
        route2 = routes[1]
        assert route2.path == "/chat/{room_id}"
        assert route2.path_params == {"room_id": "str"}

    def test_discover_routes_with_mount(self) -> None:
        """Test route discovery with mounted applications."""

        async def websocket_endpoint(websocket: WebSocket) -> None:
            pass

        sub_app = Starlette(
            routes=[
                WebSocketRoute("/chat", websocket_endpoint),
            ]
        )

        app = Starlette(
            routes=[
                Mount("/api/v1", sub_app),
                WebSocketRoute("/ws", websocket_endpoint),
            ]
        )

        discovery = FastAPIRouteDiscovery(app)
        routes = discovery.discover_routes("ws://localhost:8000")

        assert len(routes) == 2

        # Check mounted route
        mounted_route = next(r for r in routes if "/api/v1" in r.path)
        assert mounted_route.path == "/api/v1/chat"

        # Check direct route
        direct_route = next(r for r in routes if r.path == "/ws")
        assert direct_route.path == "/ws"

    def test_extract_path_params_simple(self) -> None:
        """Test path parameter extraction for simple cases."""
        app = Starlette()
        discovery = FastAPIRouteDiscovery(app)

        # No parameters
        assert discovery._extract_path_params("/ws") is None

        # Single parameter
        params = discovery._extract_path_params("/chat/{room_id}")
        assert params == {"room_id": "str"}

        # Multiple parameters
        params = discovery._extract_path_params("/chat/{room_id}/user/{user_id}")
        assert params == {"room_id": "str", "user_id": "str"}

    def test_extract_path_params_with_types(self) -> None:
        """Test path parameter extraction with type annotations."""
        app = Starlette()
        discovery = FastAPIRouteDiscovery(app)

        # Typed parameters
        params = discovery._extract_path_params("/chat/{room_id:int}")
        assert params == {"room_id": "int"}

        # Mixed typed and untyped
        params = discovery._extract_path_params("/chat/{room_id:int}/user/{user_name}")
        assert params == {"room_id": "int", "user_name": "str"}

    def test_extract_consumer_from_endpoint_with_consumer_class(self) -> None:
        """Test consumer extraction when endpoint has consumer_class attribute."""
        mock_consumer = Mock()
        mock_endpoint = Mock()
        mock_endpoint.consumer_class = mock_consumer

        app = Starlette()
        discovery = FastAPIRouteDiscovery(app)
        result = discovery._extract_consumer_from_endpoint(mock_endpoint)
        assert result is mock_consumer

    def test_extract_consumer_from_endpoint_with_chanx_consumer(self) -> None:
        """Test consumer extraction for chanx consumer instances."""
        mock_consumer_class = Mock()
        mock_consumer_class._MESSAGE_HANDLER_INFO_MAP = {}

        mock_endpoint = Mock()
        # Remove consumer_class to test the __self__ path
        if hasattr(mock_endpoint, "consumer_class"):
            delattr(mock_endpoint, "consumer_class")
        mock_endpoint.__self__ = Mock()
        mock_endpoint.__self__.__class__ = mock_consumer_class

        app = Starlette()
        discovery = FastAPIRouteDiscovery(app)
        result = discovery._extract_consumer_from_endpoint(mock_endpoint)
        assert result is mock_consumer_class

    def test_extract_consumer_from_endpoint_no_consumer(self) -> None:
        """Test consumer extraction when no consumer found."""
        mock_endpoint = Mock()
        # Remove any consumer-related attributes
        if hasattr(mock_endpoint, "consumer_class"):
            delattr(mock_endpoint, "consumer_class")

        app = Starlette()
        discovery = FastAPIRouteDiscovery(app)
        result = discovery._extract_consumer_from_endpoint(mock_endpoint)
        assert result is None

    def test_walk_routes_ignores_non_websocket_routes(self) -> None:
        """Test that non-WebSocket routes are ignored."""

        def http_handler(request: Request) -> None:
            pass

        app = Starlette(
            routes=[
                Route("/api", http_handler),
                Route("/health", http_handler, methods=["GET"]),
            ]
        )

        discovery = FastAPIRouteDiscovery(app)
        routes = discovery.discover_routes("ws://localhost:8000")

        # Should find no WebSocket routes
        assert routes == []

    def test_walk_routes_handles_app_without_routes(self) -> None:
        """Test handling of applications without routes attribute."""
        # Create a mock app without routes attribute
        mock_app = Mock(spec=[])  # spec=[] means no attributes

        discovery = FastAPIRouteDiscovery(mock_app)
        routes: list[RouteInfo] = []

        # Should not raise an exception
        discovery._walk_routes(mock_app, routes, "ws://localhost:8000")
        assert routes == []

    def test_get_websocket_application(self) -> None:
        """Test getting the WebSocket application."""
        app = Starlette()
        discovery = FastAPIRouteDiscovery(app)
        assert discovery.get_websocket_application() is app

    def test_extract_routes_from_router(self) -> None:
        """Test extracting routes from router (using walk method)."""

        async def websocket_endpoint(websocket: WebSocket) -> None:
            pass

        router = Starlette(
            routes=[
                WebSocketRoute("/ws", websocket_endpoint),
            ]
        )

        app = Starlette()
        discovery = FastAPIRouteDiscovery(app)
        routes: list[RouteInfo] = []

        discovery.extract_routes_from_router(
            router, "/api", routes, "ws://localhost:8000"
        )

        assert len(routes) == 1
        assert routes[0].path == "/api/ws"

    def test_discover_from_consumers_placeholder(self) -> None:
        """Test the placeholder _discover_from_consumers method."""
        app = Starlette()
        discovery = FastAPIRouteDiscovery(app)
        routes: list[RouteInfo] = []

        # Should not modify routes (placeholder implementation)
        discovery._discover_from_consumers(routes, "ws://localhost:8000")
        assert routes == []


def test_a_mount_prefix_parameter_is_a_route_parameter() -> None:
    async def websocket_endpoint(websocket: WebSocket) -> None:
        pass

    app = Starlette(
        routes=[
            Mount(
                "/ws/{tenant}",
                Starlette(routes=[WebSocketRoute("/chat/{room}", websocket_endpoint)]),
            )
        ]
    )

    (route,) = FastAPIRouteDiscovery(app).discover_routes("ws://localhost:8000")

    assert route.path_params == {"tenant": "str", "room": "str"}
