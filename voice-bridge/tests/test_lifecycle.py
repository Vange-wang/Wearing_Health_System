"""Request cancellation must close actual producers, streams and workers."""
import asyncio
import threading
import json
import time
import pytest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from app.pipeline import StreamingPipeline
from app.tts import EdgeTTS, wrap_pcm_as_wav
from app.vad import VADGate
from app.pipeline import TimingRecord
from app.llm import HermesLLM


@pytest.mark.parametrize("hold_headers", [False, True])
def test_cancel_real_blocked_httpx_read_releases_next_round(monkeypatch, hold_headers):
    """Own loopback fixture only; never 8710/8780/8781 or a real model."""
    release_server = threading.Event()
    headers_waiting = threading.Event()
    request_count = [0]
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args): pass
        def do_POST(self):
            self.close_connection = True
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            request_count[0] += 1
            call = request_count[0]
            if call == 1 and hold_headers:
                headers_waiting.set()
                release_server.wait(3)
            payload = ("data: " + json.dumps({"choices": [{"delta": {
                "content": "第一句话。" if call == 1 else "第二轮正常。"}}]}, ensure_ascii=False) + "\n\n").encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            try:
                self.wfile.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n")
                self.wfile.flush()
                if call == 1: release_server.wait(3)
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except OSError: pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    llm = HermesLLM("fixture-key", f"http://127.0.0.1:{server.server_port}/v1", "fixture")
    monkeypatch.setattr(llm, "_get_messages", lambda _: [])
    async def exercise():
        block_tts = asyncio.Event()
        class TTS:
            calls = 0
            async def stream_synthesize(self, text):
                self.calls += 1
                yield wrap_pcm_as_wav(bytes(320), 16000)
                yield wrap_pcm_as_wav(bytes(320), 16000)
                if self.calls == 1 and not hold_headers: await block_tts.wait()
        pipeline = StreamingPipeline(None, llm, TTS(), VADGate(enabled=False),
                                     tts_workers=1, sentence_gap_ms=0)
        timing = TimingRecord()
        gen = pipeline.run_text("第一轮", timing)
        try:
            opening = None
            if hold_headers:
                opening = asyncio.create_task(anext(gen))
                assert await asyncio.to_thread(headers_waiting.wait, 1)
            else:
                assert await asyncio.wait_for(anext(gen), 1)
            started = time.perf_counter()
            if opening is not None:
                opening.cancel()
                await asyncio.gather(opening, return_exceptions=True)
            await asyncio.wait_for(gen.aclose(), 1)
            quiescent = asyncio.Event()
            timing.resources.when_quiescent(quiescent.set)
            await asyncio.wait_for(quiescent.wait(), 1)
            cancel_ms = (time.perf_counter() - started) * 1000
            assert timing.resources.pending_sync == 0
            started = time.perf_counter()
            async def next_round():
                return [f async for f in pipeline.run_text("第二轮")]
            assert await asyncio.wait_for(next_round(), 1)
            print({"real_httpx_cancel_ms": round(cancel_ms, 3),
                   "held_response_headers": hold_headers,
                   "next_round_ms": round((time.perf_counter() - started) * 1000, 3),
                   "fixture_http_requests": request_count[0]})
        finally:
            block_tts.set()
            release_server.set()
            await gen.aclose()
    try:
        asyncio.run(exercise())
    finally:
        release_server.set()
        llm.close()
        server.shutdown()
        server.server_close()
        thread.join(1)


def test_response_generator_close_finishes_tasks_and_sync_read():
    async def exercise():
        release = threading.Event()
        reading = threading.Event()
        exited = threading.Event()
        tts_release = asyncio.Event()

        class Stream:
            first = True
            closed = False
            def __iter__(self): return self
            def __next__(self):
                if self.first:
                    self.first = False
                    return "第一句话。第二句话。"
                reading.set()
                try:
                    release.wait(2)
                    raise StopIteration
                finally:
                    exited.set()
            def close(self):
                self.closed = True
                release.set()

        stream = Stream()
        class LLM:
            name = "fake"
            stats = {}
            def stream_chat(self, text): return stream
        class TTS:
            closed = 0
            started = 0
            async def stream_synthesize(self, text):
                self.started += 1
                try:
                    yield wrap_pcm_as_wav(bytes(320), 16000)
                    yield wrap_pcm_as_wav(bytes(320), 16000)
                    await tts_release.wait()
                finally:
                    self.closed += 1
        tts = TTS()
        pipeline = StreamingPipeline(None, LLM(), tts, VADGate(enabled=False),
                                     tts_workers=2, sentence_gap_ms=0)
        gen = pipeline.run_text("取消")
        def tasks():
            return [t for t in asyncio.all_tasks() if not t.done() and any(
                name in getattr(t.get_coro(), "__qualname__", "")
                for name in ("._worker", "._produce"))]
        try:
            assert await asyncio.wait_for(anext(gen), 1)
            await asyncio.wait_for(gen.aclose(), 1)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert tasks() == []
            assert stream.closed
            if reading.is_set():
                assert exited.is_set(), "cancelled asyncio task is not a stopped sync read"
            assert tts.closed == tts.started
        finally:
            release.set()
            tts_release.set()
            pending = tasks()
            for task in pending: task.cancel()
            if pending: await asyncio.gather(*pending, return_exceptions=True)
            await gen.aclose()
    asyncio.run(exercise())


def test_normal_eof_reuses_http11_connection_and_late_close_is_harmless(monkeypatch):
    peers = []
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            peers.append(self.client_address)
            body = b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    llm = HermesLLM("fixture-key", f"http://127.0.0.1:{server.server_port}/v1", "fixture")
    monkeypatch.setattr(llm, "_get_messages", lambda _: [])
    try:
        first = llm.stream_chat("first")
        assert list(first) == ["ok"]
        second = llm.stream_chat("second")
        first.close()  # no shutdown of the socket now borrowed by request two
        assert list(second) == ["ok"]
        assert len(peers) == 2 and peers[0] == peers[1]
    finally:
        llm.close()
        server.shutdown()
        server.server_close()
        thread.join(1)


def test_cancel_during_preconnect_closes_created_session(monkeypatch):
    async def exercise():
        entered = asyncio.Event()
        sessions = []
        class Session:
            def __init__(self, **kwargs):
                self.connector = kwargs["connector"]
                self.closed = False
                sessions.append(self)
            async def ws_connect(self, *args, **kwargs):
                entered.set()
                await asyncio.Event().wait()
            async def close(self):
                self.closed = True
                await self.connector.close()
        monkeypatch.setattr("app.tts.aiohttp.ClientSession", Session)
        task = asyncio.create_task(EdgeTTS().open_preconnect())
        try:
            await entered.wait()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            assert sessions and all(session.closed for session in sessions)
        finally:
            for session in sessions: await session.close()
    asyncio.run(exercise())


def test_shutdown_finishes_registered_background_tasks(monkeypatch):
    from app import main
    async def exercise():
        task = asyncio.create_task(asyncio.Event().wait())
        monkeypatch.setattr(main, "_background_tasks", {task}, raising=False)
        monkeypatch.setattr(main, "llm", None)
        monkeypatch.setattr(main, "lightweight_llm", None)
        try:
            await main.shutdown()
            assert task.done()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())
