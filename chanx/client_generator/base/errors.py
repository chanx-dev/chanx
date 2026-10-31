"""The payload of a chanx error frame, for clients."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

ERROR_ACTION = "error"


class ErrorType(StrEnum):
    """Problem types a chanx server sends; branch on these."""

    VALIDATION_FAILED = "https://chanx.dev/errors/validation-failed"
    INVALID_JSON = "https://chanx.dev/errors/invalid-json"
    HANDLER_FAILED = "https://chanx.dev/errors/handler-failed"
    INTERNAL_ERROR = "https://chanx.dev/errors/internal-error"
    UNKNOWN_TOPIC = "https://chanx.dev/errors/unknown-topic"
    UNAUTHORIZED = "https://chanx.dev/errors/unauthorized"
    NOT_SUBSCRIBED = "https://chanx.dev/errors/not-subscribed"


class ValidationFailure(BaseModel):
    """One validation failure; ``property`` names the member a ``required`` lacks."""

    keyword: str
    pointer: str
    detail: str
    property: str | int | None = None


class ProblemDetails(BaseModel):
    """An error frame's payload, an RFC 9457 problem details object."""

    # RFC 9457: members a client does not know are kept, not rejected.
    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    detail: str
    status: int | None = None
    instance: str | None = None
    errors: list[ValidationFailure] | None = None


def parse_problem(payload: Any) -> ProblemDetails | None:
    """
    Read an error frame's payload as ProblemDetails.

    Returns None for a payload in another shape, such as a server using
    ``error_format = "pydantic"`` or a custom error hook.
    """
    try:
        return ProblemDetails.model_validate(payload)
    except ValidationError:
        return None
