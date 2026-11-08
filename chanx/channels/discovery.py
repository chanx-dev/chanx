"""
Django Channels-specific route discovery implementation.

This module provides the Django Channels implementation of route discovery,
moving the Django-specific logic from the duplicated implementations.
"""

from typing import TYPE_CHECKING, Any, cast

from channels.routing import URLRouter
from django.http import HttpRequest

from chanx.channels.websocket import AsyncJsonWebsocketConsumer
from chanx.routing.discovery import RouteDiscovery, RouteInfo, expand_topic_routes
from chanx.routing.patterns import (
    extract_path_parameters,
    get_pattern_string_and_params,
)
from chanx.routing.traversal import traverse_middleware_stack
from chanx.utils.logging import logger

from .settings import chanx_settings
from .utils.asgi import get_websocket_application

if TYPE_CHECKING:
    from channels.routing import (
        _ExtendedURLPattern,  # pragma: no cover ; TYPE CHECK only
    )
else:
    _ExtendedURLPattern = Any


# Django path converter mappings to regex patterns
DJANGO_PATH_CONVERTERS = {
    "str": r"[^/]+",
    "int": r"[0-9]+",
    "slug": r"[-a-zA-Z0-9_]+",
    "uuid": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    "path": r".+",
}


class DjangoRouteDiscovery(RouteDiscovery):
    """Django Channels implementation of route discovery."""

    def discover_routes(self, base_url: str = "ws://localhost:8000") -> list[RouteInfo]:
        """
        Discover all WebSocket routes from the Django Channels application.

        Args:
            base_url: The base WebSocket URL to use for discovered routes.

        Returns:
            List of RouteInfo objects containing discovered routes.
        """
        routes: list[RouteInfo] = []

        # Get the WebSocket application
        ws_app = self.get_websocket_application()

        if ws_app:
            # Use the generic traversal function with Django-specific extraction
            traverse_middleware_stack(
                ws_app, "", routes, base_url, self.extract_routes_from_router
            )

        return expand_topic_routes(routes)

    def get_websocket_application(self) -> Any:
        """Get the Django Channels WebSocket application."""
        return get_websocket_application()

    def extract_routes_from_router(
        self,
        router: Any,
        prefix: str,
        routes: list[RouteInfo],
        base_url: str,
    ) -> None:
        """
        Extract routes from a Django URLRouter object.

        Args:
            router: The URLRouter to extract routes from.
            prefix: URL prefix accumulated so far.
            routes: List to store discovered RouteInfo objects.
            base_url: Base URL for WebSocket connections.
        """
        # Only handle URLRouter objects
        if not isinstance(router, URLRouter):
            raise TypeError(f"Expected URLRouter, got {type(router)}")

        router_routes = cast(list[_ExtendedURLPattern], router.routes)
        for route in router_routes:
            try:
                pattern, _ = get_pattern_string_and_params(route)

                # Build the full path
                full_path: str = f"{prefix}{pattern}"

                # Get the handler
                handler = route.callback

                # If it's another router, recurse into it
                if isinstance(handler, URLRouter):
                    self.extract_routes_from_router(
                        handler, full_path, routes, base_url
                    )
                else:
                    # For consumers, add to the routes list
                    consumer = cast(
                        type[AsyncJsonWebsocketConsumer], handler.consumer_class
                    )
                    routes.append(
                        RouteInfo(
                            path=full_path,
                            handler=handler,
                            base_url=base_url,
                            path_params=extract_path_parameters(full_path) or None,
                            consumer=consumer,
                        )
                    )
            except AttributeError as e:
                logger.exception(
                    f"AttributeError while parsing route: {base_url}/{prefix}. Error: {str(e)}"
                )
            except Exception as e:
                logger.exception(
                    f"Error parsing route: {base_url}/{prefix}. Error: {str(e)}"
                )

    def get_base_url(self, request: HttpRequest) -> str:
        """
        Determine the WebSocket base URL based on Django request.

        Args:
            request: The Django HTTP request object.

        Returns:
            The WebSocket base URL (ws:// or wss:// followed by domain).
        """
        if chanx_settings.WEBSOCKET_BASE_URL is not None:
            return chanx_settings.WEBSOCKET_BASE_URL

        # Get the current domain from the request
        domain: str = request.get_host()

        # Determine if we should use secure WebSockets based on the request
        is_secure: bool = request.is_secure()
        protocol: str = "wss://" if is_secure else "ws://"

        return f"{protocol}{domain}"


# Convenience function for backward compatibility
def get_websocket_routes(request: HttpRequest) -> list[RouteInfo]:
    """
    Discover all WebSocket routes from the Django Channels application.

    This is a convenience function that maintains backward compatibility
    with the previous implementation.

    Args:
        request: The HTTP request object, used to determine the current domain.
               If None, defaults to configured base URL.

    Returns:
        A list of RouteInfo objects containing path, handler, and base_url for each WebSocket route.
    """
    discovery = DjangoRouteDiscovery()
    base_url = discovery.get_base_url(request)
    return discovery.discover_routes(base_url)
