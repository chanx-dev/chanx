:layout: landing
:description: Typed WebSocket APIs for Python. Routing, validation, broadcasting, AsyncAPI docs and typed clients for Django Channels, FastAPI and any ASGI framework.
:og:description: Typed WebSocket APIs for Python. Routing, validation, broadcasting, AsyncAPI docs and typed clients for Django Channels, FastAPI and any ASGI framework.

.. meta::
   :description: Typed WebSocket APIs for Python. Routing, validation, broadcasting, AsyncAPI docs and typed clients for Django Channels, FastAPI and any ASGI framework.

chanx
=====

.. image:: _static/brand/chanx-wordmark.svg
   :alt: chanx
   :class: hero-wordmark hero-light

.. image:: _static/brand/chanx-wordmark-dark.svg
   :alt: chanx
   :class: hero-wordmark hero-dark

.. rst-class:: lead

   Typed WebSocket APIs for Python. Write one handler per message; chanx routes,
   validates, broadcasts and documents it, and generates typed clients from the result.
   Runs on Django Channels, FastAPI, or any ASGI framework.

.. container:: buttons

   :doc:`Get started <introduction>`
   `GitHub <https://github.com/chanx-dev/chanx>`_

.. code-block:: bash

   pip install "chanx[channels]"        # Django Channels
   pip install "chanx[fast_channels]"   # FastAPI, Starlette and other ASGI frameworks

.. raw:: html

   <video class="demo-video" autoplay muted loop playsinline controls preload="metadata"
          poster="_static/chanx-demo-poster.jpg" width="1600" height="700" aria-label="A typed Python handler, the AsyncAPI docs chanx generates from it, generating a TypeScript client, and that client catching a typo">
     <source src="_static/chanx-demo.mp4" type="video/mp4">
     <img src="_static/chanx-demo.gif" alt="A typed Python handler, the AsyncAPI docs chanx generates from it, generating a TypeScript client, and that client catching a typo">
   </video>
   <script>
     // Respect reduced motion: show the poster and let the visitor press play.
     if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
       document.querySelectorAll("video.demo-video").forEach((v) => { v.removeAttribute("autoplay"); v.pause(); });
     }
   </script>

One handler per message
-----------------------

Messages are Pydantic models with a ``Literal`` action. Handlers are typed methods. The
same consumer runs on either framework; only the import changes.

.. tab-set::
   :sync-group: framework

   .. tab-item:: Django
      :sync: django

      .. code-block:: python

         from chanx.channels.websocket import AsyncJsonWebsocketConsumer
         from chanx.core.decorators import channel, ws_handler

         @channel(name="chat", description="Room chat")
         class ChatConsumer(AsyncJsonWebsocketConsumer):
             groups = ["lobby"]

             @ws_handler(output_type=ChatNotification)
             async def handle_chat(self, message: ChatMessage) -> None:
                 await self.broadcast_message(ChatNotification(payload=message.payload))

   .. tab-item:: FastAPI
      :sync: fastapi

      .. code-block:: python

         from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer
         from chanx.core.decorators import channel, ws_handler

         @channel(name="chat", description="Room chat")
         class ChatConsumer(AsyncJsonWebsocketConsumer):
             channel_layer_alias = "default"
             groups = ["lobby"]

             @ws_handler(output_type=ChatNotification)
             async def handle_chat(self, message: ChatMessage) -> None:
                 await self.broadcast_message(ChatNotification(payload=message.payload))

   .. tab-item:: Messages

      .. code-block:: python

         from typing import Literal
         from pydantic import BaseModel
         from chanx.messages.base import BaseMessage

         class ChatPayload(BaseModel):
             text: str

         class ChatMessage(BaseMessage):  # client -> server
             action: Literal["chat"] = "chat"
             payload: ChatPayload

         class ChatNotification(BaseMessage):  # server -> everyone in the group
             action: Literal["chat_notification"] = "chat_notification"
             payload: ChatPayload

What you get
------------

.. grid:: 1 2 3 3
   :gutter: 3

   .. grid-item-card:: Routing by type
      :link: user-guide/consumers-decorators
      :link-type: doc

      Incoming JSON is dispatched on its ``action`` to the handler whose argument type
      matches. No ``if``/``elif`` chains.

   .. grid-item-card:: Validation
      :link: user-guide/consumers-decorators
      :link-type: doc

      Pydantic checks every payload before your code runs; bad ones get a structured
      error reply.

   .. grid-item-card:: Groups and events
      :link: user-guide/topics
      :link-type: doc

      Broadcast to groups and topics, and push messages from views, tasks or workers
      through the channel layer.

   .. grid-item-card:: AsyncAPI 3.0 docs
      :link: user-guide/asyncapi
      :link-type: doc

      A spec and an interactive docs page generated from your handlers, so the contract
      is the code that runs.

   .. grid-item-card:: Typed clients
      :link: user-guide/client-generator
      :link-type: doc

      Generate Python clients, or TypeScript clients with React, Vue, Svelte and Solid
      bindings via chanx-js.

   .. grid-item-card:: Testing and auth
      :link: user-guide/testing
      :link-type: doc

      Test communicators for both frameworks, and authenticators that reuse DRF
      permission classes on Django.

Pick your path
--------------

.. grid:: 1 2 2 2
   :gutter: 3

   .. grid-item-card:: Django quick start
      :link: quick-start.html?framework=django

      Add chanx to an existing Django Channels project.

   .. grid-item-card:: FastAPI quick start
      :link: quick-start.html?framework=fastapi

      Consumers, channel layers and AsyncAPI on FastAPI or Starlette.

   .. grid-item-card:: Tutorials
      :link: tutorial-django/prerequisites
      :link-type: doc

      Build a full app step by step: chat, AI streaming, background jobs and tests.

   .. grid-item-card:: TypeScript clients
      :link: https://js.chanx.dev/

      chanx-js generates a typed client from your server's AsyncAPI spec.

.. toctree::
   :hidden:
   :caption: Getting Started

   introduction
   installation
   quick-start
   comparison
   ecosystem

.. toctree::
   :hidden:
   :caption: User Guide

   user-guide/prerequisites
   user-guide/consumers-decorators
   user-guide/mixins
   user-guide/topics
   user-guide/asyncapi
   user-guide/testing
   user-guide/framework-integration
   user-guide/client-generator

.. toctree::
   :hidden:
   :caption: Django Tutorial

   tutorial-django/prerequisites
   tutorial-django/cp0-initial-setup
   tutorial-django/cp1-chat-websocket
   tutorial-django/cp2-assistants-websocket
   tutorial-django/cp3-system-websocket
   tutorial-django/cp4-integration-tests

.. toctree::
   :hidden:
   :caption: FastAPI Tutorial

   tutorial-fastapi/prerequisites
   tutorial-fastapi/cp1-system-echo
   tutorial-fastapi/cp2-room-chat
   tutorial-fastapi/cp3-background-jobs
   tutorial-fastapi/cp4-multi-layer
   tutorial-fastapi/cp5-testing

.. toctree::
   :hidden:
   :caption: Examples

   examples/django
   examples/fastapi

.. toctree::
   :hidden:
   :caption: Reference

   configuration
   protocol
   reference/core
   reference/messages
   reference/routing
   reference/asyncapi
   reference/channels
   reference/fast-channels
   reference/utils
   reference/testing

.. toctree::
   :hidden:
   :caption: Development

   contributing
   changelog
