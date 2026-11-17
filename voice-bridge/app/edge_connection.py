"""Own one IPv4 connector across edge-tts' session-per-attempt lifecycle."""
from contextlib import asynccontextmanager
import socket
import aiohttp
from functools import lru_cache
from types import FunctionType


def _explicit_session(*args, **kwargs):
    kwargs["trust_env"] = False
    return aiohttp.ClientSession(*args, **kwargs)


class _ScopedAiohttp:
    ClientSession = staticmethod(_explicit_session)

    def __getattr__(self, name):
        return getattr(aiohttp, name)


@lru_cache(maxsize=2)
def _explicit_session_factory(factory):
    """Reuse pinned upstream stream bytecode with request-local session routing.

    No installed library or global aiohttp module is modified. Authentication,
    response parsing and retry logic remain the upstream implementation.
    """
    original = factory._Communicate__stream
    scope = dict(original.__globals__)
    scope["aiohttp"] = _ScopedAiohttp()
    stream = FunctionType(original.__code__, scope, original.__name__,
                          original.__defaults__, original.__closure__)
    stream.__kwdefaults__ = original.__kwdefaults__
    return type("ExplicitSessionCommunicate", (factory,), {"_Communicate__stream": stream})


class CommunicateConnector(aiohttp.TCPConnector):
    """edge-tts may close a session before its built-in 403 retry.

    Sessions borrow this connector; the enclosing Communicate request releases
    it exactly once. No global aiohttp or installed dependency is patched.
    """
    async def close(self, *args, **kwargs):
        # ClientSession's default ownership cannot be configured through the
        # installed Communicate API. Its close must not end the request pool.
        return None

    async def release(self):
        await super().close()


@asynccontextmanager
async def owned_communicate(factory, **kwargs):
    connector = CommunicateConnector(family=socket.AF_INET)
    try:
        yield _explicit_session_factory(factory)(connector=connector, **kwargs)
    finally:
        await connector.release()
