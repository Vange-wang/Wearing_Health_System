"""Cancel only a request's blocking HTTP I/O, preserving reusable clients."""
import contextvars
import os
import socket
import ssl
import threading
import httpx
import httpcore
from httpcore._backends.sync import SyncStream

current_scope = contextvars.ContextVar("voice_http_cancel_scope", default=None)


class CancelScope:
    def __init__(self):
        self._lock = threading.Lock()
        self._sockets = {}
        self.cancelled = False

    def register(self, stream, lineage=None):
        connection = stream.get_extra_info("socket")
        if connection is None:
            raise UnsupportedTransportLayout("network stream socket cancellation unavailable")
        with self._lock:
            if self.cancelled:
                raise OSError("request cancelled before transport operation")
            # Native socket handles can be reused while a duplicate still
            # points to the old connection. TLS wrappers inherit this identity.
            key = stream if lineage is None else lineage
            if key in self._sockets:
                duplicate, _ = self._sockets[key]
                self._sockets[key] = (duplicate, stream)
                return
            # A duplicate kernel socket can shutdown a recv/TLS handshake even
            # after wrap_socket detaches the original Python socket object.
            if os.name == "nt":
                duplicate = socket.fromshare(connection.share(os.getpid()))
            else:
                duplicate = socket.socket(fileno=os.dup(connection.fileno()))
            self._sockets[key] = (duplicate, stream)

    def unregister(self, lineage):
        with self._lock:
            value = self._sockets.pop(lineage, None)
        if value is not None:
            value[0].close()

    def release_io(self, *, abort=False):
        with self._lock:
            if abort:
                self.cancelled = True
            connections, self._sockets = list(self._sockets.values()), {}
        for connection, stream in connections:
            try:
                if abort:
                    try:
                        connection.shutdown(socket.SHUT_RDWR)
                    finally:
                        stream.close()
            except OSError:
                pass
            finally:
                connection.close()

    def abort_registered(self, lineages):
        """Abort selected owned sockets without cancelling the response request.

        Weather deadline may still need to send a failure answer through TTS.
        User cancellation continues to use release_io(abort=True).
        """
        with self._lock:
            connections = [self._sockets.pop(key) for key in lineages if key in self._sockets]
        for connection, stream in connections:
            try:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                finally:
                    stream.close()
            except OSError:
                pass
            finally:
                connection.close()


class _Stream:
    def __init__(self, stream, lineage=None):
        self._stream = stream
        self._lineage = object() if lineage is None else lineage

    def _register(self):
        scope = current_scope.get()
        if scope is not None:
            scope.register(self._stream, self._lineage)

    def read(self, *args, **kwargs):
        self._register()
        return self._stream.read(*args, **kwargs)

    def write(self, *args, **kwargs):
        self._register()
        return self._stream.write(*args, **kwargs)

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self._register()
        if not isinstance(self._stream, SyncStream):
            stream = _Stream(self._stream.start_tls(ssl_context, server_hostname, timeout), self._lineage)
            stream._register()
            return stream
        connection = self._stream.get_extra_info("socket")
        if isinstance(connection, ssl.SSLSocket):
            raise UnsupportedTransportLayout("TLS-in-TLS scoped cancellation unavailable")
        stream = self
        try:
            connection.settimeout(timeout)
            # The old raw socket is detached by wrap_socket. Register the
            # actual SSL wrapper before its Windows handshake can block.
            wrapped = ssl_context.wrap_socket(connection, server_hostname=server_hostname,
                                              do_handshake_on_connect=False)
            stream = _Stream(SyncStream(wrapped), self._lineage)
            stream._register()
            wrapped.do_handshake()
            return stream
        except BaseException as exc:
            stream.close()
            if isinstance(exc, socket.timeout):
                raise httpcore.ConnectTimeout(str(exc)) from exc
            if isinstance(exc, OSError):
                raise httpcore.ConnectError(str(exc)) from exc
            raise

    def close(self):
        try:
            return self._stream.close()
        finally:
            scope = current_scope.get()
            if scope is not None:
                scope.unregister(self._lineage)

    def get_extra_info(self, info):
        return self._stream.get_extra_info(info)


class _Backend:
    def __init__(self, backend):
        self._backend = backend

    def connect_tcp(self, *args, **kwargs):
        stream = _Stream(self._backend.connect_tcp(*args, **kwargs))
        try:
            stream._register()
            return stream
        except BaseException:
            stream.close()
            raise

    def connect_unix_socket(self, *args, **kwargs):
        return _Stream(self._backend.connect_unix_socket(*args, **kwargs))

    def sleep(self, *args, **kwargs):
        return self._backend.sleep(*args, **kwargs)


class UnsupportedTransportLayout(RuntimeError):
    """The installed HTTP transport cannot provide scoped cancellation."""


def cancellable_transport():
    transport = httpx.HTTPTransport(trust_env=False)
    # A narrow seam of the installed HTTPX/httpcore versions. The dependency
    # contract tests pin this layout; no library source/global class is changed.
    pool = getattr(transport, "_pool", None)
    backend = getattr(pool, "_network_backend", None)
    if backend is None or not all(callable(getattr(backend, name, None))
                                  for name in ("connect_tcp", "connect_unix_socket", "sleep")):
        transport.close()
        raise UnsupportedTransportLayout("HTTPX/httpcore scoped-cancellation layout unavailable")
    pool._network_backend = _Backend(backend)
    return transport
