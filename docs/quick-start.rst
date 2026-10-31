Quick Start
===========

Build a small chat consumer that answers pings, echoes messages, broadcasts to a group,
and receives events from your HTTP code. Pick your framework once; every tab on this page
follows it.

.. tab-set::
   :sync-group: framework

   .. tab-item:: Django
      :sync: django

      You need an existing Django project, since chanx sits on top of
      `Django Channels <https://channels.readthedocs.io/>`_.

   .. tab-item:: FastAPI
      :sync: fastapi

      Works with FastAPI, Starlette and other ASGI frameworks, using
      `fast-channels <https://fast-channels.readthedocs.io/>`_ for channel layers.

1. Install
----------

.. tab-set::
   :sync-group: framework

   .. tab-item:: Django
      :sync: django

      .. code-block:: bash

         pip install "chanx[channels]"

      This installs Django, Channels and Django REST Framework.

   .. tab-item:: FastAPI
      :sync: fastapi

      .. code-block:: bash

         pip install "chanx[fast_channels]" uvicorn

      This installs FastAPI and fast-channels.

2. Define messages
------------------

Every message is a Pydantic model with a ``Literal`` ``action``, and chanx routes incoming
JSON by that field and validates the rest. This file is the same for both frameworks;
save it as ``myapp/messages.py`` (Django) or ``messages.py`` (FastAPI).

.. code-block:: python

    from typing import Literal

    from pydantic import BaseModel

    from chanx.messages.base import BaseMessage


    class EchoPayload(BaseModel):
        message: str


    class NotificationPayload(BaseModel):
        alert: str
        level: str = "info"


    # Client -> server
    class EchoMessage(BaseMessage):
        action: Literal["echo"] = "echo"
        payload: EchoPayload


    class BroadcastMessage(BaseMessage):
        action: Literal["broadcast"] = "broadcast"
        payload: EchoPayload


    # Server -> client
    class EchoResponseMessage(BaseMessage):
        action: Literal["echo_response"] = "echo_response"
        payload: EchoPayload


    class NotificationMessage(BaseMessage):
        action: Literal["notification"] = "notification"
        payload: NotificationPayload


    # Server-side event, sent through the channel layer
    class SystemNotifyEvent(BaseMessage):
        action: Literal["system_notify"] = "system_notify"
        payload: NotificationPayload

3. Write the consumer
---------------------

Each ``@ws_handler`` handles one client message, chosen by its argument type. A returned
message goes back to the sender; ``broadcast_message`` sends to every member of the
consumer's groups. ``@event_handler`` receives events your server code sends.

.. tab-set::
   :sync-group: framework

   .. tab-item:: Django
      :sync: django

      ``myapp/consumers.py``:

      .. code-block:: python

         from chanx.channels.websocket import AsyncJsonWebsocketConsumer
         from chanx.core.decorators import channel, event_handler, ws_handler
         from chanx.messages.incoming import PingMessage
         from chanx.messages.outgoing import PongMessage

         from .messages import (
             BroadcastMessage,
             EchoMessage,
             EchoPayload,
             EchoResponseMessage,
             NotificationMessage,
             NotificationPayload,
             SystemNotifyEvent,
         )


         @channel(name="chat", description="Simple chat and echo system", tags=["demo"])
         class ChatConsumer(AsyncJsonWebsocketConsumer):
             groups = ["general_chat"]  # joined on connect

             @ws_handler(summary="Handle ping requests")
             async def handle_ping(self, message: PingMessage) -> PongMessage:
                 return PongMessage()

             @ws_handler(summary="Echo messages back to the sender")
             async def handle_echo(self, message: EchoMessage) -> EchoResponseMessage:
                 return EchoResponseMessage(
                     payload=EchoPayload(message=f"Echo: {message.payload.message}")
                 )

             @ws_handler(
                 summary="Broadcast a message to every client in the group",
                 output_type=NotificationMessage,
             )
             async def handle_broadcast(self, message: BroadcastMessage) -> None:
                 await self.broadcast_message(
                     NotificationMessage(
                         payload=NotificationPayload(
                             alert=f"Broadcast: {message.payload.message}"
                         )
                     )
                 )

             @event_handler
             async def handle_system_notify(
                 self, event: SystemNotifyEvent
             ) -> NotificationMessage:
                 return NotificationMessage(payload=event.payload)

   .. tab-item:: FastAPI
      :sync: fastapi

      ``consumers.py``:

      .. code-block:: python

         from chanx.core.decorators import channel, event_handler, ws_handler
         from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer
         from chanx.messages.incoming import PingMessage
         from chanx.messages.outgoing import PongMessage

         from messages import (
             BroadcastMessage,
             EchoMessage,
             EchoPayload,
             EchoResponseMessage,
             NotificationMessage,
             NotificationPayload,
             SystemNotifyEvent,
         )


         @channel(name="chat", description="Simple chat and echo system", tags=["demo"])
         class ChatConsumer(AsyncJsonWebsocketConsumer):
             channel_layer_alias = "default"  # registered in main.py
             groups = ["general_chat"]  # joined on connect

             @ws_handler(summary="Handle ping requests")
             async def handle_ping(self, message: PingMessage) -> PongMessage:
                 return PongMessage()

             @ws_handler(summary="Echo messages back to the sender")
             async def handle_echo(self, message: EchoMessage) -> EchoResponseMessage:
                 return EchoResponseMessage(
                     payload=EchoPayload(message=f"Echo: {message.payload.message}")
                 )

             @ws_handler(
                 summary="Broadcast a message to every client in the group",
                 output_type=NotificationMessage,
             )
             async def handle_broadcast(self, message: BroadcastMessage) -> None:
                 await self.broadcast_message(
                     NotificationMessage(
                         payload=NotificationPayload(
                             alert=f"Broadcast: {message.payload.message}"
                         )
                     )
                 )

             @event_handler
             async def handle_system_notify(
                 self, event: SystemNotifyEvent
             ) -> NotificationMessage:
                 return NotificationMessage(payload=event.payload)

      Everything except the import and ``channel_layer_alias`` is identical to the
      Django version.

4. Wire it up
-------------

.. tab-set::
   :sync-group: framework

   .. tab-item:: Django
      :sync: django

      ``settings.py``:

      .. code-block:: python

         INSTALLED_APPS = [
             "daphne",  # only for `manage.py runserver`; skip if you run uvicorn
             # ... your apps
             "channels",
             "rest_framework",
             "chanx.channels",
         ]

         ASGI_APPLICATION = "myproject.asgi.application"

         # In-memory works in one process; use channels_redis in production.
         CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

         CHANX = {"ASYNCAPI_TITLE": "My WebSocket API"}

      ``myproject/routing.py``:

      .. code-block:: python

         from channels.routing import URLRouter

         from chanx.channels.routing import path
         from myapp.consumers import ChatConsumer

         router = URLRouter([
             path("ws/chat/", ChatConsumer.as_asgi()),
         ])

      ``myproject/asgi.py``:

      .. code-block:: python

         import os

         from channels.routing import ProtocolTypeRouter
         from channels.sessions import CookieMiddleware
         from django.core.asgi import get_asgi_application

         from chanx.channels.routing import include

         os.environ.setdefault("DJANGO_SETTINGS_MODULE", "myproject.settings")
         django_asgi_app = get_asgi_application()

         application = ProtocolTypeRouter({
             "http": django_asgi_app,
             "websocket": CookieMiddleware(include("myproject.routing")),
         })

      ``myproject/urls.py``, for the AsyncAPI spec and docs page:

      .. code-block:: python

         from django.urls import include, path

         urlpatterns = [
             # ... your URLs
             path("asyncapi/", include("chanx.channels.urls")),
         ]

   .. tab-item:: FastAPI
      :sync: fastapi

      ``main.py``:

      .. code-block:: python

         from fastapi import FastAPI, Request
         from fast_channels.layers import InMemoryChannelLayer, register_channel_layer

         from chanx.fast_channels import asyncapi_docs, asyncapi_spec_json
         from chanx.fast_channels.type_defs import AsyncAPIConfig
         from consumers import ChatConsumer

         # In-memory works in one process; use RedisChannelLayer in production.
         register_channel_layer("default", InMemoryChannelLayer())

         app = FastAPI()
         app.router.add_websocket_route("/ws/chat/", ChatConsumer.as_asgi())

         asyncapi_config = AsyncAPIConfig(title="My WebSocket API")


         @app.get("/asyncapi/docs/")
         async def asyncapi_page(request: Request):
             return await asyncapi_docs(request=request, app=app, config=asyncapi_config)


         @app.get("/asyncapi/schema/")
         async def asyncapi_schema(request: Request):
             return await asyncapi_spec_json(
                 request=request, app=app, config=asyncapi_config
             )

      ``asyncapi_spec_yaml`` serves the same spec as YAML.

5. Run and try it
-----------------

.. tab-set::
   :sync-group: framework

   .. tab-item:: Django
      :sync: django

      .. code-block:: bash

         python manage.py runserver      # with daphne in INSTALLED_APPS
         uvicorn myproject.asgi:application  # or without it

   .. tab-item:: FastAPI
      :sync: fastapi

      .. code-block:: bash

         uvicorn main:app

Open ``http://localhost:8000/asyncapi/docs/`` for the generated documentation:

.. image:: _static/asyncapi-info.png
   :alt: AsyncAPI documentation generated by chanx
   :align: center

Then, in the browser console:

.. code-block:: javascript

    const ws = new WebSocket("ws://localhost:8000/ws/chat/");
    ws.onmessage = (event) => console.log(JSON.parse(event.data));

    ws.send(JSON.stringify({ action: "ping" }));
    // {action: "pong", payload: null}

    ws.send(JSON.stringify({ action: "echo", payload: { message: "Hello" } }));
    // {action: "echo_response", payload: {message: "Echo: Hello"}}

    ws.send(JSON.stringify({ action: "broadcast", payload: { message: "Hi all" } }));
    // every connected client: {action: "notification", payload: {alert: "Broadcast: Hi all", level: "info"}}

    ws.send(JSON.stringify({ action: "echo", payload: {} }));
    // {action: "error", payload: {type: "https://chanx.dev/errors/validation-failed", title: "Message failed validation",
    //   detail: "1 validation error", errors: [{keyword: "required", pointer: "/payload", property: "message", detail: "Field required"}]}}

6. Send events from your server code
------------------------------------

Push to connected clients from a view, a task or a worker. The event goes through the
channel layer to ``handle_system_notify`` in every consumer in the group.

.. tab-set::
   :sync-group: framework

   .. tab-item:: Django
      :sync: django

      .. code-block:: python

         from django.http import JsonResponse

         from myapp.consumers import ChatConsumer
         from myapp.messages import NotificationPayload, SystemNotifyEvent


         def notify(request):
             ChatConsumer.broadcast_event_sync(
                 SystemNotifyEvent(
                     payload=NotificationPayload(
                         alert="Server maintenance in 5 minutes", level="warning"
                     )
                 ),
                 groups=["general_chat"],
             )
             return JsonResponse({"status": "sent"})

      Use ``await ChatConsumer.broadcast_event(...)`` from async views.

   .. tab-item:: FastAPI
      :sync: fastapi

      Add to ``main.py``:

      .. code-block:: python

         from messages import NotificationPayload, SystemNotifyEvent


         @app.post("/notify")
         async def notify():
             await ChatConsumer.broadcast_event(
                 SystemNotifyEvent(
                     payload=NotificationPayload(
                         alert="Server maintenance in 5 minutes", level="warning"
                     )
                 ),
                 groups=["general_chat"],
             )
             return {"status": "sent"}

Next steps
----------

.. tab-set::
   :sync-group: framework

   .. tab-item:: Django
      :sync: django

      - :doc:`tutorial-django/prerequisites`: build a full app with chat, AI assistant
        streaming, background tasks and tests.
      - :doc:`user-guide/framework-integration`: authentication with DRF permissions and
        the AsyncAPI views.
      - :doc:`examples/django`: a complete project.

   .. tab-item:: FastAPI
      :sync: fastapi

      - :doc:`tutorial-fastapi/prerequisites`: build a full app with room chat,
        background jobs, multiple channel layers and tests.
      - :doc:`user-guide/framework-integration`: AsyncAPI helpers and app discovery.
      - :doc:`examples/fastapi`: a complete project.

For both: :doc:`user-guide/consumers-decorators`, :doc:`user-guide/testing`,
:doc:`user-guide/asyncapi`, and `chanx-js <https://js.chanx.dev/>`_
for a typed TypeScript client.
