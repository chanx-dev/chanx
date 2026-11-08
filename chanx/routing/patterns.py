"""
URL pattern utilities for route discovery.

This module provides utilities for extracting and processing URL patterns
from various routing frameworks, including Django Channels, FastAPI, and Starlette.
"""

import re
from typing import Any

# Regular expressions for extracting different types of path parameters

REGEX_PARAM_PATTERN = r"\(\?P<([^>]+)>([^)]+)\)"
"""Pattern for Python regex named groups like (?P<name>pattern)."""

DJANGO_PARAM_PATTERN = r"(?<!\?P)<(?:(\w+):)?(\w+)>"
"""Pattern for Django path parameters like <type:name> or <name>, not (?P<name>."""

STARLETTE_PARAM_PATTERN = r"\{(\w+)(?::(\w+))?\}"
"""Pattern for Starlette/FastAPI path parameters like {name} or {name:type}."""


def get_pattern_string_and_params(route: Any) -> tuple[str, dict[str, str] | None]:
    """
    Extract pattern string and path parameters from a route object.

    Handles different route pattern implementations to extract
    the URL pattern string and identified named path parameters.

    Supports both Django-style path parameters (<type:name>) and regex patterns.

    Args:
        route: The route object to extract pattern from.

    Returns:
        A tuple containing:
        - The cleaned URL pattern string
        - Dictionary of path parameters with their type/pattern info, or None if no parameters
    """
    # Get the pattern string
    if hasattr(route, "pattern"):
        # For URLRoute
        if hasattr(route.pattern, "pattern"):
            pattern: str = route.pattern.pattern
        else:
            # For RoutePattern
            pattern = str(route.pattern)
    else:
        pattern = str(route)

    # Extract path parameters
    path_params = extract_path_parameters(pattern)

    # Clean up the pattern string (remove ^ and $ anchors)
    pattern = pattern.replace("^", "").replace("$", "")

    return pattern, path_params if path_params else None


def extract_path_parameters(pattern: str) -> dict[str, str]:
    """
    Extract path parameters from a URL pattern string.

    Supports Django, Starlette/FastAPI, and regex-style parameters.

    Args:
        pattern: The URL pattern string to extract parameters from.

    Returns:
        Dictionary of parameter names to their types/patterns.
    """
    path_params: dict[str, str] = {}

    # First, extract Django-style path parameters: <type:name>
    django_matches = re.findall(DJANGO_PARAM_PATTERN, pattern)
    if django_matches:
        for converter_type, param_name in django_matches:
            path_params[param_name] = converter_type or "str"

    # Second, extract Starlette/FastAPI path parameters: {name} or {name:type}
    starlette_matches = re.findall(STARLETTE_PARAM_PATTERN, pattern)
    if starlette_matches:
        for param_name, converter_type in starlette_matches:
            # Only add if not already added by Django converter
            if param_name not in path_params:
                # Default to 'str' if no converter specified
                path_params[param_name] = converter_type or "str"

    # Third, extract regex-style parameters: (?P<name>pattern)
    regex_matches = re.findall(REGEX_PARAM_PATTERN, pattern)
    if regex_matches:
        for name, regex_pattern in regex_matches:
            # Only add if not already added by other converters
            if name not in path_params:
                path_params[name] = regex_pattern

    return path_params
