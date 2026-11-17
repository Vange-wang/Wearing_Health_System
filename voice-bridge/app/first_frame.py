"""Watch ASGI disconnect only after the upload has been completely consumed."""
import asyncio


class BeforeFirstFrameDisconnect(asyncio.CancelledError):
    """No response can be delivered; unwind the existing request owner."""


async def first_frame_or_disconnect(gen, receive):
    async def disconnected():
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return

    first = asyncio.create_task(gen.__anext__())
    watcher = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((first, watcher), return_when=asyncio.FIRST_COMPLETED)
        if watcher in done:
            watcher.result()
            raise BeforeFirstFrameDisconnect()
        return first.result()
    finally:
        # Join the cancelled generator before its owner calls aclose().
        # Cancelling the watcher on success removes the competing ASGI reader.
        for task in (first, watcher):
            if not task.done():
                task.cancel()
        await asyncio.gather(first, watcher, return_exceptions=True)
