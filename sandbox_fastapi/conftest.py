from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from arq import create_pool
from arq.worker import Worker

from fast_channels.layers.registry import channel_layers

from .layers import setup_layers
from .tasks import REDIS_SETTINGS, WorkerSettings


@pytest_asyncio.fixture(scope="function")
async def bg_worker() -> Any:
    """Create a real ARQ worker for testing."""
    redis = await create_pool(REDIS_SETTINGS)

    worker = Worker(
        functions=WorkerSettings.functions,
        redis_pool=redis,
        burst=True,
        poll_delay=0.1,
    )

    yield worker
    await redis.aclose()


@pytest_asyncio.fixture(autouse=True)
async def fresh_redis_layers(worker_id: str) -> AsyncIterator[None]:
    """
    Give each test its own layers, flushed on its own event loop afterwards.

    A layer keeps loop-bound state between calls (RedisChannelLayer's per-channel
    receive locks, held until a cleaner task finishes), so one shared across tests
    fails in a later test with "bound to a different event loop".
    """
    wid = 0 if worker_id == "master" else int(worker_id.replace("gw", "")) % 16
    channel_layers.clear()
    setup_layers(True, wid)
    yield
    for alias in channel_layers.list_aliases():
        await channel_layers[alias].flush()
