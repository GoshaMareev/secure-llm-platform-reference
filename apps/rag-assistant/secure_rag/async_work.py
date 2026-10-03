"""Join bounded blocking work before releasing request capacity on cancellation."""

import asyncio


async def run_blocking(function, *args, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Python cannot interrupt a running worker thread. Keep its request slot
        # reserved until the fixed socket/service deadline ends the operation.
        await asyncio.shield(task)
        raise
