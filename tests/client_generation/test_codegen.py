"""Tests for codegen module - discriminated union support."""

from chanx.asyncapi.type_defs import SchemaObject
from chanx.client_generator.codegen import (
    _generate_class,
    _get_discriminator_info,
    _get_python_type,
    _schema_needs_discriminator,
    generate_pydantic_code,
)

# Reusable variant schemas (simulating resolved $ref SchemaObjects)
VARIANT_A = SchemaObject(
    title="VariantA",
    type="object",
    properties={
        "kind": SchemaObject(type="string", const="a", default="a"),
        "value_a": SchemaObject(type="string"),
    },
    required=["value_a"],
)

VARIANT_B = SchemaObject(
    title="VariantB",
    type="object",
    properties={
        "kind": SchemaObject(type="string", const="b", default="b"),
        "value_b": SchemaObject(type="integer"),
    },
    required=["value_b"],
)

# AsyncAPI takes the property name on its own, not OpenAPI's object form.
DISCRIMINATOR = "kind"


class TestGetPythonTypeOneOf:
    """Test _get_python_type with oneOf schemas."""

    def test_one_of_returns_union(self) -> None:
        """oneOf with named schemas returns a union type."""
        schema = SchemaObject(oneOf=[VARIANT_A, VARIANT_B])
        assert _get_python_type(schema) == "VariantA | VariantB"

    def test_any_of_wrapping_one_of_nullable(self) -> None:
        """anyOf[{oneOf: [...]}, null] returns the union without None."""
        schema = SchemaObject(
            anyOf=[
                SchemaObject(
                    oneOf=[VARIANT_A, VARIANT_B],
                    discriminator=DISCRIMINATOR,
                ),
                SchemaObject(type="null"),
            ]
        )
        # anyOf with one non-null type + null strips the None
        assert _get_python_type(schema) == "VariantA | VariantB"


class TestGetDiscriminatorInfo:
    """Test _get_discriminator_info for both direct and nested patterns."""

    def test_direct_discriminator(self) -> None:
        """Direct oneOf + discriminator at top level."""
        schema = SchemaObject(
            oneOf=[VARIANT_A, VARIANT_B],
            discriminator=DISCRIMINATOR,
        )
        result = _get_discriminator_info(schema)
        assert result is not None
        prop_name, union_str = result
        assert prop_name == "kind"
        assert union_str == "VariantA | VariantB"

    def test_nested_discriminator_in_anyof(self) -> None:
        """Nested: anyOf contains sub-schema with oneOf + discriminator."""
        schema = SchemaObject(
            anyOf=[
                SchemaObject(
                    oneOf=[VARIANT_A, VARIANT_B],
                    discriminator=DISCRIMINATOR,
                ),
                SchemaObject(type="null"),
            ]
        )
        result = _get_discriminator_info(schema)
        assert result is not None
        prop_name, union_str = result
        assert prop_name == "kind"
        assert union_str == "VariantA | VariantB"

    def test_no_discriminator(self) -> None:
        """Plain anyOf without discriminator returns None."""
        schema = SchemaObject(
            anyOf=[
                SchemaObject(type="string"),
                SchemaObject(type="null"),
            ]
        )
        assert _get_discriminator_info(schema) is None

    def test_one_of_without_discriminator(self) -> None:
        """oneOf without discriminator returns None."""
        schema = SchemaObject(oneOf=[VARIANT_A, VARIANT_B])
        assert _get_discriminator_info(schema) is None


class TestSchemaNeedsDiscriminator:
    """Test _schema_needs_discriminator detection."""

    def test_detects_direct_discriminator(self) -> None:
        schema = SchemaObject(
            title="Payload",
            type="object",
            properties={
                "variant": SchemaObject(
                    oneOf=[VARIANT_A, VARIANT_B],
                    discriminator=DISCRIMINATOR,
                )
            },
        )
        assert _schema_needs_discriminator(schema) is True

    def test_detects_nested_discriminator(self) -> None:
        schema = SchemaObject(
            title="Payload",
            type="object",
            properties={
                "variant": SchemaObject(
                    anyOf=[
                        SchemaObject(
                            oneOf=[VARIANT_A, VARIANT_B],
                            discriminator=DISCRIMINATOR,
                        ),
                        SchemaObject(type="null"),
                    ]
                )
            },
        )
        assert _schema_needs_discriminator(schema) is True

    def test_no_discriminator(self) -> None:
        schema = SchemaObject(
            title="Payload",
            type="object",
            properties={"name": SchemaObject(type="string")},
        )
        assert _schema_needs_discriminator(schema) is False


class TestGenerateClassDiscriminatedUnion:
    """Test _generate_class with discriminated union fields."""

    def test_required_discriminated_union(self) -> None:
        """Required field generates Annotated[..., Field(discriminator=...)]."""
        schema = SchemaObject(
            title="Payload",
            type="object",
            required=["variant"],
            properties={
                "variant": SchemaObject(
                    oneOf=[VARIANT_A, VARIANT_B],
                    discriminator=DISCRIMINATOR,
                )
            },
        )
        lines = _generate_class(schema)
        code = "\n".join(lines)
        assert (
            'variant: Annotated[VariantA | VariantB, Field(discriminator="kind")]'
            in code
        )

    def test_nullable_discriminated_union(self) -> None:
        """Nullable field generates Annotated[...] | None = None."""
        schema = SchemaObject(
            title="Payload",
            type="object",
            properties={
                "variant": SchemaObject(
                    anyOf=[
                        SchemaObject(
                            oneOf=[VARIANT_A, VARIANT_B],
                            discriminator=DISCRIMINATOR,
                        ),
                        SchemaObject(type="null"),
                    ]
                )
            },
        )
        lines = _generate_class(schema)
        code = "\n".join(lines)
        assert (
            'variant: Annotated[VariantA | VariantB, Field(discriminator="kind")]'
            " | None = None" in code
        )

    def test_discriminated_union_with_default(self) -> None:
        """Field with default generates Annotated[...] = <default>."""
        schema = SchemaObject(
            title="Payload",
            type="object",
            properties={
                "variant": SchemaObject(
                    oneOf=[VARIANT_A, VARIANT_B],
                    discriminator=DISCRIMINATOR,
                    default={"kind": "a"},
                )
            },
        )
        lines = _generate_class(schema)
        code = "\n".join(lines)
        assert (
            "variant: Annotated[VariantA | VariantB,"
            ' Field(discriminator="kind")]'
            " = {'kind': 'a'}" in code
        )


class TestGeneratePydanticCodeImports:
    """Test that generate_pydantic_code adds correct imports."""

    def test_imports_annotated_and_field_for_discriminated_union(self) -> None:
        """Schemas with discriminator should import Annotated and Field."""
        schemas = [
            VARIANT_A,
            VARIANT_B,
            SchemaObject(
                title="Payload",
                type="object",
                required=["variant"],
                properties={
                    "variant": SchemaObject(
                        oneOf=[VARIANT_A, VARIANT_B],
                        discriminator=DISCRIMINATOR,
                    )
                },
            ),
        ]
        code = generate_pydantic_code(schemas)
        assert "Annotated" in code
        assert "Field" in code

    def test_no_discriminator_no_extra_imports(self) -> None:
        """Schemas without discriminator should not import Annotated or Field."""
        schemas = [
            SchemaObject(
                title="Simple",
                type="object",
                required=["name"],
                properties={"name": SchemaObject(type="string")},
            ),
        ]
        code = generate_pydantic_code(schemas)
        assert "from typing import Literal" in code
        assert "Annotated" not in code
        assert "Field" not in code


class TestDefaultFactoryFields:
    def test_optional_array_without_a_default_keeps_its_type(self) -> None:
        schema = SchemaObject(
            title="Decided",
            type="object",
            properties={
                "urls": SchemaObject(type="array", items=SchemaObject(type="string"))
            },
        )
        code = "\n".join(_generate_class(schema))
        assert "urls: list[str] = Field(default_factory=list)" in code

    def test_optional_free_form_object_gets_a_dict_factory(self) -> None:
        schema = SchemaObject(
            title="Meta",
            type="object",
            properties={"extra": SchemaObject(type="object")},
        )
        code = "\n".join(_generate_class(schema))
        assert "= Field(default_factory=dict)" in code

    def test_nullable_array_stays_nullable(self) -> None:
        schema = SchemaObject(
            title="Maybe",
            type="object",
            properties={
                "urls": SchemaObject(
                    anyOf=[
                        SchemaObject(type="array", items=SchemaObject(type="string")),
                        SchemaObject(type="null"),
                    ]
                )
            },
        )
        code = "\n".join(_generate_class(schema))
        assert "urls: list[str] | None = None" in code

    def test_field_is_imported_for_a_default_factory(self) -> None:
        schema = SchemaObject(
            title="Decided",
            type="object",
            properties={
                "urls": SchemaObject(type="array", items=SchemaObject(type="string"))
            },
        )
        code = generate_pydantic_code([schema])
        assert "from pydantic import BaseModel, Field" in code
