"""A message collection that ends in a timeout must leave the socket usable."""

import asyncio
import time
from typing import Literal

import pytest
from chanx.core.decorators import ws_handler
from chanx.fast_channels.testing import WebsocketCommunicator
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer
from chanx.messages.base import BaseMessage
from fastapi import FastAPI


class EchoReq(BaseMessage):
    action: Literal["drain_echo"] = "drain_echo"
    payload: str


class EchoRes(BaseMessage):
    action: Literal["drain_echo_res"] = "drain_echo_res"
    payload: str


class QuietConsumer(AsyncJsonWebsocketConsumer):
    """Sends nothing until asked, so a collection has to run out its timeout."""

    send_completion = True

    @ws_handler
    async def handle_echo(self, message: EchoReq) -> EchoRes:
        return EchoRes(payload=message.payload)


app = FastAPI()
app.add_websocket_route("/ws/quiet", QuietConsumer.as_asgi())


@pytest.mark.asyncio
async def test_collection_timeout_leaves_the_connection_alive() -> None:
    """The inner receive must not expire first and cancel the application task.

    The event loop is blocked so that it wakes up past both the collection's
    deadline and the inner receive's. Without a margin between the two the
    inner one expires as well, asgiref cancels the ASGI application task, and
    the send below raises CancelledError.
    """
    async with WebsocketCommunicator(app, "/ws/quiet", consumer=QuietConsumer) as comm:
        loop = asyncio.get_running_loop()
        loop.call_later(0.45, lambda: time.sleep(0.2))

        assert await comm.receive_all_messages(timeout=0.5) == []
        assert not comm.future.cancelled()

        await comm.send_message(EchoReq(payload="still here"))
        assert await comm.receive_all_messages() == [EchoRes(payload="still here")]
