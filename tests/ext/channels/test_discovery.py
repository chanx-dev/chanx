"""Django route discovery reads parameters from the whole path, prefixes included."""

from channels.routing import URLRouter

from chanx.channels.discovery import DjangoRouteDiscovery
from chanx.channels.routing import include, path
from chanx.routing.discovery import RouteInfo

from .test_topic import DjangoHubConsumer


def test_a_parameter_in_an_include_prefix_is_a_route_parameter() -> None:
    leaf = URLRouter([path("notifications/", DjangoHubConsumer.as_asgi())])
    router = URLRouter([path("ws/<lang>/", include(leaf))])
    routes: list[RouteInfo] = []

    DjangoRouteDiscovery().extract_routes_from_router(
        router, "", routes, "ws://localhost:8000"
    )

    (route,) = routes
    assert route.path_params == {"lang": "str"}
    assert route.channel_path == "/ws/{lang}/notifications/"
