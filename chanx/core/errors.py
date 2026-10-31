"""
Standard error payloads: RFC 9457 problem details, the same in every chanx implementation.

Validation failures add ``errors``, one per failure, with the JSON Schema ``keyword``
that failed and a JSON Pointer into the frame. See docs/protocol.rst.
"""

from collections.abc import Sequence
from contextvars import ContextVar
from enum import StrEnum
from typing import Any, Literal, NotRequired, TypedDict, cast

import humps
from pydantic import ValidationError
from pydantic_core import ErrorDetails

ErrorFormat = Literal["standard", "pydantic"]

ERROR_TYPE_BASE = "https://chanx.dev/errors/"

# The frame being validated, set by the consumer: locations are checked against it.
current_input: ContextVar[Any] = ContextVar("chanx_current_input", default=None)


class ErrorType(StrEnum):
    """Problem type URIs an ``error`` frame can carry."""

    VALIDATION_FAILED = ERROR_TYPE_BASE + "validation-failed"
    INVALID_JSON = ERROR_TYPE_BASE + "invalid-json"
    HANDLER_FAILED = ERROR_TYPE_BASE + "handler-failed"
    INTERNAL_ERROR = ERROR_TYPE_BASE + "internal-error"
    UNKNOWN_TOPIC = ERROR_TYPE_BASE + "unknown-topic"
    UNAUTHORIZED = ERROR_TYPE_BASE + "unauthorized"
    NOT_SUBSCRIBED = ERROR_TYPE_BASE + "not-subscribed"


TITLES: dict[ErrorType, str] = {
    ErrorType.VALIDATION_FAILED: "Message failed validation",
    ErrorType.INVALID_JSON: "Frame is not valid JSON",
    ErrorType.HANDLER_FAILED: "Message handler failed",
    ErrorType.INTERNAL_ERROR: "Message could not be processed",
    ErrorType.UNKNOWN_TOPIC: "Unknown topic",
    ErrorType.UNAUTHORIZED: "Subscription not allowed",
    ErrorType.NOT_SUBSCRIBED: "Not subscribed to topic",
}


class ValidationFailure(TypedDict):
    """One validation failure; ``property`` names the member a ``required`` lacks."""

    keyword: str
    pointer: str
    detail: str
    property: NotRequired[str | int]


class ProblemDetails(TypedDict):
    """An ``error`` frame's payload in the standard format (RFC 9457)."""

    type: str
    title: str
    detail: str
    status: NotRequired[int]
    instance: NotRequired[str]
    errors: NotRequired[list[ValidationFailure]]


# Pydantic error types mapped to the JSON Schema keyword that fails.
_KEYWORDS: dict[str, str] = {
    "missing": "required",
    "union_tag_not_found": "required",
    "union_tag_invalid": "enum",
    "literal_error": "enum",
    "enum": "enum",
    "string_too_short": "minLength",
    "string_too_long": "maxLength",
    "string_pattern_mismatch": "pattern",
    "greater_than_equal": "minimum",
    "greater_than": "exclusiveMinimum",
    "less_than_equal": "maximum",
    "less_than": "exclusiveMaximum",
    "multiple_of": "multipleOf",
    "too_short": "minItems",
    "too_long": "maxItems",
    "extra_forbidden": "additionalProperties",
    "uuid_parsing": "format",
    "uuid_version": "format",
    "url_parsing": "format",
    "url_scheme": "format",
    "url_syntax_violation": "format",
    "url_too_long": "format",
    "date_parsing": "format",
    "date_from_datetime_parsing": "format",
    "datetime_parsing": "format",
    "datetime_from_date_parsing": "format",
    "time_parsing": "format",
    "time_delta_parsing": "format",
}

# Types (int_type, string_type, int_parsing, none_required, ...) fail on "type".
_TYPE_SUFFIXES = ("_type", "_parsing", "_from_float")


def problem(
    type_: ErrorType, detail: str, errors: list[ValidationFailure] | None = None
) -> ProblemDetails:
    """Build an error payload, also for handlers that send their own."""
    payload: ProblemDetails = {
        "type": str(type_),
        "title": TITLES[type_],
        "detail": detail,
    }
    if errors is not None:
        payload["errors"] = errors
    return payload


def keyword_for(error_type: str) -> str:
    """The JSON Schema keyword behind a Pydantic error type, or ``custom``."""
    if error_type in _KEYWORDS:
        return _KEYWORDS[error_type]
    if error_type == "none_required" or error_type.endswith(_TYPE_SUFFIXES):
        return "type"
    return "custom"


def json_pointer(path: Sequence[str | int]) -> str:
    """Encode path segments as an RFC 6901 JSON Pointer."""
    return "".join("/" + str(seg).replace("~", "~0").replace("/", "~1") for seg in path)


def validation_problem(
    error: ValidationError, *, discriminator: str, camelize: bool
) -> ProblemDetails:
    """Convert a ValidationError into a problem; a JSON decode error is invalid-json."""
    details = error.errors(include_url=False, include_input=False)
    if details and all(d["type"] == "json_invalid" for d in details):
        return problem(ErrorType.INVALID_JSON, details[0]["msg"])

    data = current_input.get()
    errors = [_error_item(d, data, discriminator, camelize) for d in details]
    count = len(errors)
    detail = f"{count} validation error{'' if count == 1 else 's'}"
    return problem(ErrorType.VALIDATION_FAILED, detail, errors)


def instance_path(
    loc: Sequence[str | int], data: Any
) -> tuple[list[str | int], str | int | None]:
    """
    Follow loc through the data, keeping only segments that exist there.

    Pydantic adds union member labels ("int", "Circle", a discriminator tag) and
    "[key]" to loc; they name nothing in the data, so they are dropped. Returns the
    path and, when the last segment is absent from an object, that member's name.
    """
    path: list[str | int] = []
    node: Any = data
    last = len(loc) - 1
    for index, seg in enumerate(loc):
        members = cast(dict[str | int, Any], node) if isinstance(node, dict) else None
        items = cast(list[object], node) if isinstance(node, list) else None
        if members is not None and seg in members:
            node = members[seg]
        elif items is not None and isinstance(seg, int) and seg < len(items):
            node = items[seg]
        elif index == last and members is not None:
            return path, seg
        else:
            continue
        path.append(seg)
    return path, None


def _error_item(
    detail: ErrorDetails, data: Any, discriminator: str, camelize: bool
) -> ValidationFailure:
    """Convert one Pydantic error into an entry of the ``errors`` list."""
    error_type = detail["type"]
    missing: str | int | None = None
    if error_type == "union_tag_not_found":
        path: list[str | int] = []
        missing = discriminator
    elif error_type == "union_tag_invalid":
        path = [discriminator]
    else:
        path, absent = instance_path(detail["loc"], data)
        if error_type == "missing":
            missing = absent
    if camelize:
        path = [humps.camelize(seg) if isinstance(seg, str) else seg for seg in path]
        if isinstance(missing, str):
            missing = humps.camelize(missing)

    item: ValidationFailure = {
        "keyword": keyword_for(error_type),
        "pointer": json_pointer(path),
        "detail": detail["msg"],
    }
    if missing is not None:
        item["property"] = missing
    return item
