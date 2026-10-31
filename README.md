<h1>
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/chanx-dev/chanx/main/docs/_static/brand/chanx-wordmark-dark.svg">
    <img alt="chanx" src="https://raw.githubusercontent.com/chanx-dev/chanx/main/docs/_static/brand/chanx-wordmark.svg" height="64">
  </picture>
</h1>

[![PyPI](https://img.shields.io/pypi/v/chanx)](https://pypi.org/project/chanx/)
[![Python](https://img.shields.io/pypi/pyversions/chanx)](https://pypi.org/project/chanx/)
[![Tests](https://github.com/chanx-dev/chanx/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/chanx-dev/chanx/actions/workflows/test.yml)
[![Coverage](https://codecov.io/gh/chanx-dev/chanx/branch/main/graph/badge.svg?token=X8R3BDPTY6)](https://codecov.io/gh/chanx-dev/chanx)

**Typed WebSocket APIs for Python.** Write one handler per message; chanx routes,
validates, broadcasts and documents it, and generates typed clients from the result.
Runs on Django Channels, FastAPI, or any ASGI framework.

**[Documentation](https://python.chanx.dev/)** ·
[Django quick start](https://python.chanx.dev/en/latest/quick-start.html?framework=django) ·
[FastAPI quick start](https://python.chanx.dev/en/latest/quick-start.html?framework=fastapi) ·
[TypeScript clients](https://js.chanx.dev/) ·
[Ready-made kits](https://kit.chanx.dev/)

![A typed Python handler, the AsyncAPI docs chanx generates from it, generating a TypeScript client, and that client catching a typo](https://raw.githubusercontent.com/chanx-dev/chanx/main/docs/_static/chanx-demo.gif)

## Why chanx

A raw WebSocket endpoint is one `receive` method that grows forever:

```python
async def receive(self, text_data):
    data = json.loads(text_data)
    if data.get("action") == "chat":
        if "text" not in data.get("payload", {}):
            return await self.send(json.dumps({"error": "missing text"}))
        ...  # find the room, loop over connections, send to each
    elif data.get("action") == "ping":
        ...
    # no types, no docs, and the frontend guesses the message shapes
```

With chanx, each message is a Pydantic model and each handler is a typed method:

```python
@ws_handler(output_type=ChatNotification)
async def handle_chat(self, message: ChatMessage) -> None:
    await self.broadcast_message(ChatNotification(payload=message.payload))
```

From that, chanx gives you:

- **Routing by type.** Incoming JSON is dispatched on its `action` field to the handler
  whose argument type matches. No `if`/`elif` chains.
- **Validation.** Payloads are checked by Pydantic before your code runs; bad ones get a
  structured error reply.
- **Groups and events.** Broadcast to groups, and push messages from HTTP views, tasks or
  workers through the channel layer (Redis or in-memory).
- **AsyncAPI 3.0 docs.** A spec and an interactive docs page, generated from your
  handlers, so the contract the frontend reads is the code that runs.
- **Typed clients.** Generate a Python client, a TypeScript client with React, Vue,
  Svelte and Solid bindings via [chanx-js](https://js.chanx.dev/), or a
  Go client via [chanx-go](https://go.chanx.dev/).
- **Testing and auth.** Test communicators for both frameworks, and authenticators that
  reuse your DRF permission classes on Django.
- **Static typing throughout.** Checked with mypy and pyright in strict mode, so handler
  and message mistakes show up in your editor.

## Install

```bash
pip install "chanx[channels]"        # Django Channels
pip install "chanx[fast_channels]"   # FastAPI, Starlette and other ASGI frameworks
```

Python 3.11 to 3.13. Optional extras: `chanx[cli]` for the client generator,
`chanx[client]` to run generated Python clients.

## Quick start

A room chat on FastAPI in one file. Save it as `main.py`:

```python
from typing import Literal

from fastapi import FastAPI, Request
from fast_channels.layers import InMemoryChannelLayer, register_channel_layer
from pydantic import BaseModel

from chanx.core.decorators import channel, ws_handler
from chanx.fast_channels import asyncapi_docs, asyncapi_spec_json
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer
from chanx.messages.base import BaseMessage


class ChatPayload(BaseModel):
    text: str


class ChatMessage(BaseMessage):  # client -> server
    action: Literal["chat"] = "chat"
    payload: ChatPayload


class ChatNotification(BaseMessage):  # server -> everyone in the group
    action: Literal["chat_notification"] = "chat_notification"
    payload: ChatPayload


@channel(name="chat", description="Room chat")
class ChatConsumer(AsyncJsonWebsocketConsumer):
    channel_layer_alias = "default"
    groups = ["lobby"]  # joined on connect

    @ws_handler(output_type=ChatNotification)
    async def handle_chat(self, message: ChatMessage) -> None:
        await self.broadcast_message(ChatNotification(payload=message.payload))


register_channel_layer("default", InMemoryChannelLayer())  # use Redis in production

app = FastAPI()
app.router.add_websocket_route("/ws/chat", ChatConsumer.as_asgi())


@app.get("/asyncapi")
async def docs(request: Request):
    return await asyncapi_docs(request=request, app=app)


@app.get("/asyncapi.json")
async def spec(request: Request):
    return await asyncapi_spec_json(request=request, app=app)
```

Run it with `uvicorn main:app`, open two connections to `ws://localhost:8000/ws/chat`,
and send from one:

```json
{"action": "chat", "payload": {"text": "hi"}}
```

Both receive:

```json
{"action": "chat_notification", "payload": {"text": "hi"}}
```

A malformed message (`{"action": "chat", "payload": {"txt": "hi"}}`) never reaches the
handler; the sender gets a validation error instead. The interactive docs are at
<http://localhost:8000/asyncapi>.

**On Django**, the consumer is the same class imported from
`chanx.channels.websocket`, routed with Channels, with docs from
`path("asyncapi/", include("chanx.channels.urls"))`. See the
[Django quick start](https://python.chanx.dev/en/latest/quick-start.html?framework=django).

## Typed clients

Clients are generated from the AsyncAPI spec, so they always match the server.

TypeScript, with [chanx-js](https://js.chanx.dev/):

```bash
npm install @chanx-js/client
npx @chanx-js/codegen http://localhost:8000/asyncapi.json -o src/generated
```

```tsx
import { useChannel } from '@chanx-js/client/react';
import { chat } from './generated';

function Chat() {
  const { send } = useChannel(chat);
  // `send` only accepts messages the server declares; a typo is a compile error.
  return <button onClick={() => send({ action: 'chat', payload: { text: 'hi' } })}>Say hi</button>;
}
```

Python, with the built-in generator:

```bash
pip install "chanx[cli]"
chanx generate-client --schema http://localhost:8000/asyncapi.json --output ./chat_client
```

## Ecosystem

- **[chanx-js](https://js.chanx.dev/)**: TypeScript clients for the
  browser and Node, and a TypeScript server that speaks the same protocol and can share a
  Redis layer with Python.
- **[chanx-go](https://go.chanx.dev/)**: the Go implementation, for net/http, gin, echo
  and Fiber servers, with a typed Go client generator. Go and Python processes can share
  one Redis layer.
- **[chanx-kit](https://kit.chanx.dev/)**: copy-in components built on
  chanx (notifications, chat with history, presence, agent streaming, voice), in the
  spirit of shadcn/ui.

## Learn more

- [Introduction](https://python.chanx.dev/en/latest/introduction.html) and
  [comparison with Channels and FastAPI](https://python.chanx.dev/en/latest/comparison.html)
- Tutorials: [Django](https://python.chanx.dev/en/latest/tutorial-django/prerequisites.html),
  [FastAPI](https://python.chanx.dev/en/latest/tutorial-fastapi/prerequisites.html)
- [Configuration](https://python.chanx.dev/en/latest/configuration.html) and
  [API reference](https://python.chanx.dev/en/latest/reference/core.html)
- [Changelog](https://github.com/chanx-dev/chanx/blob/main/CHANGELOG.md)

## Contributing

Issues and pull requests are welcome. See [CONTRIBUTING.md](https://github.com/chanx-dev/chanx/blob/main/CONTRIBUTING.md).

## License

BSD. See [LICENSE](https://github.com/chanx-dev/chanx/blob/main/LICENSE).
