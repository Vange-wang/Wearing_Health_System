"""Request-scoped task/HTTP ownership; unfinished threads stay observable."""
import asyncio
import logging
import threading
import socket
import contextvars
from concurrent.futures import ThreadPoolExecutor
from .http_stream_transport import CancelScope, current_scope

logger = logging.getLogger("voice-bridge.resources")


class OwnedSyncStream:
    """Close the HTTP response even while a generator is executing next()."""
    def __init__(self, iterator, response, stats, commit):
        self._iterator = iterator
        self._response = response
        self.stats = stats
        self._commit = commit
        self._next_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._closed = False
        self._response_closed = False
        self._completed = False
        self._committed = False
        self._deferred = False

    def __iter__(self):
        return self

    def __next__(self):
        with self._next_lock:
            if self._closed:
                raise StopIteration
            try:
                return next(self._iterator)
            except StopIteration:
                if not self._closed:
                    self._completed = True
                    if not self._deferred:
                        self.commit_history()
                self._close_response()
                raise
            except BaseException:
                self._close_response()
                raise
            finally:
                if self._closed:
                    close = getattr(self._iterator, "close", None)
                    if close:
                        close()

    def defer_history_commit(self):
        self._deferred = True

    def commit_history(self):
        if self._completed and not self._closed and not self._committed:
            self._committed = True
            self._commit()

    def _close_response(self, *, abort=False):
        with self._state_lock:
            if self._response_closed:
                return
            self._response_closed = True
        close = getattr(self._response, "close", None)
        # HTTPX exposes the exact response transport. shutdown wakes a blocking
        # recv in another thread before close; closing a generator or just the
        # asyncio wrapper cannot do that. Never close the reused client/pool.
        response = getattr(self._response, "response", self._response)
        transport = getattr(response, "extensions", {}).get("network_stream")
        if abort and transport is not None:
            try:
                connection = transport.get_extra_info("socket")
                if connection is not None:
                    connection.shutdown(socket.SHUT_RDWR)
            except (OSError, AttributeError):
                pass
        if close:
            close()

    def close(self):
        self._closed = True
        # Generator.close alone cannot interrupt a concurrent blocking next.
        self._close_response(abort=True)
        if self._next_lock.acquire(blocking=False):
            try:
                close = getattr(self._iterator, "close", None)
                if close:
                    close()
            finally:
                self._next_lock.release()


class RequestResources:
    def __init__(self):
        self._tasks = set()
        self._sync_operations = set()
        self._streams = []
        self._async_resources = []
        self._state_lock = threading.Lock()
        self._closed = False
        self._callbacks = []
        self._cleanup_task = None
        self._transport_scope = CancelScope()

    def task(self, coroutine, *, resource_result=False):
        task = asyncio.create_task(coroutine)
        self._tasks.add(task)
        def done(completed):
            if resource_result and not completed.cancelled():
                try:
                    resource = completed.result()
                    if resource is not None:
                        self._async_resources.append(resource)
                except Exception:
                    pass
            self._notify_quiescent()
        task.add_done_callback(done)
        return task

    def _register_stream(self, stream):
        defer = getattr(stream, "defer_history_commit", None)
        if defer:
            defer()
        with self._state_lock:
            self._streams.append(stream)
            closed = self._closed
        if closed:
            close = getattr(stream, "close", None)
            if close:
                close()
        return stream

    async def call(self, function, *args, returns_stream=False):
        # Same executor/context boundary as asyncio.to_thread. Completion is
        # signalled by the real worker's finally, not a cancelled asyncio Future.
        # There is no extra shield/task scheduling on the normal first-frame path.
        loop = asyncio.get_running_loop()
        operation = object()
        self._sync_operations.add(operation)
        def finished():
            self._sync_operations.discard(operation)
            self._notify_quiescent()
        def invoke():
            scope_token = current_scope.set(self._transport_scope)
            try:
                result = function(*args)
                return self._register_stream(result) if returns_stream else result
            finally:
                current_scope.reset(scope_token)
                try:
                    loop.call_soon_threadsafe(finished)
                except RuntimeError:
                    pass  # process/event loop shutdown; no successor lease exists
        context = contextvars.copy_context()
        # Keep the actual concurrent Future: cancellation while queued means
        # invoke() never runs, so only its real cancelled state proves quiescence.
        # This mirrors run_in_executor's submit/wrap boundary, without a shield
        # or an extra task/tick on the normal first-frame path.
        if not hasattr(loop, "_default_executor") or getattr(loop, "_executor_shutdown_called", False):
            finished()
            raise RuntimeError("event-loop executor lifecycle unavailable")
        executor = loop._default_executor
        if executor is None:
            executor = ThreadPoolExecutor(thread_name_prefix="asyncio")
            loop.set_default_executor(executor)
        try:
            actual = executor.submit(context.run, invoke)
        except BaseException:
            finished()
            raise
        def submitted_done(completed):
            if completed.cancelled():
                try:
                    loop.call_soon_threadsafe(finished)
                except RuntimeError:
                    pass
        actual.add_done_callback(submitted_done)
        return await asyncio.wrap_future(actual, loop=loop)

    @property
    def pending_sync(self):
        return len(self._sync_operations)

    def when_quiescent(self, callback):
        self._callbacks.append(callback)
        self._notify_quiescent()

    def _notify_quiescent(self):
        if (self.pending_sync or any(not task.done() for task in self._tasks)
                or any(not getattr(resource, "quiescent", True) for resource in self._async_resources)
                or self._cleanup_task is not None and not self._cleanup_task.done()):
            return
        callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            callback()

    async def aclose(self):
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._close_impl())
            self._cleanup_task.add_done_callback(lambda _: self._notify_quiescent())
        await asyncio.shield(self._cleanup_task)

    async def _close_impl(self):
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            streams = list(self._streams)
        self._transport_scope.release_io(abort=bool(self.pending_sync))
        # Close underlying request responses, not the reused backend client.
        for stream in streams:
            close = getattr(stream, "close", None)
            if close:
                try:
                    await asyncio.to_thread(close)
                except Exception:
                    logger.exception("request stream close failed")
        # Harvest already-failed tasks as well as cancelled running tasks.
        # Their exceptions remain available to the original consumer; gathering
        # only marks ownership/observation complete during request cleanup.
        tasks = list(self._tasks)
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        seen = set()
        for resource in self._async_resources:
            if id(resource) in seen:
                continue
            seen.add(id(resource))
            notify = getattr(resource, "when_quiescent", None)
            if notify is not None:
                notify(self._notify_quiescent)
            for attempt in range(2):
                try:
                    await resource.close()
                    break
                except (Exception, asyncio.CancelledError):
                    logger.exception("request async resource close failed; attempt=%d", attempt + 1)
        # Pending executor calls are not falsely reported stopped. A late open
        # registers and closes its stream in invoke(); its done callback releases
        # the lease only after the real operation finishes.
        if self.pending_sync:
            logger.warning("request cleanup pending_sync=%d; completion not confirmed", self.pending_sync)
        self._notify_quiescent()
