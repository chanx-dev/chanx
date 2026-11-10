"""Path parameters are found in every route style, and rendered as {name} for AsyncAPI."""

from unittest.mock import Mock

from chanx.channels.websocket import AsyncJsonWebsocketConsumer
from chanx.routing.discovery import RouteInfo
from chanx.routing.patterns import extract_path_parameters


class _Consumer(AsyncJsonWebsocketConsumer):
    """A consumer with no handlers, for a route that is only read."""


def test_typed_django_parameter() -> None:
    assert extract_path_parameters("ws/room/<int:room_id>/") == {"room_id": "int"}


def test_bare_django_parameter_defaults_to_str() -> None:
    assert extract_path_parameters("ws/<lang>/notifications/") == {"lang": "str"}


def test_regex_group_is_not_also_read_as_a_django_parameter() -> None:
    assert extract_path_parameters(r"ws/(?P<room>\w+)/") == {"room": r"\w+"}


def test_parameters_across_a_whole_prefixed_path() -> None:
    assert extract_path_parameters("ws/<lang>/rooms/<int:room_id>/") == {
        "lang": "str",
        "room_id": "int",
    }


def test_channel_path_renders_bare_and_typed_django_parameters() -> None:
    route = RouteInfo(
        path="ws/<lang>/rooms/<int:room_id>/",
        handler=Mock(),
        base_url="ws://localhost",
        path_params={"lang": "str", "room_id": "int"},
        consumer=_Consumer,
    )
    assert route.channel_path == "/ws/{lang}/rooms/{room_id}/"


def test_channel_path_is_absolute_without_parameters() -> None:
    route = RouteInfo(
        path="ws/notifications",
        handler=Mock(),
        base_url="ws://localhost",
        consumer=_Consumer,
    )
    assert route.channel_path == "/ws/notifications"
