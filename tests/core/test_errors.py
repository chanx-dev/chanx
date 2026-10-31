"""Tests for the standard error payload helpers."""

from typing import Any

import pytest
from chanx.core.errors import instance_path, json_pointer, keyword_for


@pytest.mark.parametrize(
    "error_type, keyword",
    [
        ("missing", "required"),
        ("int_type", "type"),
        ("int_parsing", "type"),
        ("int_from_float", "type"),
        ("none_required", "type"),
        ("literal_error", "enum"),
        ("string_too_short", "minLength"),
        ("greater_than", "exclusiveMinimum"),
        ("too_long", "maxItems"),
        ("extra_forbidden", "additionalProperties"),
        ("datetime_parsing", "format"),
        ("value_error", "custom"),
        ("assertion_error", "custom"),
    ],
)
def test_keyword_for(error_type: str, keyword: str) -> None:
    assert keyword_for(error_type) == keyword


def test_json_pointer_escapes_tilde_and_slash() -> None:
    assert json_pointer([]) == ""
    assert json_pointer(["payload", "items", 0, "a/b~c"]) == "/payload/items/0/a~1b~0c"


@pytest.mark.parametrize(
    "loc, data, expected",
    [
        (
            ("echo", "payload", "text"),
            {"payload": {"text": 1}},
            (["payload", "text"], None),
        ),
        (("echo", "payload", "text"), {"payload": {}}, (["payload"], "text")),
        (("v", "int"), {"v": []}, (["v"], None)),
        (("s", "Circle", "r"), {"s": {"r": "x"}}, (["s", "r"], None)),
        (("s", "Square", "side"), {"s": {"r": "x"}}, (["s"], "side")),
        (("scores", "a", "[key]"), {"scores": {"a": 1}}, (["scores", "a"], None)),
        (("items", 1, "n"), {"items": [{}, {"n": "x"}]}, (["items", 1, "n"], None)),
    ],
)
def test_instance_path_drops_pydantic_labels(
    loc: tuple[str | int, ...], data: Any, expected: tuple[list[str | int], Any]
) -> None:
    assert instance_path(loc, data) == expected
