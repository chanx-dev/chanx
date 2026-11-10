## v2.15.0 (2026-11-10)

### Feat

- cancel_handlers_on_disconnect to stop a connection's in-flight handlers

### Fix

- **asyncapi**: give Django channel addresses a leading slash
- **client-generator**: log unparseable and error frames instead of printing them
- **client-generator**: keep a defaulted list or dict non-nullable
- **asyncapi**: find path parameters in include prefixes and bare <name> converters

## v2.14.0 (2026-11-03)

### Feat

- hand error frames to generated clients as typed problems
- list the error payload schemas in AsyncAPI documents
- send errors as RFC 9457 problem details

## v2.13.0 (2026-10-27)

### Feat

- add emits for messages a consumer sends outside its handlers
- add join_group and leave_group for groups at run time

## v2.12.4 (2026-10-26)

## v2.12.3 (2026-10-25)

## v2.12.2 (2026-10-25)

## v2.12.1 (2026-10-25)

### Fix

- **channels**: honor SEND_AUTHENTICATION_MESSAGE in DjangoAuthenticator
- **docs**: give quick start broadcast handler its own action

## v2.12.0 (2026-10-25)

### Feat

- **asyncapi**: document servers, security schemes and ws bindings from authenticator credentials
- **asyncapi**: pin docs page assets with SRI and make their URLs configurable
- **asyncapi**: mark request/reply messages with a ref correlationId
- **core**: close with 4000 + status when authentication fails

### Fix

- **asyncapi**: omit info.description when unset

## v2.11.8 (2026-10-23)

### Fix

- **core**: answer non-JSON frames with an error instead of dropping the socket
- **core**: order discriminated unions by action

## v2.11.7 (2026-10-02)

### Fix

- **client-generator**: run the init message alongside the read loop
- **client-generator**: make the topic accessor generic in its handle

## v2.11.6 (2026-10-01)

### Fix

- **tests**: annotate the fake connect as the async iterator it is
- **tests**: declare groups the way every other consumer does

## v2.11.5 (2026-10-01)

### Fix

- **client-generator**: send the headers the client was given

## v2.11.4 (2026-09-29)

### Fix

- **core**: camelize group broadcasts, not just direct sends

## v2.11.3 (2026-09-27)

### Docs

- **readme**: show typed JavaScript/TypeScript clients via chanx-js
- add an ecosystem page for chanx-js and chanx-kit

## v2.11.2 (2026-09-24)

### Fix

- **core**: echo the ref on replies to untopiced frames

## v2.11.1 (2026-09-18)

### Fix

- **core**: explain missing channel layer instead of asserting
- **fast_channels**: register websocket routes via app.router

## v2.11.0 (2026-09-18)

### Feat

- **channels**: default LOG_WEBSOCKET_MESSAGE to False

### Perf

- **core**: skip building log context when message logging is disabled

## v2.10.2 (2026-09-13)

### Fix

- **asyncapi**: emit the discriminator in the form AsyncAPI accepts

## v2.10.1 (2026-09-04)

### Fix

- **asyncapi**: drop non-message arms from union reply types

## v2.10.0 (2026-08-12)

### Feat

- **sandbox**: demo topics in the FastAPI sandbox
- **client-generator**: generate one connection client with topic handles
- **asyncapi**: document each topic as its own channel
- **topic**: add topic subscriptions multiplexed over one connection
- **utils**: add group naming, scope, framework and streaming helpers

### Fix

- **topic**: follow consumer camelize on topic frames and tighten lifecycle
- **asyncapi**: keep channel extensions across a document round-trip

## v2.9.0 (2026-08-06)

### Feat

- complete mixin composition for groups and handler actions

## v2.8.1 (2026-07-29)

### Fix

- **class**: use pydantic v2 model_config

## v2.8.0 (2026-06-23)

### Feat

- merge passthrough_events across the consumer inheritance chain

## v2.7.1 (2026-05-08)

### Fix

- handle discriminated union schemas in registry and codegen

## v2.7.0 (2026-05-04)

### Feat

- add passthrough_events for auto-forwarding channel events to WebSocket clients

## v2.6.2 (2026-04-17)

### Fix

- handle empty handler maps in adapter building

## v2.6.1 (2026-03-13)

### Fix

- support `from __future__ import annotations` in decorators and BaseMessage

## v2.6.0 (2026-03-07)

### Feat

- add mixin support for ws and event handlers

## v2.5.0 (2026-01-17)

### Feat

- **ci**: add Django 6 support and multi-package testing matrix

### Fix

- **deps**: upgrade packages to address security vulnerabilities

## v2.4.1 (2026-01-15)

### Fix

- **asyncapi**: preserve default value when resolving schema $ref

## v2.4.0 (2026-01-06)

### Feat

- **cli**: add options to control client generator output behavior

### Fix

- **cli**: generated client re-raise error instead of just printing out error

## v2.3.1 (2025-12-10)

### Fix

- add docs for generate_asyncapi_schema command

## v2.3.0 (2025-12-10)

### Feat

- **channels**: add management command to generate AsyncAPI schema files

## v2.2.2 (2025-12-07)

### Fix

- change CapturedBroadcastEvent from TypedDict to dataclass

## v2.2.1 (2025-12-07)

### Fix

- add suppress param for capture_broadcast_events and update docs

## v2.2.0 (2025-12-07)

### Feat

- add capture_broadcast_events utils for testing

## v2.1.1 (2025-12-05)

### Fix

- correct codegen type for literal and any

## v2.1.0 (2025-11-28)

### Feat

- client generator

### Fix

- update docs for client generation
- improve code gen for dict and add some hooks, error handling for base client
- add tests for the client generation feature
- use netloc instead of hostname for fastapi autodoc

### Refactor

- restructure optional dependencies into focused extras

## v2.0.2 (2025-11-15)

### Fix

- suppress mypy override warning for EmailUserField.to_representation
- use aexception for channel event ValidationError to capture full traceback

## v2.0.1 (2025-10-13)

### Fix

- **docs**: minor fix for tutorial docs
- **docs**: add AsyncAPI mapping explanations and improve navigation
- **docs**: add comprehensive FastAPI Chanx WebSocket tutorial
- **packages**: correct package dependencies
- **docs**: add comprehensive Django WebSocket tutorial and framework comparison

## v2.0.0 (2025-10-12)

### BREAKING CHANGE

- Import paths changed from chanx.ext.channels to chanx.channels and chanx.ext.fast_channels to chanx.fast_channels

### Feat

- restructure package and adopt mixin pattern for better static type checking

## v1.1.3 (2025-10-11)

### Fix

- **core**: support list/tuple output types in handlers

## v1.1.2 (2025-10-11)

### Fix

- **core**: add missing init file to core

## v1.1.1 (2025-10-11)

### Fix

- **asyncapi**: preserve schema keys as PascalCase class names in camelCase mode

## v1.1.0 (2025-10-10)

### Feat

- **asyncapi**: add camelCase naming convention support

## v1.0.4 (2025-10-10)

### Fix

- properly handle nested references in $defs schemas for message registry

## v1.0.3 (2025-10-10)

### Fix

- properly handle $defs references in AsyncAPI schemas

## v1.0.2 (2025-10-09)

### Fix

- improve DjangoAuthenticator flexibility and type safety

## v1.0.1 (2025-10-09)

### Fix

- improve queryset handling in DjangoAuthenticator

## v1.0.0 (2025-10-08)

### BREAKING CHANGE

- Major rewrite introducing decorator-based WebSocket handlers and automatic AsyncAPI documentation generation

### Feat

- reimplement chanx with decorator approach and auto-generate asyncapi docs

### Fix

- install all extras for readthedocs
- update documentation and improve type safety in message registry

## v0.13.3 (2025-07-15)

### Fix

- **packages**: loosen package dependencies versions

## v0.13.2 (2025-07-12)

### Fix

- **testing**: ignore CancelledError for WebsocketTestCase tearDown

## v0.13.1 (2025-07-12)

### Fix

- **deps**: replace channels-stubs with types-channels

## v0.13.0 (2025-06-07)

### Feat

- **messages**: remove outgoing group message system and simplify generic types

## v0.12.0 (2025-06-07)

### Feat

- **testing**: add receive_until_action method for flexible message collection

## v0.11.2 (2025-06-06)

### Fix

- **websocket**: use json mode for message serialization

## v0.11.1 (2025-06-02)

### Fix

- **websocket**: add AbstractBaseUser support for custom user models

## v0.11.0 (2025-05-28)

### Feat

- **event**: replace dynamic method dispatch with receive_event for channel events

## v0.10.0 (2025-05-27)

### Feat

- **event**: add typed channel event system with static type checking
- **generic**: add generic type parameters and simplify message architecture

## v0.9.0 (2025-05-15)

### Feat

- **playground**: camelize websocket endpoint responses and update affected variables

## v0.8.0 (2025-05-15)

### Feat

- **path_param**: support for django path converter param within angle bracket

## v0.7.1 (2025-05-15)

### Fix

- **docs**: update testing docs to remind user to set SEND_COMPLETION to true for properly testing

## v0.7.0 (2025-05-15)

### Feat

- **routing**: migrate path and re_path from urls module to routing module for consistency and update docs

## v0.6.1 (2025-05-12)

### Fix

- **py.typed**: add py.typed to let static type checker know that chanx has fulfilled type hint

## v0.6.0 (2025-05-11)

### Feat

- **python310**: add support for python version 310
- **websocket**: add kind to broadcast_message to handle both pydantic message and json case

### Fix

- **pyright**: remove pyright section in pyproject toml and use python 310 for pyright python target version
- **sandbox**: update sandbox api schema auth and group chat serializer fields
- **docs**: only create docs if the commit message is the bump version message

## v0.5.0 (2025-05-09)

### Feat

- **pyright,urls**: add support for (based)pyright and urls path,repath utils

### Fix

- **basedpyright,yml,ci**: fix yml indent, ci branches to run and basedpyright venv path in tox
- **tox**: install camel-case for all env in tox

## v0.4.0 (2025-05-02)

### Feat

- **types**: add and update type annotations for the entire project, and install channels stubs as well

### Fix

- **dev**: migrate django-environ to environs for better typing support, and update user type hint
- **refactor**: remove redundant code or comments

## v0.3.0 (2025-04-22)

### Feat

- **camelize**: add ability to auto convert incoming and outgoing message between snake and camelcase for fe compatibility

### Fix

- **jwt**: migrate jwt packages from extra dependencies to jwt group

## v0.2.3 (2025-04-22)

### Fix

- **interrogate**: move interrogate badge to docs _static folder to serve on readthedocs

## v0.2.2 (2025-04-22)

### Refactor

- **readthedocs**: force readthedocs to install the extras package

## v0.2.1 (2025-04-22)

### Fix

- **commitizen**: add update uv.lock before bump and use shortcuts option

### Refactor

- **commitizen**: remove unused section

## v0.2.0 (2025-04-22)

## v0.1.0 (2025-04-21)

### Feat

- **authenticator**: refactor and enhance authenticator of chanx websocket consumer
- **playground**: improve playground websocket path params handling
- **chanx**: enhance authentication using drf object permission, and add path param for playground
- **utils,websocket**: create reuseable websocket utils and add transform function for playground to transform websocket route info
- **utils**: migrate and separate utils function under utils package with separate meaningful file module
- **auth,testing**: improve auth message, and add test helper as well as the first test case
- **chanx**: add routing utility and update base incoming message
- **chanx**: write workable version for chanx and create sandbox app
- **init-project**: start the chanx project

### Fix

- **group,refactor**: add some more group helper, add some more tests for group cases and some extra testing utils
- **testing**: update testing get websocket header function
- **python**: target python 3.11+ and remove support for python 3.10
- **pydantic**: force user to use pydantic v2
- **redis**: add redis to github test workflow
- **test.yml**: add postgres service to github test workflow
- **test,coverage**: update coveragerc and test command

### Refactor

- **websocket.js**: refactor big js file to multiple sub files to easier maintain and enhance
- **websocket.html**: separate websocket html to different files (html, css, js) for easier maintain and update
- **sandbox-chat**: migrate sandbox chat app to assistants
- **websocket**: authenticated request get from response without fallback to original request
