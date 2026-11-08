"""
Generate Pydantic model code from SchemaObject list.
"""

from typing import Any, cast

from chanx.asyncapi.type_defs import (
    AsyncAPIDocument,
    ChannelObject,
    MessageObject,
    SchemaObject,
)


def generate_pydantic_code(
    schemas: list[SchemaObject], shared_schemas: list[SchemaObject] | None = None
) -> str:
    """
    Generate Pydantic model code from list of SchemaObject instances.

    All classes inherit from BaseModel.

    Args:
        schemas: list of SchemaObject instances (already topologically sorted)

    Returns:
        Python code string with Pydantic models
    """
    lines: list[str] = []

    # Check if Any type is needed
    active_schemas = [
        s for s in schemas if not (shared_schemas and s in shared_schemas)
    ]
    needs_any = any(_schema_needs_any(schema) for schema in active_schemas)
    needs_discriminator = any(
        _schema_needs_discriminator(schema) for schema in active_schemas
    )
    needs_default_factory = any(
        _schema_needs_default_factory(schema) for schema in active_schemas
    )

    # Add imports
    typing_imports = ["Literal"]
    if needs_discriminator:
        typing_imports.insert(0, "Annotated")
    if needs_any:
        typing_imports.insert(0, "Any")
    lines.append(f"from typing import {', '.join(typing_imports)}")
    lines.append("")
    pydantic_imports = ["BaseModel"]
    if needs_discriminator or needs_default_factory:
        pydantic_imports.append("Field")
    lines.append(f"from pydantic import {', '.join(pydantic_imports)}")
    lines.append("")

    if shared_schemas:
        reused_schemas: list[str] = []
        for schema in schemas:
            if schema in shared_schemas:
                schema_class_name = getattr(schema, "title")
                reused_schemas.append(schema_class_name)

        # A channel can reuse nothing while others do, which would leave an
        # import with no names behind it.
        if reused_schemas:
            lines.append(f"from ..shared.messages import {', '.join(reused_schemas)}")

    lines.append("")

    # Generate each schema
    for schema in schemas:
        # Get schema info
        if shared_schemas and schema in shared_schemas:
            continue
        title = getattr(schema, "title", None)
        if not title or callable(title):
            continue

        lines.extend(_generate_class(schema))
        lines.append("")
        lines.append("")

    return "\n".join(lines)


def _schema_needs_any(schema: SchemaObject) -> bool:
    """
    Check if a schema uses Any type in its fields.

    Args:
        schema: SchemaObject to check

    Returns:
        True if the schema has any field with type Any or dict[str, Any]
    """
    properties: dict[str, SchemaObject] = getattr(schema, "properties", {})
    if not properties:
        return False

    for field_schema in properties.values():
        python_type = _get_python_type(field_schema)
        if "Any" in python_type:
            return True
    return False


def _get_discriminator_info(
    field_schema: SchemaObject,
) -> tuple[str, str] | None:
    """
    Extract discriminator info from a field schema.

    Handles both direct (oneOf + discriminator) and nullable
    (anyOf: [{oneOf + discriminator}, {type: null}]) patterns.

    Returns:
        (property_name, union_type_str) or None if no discriminator found.
        union_type_str is the Python union type for the oneOf members only.
    """
    # Direct: field has oneOf + discriminator at top level
    one_of = field_schema.oneOf
    discriminator = field_schema.discriminator
    if one_of and discriminator:
        types = [t for opt in one_of if (t := _get_python_type(opt)) != "None"]
        if types:
            return discriminator, " | ".join(types)

    # Nested: anyOf contains one sub-schema with oneOf + discriminator, plus null
    any_of = field_schema.anyOf
    if any_of:
        for option in any_of:
            nested_one_of = option.oneOf
            nested_disc = option.discriminator
            if nested_one_of and nested_disc:
                types = [
                    t for opt in nested_one_of if (t := _get_python_type(opt)) != "None"
                ]
                if types:
                    return nested_disc, " | ".join(types)

    return None


def _default_factory(
    field_schema: SchemaObject, is_required: bool, default_value: Any
) -> str | None:
    """Factory for an optional list/dict, whose schema has no default (default_factory)."""
    if is_required or default_value is not None:
        return None
    schema_type = getattr(field_schema, "type", None)
    if schema_type == "array":
        return "list"
    if schema_type == "object" and not getattr(field_schema, "properties", None):
        return "dict"
    return None


def _schema_needs_default_factory(schema: SchemaObject) -> bool:
    """Check if a schema has any field using a default factory."""
    properties: dict[str, SchemaObject] = getattr(schema, "properties", {})
    required = getattr(schema, "required", None) or list[str]()
    return any(
        _default_factory(fs, name in required, getattr(fs, "default", None)) is not None
        for name, fs in properties.items()
    )


def _schema_needs_discriminator(schema: SchemaObject) -> bool:
    """Check if a schema has any field using a discriminated union."""
    properties: dict[str, SchemaObject] = getattr(schema, "properties", {})
    if not properties:
        return False

    return any(_get_discriminator_info(fs) is not None for fs in properties.values())


def _generate_class(schema: SchemaObject) -> list[str]:
    """
    Generate a Pydantic BaseModel class from a schema.

    Args:
        schema: SchemaObject to generate class code for

    Returns:
        List of code lines representing the class definition
    """
    lines: list[str] = []

    title = getattr(schema, "title", "UnnamedModel")
    description = getattr(schema, "description", None) or title
    properties: dict[str, SchemaObject] = getattr(schema, "properties", {})
    required = getattr(schema, "required", None) or list[str]()

    # Class header - always BaseModel
    lines.append(f"class {title}(BaseModel):")
    lines.append(f'    """{description}"""')
    lines.append("")

    # Generate fields
    if not properties:
        lines.append("    pass")
        return lines

    for field_name, field_schema in properties.items():
        python_type = _get_python_type(field_schema)
        is_required = field_name in required

        # Wrap with Annotated[..., Field(discriminator=...)] for discriminated unions
        disc_info = _get_discriminator_info(field_schema)
        if disc_info:
            prop_name, union_type_str = disc_info
            python_type = (
                f'Annotated[{union_type_str}, Field(discriminator="{prop_name}")]'
            )

        # Check for const value (for action fields)
        const_value = getattr(field_schema, "const", None)
        default_value = getattr(field_schema, "default", None)

        if const_value is not None:
            # Field has const value (like action)
            if isinstance(const_value, str):
                lines.append(
                    f'    {field_name}: Literal["{const_value}"] = "{const_value}"'
                )
            else:
                lines.append(
                    f"    {field_name}: Literal[{const_value}] = {const_value}"
                )
        elif is_required and default_value is None:
            # Required field with no default
            lines.append(f"    {field_name}: {python_type}")
        elif factory := _default_factory(field_schema, is_required, default_value):
            lines.append(
                f"    {field_name}: {python_type} = Field(default_factory={factory})"
            )
        elif default_value is not None:
            # Has default value
            if isinstance(default_value, str):
                lines.append(f'    {field_name}: {python_type} = "{default_value}"')
            else:
                lines.append(f"    {field_name}: {python_type} = {default_value}")
        # Optional field
        elif python_type == "None":
            lines.append(f"    {field_name}: None = None")
        else:
            lines.append(f"    {field_name}: {python_type} | None = None")

    return lines


def _get_python_type(schema: SchemaObject | None) -> str:
    """
    Get Python type annotation from SchemaObject.

    Args:
        schema: SchemaObject to infer type from

    Returns:
        Python type annotation string (e.g., "str", "int", "list[str]")
    """
    if not schema:
        return "Any"

    # Check for enum first (should generate Literal types)
    enum_values: list[Any] | None = getattr(schema, "enum", None)
    if enum_values:
        # Generate Literal type from enum values
        formatted_values: list[str] = []
        for value in enum_values:
            if isinstance(value, str):
                formatted_values.append(f'"{value}"')
            else:
                formatted_values.append(str(value))
        return f"Literal[{', '.join(formatted_values)}]"

    # Check for anyOf first (common in AsyncAPI for nullable types)
    any_of: list[SchemaObject] | None = getattr(schema, "anyOf", None)
    if any_of:
        # Extract types from anyOf, filtering out null
        types: list[str] = []
        has_null = False
        for option in any_of:
            option_type: str = _get_python_type(option)
            if option_type == "None":
                has_null = True
            else:
                types.append(option_type)

        # If we have exactly one non-null type and a null, return "type | None"
        if len(types) == 1 and has_null:
            return types[0]
        # If we have multiple non-null types, join them with |
        elif types:
            return " | ".join(types)
        # If only null, return None
        elif has_null:
            return "None"

    # Check for oneOf (discriminated unions)
    one_of: list[SchemaObject] | None = getattr(schema, "oneOf", None)
    if one_of:
        types = []
        for option in one_of:
            option_type = _get_python_type(option)
            if option_type != "None":
                types.append(option_type)
        if types:
            return " | ".join(types)

    # First check schema type (actual type)
    schema_type = getattr(schema, "type", None)

    if schema_type == "null":
        return "None"
    elif schema_type == "string":
        return "str"
    elif schema_type == "integer":
        return "int"
    elif schema_type == "number":
        return "float"
    elif schema_type == "boolean":
        return "bool"
    elif schema_type == "array":
        items = getattr(schema, "items", None)
        if items:
            item_type = _get_python_type(items)
            return f"list[{item_type}]"
        return "list"
    elif schema_type == "object":
        # Check if this object schema has a title (references another class)
        title = getattr(schema, "title", None)
        if title and not callable(title):
            # Check if it has properties (is a defined schema)
            properties = getattr(schema, "properties", None)
            if properties and isinstance(properties, dict):
                # It's a reference to another schema class
                return str(title)
        return "dict[str, Any]"

    # If no type, check if it has properties (is a schema class reference)
    properties = getattr(schema, "properties", None)
    if properties and isinstance(properties, dict):
        title = getattr(schema, "title", None)
        if title and not callable(title):
            return str(title)

    # Default to Any for fields without explicit type
    # This is safer than assuming str, as the field can contain any value
    return "Any"


def extract_schemas_from_messages(messages: list[MessageObject]) -> list[SchemaObject]:
    """
    Extract schemas from messages and return them in topological order.

    Excludes inline 'action' fields from schema extraction.

    Args:
        messages: list of MessageObject instances

    Returns:
        list[SchemaObject] - schemas in topological order (dependencies first)
    """
    # Step 1: Extract message payloads as root schemas
    root_schemas: list[SchemaObject] = []
    root_ids: set[int] = set()

    for message in messages:
        payload = getattr(message, "payload", None)
        if payload and hasattr(payload, "title") and payload.title:
            schema_id = id(payload)
            if schema_id not in root_ids:
                root_ids.add(schema_id)
                root_schemas.append(payload)

    # Step 2: Find nested schemas that are referenced (but exclude 'action' fields)
    additional_schemas: list[SchemaObject] = []
    additional_ids: set[int] = set()

    for schema in root_schemas:
        _find_nested_schemas(
            schema,
            root_ids,
            additional_schemas,
            additional_ids,
            exclude_field_name=None,  # Don't exclude at root level
        )

    # Combine all schemas
    all_schemas = root_schemas + additional_schemas

    # Step 3: Sort topologically
    return topological_sort_schemas(all_schemas)


def _find_nested_schemas(
    schema: SchemaObject,
    root_ids: set[int],
    additional_schemas: list[SchemaObject],
    additional_ids: set[int],
    exclude_field_name: str | None = None,
    visited: set[int] | None = None,
) -> None:
    """
    Find nested schemas, excluding 'action' fields.

    Args:
        schema: Current schema being processed
        root_ids: set of root schema IDs
        additional_schemas: list to append found schemas
        additional_ids: set of additional schema IDs already found
        exclude_field_name: Field name to exclude (e.g., 'action')
        visited: set of visited schema IDs
    """
    if visited is None:
        visited = set()

    schema_id = id(schema)
    if schema_id in visited:
        return
    visited.add(schema_id)

    # Helper to collect a schema if it's not already tracked
    def collect_schema_if_needed(s: SchemaObject) -> None:
        """Collect schema if it has properties and isn't already tracked."""
        s_id = id(s)
        s_title = getattr(s, "title", None)

        if s_title and s_id not in root_ids and s_id not in additional_ids:
            # Add as additional schema if it has properties (not just a simple type)
            if getattr(s, "properties", None):
                additional_ids.add(s_id)
                additional_schemas.append(s)

    # Check properties
    properties: dict[str, SchemaObject] = getattr(schema, "properties", {})
    if properties:
        for field_name, field_schema in properties.items():
            # Skip 'action' fields - they're inline and shouldn't be extracted
            if field_name == "action":
                continue

            collect_schema_if_needed(field_schema)

            # Recurse into nested properties
            _find_nested_schemas(
                field_schema,
                root_ids,
                additional_schemas,
                additional_ids,
                exclude_field_name="action",
                visited=visited,
            )

    # Helper to process schema field values
    def process_value(val: SchemaObject | list[SchemaObject]) -> None:
        """Process schema field values, handling both lists and individual schemas."""
        if isinstance(val, list):
            for item in val:
                collect_schema_if_needed(item)
                _find_nested_schemas(
                    item,
                    root_ids,
                    additional_schemas,
                    additional_ids,
                    "action",
                    visited,
                )
        else:
            collect_schema_if_needed(val)
            _find_nested_schemas(
                val, root_ids, additional_schemas, additional_ids, "action", visited
            )

    # Check other schema fields (allOf, anyOf, oneOf, etc.)
    schema_fields = ["allOf", "anyOf", "oneOf", "items", "additionalProperties"]
    for field in schema_fields:
        value = getattr(schema, field, None)
        if value and not isinstance(value, bool):
            process_value(value)


def topological_sort_schemas(schemas: list[SchemaObject]) -> list[SchemaObject]:
    """
    Sort schemas in dependency order (dependencies first).

    Args:
        schemas: list[SchemaObject] - schemas to sort

    Returns:
        list[SchemaObject] - schemas in topological order
    """
    # Build schema map by title
    schema_map = cast(
        dict[str, SchemaObject],
        {s.title: s for s in schemas if getattr(s, "title", None)},
    )

    # Get set of root schema IDs
    root_ids: set[int] = {id(s) for s in schema_map.values()}

    # Build dependency graph - which root schemas does each root schema reference?
    deps: dict[str, set[str]] = {
        name: _find_root_schema_deps(schema, root_ids, id(schema))
        for name, schema in schema_map.items()
    }

    # Kahn's algorithm
    in_degree: dict[str, int] = {name: len(d) for name, d in deps.items()}
    queue: list[str] = sorted(name for name, degree in in_degree.items() if degree == 0)
    result: list[SchemaObject] = []

    while queue:
        node = queue.pop(0)
        result.append(schema_map[node])

        for name, dep_set in deps.items():
            if node in dep_set:
                in_degree[name] -= 1
                if in_degree[name] == 0:
                    queue.append(name)
                    queue.sort()

    # Add any remaining (cycles or isolated)
    remaining = sorted(set(schema_map.keys()) - {s.title for s in result})
    result.extend(schema_map[name] for name in remaining)

    return result


def _find_root_schema_deps(
    schema: SchemaObject,
    root_ids: set[int],
    current_root_id: int,
    visited: set[int] | None = None,
) -> set[str]:
    """
    Find which root schemas this schema references.

    Since AsyncAPI auto-resolves $refs, embedded schemas may be the same
    Python object as root schemas. We detect this by checking object IDs.
    """
    if visited is None:
        visited = set()

    obj_id = id(schema)
    if obj_id in visited:
        return set()
    visited.add(obj_id)

    deps: set[str] = set()

    # If this schema IS a root schema (and not the one we started from), it's a dependency
    if obj_id in root_ids and obj_id != current_root_id:
        schema_title = getattr(schema, "title", None)
        if schema_title:
            deps.add(schema_title)
        return deps  # Don't recurse into other root schemas

    # Helper to process schema field values
    def process_value(
        val: SchemaObject | dict[str, SchemaObject] | list[SchemaObject],
    ) -> None:
        """Recursively process schema field values to find dependencies."""
        if isinstance(val, dict):
            for v in val.values():
                deps.update(
                    _find_root_schema_deps(v, root_ids, current_root_id, visited)
                )
        elif isinstance(val, list):
            for item in val:
                deps.update(
                    _find_root_schema_deps(item, root_ids, current_root_id, visited)
                )
        else:
            deps.update(_find_root_schema_deps(val, root_ids, current_root_id, visited))

    # Recursively check all schema-valued fields
    schema_fields = [
        "properties",
        "patternProperties",
        "additionalProperties",
        "unevaluatedProperties",
        "items",
        "contains",
        "prefixItems",
        "propertyNames",
        "allOf",
        "anyOf",
        "oneOf",
        "not_",
        "if_",
        "then",
        "else_",
        "dependentSchemas",
    ]

    for field in schema_fields:
        value = getattr(schema, field, None)
        if value and not isinstance(value, bool):
            process_value(value)

    return deps


def extract_channel_messages(
    doc: AsyncAPIDocument,
) -> dict[str, tuple[list[MessageObject], list[MessageObject]]]:
    """
    Extract incoming and outgoing messages for each channel.

    For each operation:
    - action='send': operation.messages are incoming_messages
    - action='receive': operation.messages are outgoing_messages,
                        operation.reply.messages are incoming_messages

    Returns:
        Dict mapping channel_title -> (incoming_messages, outgoing_messages)
    """
    result: dict[str, tuple[list[MessageObject], list[MessageObject]]] = {}

    if not doc.operations:
        return result

    for operation in doc.operations.values():
        if not operation.channel:
            continue
        channel = cast(ChannelObject, operation.channel)
        channel_title = channel.title
        assert channel_title

        if channel_title not in result:
            result[channel_title] = ([], [])

        incoming, outgoing = result[channel_title]

        if operation.action == "send":
            if operation.messages:
                incoming.extend(cast(list[MessageObject], operation.messages))

        elif operation.action == "receive":
            if operation.messages:
                outgoing.extend(cast(list[MessageObject], operation.messages))

            if operation.reply and operation.reply.messages:
                incoming.extend(operation.reply.messages)

    return result
