"""
Discovery module for chanx FastAPI integration.

This module provides utilities to discover and register chanx consumers
in FastAPI applications, similar to Django's app discovery.
"""

from typing import Any

from starlette.applications import Starlette
from starlette.routing import Mount, WebSocketRoute

from chanx.routing.discovery import RouteDiscovery, RouteInfo, expand_topic_routes


class FastAPIRouteDiscovery(RouteDiscovery):
    """FastAPI/Starlette-specific route discovery implementation."""

    def __init__(self, app: Starlette):
        self.app = app

    def discover_routes(self, base_url: str = "ws://localhost:8000") -> list[RouteInfo]:
        """
        Discover WebSocket routes from FastAPI/Starlette application.

        Args:
            base_url: Base WebSocket URL

        Returns:
            List of RouteInfo objects
        """
        routes: list[RouteInfo] = []

        if self.app:
            self._walk_routes(self.app, routes, base_url)
        else:
            # Fallback: create routes from discovered consumers
            self._discover_from_consumers(routes, base_url)

        return expand_topic_routes(routes)

    def _discover_from_consumers(self, routes: list[RouteInfo], base_url: str) -> None:
        """
        Fallback method to discover consumers without an app instance.

        This would typically scan for consumer classes and create routes,
        but for now it's a placeholder since FastAPI discovery primarily
        works with the actual app routes.
        """
        # This is a placeholder - in a real implementation, you might
        # scan for consumer classes or read from configuration
        pass

    def _walk_routes(
        self, application: Any, routes: list[RouteInfo], base_url: str, prefix: str = ""
    ) -> None:
        """
        Walk through FastAPI/Starlette routes to find WebSocket endpoints.

        Args:
            application: FastAPI app or Mount
            routes: List to append discovered routes to
            base_url: Base WebSocket URL
            prefix: Current path prefix
        """

        # Skip if application doesn't have routes (e.g., StaticFiles)
        if not hasattr(application, "routes"):
            return

        for route in application.routes:
            if isinstance(route, Mount):
                # Recursively walk mounted applications
                self._walk_routes(route.app, routes, base_url, prefix + route.path)
            elif isinstance(route, WebSocketRoute):
                # Found a WebSocket route
                full_path = prefix + route.path

                # Try to extract consumer class from the endpoint
                consumer_class = self._extract_consumer_from_endpoint(route.endpoint)

                # Extract path parameters if any
                path_params = self._extract_path_params(full_path)

                route_info = RouteInfo(
                    path=full_path,
                    handler=route.endpoint,
                    base_url=base_url,
                    path_params=path_params,
                    consumer=consumer_class,
                )

                routes.append(route_info)

    def _extract_consumer_from_endpoint(self, endpoint: Any) -> Any:
        """
        Try to extract the chanx consumer class from a WebSocket endpoint.

        Args:
            endpoint: The WebSocket endpoint function/callable

        Returns:
            Consumer class if found, None otherwise
        """
        # Check if the endpoint has a consumer_class attribute (from .as_asgi())
        if hasattr(endpoint, "consumer_class"):
            return endpoint.consumer_class

        # Check if it's a chanx consumer ASGI application
        if hasattr(endpoint, "__self__") and hasattr(endpoint.__self__, "__class__"):
            consumer_class = endpoint.__self__.__class__
            # Check if it's a chanx consumer
            if hasattr(consumer_class, "_MESSAGE_HANDLER_INFO_MAP"):
                return consumer_class

        return None

    def _extract_path_params(self, path: str) -> dict[str, str] | None:
        """
        Extract path parameters from FastAPI/Starlette path pattern.

        Args:
            path: Route path pattern (e.g., "/room/{room_name}")

        Returns:
            Dictionary of parameter names to their types, or None if no params
        """
        import re

        # Find FastAPI-style path parameters like {room_name} or {room_name:str}
        params: dict[str, str] = {}
        param_pattern = r"\{([^}:]+)(?::([^}]+))?\}"

        for match in re.finditer(param_pattern, path):
            param_name = match.group(1)
            param_type = match.group(2) or "str"  # Default to str if no type specified
            params[param_name] = param_type

        return params if params else None

    def get_websocket_application(self) -> Any:
        """Get the FastAPI WebSocket application."""
        return self.app

    def extract_routes_from_router(
        self, router: Any, prefix: str, routes: list[RouteInfo], base_url: str
    ) -> None:
        """Extract routes from FastAPI router (using the walk method instead)."""
        self._walk_routes(router, routes, base_url, prefix)
