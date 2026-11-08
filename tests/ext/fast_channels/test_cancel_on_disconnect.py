"""A consumer can cancel its in-flight handlers when the client goes away."""

import asyncio
from collections.abc import Iterator
from typing import Literal

import pytest
from chanx.core.decorators import ws_handler
from chanx.fast_channels.testing import WebsocketCommunicator
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer
from chanx.messages.base import BaseMessage
from chanx.utils.asyncio import global_background_tasks
from fastapi import FastAPI

from fast_channels.layers import InMemoryChannelLayer, register_channel_layer

LAYER_ALIAS = "cancel_on_disconnect_memory"


class WorkMessage(BaseMessage):
    action: Literal["work"] = "work"
    payload: None = None


class Progress:
    """What the slow handler got to, reset per test so it binds to that test's loop."""

    started: asyncio.Event
    outcome: list[str]


progress = Progress()


class SlowConsumer(AsyncJsonWebsocketConsumer):
    channel_layer_alias = LAYER_ALIAS

    @ws_handler
    async def handle_work(self, _message: WorkMessage) -> None:
        progress.started.set()
        try:
            await asyncio.sleep(5)
            progress.outcome.append("finished")
        except asyncio.CancelledError:
            progress.outcome.append("cancelled")
            raise


class CancellingConsumer(SlowConsumer):
    cancel_handlers_on_disconnect = True


app = FastAPI()
app.router.add_websocket_route("/ws/slow", SlowConsumer.as_asgi())
app.router.add_websocket_route("/ws/cancelling", CancellingConsumer.as_asgi())


@pytest.fixture(autouse=True)
def memory_layer() -> Iterator[None]:
    register_channel_layer(LAYER_ALIAS, InMemoryChannelLayer())
    progress.started = asyncio.Event()
    progress.outcome = []
    yield
    for task in list(global_background_tasks):
        task.cancel()


async def _start_work_then_leave(path: str, consumer: type[SlowConsumer]) -> None:
    comm = WebsocketCommunicator(app, path, consumer=consumer)
    await comm.connect()
    await comm.send_json_to({"action": "work"})
    await asyncio.wait_for(progress.started.wait(), timeout=2)
    await comm.disconnect()
    await asyncio.sleep(0.1)


async def test_handlers_are_cancelled_when_enabled() -> None:
    await _start_work_then_leave("/ws/cancelling", CancellingConsumer)
    assert progress.outcome == ["cancelled"]


async def test_handlers_keep_running_by_default() -> None:
    await _start_work_then_leave("/ws/slow", SlowConsumer)
    assert progress.outcome == []
