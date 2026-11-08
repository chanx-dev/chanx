"""
Route discovery base classes and unified RouteInfo.

This module provides the abstract base class for route discovery implementations
and a unified RouteInfo dataclass that consolidates the functionality from
the previous duplicated implementations.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import Any

from chanx.core.topic import Topic
from chanx.core.websocket import ChanxWebsocketConsumerMixin


@dataclass(frozen=True)
class RouteInfo:
    """
    Unified WebSocket route information.

    This class consolidates the functionality from the previous separate RouteInfo
    implementations that were duplicated across multiple modules.

    Attributes:
        path: The URL path pattern for the WebSocket route.
        handler: The consumer or handler function for this route.
        base_url: The base WebSocket URL (e.g., ws://domain.com).
        path_params: Dictionary of path parameters with their regex patterns.
        consumer: The WebSocket consumer class (optional).
    """

    path: str
    handler: Any
    base_url: str
    consumer: type[ChanxWebsocketConsumerMixin]
    path_params: dict[str, str] | None = None
    topic: type[Topic[Any]] | None = None
    host: type[ChanxWebsocketConsumerMixin] | None = None

    @property
    def channel_path(self) -> str:
        """
        Get a channel path with {param} format for AsyncAPI specification.

        This method is used by AsyncAPI generation to create user-friendly
        path representations.
        """
        if not self.path_params:
            return self.path

        path = self.path
        for param_name, pattern in self.path_params.items():
            # Replace regex patterns with {param} format for AsyncAPI
            path = path.replace(f"(?P<{param_name}>{pattern})", f"{{{param_name}}}")
            # Also handle Django-style path parameters
            path = re.sub(
                rf"(?<!\?P)<(?:\w+:)?{param_name}>", f"{{{param_name}}}", path
            )
        return path


def expand_topic_routes(routes: list[RouteInfo]) -> list[RouteInfo]:
    """
    Document each mounted topic as its own route at the same address.

    Tools that work per consumer, AsyncAPI in particular, need one entry per
    topic. ``host`` records which consumer mounted it, so the same topic served
    from two routes stays distinguishable.
    """
    expanded: list[RouteInfo] = []
    for route in routes:
        topics = getattr(route.consumer, "topics", None)
        if not topics:
            expanded.append(route)
            continue

        # A route dedicated to one topic is that topic, not a host for it.
        standalone = getattr(route.consumer, "default_topic", None)
        if standalone is not None:
            expanded.append(replace(route, consumer=standalone, topic=standalone))
            continue

        if route.consumer._MESSAGE_HANDLER_INFO_MAP:
            expanded.append(route)

        expanded.extend(
            replace(route, consumer=topic, topic=topic, host=route.consumer)
            for topic in topics
        )

    return expanded


class RouteDiscovery(ABC):
    """
    Abstract base class for route discovery implementations.

    This class defines the interface that framework-specific route discovery
    implementations must follow. It provides a consistent API for discovering
    WebSocket routes across different frameworks.
    """

    @abstractmethod
    def discover_routes(self, base_url: str = "ws://localhost:8000") -> list[RouteInfo]:
        """
        Discover all available WebSocket routes.

        Args:
            base_url: The base WebSocket URL to use for discovered routes.

        Returns:
            List of RouteInfo objects representing discovered routes.
        """

    @abstractmethod
    def extract_routes_from_router(
        self,
        router: Any,
        prefix: str,
        routes: list[RouteInfo],
        base_url: str,
    ) -> None:
        """
        Extract routes from a router object.

        This method should be implemented by subclasses to handle
        framework-specific router objects.

        Args:
            router: The router object to extract routes from.
            prefix: URL prefix accumulated so far.
            routes: List to store discovered RouteInfo objects.
            base_url: Base URL for WebSocket connections.
        """
