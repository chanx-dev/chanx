"""
Settings configuration system for chanx.

This module provides a flexible configuration system for chanx, allowing
settings to be defined with defaults in a dataclass and overridden through
Django settings. It handles importing string references, reloading when settings
change, and providing type-safe access to configuration values.
"""

import dataclasses
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, cast

from django.conf import settings
from django.core.signals import setting_changed
from rest_framework.settings import APISettings

from chanx.core.errors import ErrorFormat


@dataclass
class MySetting:
    """
    Configuration settings for chanx websocket framework.

    This dataclass defines all available configuration options with their default values.
    These settings can be overridden through Django's settings with the CHANX dictionary.

    Attributes:
        MESSAGE_ACTION_KEY: Key name for action field in messages (default: "action")
        SEND_COMPLETION: Whether to send completion messages after processing (default: False)
        SEND_MESSAGE_IMMEDIATELY: Whether to yield control after sending messages (default: True)
        SEND_AUTHENTICATION_MESSAGE: Whether to send auth status after connection (default: True)
        CAMELIZE: Whether to convert keys to camelCase in messages (default: False)
        ERROR_FORMAT: Shape of error payloads, "standard" or "pydantic" (default: "standard")
        LOG_WEBSOCKET_MESSAGE: Whether to log websocket messages (default: False)
        LOG_IGNORED_ACTIONS: Message actions that should not be logged (default: empty list)
        WEBSOCKET_BASE_URL: WebSocket URL for overriding (default: None)
        ASYNCAPI_TITLE: Title for generated AsyncAPI documentation (default: "AsyncAPI Documentation")
        ASYNCAPI_DESCRIPTION: Description for generated AsyncAPI documentation (default: "")
        ASYNCAPI_VERSION: Version for generated AsyncAPI documentation (default: "1.0.0")
        ASYNCAPI_SERVER_URL: Server URL for AsyncAPI documentation (default: None)
        ASYNCAPI_SERVER_PROTOCOL: Server protocol for AsyncAPI documentation (default: None)
        ASYNCAPI_SERVERS: AsyncAPI Server Objects by name, replacing SERVER_URL/PROTOCOL (default: None)
        ASYNCAPI_SECURITY_SCHEMES: AsyncAPI Security Scheme Objects by name (default: None)
        ASYNCAPI_DOCS_JS_URL: Docs page script URL or static path (default: pinned CDN)
        ASYNCAPI_DOCS_CSS_URL: Docs page stylesheet URL or static path (default: pinned CDN)
        ASYNCAPI_DOCS_JS_INTEGRITY: SRI hash for the script (default: pinned hash for the CDN URL)
        ASYNCAPI_DOCS_CSS_INTEGRITY: SRI hash for the stylesheet (default: pinned hash for the CDN URL)
        user_settings: Internal field used by APISettings (default: empty dict)
    """

    MESSAGE_ACTION_KEY: str = "action"
    SEND_COMPLETION: bool = False
    SEND_MESSAGE_IMMEDIATELY: bool = True
    SEND_AUTHENTICATION_MESSAGE: bool = True
    CAMELIZE: bool = False
    ERROR_FORMAT: ErrorFormat = "standard"

    LOG_WEBSOCKET_MESSAGE: bool = False
    LOG_IGNORED_ACTIONS: Iterable[str] = dataclasses.field(default_factory=list[str])

    WEBSOCKET_BASE_URL: str | None = None

    # AsyncAPI documentation settings
    ASYNCAPI_TITLE: str = "AsyncAPI Documentation"
    ASYNCAPI_DESCRIPTION: str = ""
    ASYNCAPI_VERSION: str = "1.0.0"
    ASYNCAPI_SERVER_URL: str | None = None
    ASYNCAPI_SERVER_PROTOCOL: str | None = None
    ASYNCAPI_SERVERS: dict[str, dict[str, Any]] | None = None
    ASYNCAPI_SECURITY_SCHEMES: dict[str, dict[str, Any]] | None = None
    ASYNCAPI_DOCS_JS_URL: str | None = None
    ASYNCAPI_DOCS_CSS_URL: str | None = None
    ASYNCAPI_DOCS_JS_INTEGRITY: str | None = None
    ASYNCAPI_DOCS_CSS_INTEGRITY: str | None = None

    # Add this field to satisfy the type checker
    # It will be used by APISettings but isn't part of the real dataclass structure
    user_settings: dict[str, Any] = dataclasses.field(default_factory=dict[str, Any])


IMPORT_STRINGS = ()


def create_api_settings_from_model(
    model_class: type,
    import_strings: tuple[str, ...],
    override_value: dict[str, Any] | None = None,
) -> MySetting:
    """
    Create an APISettings instance from a dataclass model.

    This function creates a DRF APISettings instance using the fields and default
    values from a provided dataclass. It allows for settings to be overridden through
    Django settings or an explicit override dictionary.

    Args:
        model_class: The dataclass type to extract default settings from
        import_strings: Tuple of setting names that should be imported as Python paths
        override_value: Optional dictionary of override values, otherwise uses settings.CHANX

    Returns:
        An APISettings instance with the model_class's type, containing all settings
    """
    # Get user settings from Django settings
    user_settings = getattr(settings, "CHANX", override_value)

    # Get defaults from dataclass fields
    defaults_dict = {}
    for field in dataclasses.fields(model_class):
        if field.name.startswith("_"):
            continue

        # Handle both regular defaults and default_factory
        if field.default is not dataclasses.MISSING:
            defaults_dict[field.name] = field.default
        elif field.default_factory is not dataclasses.MISSING:
            defaults_dict[field.name] = field.default_factory()
    # Create APISettings instance
    api_settings = APISettings(
        user_settings=user_settings,  # type: ignore
        defaults=defaults_dict,  # type: ignore
        import_strings=import_strings,
    )

    return cast(MySetting, api_settings)


chanx_settings = create_api_settings_from_model(MySetting, IMPORT_STRINGS)


def reload_api_settings(*args: Any, **kwargs: Any) -> None:
    """
    Reload API settings when Django settings are changed.

    This function is connected to Django's setting_changed signal and recreates
    the chanx_settings object when the CHANX setting is modified.

    Args:
        *args: Variable arguments passed by the signal
        **kwargs: Keyword arguments passed by the signal, including 'setting' and 'value'
    """
    global chanx_settings  # noqa

    setting, value = kwargs["setting"], kwargs["value"]
    if setting == "CHANX":
        chanx_settings = create_api_settings_from_model(
            MySetting, IMPORT_STRINGS, value
        )


setting_changed.connect(reload_api_settings)  # pyright: ignore[reportUnknownMemberType]
