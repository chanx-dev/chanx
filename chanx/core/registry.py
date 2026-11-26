"""
Message registry and schema generation.

This module provides utilities to collect BaseMessage types from consumers
and generate JSON schemas. Originally used for AsyncAPI generation, but now
serves as the core message type registry for the chanx framework.
"""

from collections import defaultdict
from types import UnionType
from typing import Any, TypeAlias, Union, cast, get_args, get_origin, get_type_hints

import humps
from pydantic import AliasChoices, AliasPath, BaseModel
from pydantic.fields import FieldInfo

from chanx.asyncapi.type_defs import SchemaObject, normalize_discriminators
from chanx.messages.base import BaseMessage

MessageSchema: TypeAlias = dict[str, Any]

MessageRef: TypeAlias = str
SchemaRef: TypeAlias = str

UNION_TYPES = (Union, UnionType)


def clean_consumer_name(consumer_name: str) -> str:
    """
    Remove 'Consumer' suffix from consumer class names.

    Args:
        consumer_name: The consumer class name to clean

    Returns:
        Consumer name without 'Consumer' suffix
    """
    return consumer_name.removesuffix("Consumer")


def get_schema_property_name(name: str, field: FieldInfo | None) -> str:
    """
    Get the key pydantic uses for a field in a validation-mode JSON schema.

    Pydantic keys schema ``properties`` by the field's validation alias, then
    its alias, and only then by its Python name.

    Args:
        name: The field's Python name
        field: The field's info, or None if it is not a model field

    Returns:
        The property name used in the model's JSON schema
    """
    if field is None:
        return name
    alias = (
        field.validation_alias if field.validation_alias is not None else field.alias
    )
    if isinstance(alias, str):
        return alias
    if isinstance(alias, AliasPath):
        paths = [alias.convert_to_aliases()]
    elif isinstance(alias, AliasChoices):
        paths = alias.convert_to_aliases()
    else:
        return name
    for path in paths:
        if len(path) == 1 and isinstance(path[0], str):
            return path[0]
    return name


def get_asyncapi_schema_ref(schema_title: str) -> str:
    """
    Generate AsyncAPI schema reference path.

    Args:
        schema_title: The schema title to reference

    Returns:
        AsyncAPI schema reference string
    """
    return f"#/components/schemas/{schema_title}"


def get_asyncapi_message_ref(message_title: str) -> str:
    """
    Generate AsyncAPI message reference path.

    Args:
        message_title: The message title to reference

    Returns:
        AsyncAPI message reference string
    """
    return f"#/components/messages/{message_title}"


class MessageRegistry:
    """Registry for collecting and managing message types from consumers."""

    def __init__(self) -> None:
        self.schemas: dict[type[BaseModel], SchemaRef] = {}
        self.messages: dict[type[BaseMessage], MessageRef] = {}
        self._schema_names: set[str] = set()

        self.remap_schema_title: dict[type[BaseModel], str] = {}

        self.schema_objects: dict[str, dict[str, Any]] = {}
        self.message_objects: dict[str, dict[str, Any]] = {}
        self.consumer_messages = defaultdict[str, set[type[BaseMessage]]](
            set[type[BaseMessage]]
        )

    def build_message(
        self, message_type: type[BaseMessage], consumer_name: str
    ) -> None:
        """
        Build and register a message type in the registry.

        Note: This method expects a single BaseMessage type, not a union/list/tuple.
        Union/list/tuple handling is done in the add() method.

        Args:
            message_type: The BaseMessage subclass to register
            consumer_name: Name of the consumer using this message type
        """
        self.consumer_messages[consumer_name].add(message_type)
        if message_type not in self.messages:
            message_title = self.remap_schema_title.get(
                message_type, message_type.__name__
            )
            message_name = humps.depascalize(message_title)

            message_schema = SchemaObject()
            message_schema.ref = self.schemas.get(message_type)

            self.message_objects[message_name] = {
                "payload": message_schema.model_dump(by_alias=True, exclude_none=True)
            }

            self.messages[message_type] = get_asyncapi_message_ref(message_name)

    def add(
        self,
        message_type: (
            type[BaseMessage]
            | list[type[BaseMessage]]
            | tuple[type[BaseMessage], ...]
            | UnionType
        ),
        consumer_name: str,
    ) -> None:
        """
        Add a message type to the registry, handling simple types, unions, lists, and tuples.

        Args:
            message_type: The BaseMessage type, union, list, or tuple to add
            consumer_name: Name of the consumer using this message type
        """
        # Handle list/tuple of message types
        if isinstance(message_type, list | tuple):
            for msg_type in message_type:
                self.build_message_schema(msg_type, consumer_name)
                self.build_message(msg_type, consumer_name)
            return

        self.build_message_schema(message_type, consumer_name)

        orig = get_origin(message_type)
        if orig in UNION_TYPES:
            for sub in get_args(message_type):
                if isinstance(sub, type) and issubclass(sub, BaseMessage):
                    self.build_message(sub, consumer_name)
        else:
            # At this point, message_type is a single type, not a UnionType
            self.build_message(cast(type[BaseMessage], message_type), consumer_name)

    def _handle_union_type(
        self, model_type: type[BaseModel], consumer_name: str
    ) -> bool:
        """
        Handle Union/UnionType processing.

        Args:
            model_type: The model type to check for union
            consumer_name: Name of the consumer

        Returns:
            True if union contained BaseModel types
        """
        """Handle Union/UnionType processing. Returns True if union contained BaseModel types."""
        orig = get_origin(model_type)
        has_base = False
        if orig in UNION_TYPES:
            for sub in get_args(model_type):
                if isinstance(sub, type) and issubclass(sub, BaseModel):
                    has_base = True
                    self.build_message_schema(sub, consumer_name)
        return has_base

    def _update_schema_title(
        self,
        model_schema: dict[str, Any],
        model_type: type[BaseModel],
        consumer_name: str,
    ) -> None:
        """
        Update schema title if there's a naming conflict.

        Args:
            model_schema: The schema dictionary to update
            model_type: The model type being processed
            consumer_name: Name of the consumer
        """
        """Update schema title if there's a naming conflict."""
        if model_type.__name__ in self._schema_names:
            prefix = clean_consumer_name(consumer_name)
            retitle = prefix + model_schema["title"]
            model_schema["title"] = retitle
            self.remap_schema_title[model_type] = retitle

    def _process_field_types(
        self, model_type_fields: dict[str, Any], consumer_name: str
    ) -> set[str]:
        """
        Process field types, register schemas, and return ref_fields.

        Args:
            model_type_fields: Dictionary of field names to types
            consumer_name: Name of the consumer

        Returns:
            Set of field names that are direct BaseModel references
        """
        ref_fields: set[str] = set()

        for f_name, f_type in model_type_fields.items():
            if isinstance(f_type, type) and issubclass(f_type, BaseModel):
                self.build_message_schema(f_type, consumer_name)
                ref_fields.add(f_name)
                continue

            self._process_union_field(f_type, consumer_name)

        return ref_fields

    def _process_union_field(self, f_type: Any, consumer_name: str) -> None:
        """
        Process a Union field type, registering any BaseModel members as schemas.

        Args:
            f_type: The field type to process
            consumer_name: Name of the consumer
        """
        orig = get_origin(f_type)
        if orig in UNION_TYPES:
            for item in get_args(f_type):
                if isinstance(item, type) and issubclass(item, BaseModel):
                    self.build_message_schema(item, consumer_name)

    def _update_ref_recursively(
        self, obj: Any, defs_to_schemas: dict[str, str]
    ) -> None:
        """
        Recursively update all $ref pointers in a schema structure.

        Replaces references from #/$defs/... to #/components/schemas/...

        Args:
            obj: The object to update (dict, list, or other)
            defs_to_schemas: Mapping from $defs names to schema refs
        """
        if isinstance(obj, dict):
            dict_obj = cast(dict[str, Any], obj)
            for key, value in dict_obj.items():
                # Update $ref pointers and discriminator mapping values
                if isinstance(value, str) and value.startswith("#/$defs/"):
                    schema_name = value.replace("#/$defs/", "")
                    if schema_name in defs_to_schemas:
                        dict_obj[key] = defs_to_schemas[schema_name]
                else:
                    self._update_ref_recursively(value, defs_to_schemas)
        elif isinstance(obj, list):
            list_obj = cast(list[Any], obj)  # type: ignore[redundant-cast]
            for item in list_obj:
                self._update_ref_recursively(item, defs_to_schemas)

    def _update_schema_references(
        self,
        model_schema: dict[str, Any],
        ref_fields: set[str],
        model_type_fields: dict[str, Any],
        model_fields: dict[str, FieldInfo],
    ) -> None:
        """
        Update schema with proper references.

        Extracts $defs as top-level schemas and recursively rewrites all
        $ref pointers and discriminator mappings from #/$defs/... to
        #/components/schemas/...

        Args:
            model_schema: The schema to update
            ref_fields: Fields that are direct BaseModel references
            model_type_fields: Original field type mapping
            model_fields: The model's fields, used to find each field's alias
        """
        # Process $defs first - extract and register them as separate schemas
        defs = model_schema.pop("$defs", None)
        defs_to_schemas: dict[str, str] = {}

        if defs:
            for def_name, _def_schema in defs.items():
                schema_ref = get_asyncapi_schema_ref(def_name)
                defs_to_schemas[def_name] = schema_ref

        # Update properties with explicit references for direct BaseModel fields
        properties = model_schema["properties"]

        if ref_fields:
            for ref in ref_fields:
                key = get_schema_property_name(ref, model_fields.get(ref))
                properties[key] = {"$ref": self.schemas[model_type_fields[ref]]}

        # Recursively update all $ref pointers and discriminator mappings
        self._update_ref_recursively(model_schema, defs_to_schemas)

        # Now update references in the extracted def schemas and store them
        if defs is not None:
            for def_name, def_schema in defs.items():
                self._update_ref_recursively(def_schema, defs_to_schemas)

                if def_name not in self.schema_objects:
                    self.schema_objects[def_name] = def_schema

    def build_message_schema(
        self, model_type: type[BaseModel] | UnionType, consumer_name: str
    ) -> None:
        """
        Build and register a JSON schema for a BaseModel type.

        Processes the model type, extracts field type information, handles unions,
        and generates proper schema references for AsyncAPI documentation.

        Args:
            model_type: The BaseModel type or UnionType to process
            consumer_name: Name of the consumer using this type
        """
        # Handle Union types first - if it's a union, process its args and return
        orig = get_origin(model_type)
        if orig in UNION_TYPES:
            # It's a union, handle it and return
            self._handle_union_type(cast(type[BaseModel], model_type), consumer_name)
            return

        # At this point, model_type is guaranteed to be type[BaseModel], not UnionType
        concrete_type = cast(type[BaseModel], model_type)

        # Skip if already processed
        if concrete_type in self.schemas:
            return

        # Generate base schema
        model_schema = concrete_type.model_json_schema()
        normalize_discriminators(model_schema)
        self._update_schema_title(model_schema, concrete_type, consumer_name)

        # Process field types
        model_type_fields = get_type_hints(concrete_type)
        ref_fields = self._process_field_types(model_type_fields, consumer_name)

        # Update references
        self._update_schema_references(
            model_schema, ref_fields, model_type_fields, concrete_type.model_fields
        )

        # Store the schema
        self.schemas[concrete_type] = get_asyncapi_schema_ref(model_schema["title"])
        self.schema_objects[model_schema["title"]] = model_schema
        self._schema_names.add(concrete_type.__name__)


message_registry = MessageRegistry()
