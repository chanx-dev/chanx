"""Configuration management for chanx.

This module provides configuration utilities that work both in Django and non-Django environments.
It automatically detects if Django is being used and retrieves settings accordingly.
"""

from collections.abc import Collection
from typing import Any

from .check import IS_USING_DJANGO
from .errors import ErrorFormat


class Config:
    """Configuration class that provides default values and Django integration.

    This class defines default configuration values and automatically retrieves
    settings from Django's chanx_settings when Django is available.

    Attributes:
        send_completion: Whether to send completion messages.
        send_message_immediately: Whether to send messages immediately.
        log_websocket_message: Whether to log websocket received and sent messages.
        log_ignored_actions: Collection of action names to ignore in logs.
        camelize: Whether to camelize field names.
        discriminator_field: Field name used for message discrimination.
        send_authentication_message: Whether authenticators send their result.
        error_format: Shape of error payloads, "standard" or "pydantic".
    """

    send_completion: bool = False
    send_message_immediately: bool = True
    log_websocket_message: bool = False
    log_ignored_actions: Collection[str] = {}
    camelize: bool = False
    discriminator_field: str = "action"
    send_authentication_message: bool = True
    error_format: ErrorFormat = "standard"

    def __getattribute__(self, item: str) -> Any:
        """Get attribute value, preferring Django settings when available.

        Args:
            item: The attribute name to retrieve.

        Returns:
            The attribute value from Django settings (if Django is used) or
            the default class attribute value.
        """
        if IS_USING_DJANGO:
            from chanx.channels.settings import chanx_settings

            return getattr(chanx_settings, item.upper())

        return super().__getattribute__(item)


config = Config()
