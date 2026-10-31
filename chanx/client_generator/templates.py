"""Jinja2 templates for code generation."""

from jinja2 import Environment, Template

# ============================================================================
# CHANNEL CLIENT TEMPLATE
# ============================================================================

CHANNEL_CLIENT_TEMPLATE = '''"""{{ channel_title }} client."""

from ..base.client import BaseClient
from .messages import IncomingMessage, OutgoingMessage


class {{ class_name }}(BaseClient):
    """
    WebSocket client for {{ channel_title }}.

    {{ channel_description }}

    Channel: {{ channel_address }}
    """

    path = "{{ channel_address }}"
    incoming_message = IncomingMessage

    async def send_message(self, message: OutgoingMessage) -> None:
        """
        Send a message to the server.

        Args:
            message: The message to send (Pydantic model or dict)
        """
        await super().send_message(message)

    async def handle_message(self, message: IncomingMessage) -> None:
        pass

'''


# ============================================================================
# TOPIC HANDLE TEMPLATE
# ============================================================================

TOPIC_HANDLE_TEMPLATE = '''"""{{ channel_title }} topic handle."""

from ..base.topic_client import BaseTopicHandle
from .messages import IncomingMessage{% if has_outgoing %}, OutgoingMessage{% endif %}


class {{ class_name }}(BaseTopicHandle):
    """
    Handle for the {{ topic_pattern }} topic.

    {{ channel_description }}

    Shares the connection at {{ channel_address }}.
    """

    pattern = "{{ topic_pattern }}"
    incoming_message = IncomingMessage
{% if has_outgoing %}
    async def send_message(self, message: OutgoingMessage) -> None:
        """
        Send a message on this topic.

        Args:
            message: The message to send
        """
        await super().send_message(message)
{% endif %}
    async def handle_message(self, message: IncomingMessage) -> None:
        pass

'''


# ============================================================================
# TOPIC CONNECTION CLIENT TEMPLATE
# ============================================================================

TOPIC_CONNECTION_TEMPLATE = '''"""{{ channel_title }} connection client."""

from typing import Any

from ..base.topic_client import BaseTopicConnection
{% for handle in handles %}
from ..{{ handle.module }}.client import {{ handle.class_name }}
{% endfor %}
from .messages import IncomingMessage{% if has_outgoing %}, OutgoingMessage{% endif %}


class {{ class_name }}(BaseTopicConnection):
    """
    WebSocket client for {{ channel_title }}.

    {{ channel_description }}

    Owns the connection at {{ channel_address }} and hands out topic handles.
    """

    path = "{{ channel_address }}"
    incoming_message = IncomingMessage

{% for handle in handles %}
    def {{ handle.method_name }}(self{% for param in handle.parameters %}, {{ param }}: Any{% endfor %}) -> {{ handle.class_name }}:
        """Handle for {{ handle.pattern }}."""
        return self.topic({{ handle.class_name }}{% for param in handle.parameters %}, {{ param }}={{ param }}{% endfor %})

{% endfor %}
{% if has_outgoing %}
    async def send_message(self, message: OutgoingMessage) -> None:
        """
        Send a message to the server outside any topic.

        Args:
            message: The message to send
        """
        await super().send_message(message)
{% endif %}

    async def handle_message(self, message: IncomingMessage) -> None:
        pass

'''


# ============================================================================
# CHANNEL __INIT__.PY TEMPLATE
# ============================================================================

CHANNEL_INIT_TEMPLATE = '''"""Channel module for {{ channel_name }}."""

from .client import {{ class_name }}
from .messages import (
{% for export in message_exports %}
    {{ export }},
{% endfor %}
)

__all__ = [
    "{{ class_name }}",
{% for export in message_exports %}
    "{{ export }}",
{% endfor %}
]
'''


# ============================================================================
# MAIN PACKAGE __INIT__.PY TEMPLATE
# ============================================================================

PACKAGE_INIT_TEMPLATE = '''"""{{ title }} - Generated AsyncAPI Client

Version: {{ version }}

This client was automatically generated from an AsyncAPI schema.
"""

__version__ = "{{ version }}"
__title__ = "{{ title }}"
'''


# ============================================================================
# README.MD TEMPLATE
# ============================================================================

README_TEMPLATE = """# {{ title }}

{{ description }}

**Version:** {{ version }}

This WebSocket client was automatically generated from an AsyncAPI 3.0 schema.

## Installation

Install the required dependencies:

```bash
pip install websockets pydantic
```

## Usage

Extend the generated client classes and override `handle_message` to process incoming messages:

```python
import asyncio
from typing import Any, assert_never
from {{ package_name }}.base.errors import ErrorType, ProblemDetails
from {{ package_name }}.{{ first_channel }} import {{ first_class }}, IncomingMessage

class My{{ first_class }}({{ first_class }}):
    async def handle_message(self, message: IncomingMessage) -> None:
        # Handle incoming messages using pattern matching
        match message:
            case SomeMessageType():
                print(f"Received SomeMessageType: {message}")
                # Handle this message type
            case AnotherMessageType():
                print(f"Received AnotherMessageType: {message}")
                # Handle this message type
            case _:
                assert_never(message)

    async def handle_error_message(
        self, problem: ProblemDetails | None, frame: dict[str, Any]
    ) -> None:
        # An error frame from the server: branch on its type
        if problem and problem.type == ErrorType.VALIDATION_FAILED:
            for error in problem.errors or []:
                print(f"{error.pointer}: {error.keyword} ({error.detail})")

    async def handle_error(self, error):
        # Handle errors during message processing
        print(f"Error: {error}")

async def main():
    # Create client instance
    client = My{{ first_class }}({% if first_params %}
        "ws://localhost:8000",
        path_params={{ '{' }}{% for param in first_params %}"{{ param }}": "value"{% if not loop.last %}, {% endif %}{% endfor %}{{ '}' }},
{% else %}
        "ws://localhost:8000"
{% endif %}
    )

    # Start the client (connects and listens for messages)
    await client.handle()

asyncio.run(main())
```

## Message Models

Each channel module exports:
- **Client class** - WebSocket client for that channel
- **Message classes** - Individual message models (e.g., `ChatMessage`)
- **Payload classes** - Message payload models (e.g., `ChatPayload`)
- **IncomingMessage** - Union type of all messages the client can receive
- **OutgoingMessage** - Union type of all messages the client can send

Import from channel modules:
```python
from {{ package_name }}.{{ first_channel }} import {{ first_class }}, IncomingMessage, OutgoingMessage
```
{% if has_shared %}

### Shared Messages

Message models shared across multiple channels:
```python
from {{ package_name }}.shared.messages import *
```
{% endif %}

## Sending Messages

Use `send_message()` to send messages to the server:

```python
from {{ package_name }}.{{ first_channel }} import {{ first_class }}, OutgoingMessage

class My{{ first_class }}({{ first_class }}):
    async def handle_message(self, message):
        # Echo back the message
        response = OutgoingMessage(...)  # Create your message
        await self.send_message(response)
```
"""


# ============================================================================
# JINJA2 ENVIRONMENT SETUP
# ============================================================================


def snake_case_filter(x: str) -> str:
    """Convert string to snake_case."""
    return x.lower().replace(" ", "_").replace("-", "_")


def pascal_case_filter(x: str) -> str:
    """Convert string to PascalCase."""
    return "".join(
        word.capitalize() for word in x.replace("_", " ").replace("-", " ").split()
    )


def get_env() -> Environment:
    """Get configured Jinja2 environment."""
    env = Environment(
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )

    # Add custom filters
    env.filters["snake_case"] = snake_case_filter
    env.filters["pascal_case"] = pascal_case_filter

    return env


def get_template(template_str: str) -> Template:
    """Get a compiled Jinja2 template."""
    env = get_env()
    return env.from_string(template_str)
