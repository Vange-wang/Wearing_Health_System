"""Actual ASGI handoff, Windows connection reuse and close cancellation seams."""
import asyncio
import socket
import pytest
from app import main
from app.audio_input import VoiceSessionLock
from app.pipeline import StreamingPipeline, TimingRecord
from app.tts import _EdgePreconnect, wrap_pcm_as_wav
from app.http_stream_transport import CancelScope, _Stream, current_scope, cancellable_transport
from httpcore._backends.sync import SyncStream


@pytest.mark.parametrize("endpoint", ["voice_stream", "voice_chat_stream"])
@pytest.mark.parametrize("version", ["2.3", "2.4"])
@pytest.mark.parametrize("mode", ["normal", "start_cancel", "body_cancel", "start_error", "body_error"])
def test_actual_response_handoff_cleanup(monkeypatch, tmp_path, endpoint, version, mode):
    async def run():
        from starlette.requests import Request
        from starlette.datastructures import UploadFile
        import io
        gate, send_entered = asyncio.Event(), asyncio.Event()
        timings = []
        class LLM:
            name = "fake"
            stats = {}
            def stream_chat(self, text): return iter(["第一句。"])
        class TTS:
            async def stream_synthesize(self, text):
                yield wrap_pcm_as_wav(bytes(320), 16000)
                yield wrap_pcm_as_wav(bytes(320), 16000)
                if mode != "normal": await gate.wait()
        class ASR:
            def create_stream(self): return object()
            def accept(self, *args): pass
            def partial(self, *args): return ""
            def final(self, *args): return "第一句"
            def transcribe(self, *args): return "第一句"
        asr = ASR()
        vad = type("VAD", (), {"is_speech": lambda self, samples: True})()
        pipeline = StreamingPipeline(asr, LLM(), TTS(), vad, tts_workers=1, sentence_gap_ms=0)
        def timing():
            value = TimingRecord(); timings.append(value); return value
        lock = VoiceSessionLock()
        monkeypatch.setattr(main, "pipeline", pipeline)
        monkeypatch.setattr(main, "asr", asr)
        monkeypatch.setattr(main, "llm", pipeline.llm)
        monkeypatch.setattr(main, "tts", pipeline.tts)
        monkeypatch.setattr(main, "streaming_asr", asr)
        monkeypatch.setattr(main, "TimingRecord", timing)
        monkeypatch.setattr(main, "voice_session_lock", lock)
        monkeypatch.setattr(main.tempfile, "tempdir", str(tmp_path))
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": version},
                 "http_version": "1.1", "method": "POST", "path": "/", "headers": []}
        used = False
        async def receive():
            nonlocal used
            if not used:
                used = True
                return {"type": "http.request", "body": bytes(320), "more_body": False}
            await asyncio.Event().wait()
        response = (await main.voice_stream(Request(scope, receive)) if endpoint == "voice_stream"
                    else await main.voice_chat_stream(UploadFile(io.BytesIO(wrap_pcm_as_wav(bytes(320), 16000)))))
        assert response.status_code == 200
        async def send(message):
            selected = (message["type"] == "http.response.start" if mode.startswith("start")
                        else message["type"] == "http.response.body" and bool(message.get("body")))
            if selected and mode.endswith("error"): raise OSError("fixture disconnected")
            if selected and mode.endswith("cancel"):
                send_entered.set(); await asyncio.Event().wait()
        task = asyncio.create_task(response(scope, receive, send))
        try:
            if mode.endswith("cancel"):
                await asyncio.wait_for(send_entered.wait(), 2)
                task.cancel()
            result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 2)
            if mode.endswith("cancel"): assert isinstance(result[0], asyncio.CancelledError)
            for _ in range(100):
                if not lock.locked(): break
                await asyncio.sleep(.005)
            resources = timings[0].resources
            assert not lock.locked(), "ASGI completion must close owner and release the actual quiescent lease"
            assert resources._closed
            assert resources.pending_sync == 0
            assert all(item.done() for item in resources._tasks)
        finally:
            gate.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            if timings: await timings[0].resources.aclose()
            if lock.locked(): lock.release()
    asyncio.run(run())


def test_real_reused_socket_handle_keeps_connection_identity():
    listener = socket.socket(); listener.bind(("127.0.0.1", 0)); listener.listen(2)
    peers, first, second = [], None, None
    scope = CancelScope()
    try:
        first = socket.create_connection(listener.getsockname()); peers.append(listener.accept()[0])
        old_handle = first.fileno()
        scope.register(SyncStream(first))
        first.close()
        for _ in range(128):
            second = socket.socket()
            if second.fileno() == old_handle: break
            second.close(); second = None
        assert second is not None, "fixture must actually reuse the native handle"
        second.connect(listener.getsockname()); peers.append(listener.accept()[0])
        scope.register(SyncStream(second))
        assert any(dup.getsockname() == second.getsockname() for dup, _ in scope._sockets.values())
        assert len(scope._sockets) == 2
    finally:
        scope.release_io(abort=True)
        if first is not None: first.close()
        if second is not None: second.close()
        for peer in peers: peer.close()
        listener.close()


@pytest.mark.parametrize("stage", ["ws", "session"])
@pytest.mark.parametrize("failure", ["cancel", "error"])
def test_preconnect_close_failure_can_retry(stage, failure):
    async def run():
        calls = {"ws": 0, "session": 0}
        class Resource:
            def __init__(self, name): self.name, self.closed = name, False
            async def close(self):
                calls[self.name] += 1
                if self.name == stage and calls[self.name] == 1:
                    if failure == "cancel": raise asyncio.CancelledError()
                    raise OSError("fixture close error")
                self.closed = True
        ws, session = Resource("ws"), Resource("session")
        pre = _EdgePreconnect(session, ws, None)
        await asyncio.gather(pre.close(), return_exceptions=True)
        assert session.closed or calls["session"] == 1, "WS failure must still attempt session cleanup"
        assert not pre._closed
        await pre.close()
        assert pre._closed and ws.closed and session.closed
    asyncio.run(run())


def test_preconnect_caller_cancellation_and_concurrent_retry():
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        class WS:
            calls = 0
            async def close(self):
                self.calls += 1; entered.set(); await release.wait()
        class Session:
            closed = False
            async def close(self): self.closed = True
        ws, session = WS(), Session()
        pre = _EdgePreconnect(session, ws, None)
        first = asyncio.create_task(pre.close())
        await entered.wait()
        first.cancel()
        assert isinstance((await asyncio.gather(first, return_exceptions=True))[0], asyncio.CancelledError)
        assert not pre._closed
        retry = asyncio.create_task(pre.close())
        another = asyncio.create_task(pre.close())
        release.set()
        await asyncio.gather(retry, another)
        assert pre._closed and session.closed and ws.calls == 1
    asyncio.run(run())


def test_queued_executor_cancellation_has_actual_completion():
    async def run():
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from app.stream_resources import RequestResources
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        loop.set_default_executor(executor)
        entered, release = threading.Event(), threading.Event()
        def block(): entered.set(); release.wait(2)
        blocking = loop.run_in_executor(None, block)
        while not entered.is_set(): await asyncio.sleep(.001)
        resource, invoked = RequestResources(), []
        task = asyncio.create_task(resource.call(lambda: invoked.append(True)))
        try:
            await asyncio.sleep(.01)
            task.cancel(); await asyncio.gather(task, return_exceptions=True)
            await resource.aclose()
            await asyncio.sleep(.01)
            assert resource.pending_sync == 0 and not invoked
            assert not release.is_set(), "no need to wait for unrelated running worker"
        finally:
            release.set(); await blocking
    asyncio.run(run())


def test_tls_wrapping_and_repeated_reads_share_one_lineage():
    left, right = socket.socketpair()
    scope = CancelScope()
    class Raw:
        def get_extra_info(self, name): return left if name == "socket" else None
        def read(self, *args, **kwargs): return b"fixture"
        def write(self, *args, **kwargs): pass
        def start_tls(self, *args, **kwargs): return Raw()
        def close(self): left.close()
    token = current_scope.set(scope)
    try:
        plain = _Stream(Raw())
        plain.read(1); plain.write(b"fixture")
        tls = plain.start_tls(None); tls.read(1)
        assert plain._lineage is tls._lineage
        assert len(scope._sockets) == 1
        duplicate, stream = next(iter(scope._sockets.values()))
        assert stream is tls._stream and duplicate.fileno() >= 0
        tls.close()
        assert not scope._sockets
    finally:
        current_scope.reset(token); scope.release_io(); left.close(); right.close()


def test_unsupported_httpcore_layout_is_explicit(monkeypatch):
    import httpx
    class Transport:
        closed = False
        def close(self): self.closed = True
    transport = Transport()
    monkeypatch.setattr(httpx, "HTTPTransport", lambda **kwargs: transport)
    with pytest.raises(RuntimeError, match="scoped-cancellation layout unavailable"):
        cancellable_transport()
    assert transport.closed


def test_close_that_ignores_cancel_is_bounded_and_observable():
    async def run():
        gate = asyncio.Event()
        class WS:
            async def close(self):
                while not gate.is_set():
                    try: await gate.wait()
                    except asyncio.CancelledError: pass
        class Session:
            closed = False
            async def close(self): self.closed = True
        session = Session(); pre = _EdgePreconnect(session, WS(), None)
        pre._close_timeout = .02
        try:
            with pytest.raises(TimeoutError): await asyncio.wait_for(pre.close(), .2)
            assert session.closed and not pre._closed and not pre.quiescent
            assert any(not task.done() for task in pre._close_steps.values())
            gate.set()
            await pre.close()
            assert pre.quiescent
        finally:
            gate.set()
            await pre.close()
    asyncio.run(run())


def test_cancel_real_stalled_tls_handshake():
    import httpx, threading
    from app.stream_resources import RequestResources
    listener = socket.socket(); listener.bind(("127.0.0.1", 0)); listener.listen(1)
    entered, release = threading.Event(), threading.Event()
    peers = []
    def server():
        connection, _ = listener.accept(); peers.append(connection)
        connection.recv(4096)  # real TLS ClientHello, intentionally no server handshake
        entered.set(); release.wait(2)
    thread = threading.Thread(target=server, daemon=True); thread.start()
    async def run():
        resource = RequestResources()
        with httpx.Client(transport=cancellable_transport(), timeout=5) as client:
            task = asyncio.create_task(resource.call(client.get, f"https://127.0.0.1:{listener.getsockname()[1]}"))
            try:
                while not entered.is_set(): await asyncio.sleep(.001)
                registered = [(dup.fileno(), stream.get_extra_info("socket").fileno())
                              for dup, stream in resource._transport_scope._sockets.values()]
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
                await resource.aclose()
                for _ in range(100):
                    if not resource.pending_sync: break
                    await asyncio.sleep(.005)
                if resource.pending_sync:
                    import sys, traceback
                    print({"tls_registered_fds": registered,
                           "worker_stacks": [traceback.format_stack(frame) for frame in sys._current_frames().values()
                                             if "start_tls" in "".join(traceback.format_stack(frame))]})
                assert resource.pending_sync == 0
                assert not release.is_set(), "socket shutdown must wake the actual TLS worker"
            finally:
                release.set()
                task.cancel(); await asyncio.gather(task, return_exceptions=True)
    try:
        asyncio.run(run())
    finally:
        release.set(); thread.join(1)
        for peer in peers: peer.close()
        listener.close()


@pytest.mark.parametrize("late_result", ["success", "error", "cancel"])
def test_late_close_completion_automatically_updates_real_quiescence(late_result):
    async def run():
        from app.stream_resources import RequestResources
        gate = asyncio.Event()
        class WS:
            closed = False
            async def close(self):
                while not gate.is_set():
                    try: await gate.wait()
                    except asyncio.CancelledError: pass
                if late_result == "error": raise OSError("fixture real close failure")
                if late_result == "cancel": raise asyncio.CancelledError()
                self.closed = True
        class Session:
            closed = False
            async def close(self): self.closed = True
        ws, session = WS(), Session()
        pre = _EdgePreconnect(session, ws, None); pre._close_timeout = .02
        resources = RequestResources(); resources._async_resources.append(pre)
        lock = VoiceSessionLock(); assert lock.try_acquire()
        releases = []
        def release(): releases.append(True); lock.release()
        try:
            await resources.aclose()
            resources.when_quiescent(release)
            assert lock.locked() and not pre.quiescent and session.closed
            gate.set()
            await asyncio.gather(*pre._close_steps.values(), return_exceptions=True)
            for _ in range(10): await asyncio.sleep(0)
            if late_result == "success":
                assert pre._closed and pre.quiescent and ws.closed
                assert releases == [True] and not lock.locked()
                assert lock.try_acquire(), "next request recovers without a third close"
                lock.release()
            else:
                assert not pre._closed and not pre.quiescent and lock.locked() and not releases
        finally:
            gate.set()
            if lock.locked(): lock.release()
    asyncio.run(run())
