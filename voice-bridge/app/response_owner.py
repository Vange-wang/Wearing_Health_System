"""Own the voice lease across endpoint/ASGI task handoff."""
import asyncio
from starlette.responses import StreamingResponse


class VoiceStreamOwner:
    def __init__(self, lease):
        self._lease = lease
        self._gen = self._timing = self._cleanup_task = None
        self._released = False

    def bind(self, gen, timing):
        self._gen, self._timing = gen, timing

    def _release_once(self):
        if not self._released:
            self._released = True
            self._lease.release()

    async def aclose(self):
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._close())
        await asyncio.shield(self._cleanup_task)

    async def _close(self):
        try:
            if self._gen is not None:
                await self._gen.aclose()
        finally:
            if self._timing is not None:
                resources = self._timing.resources
                try:
                    await resources.aclose()
                finally:
                    resources.when_quiescent(self._release_once)
            else:
                self._release_once()


class OwnedStreamingResponse(StreamingResponse):
    def __init__(self, content, *, owner, **kwargs):
        super().__init__(content, **kwargs)
        self.owner = owner
        self._finish_task = None

    async def _finish(self):
        try:
            close = getattr(self.body_iterator, "aclose", None)
            if close is not None:
                await close()
        finally:
            await self.owner.aclose()

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            # Even response.start failure must reach cleanup. A separate task
            # survives caller cancellation; cancellation still propagates.
            if self._finish_task is None:
                self._finish_task = asyncio.create_task(self._finish())
            await asyncio.shield(self._finish_task)
