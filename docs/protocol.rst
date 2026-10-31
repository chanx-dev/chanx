Wire Protocol
=============

This page specifies what chanx sends over the socket and through the channel layer. You
do not need it to use chanx; it is for people writing a client by hand, implementing
the protocol in another language (as `chanx-js <https://js.chanx.dev/>`_
and `chanx-go <https://go.chanx.dev/>`_ do), or debugging traffic.

Examples use the defaults: the discriminator field is ``action`` and camelization is off.

Frames
------

Every frame is a WebSocket **text** frame holding one JSON object. Binary frames are
rejected with an ``error`` frame (see `Errors`_), and the connection stays open.

A message has an ``action`` naming its type and a ``payload`` whose shape depends on the
action:

.. code-block:: json

    {"action": "echo", "payload": {"message": "Hello"}}

- The discriminator key is ``action`` unless the consumer sets ``discriminator_field``
  (``MESSAGE_ACTION_KEY`` on Django).
- With ``camelize`` on (``CAMELIZE`` on Django), the server converts keys to camelCase
  on the way out and back to snake_case on the way in. Envelope keys are single words,
  so camelization leaves them alone.
- Messages without a payload send ``"payload": null``.

Envelope
--------

Routing metadata travels on the same flat object as the message, under four reserved
keys:

.. list-table::
   :header-rows: 1
   :widths: 15 15 70

   * - Key
     - Type
     - Meaning
   * - ``version``
     - integer
     - Envelope version, currently ``1``. The server stamps it on every frame that
       carries ``ref`` or ``topic``.
   * - ``ref``
     - string
     - Client-chosen request id. Replies to that frame carry the same ``ref``.
   * - ``topic``
     - string
     - The topic a frame is addressed to or sent from. See `Topics`_.
   * - ``seq``
     - integer
     - Sequence number on topic pushes, when the publisher assigns one.

The server removes these keys before validating the message, so a message model never
sees them. A reserved key with the wrong type (for example ``"version": "x"``) is
answered with a validation error.

Requests and replies
--------------------

Anything the server sends **while handling** a frame carries that frame's ``ref``: the
handler's return value, validation errors, handler errors and the ``complete`` signal.

.. code-block:: text

    → {"action": "echo", "payload": {"message": "x"}, "ref": "r1"}
    ← {"action": "echo_response", "payload": {"message": "Echo: x"}, "version": 1, "ref": "r1"}

Messages that arrive through the channel layer carry no ``ref``, even when the sender's
own frame triggered them. A broadcast reaches the sender like every other group member:

.. code-block:: text

    → {"action": "broadcast", "payload": {"message": "b"}, "ref": "r3"}
    ← {"action": "notification", "payload": {"alert": "Broadcast: b", "level": "info"}}

Frames without a ``ref`` work the same way; their replies just carry none.

Built-in actions
----------------

These actions are defined by chanx itself. Clients should treat the server-sent ones as
framework signals rather than application messages.

.. list-table::
   :header-rows: 1
   :widths: 22 12 66

   * - Action
     - Direction
     - Meaning
   * - ``ping`` / ``pong``
     - both
     - Liveness check, when the consumer mounts a ``PingMessage`` handler. Both have
       ``"payload": null``.
   * - ``error``
     - server
     - A frame could not be handled. See `Errors`_.
   * - ``authentication``
     - server
     - Result of authentication, sent by ``DjangoAuthenticator`` right after the
       handshake unless ``SEND_AUTHENTICATION_MESSAGE`` is off. See
       `Connection lifecycle`_.
   * - ``complete``
     - server
     - Handling of a client frame finished. Only with ``send_completion`` on.
   * - ``event_complete``
     - server
     - Handling of a channel event finished. Only with ``send_completion`` on.
   * - ``group_complete``
     - server
     - Delivery of a group message finished. Only with ``send_completion`` on.
   * - ``subscribe`` / ``unsubscribe``
     - client
     - Join or leave a topic. See `Topics`_.
   * - ``subscribed`` / ``unsubscribed``
     - server
     - Confirm a subscribe or unsubscribe.

.. _protocol-errors:

Errors
------

Errors never close the connection. The ``payload`` shape depends on ``error_format``
(``ERROR_FORMAT`` on Django). The default, ``"standard"``, is the cross-language format
that every chanx implementation targets. ``"pydantic"`` keeps chanx's earlier payloads,
which pass Pydantic's error list through as is.

Standard format
~~~~~~~~~~~~~~~

The payload is an `RFC 9457 <https://www.rfc-editor.org/rfc/rfc9457>`_ problem details
object. Validation failures add an ``errors`` extension in the shape of the RFC's own
validation example (section 3), with a ``keyword`` naming the JSON Schema keyword that
failed:

.. code-block:: json

    {"action": "error", "ref": "r1", "version": 1, "payload": {
        "type": "https://chanx.dev/errors/validation-failed",
        "title": "Message failed validation",
        "detail": "2 validation errors",
        "errors": [
            {"keyword": "required", "pointer": "/payload", "property": "message", "detail": "Field required"},
            {"keyword": "minLength", "pointer": "/payload/title", "detail": "String should have at least 2 characters"}
        ]
    }}

``type`` identifies the problem and is what clients branch on. ``title`` is fixed per
type; ``detail`` describes this occurrence. Both are for people: clients should not
parse them, and their wording differs between implementations.

.. list-table::
   :header-rows: 1
   :widths: 40 25 35

   * - ``type``
     - ``title``
     - When
   * - ``https://chanx.dev/errors/validation-failed``
     - Message failed validation
     - The frame does not match a message the consumer or topic accepts. Has ``errors``.
   * - ``https://chanx.dev/errors/invalid-json``
     - Frame is not valid JSON
     - The frame is not JSON, or is a binary frame.
   * - ``https://chanx.dev/errors/handler-failed``
     - Message handler failed
     - A handler raised. The exception is logged on the server and not sent.
   * - ``https://chanx.dev/errors/internal-error``
     - Message could not be processed
     - The frame could not be processed for another reason.
   * - ``https://chanx.dev/errors/unknown-topic``
     - Unknown topic
     - No mounted topic matches the name.
   * - ``https://chanx.dev/errors/unauthorized``
     - Subscription not allowed
     - The topic's ``authorize`` hook refused the subscription.
   * - ``https://chanx.dev/errors/not-subscribed``
     - Not subscribed to topic
     - A message was sent to a topic this connection has not joined.

Each entry in ``errors`` has:

- ``keyword``: the JSON Schema keyword the value fails, as the message's schema in the
  AsyncAPI document states it: ``required``, ``type``, ``enum``, ``minLength``,
  ``maxLength``, ``pattern``, ``minimum``, ``maximum``, ``exclusiveMinimum``,
  ``exclusiveMaximum``, ``multipleOf``, ``minItems``, ``maxItems``,
  ``additionalProperties`` or ``format``. Checks a schema cannot express, such as a
  custom validator, use ``custom``.
- ``pointer``: an `RFC 6901 <https://www.rfc-editor.org/rfc/rfc6901>`_ JSON Pointer to
  the failing value in the frame as the client sent it (camelized keys appear
  camelized). It always points at a value that exists, so for ``required`` it points at
  the object that lacks the member.
- ``property``: for ``required`` only, the name of the missing member. Join it to
  ``pointer`` to locate the field.
- ``detail``: a human-readable message.

An unknown action is ``enum`` at ``/action``; a frame without one is ``required`` at
``""`` with ``property`` ``action``. ``const`` mismatches are reported as ``enum``, so a
consumer with one message type reports an unknown action the same way as one with
many.

How this relates to the standards it builds on:

- RFC 9457 defines problem details for HTTP. chanx sends the same object inside an
  ``error`` frame, so there is no HTTP status and ``status`` is never sent. Clients
  must ignore members they do not recognize (RFC 9457 section 3.2).
- ``pointer`` follows the rule in JSON Schema output (2020-12, section 12) and JSON:API
  that a location names a value that exists, which is why ``required`` reports the
  parent. ``keyword`` names the keyword where JSON Schema output gives a path into the
  schema (``keywordLocation``); that path depends on how each implementation lays out
  its schema, so it cannot match across languages.

Each implementation exposes the payload as a type: ``ProblemDetails`` and
``ValidationFailure`` in ``chanx.core.errors`` (Python), ``protocol.ProblemDetails`` and
``protocol.ValidationFailure`` (Go), and ``ProblemDetails`` and ``ValidationFailure`` with
an ``isProblem()`` guard in ``@chanx-js/client`` and ``@chanx-js/server``. ``problem()``
(``protocol.NewProblem`` in Go) builds a payload for a handler that sends its own.

AsyncAPI documents list ``ProblemDetails``, the schema of RFC 9457 Appendix A plus the
``errors`` extension, and ``ValidationFailure`` under ``components.schemas`` when the
standard format is on. No channel refers to them, since error frames are framework frames
rather than channel messages, but client generators turn them into types. A model of
yours with either name is refused when the document is generated.

The payload validates against this schema:

.. code-block:: json

    {
      "$schema": "https://json-schema.org/draft/2020-12/schema",
      "type": "object",
      "required": ["type", "title", "detail"],
      "properties": {
        "type": {"type": "string", "format": "uri"},
        "title": {"type": "string"},
        "detail": {"type": "string"},
        "errors": {
          "type": "array",
          "items": {
            "type": "object",
            "required": ["keyword", "pointer", "detail"],
            "properties": {
              "keyword": {"type": "string"},
              "pointer": {"type": "string", "format": "json-pointer"},
              "property": {"type": ["string", "integer"]},
              "detail": {"type": "string"}
            }
          }
        }
      }
    }

Pydantic format
~~~~~~~~~~~~~~~

The ``payload`` takes one of three shapes.

**Validation errors** are a list of Pydantic error objects with ``type``, ``loc`` and
``msg``. Unknown actions, missing fields, bad envelope types, invalid JSON and binary
frames all use this shape:

.. code-block:: json

    {"action": "error", "payload": [
        {"type": "missing", "loc": ["echo", "payload", "message"], "msg": "Field required"}
    ]}

.. code-block:: json

    {"action": "error", "payload": [
        {"type": "json_invalid", "loc": [], "msg": "Invalid JSON: binary frames are not supported"}
    ]}

**Handler failures** are an object with a ``detail`` string, such as
``{"detail": "Failed to process message for echo"}``.

**Topic errors** are an object with a ``reason`` (``unknown_topic``, ``unauthorized`` or
``not_subscribed``) and a ``detail``, sent on the topic the frame addressed.

Custom errors
~~~~~~~~~~~~~

Consumers can override ``handle_validation_error``, ``handle_json_processing_error`` and
``handle_message_handler_error`` to change these payloads.

Topics
------

A frame with a ``topic`` goes to that topic instead of the consumer's own handlers.

.. code-block:: text

    → {"action": "subscribe", "topic": "discussion:42", "ref": "s1"}
    ← {"action": "subscribed", "payload": null, "version": 1, "topic": "discussion:42", "ref": "s1"}

    → {"action": "reply", "payload": {"text": "hi"}, "topic": "discussion:42", "ref": "m1"}
    ← {"action": "reply_created", "payload": {"text": "hi"}, "version": 1, "topic": "discussion:42", "ref": "m1"}

    ← {"action": "reply_created", "payload": {...}, "version": 1, "topic": "discussion:42", "seq": 7}

    → {"action": "unsubscribe", "topic": "discussion:42", "ref": "s2"}
    ← {"action": "unsubscribed", "payload": null, "version": 1, "topic": "discussion:42", "ref": "s2"}

- Subscribing twice is idempotent: the second ``subscribe`` is confirmed again.
- Messages a topic sends from ``on_subscribe`` (initial state) carry the topic but no
  ``ref``, so clients do not mistake them for the reply.
- Pushes published with ``Topic.broadcast`` carry the topic and, when the publisher set
  one, ``seq``. Gaps in ``seq`` let a client detect missed pushes. A topic with several
  writers leaves ``seq`` unset.
- Disconnecting leaves every subscribed topic.
- A route built with ``Topic.as_consumer()`` serves one topic, subscribed from the URL
  on connect. Frames without a ``topic`` belong to it, so clients need no envelope.

Connection lifecycle
--------------------

1. The server accepts the WebSocket handshake.
2. If the consumer has an authenticator, it runs. ``DjangoAuthenticator`` then sends an
   ``authentication`` frame, unless ``SEND_AUTHENTICATION_MESSAGE`` is ``False``:

   .. code-block:: json

       {"action": "authentication", "payload": {"status_code": 200, "status_text": "OK", "data": {"detail": "OK"}}}

   On failure the server closes the socket with code ``4000 + status`` (for example
   ``4403``) when the authenticator reports a 4xx or 5xx status, and ``4401`` otherwise.
3. The connection joins the consumer's groups, runs ``post_authentication``, and, on a
   single-topic route, subscribes its topic.

Frames are handled concurrently: each one runs in its own task, so replies to two quick
requests can arrive in either order. Use ``ref`` to match them.

Channel layer messages
----------------------

Servers in different processes, or in different languages, cooperate through the
channel layer. A server that wants to share a Redis layer with chanx must use these
message shapes and group names.

**Group messages** (``broadcast_message``) carry the already-serialized frame:

.. code-block:: json

    {"type": "handle_group_message",
     "message": {"action": "notification", "payload": {"alert": "Hi all", "level": "info"}},
     "exclude_current": false, "from_channel": "specific.abc123!def456"}

A receiver skips the message when ``exclude_current`` is true and ``from_channel`` is its
own channel name; otherwise it sends ``message`` to its client as is.

**Events** (``send_event``, ``broadcast_event``) carry a message for the receiving
consumer's ``@event_handler`` methods, which decide what reaches the client:

.. code-block:: json

    {"type": "handle_channel_event",
     "event_data": {"action": "system_notify", "payload": {"alert": "Maintenance", "level": "warning"}}}

**Topic events** (``Topic.broadcast``) add the topic and optional sequence number:

.. code-block:: json

    {"type": "handle_topic_event", "topic": "discussion:42", "seq": 7,
     "event_data": {"action": "new_reply", "payload": {"text": "hi"}}}

**Group names** come from ``safe_group_name(*parts, namespace=None)``:

1. Convert each part to a string, replace every run of characters outside
   ``A-Za-z0-9._-`` with ``-``, and strip leading and trailing ``-``.
2. Drop empty parts and join the rest with ``.``, namespace first.
3. If the result is longer than 99 characters, keep the first 86 and append ``.`` plus
   the hex digest of BLAKE2s over the full name with a 6-byte digest size (12 hex
   characters).

A topic's group is ``safe_group_name(topic, namespace=TopicClassName)``, so
``DiscussionTopic`` and ``discussion:42`` give ``DiscussionTopic.discussion-42``.

Implementations
---------------

- **chanx** (this project): servers on Django Channels and ASGI, and generated Python
  clients.
- `chanx-js <https://js.chanx.dev/>`_: TypeScript clients and a
  Node server that implement this protocol and can share a Redis layer with chanx.
- `chanx-go <https://go.chanx.dev/>`_: Go servers on net/http, gin, echo and Fiber, and
  generated Go clients, sharing the same Redis layer.
