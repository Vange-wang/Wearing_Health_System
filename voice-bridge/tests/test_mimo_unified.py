"""Offline provider contracts; no real credentials, network or audio files."""
import asyncio
import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace as NS
import wave

import numpy as np
import pytest

from app import mimo_asr, mimo_llm
from app.asr import ASRError
from app.llm import LLMError, ConversationHistory


class PureLoop(asyncio.SelectorEventLoop):
    """Tests have no OS I/O: avoid Windows sandbox socketpair during loop init."""
    def _make_self_pipe(self): pass
    def _close_self_pipe(self): pass
    def _write_to_self(self): pass


def run(coro):
    loop = PureLoop()
    loop._selector.select = lambda timeout=None: []
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(mimo_asr, "read_mimo_settings", lambda: "fixture-only-key")
    return mimo_asr.MiMoBufferedASR(max_bytes=480000, timeout=15)


def test_whole_recording_signal_not_last_block(provider):
    stream = provider.create_stream()
    samples = np.array([-1, .5, 0, 0], dtype=np.float32)
    provider.accept(stream, samples)
    provider.accept(stream, np.zeros(16, dtype=np.float32))
    metrics = mimo_asr.pcm_signal(stream.pcm)
    assert metrics["samples"] == 20 and metrics["peak"] == 32768
    assert metrics["nonzero"] == 2 and metrics["rms"] > 0
    provider.close_stream(stream)
    assert stream.closed and not stream.pcm


def test_wav_is_16k_pcm16_mono_and_payload_is_pinned(provider):
    pcm = np.array([-32768, -1, 0, 32767], dtype="<i2").tobytes()
    payload = mimo_asr._payload(pcm)
    assert payload["model"] == "mimo-v2.5-asr" and payload["stream"] is False
    assert payload["asr_options"] == {"language": "zh"}
    data = payload["messages"][0]["content"][0]["input_audio"]["data"]
    with wave.open(io.BytesIO(base64.b64decode(data.split(",", 1)[1])), "rb") as wav:
        assert (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) == (16000, 2, 1)
        assert wav.readframes(4) == pcm


@pytest.mark.parametrize("mode", ["ok", "empty", "http", "malformed", "oversize", "cancel"])
def test_async_lifecycle_and_safe_errors(provider, monkeypatch, caplog, mode):
    flags = dict(session_closed=False, response_closed=False)
    class Content:
        async def iter_any(self):
            if mode == "cancel": raise asyncio.CancelledError()
            if mode == "oversize": yield bytes(1024 * 1024 + 1); return
            if mode == "malformed": yield b"synthetic-private"; return
            yield json.dumps({"model": "mimo-v2.5-asr", "choices": [{"message": {"content": "" if mode == "empty" else "fixture"}}]}).encode()
    class Response:
        status = 401 if mode == "http" else 200
        content = Content()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): flags["response_closed"] = True
    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): flags["session_closed"] = True
        def post(self, url, **kwargs):
            assert url == "https://api.xiaomimimo.com/v1/chat/completions"
            assert kwargs["allow_redirects"] is False and kwargs["ssl"] is mimo_asr._SSL
            assert kwargs["headers"] == {"api-key": "fixture-only-key"}
            return Response()
    monkeypatch.setattr(mimo_asr.aiohttp, "TCPConnector", lambda **kw: object())
    monkeypatch.setattr(mimo_asr.aiohttp, "ClientSession", Client)
    stream = provider.create_stream()
    provider.accept(stream, np.array([.5, 0], dtype=np.float32))
    if mode in {"ok", "empty"}:
        assert run(provider.final_async(stream)) == ("fixture" if mode == "ok" else "")
    elif mode == "cancel":
        with pytest.raises(asyncio.CancelledError): run(provider.final_async(stream))
    else:
        with pytest.raises(ASRError) as error: run(provider.final_async(stream))
        assert "synthetic-private" not in str(error.value) and "fixture-only-key" not in str(error.value)
    assert all(flags.values()) and stream.closed and not stream.pcm
    assert "fixture-only-key" not in caplog.text and "synthetic-private" not in caplog.text
    if mode == "empty": assert "whole_request" in caplog.text and '"nonzero": 1' in caplog.text


def test_input_limit_and_reuse_rejected(provider):
    stream = provider.create_stream()
    stream.limit = 2
    with pytest.raises(ASRError): provider.accept(stream, np.ones(2, dtype=np.float32))
    provider.close_stream(stream)
    with pytest.raises(ASRError): provider.accept(stream, np.zeros(1, dtype=np.float32))


def test_disconnect_cancels_cloud_before_return(provider):
    stream = provider.create_stream()
    closed = []
    async def cloud(_):
        try: await asyncio.Event().wait()
        finally: closed.append(True)
    provider.final_async = cloud
    class Request:
        async def is_disconnected(self): return True
    with pytest.raises(asyncio.CancelledError): run(provider.final_for_request(stream, Request()))
    assert closed == [True] and stream.closed


@pytest.mark.parametrize("finish", ["stop", None, "length", "content_filter", "tool_calls"])
def test_llm_only_content_requires_stop_and_closes(finish):
    closed = []
    captured = []
    chunks = [NS(model=mimo_llm.MODEL, choices=[NS(delta=NS(content=None, reasoning_content="synthetic-private"), finish_reason=None)]),
              NS(model=mimo_llm.MODEL, choices=[NS(delta=NS(content="fixture", reasoning_content=None), finish_reason=finish)])]
    class Response:
        def __iter__(self): return iter(chunks)
        def close(self): closed.append(True)
    class SDK:
        def __init__(self): self.chat = NS(completions=NS(create=self.create))
        def create(self, **kwargs): captured.append(kwargs); return Response()
        def close(self): pass
    sdk = SDK()
    llm = mimo_llm.MiMoLLM.__new__(mimo_llm.MiMoLLM)
    llm.client = mimo_llm._PinnedClient(sdk)
    llm.conversation_history = ConversationHistory()
    llm._get_messages = lambda text: [{"role": "user", "content": text}]
    llm.last_call_ok = None
    stream = llm.stream_chat("public fixture")
    if finish == "stop":
        assert list(stream) == ["fixture"] and llm.last_call_ok is True
    else:
        with pytest.raises(LLMError): list(stream)
        assert not llm.conversation_history.snapshot()
    assert closed and sdk.max_retries == 0
    assert captured[0]["model"] == "mimo-v2.6-pro"
    assert captured[0]["stream"] is True
    assert captured[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_pinned_client_safe_exception():
    def broken(**kwargs): raise ValueError("synthetic-private fixture-only-key")
    sdk = NS(chat=NS(completions=NS(create=broken)))
    with pytest.raises(LLMError) as error:
        mimo_llm._PinnedClient(sdk).create(model="deepseek-chat", max_tokens=1)
    assert "synthetic" not in str(error.value)


def test_factories_never_read_old_keys(monkeypatch):
    from app.asr import create_asr, create_streaming_asr
    from app.llm import create_llm, create_lightweight_llm
    monkeypatch.setattr(mimo_asr, "read_mimo_settings", lambda: "fixture")
    made = []
    monkeypatch.setattr(mimo_llm, "MiMoLLM", lambda *a, **kw: made.append((a, kw)) or "mimo")
    cfg = NS(asr_engine="mimo", llm_engine="mimo", lw_engine="mimo", asr_sample_rate=16000,
             pipeline_max_input_bytes=512000, pipeline_max_input_seconds=15, asr_mimo_timeout=15,
             user_profile_path=Path("fixture-profile"))
    assert create_asr(cfg).name == "mimo" and create_streaming_asr(cfg).name == "mimo"
    assert create_llm(cfg) == "mimo" and create_lightweight_llm(cfg) == "mimo"
    assert len(made) == 2


def test_memory_wav_no_file_and_rewind(monkeypatch):
    # Exercise main's exact helpers without importing configuration or secrets.
    import ast
    from app.asr import read_wav_16k_mono
    source = Path(__file__).resolve().parents[1] / "app/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"_wav_input", "_close_wav_input"}]
    ns = dict(io=io, asr=NS(name="mimo"))
    exec(compile(ast.fix_missing_locations(ast.Module(body=helpers, type_ignores=[])), "helpers", "exec"), ns)
    payload = mimo_asr._payload(bytes(32))
    raw = base64.b64decode(payload["messages"][0]["content"][0]["input_audio"]["data"].split(",")[1])
    wav = ns["_wav_input"](raw)
    assert isinstance(wav, io.BytesIO)
    assert read_wav_16k_mono(wav).size == 16
    assert read_wav_16k_mono(wav).size == 16
    ns["_close_wav_input"](wav)
    assert wav.closed


@pytest.mark.parametrize("mode", ["success", "empty", "cloud_error", "odd", "too_large", "idle", "cancel"])
def test_actual_raw_route_clears_buffer_and_lock(provider, monkeypatch, mode):
    import ast
    import logging
    import time
    from app.audio_input import VoiceSessionLock, bounded_chunks, AudioInputTooLarge, AudioInputIdleTimeout
    from app.response_owner import VoiceStreamOwner, OwnedStreamingResponse
    from app.first_frame import first_frame_or_disconnect
    from app.pipeline import TimingRecord, NoSpeechError, FrameTooLargeError
    from app.tts import TTSError
    source = Path(__file__).resolve().parents[1] / "app/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    route = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "voice_stream")
    route.decorator_list = []
    buffers = []
    original_create = provider.create_stream
    def create():
        result = original_create()
        buffers.append(result)
        return result
    monkeypatch.setattr(provider, "create_stream", create)
    async def final(stream):
        if mode == "cloud_error": raise ASRError("MiMo ASR HTTP 503")
        if mode == "cancel": raise asyncio.CancelledError()
        return "" if mode == "empty" else "public fixture"
    monkeypatch.setattr(provider, "final_async", final)
    class Request:
        headers = {}
        async def receive(self):
            await asyncio.Event().wait()  # connected client after body is consumed
        async def stream(self):
            yield bytes(3 if mode == "odd" else 8)
            if mode == "idle": await asyncio.Event().wait()
        async def is_disconnected(self): return False
    class Pipeline:
        async def run_text(self, text, timing):
            timing["llm_backend"] = "mimo"
            yield b"fixture-frame"
    lock = VoiceSessionLock()
    ns = dict(Request=object, streaming_asr=provider, pipeline=Pipeline(), voice_session_lock=lock,
              VoiceStreamOwner=VoiceStreamOwner, OwnedStreamingResponse=OwnedStreamingResponse,
              first_frame_or_disconnect=first_frame_or_disconnect,
              time=time, np=np, asyncio=asyncio, json=json,
              cfg=NS(pipeline_max_input_bytes=2 if mode == "too_large" else 100,
                     asr_sample_rate=16000, pipeline_max_input_seconds=15,
                     pipeline_stream_idle_timeout_seconds=.001),
              bounded_chunks=bounded_chunks, AudioInputTooLarge=AudioInputTooLarge,
              AudioInputIdleTimeout=AudioInputIdleTimeout, ASRError=ASRError,
              logger=logging.getLogger("fixture-route"), _ms=lambda _: 1,
              TimingRecord=TimingRecord, NoSpeechError=NoSpeechError, LLMError=LLMError,
              TTSError=TTSError, FrameTooLargeError=FrameTooLargeError,
              _err=lambda code, error, detail: NS(status_code=code, error=error))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[route], type_ignores=[])), "raw-route", "exec"), ns)
    async def exercise():
        response = await ns["voice_stream"](Request())
        if mode == "success":
            assert response.status_code == 200
            assert [part async for part in response.body_iterator] == [b"fixture-frame"]
        else:
            assert response.status_code == {"empty": 400, "cloud_error": 502, "odd": 400, "too_large": 413, "idle": 408}[mode]
    if mode == "cancel":
        with pytest.raises(asyncio.CancelledError): run(exercise())
    else:
        run(exercise())
    assert buffers and all(stream.closed and not stream.pcm for stream in buffers)
    assert not lock.locked()


def test_deepseek_factory_uses_its_own_key(monkeypatch):
    from app import llm
    captured = []
    monkeypatch.setattr(mimo_llm, "DeepSeekVoiceLLM", lambda *a, **kw: captured.append((a, kw)) or "deepseek")
    cfg = NS(llm_engine="deepseek", lw_engine="deepseek", lw_base_url="https://api.deepseek.com",
             lw_model="deepseek-chat", user_profile_path=Path("fixture-profile"),
             lightweight_api_key=lambda: "fixture-deepseek-key")
    assert llm.create_llm(cfg) == "deepseek"
    assert captured[0][0][:3] == ("fixture-deepseek-key", "https://api.deepseek.com", "deepseek-chat")


@pytest.mark.parametrize("engine", ["mimo", "deepseek"])
def test_config_allows_same_selected_llm_paths(monkeypatch, tmp_path, engine):
    from app.config import Config
    monkeypatch.setattr(Config, "_read_key", lambda *args: None)
    path = tmp_path / "fixture.yaml"
    path.write_text(f"asr:\n  engine: mimo\nllm:\n  engine: {engine}\nlightweight:\n  engine: {engine}\nhealth:\n  wechat_push_enabled: false\n", encoding="utf-8")
    cfg = Config(path)
    assert cfg.asr_engine == "mimo" and cfg.llm_engine == cfg.lw_engine == engine


def test_health_reports_actual_provider_without_implying_cloud_verified(provider):
    import ast
    from app.schemas import HealthResponse, TTSHealth
    source = Path(__file__).resolve().parents[1] / "app/main.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "health")
    function.decorator_list = []
    llm = NS(name="mimo", model="mimo-v2.6-pro", last_call_ok=None, tools_available=False)
    ns = dict(asr=provider, streaming_asr=provider, llm=llm, lightweight_llm=llm,
              tts=NS(health=lambda: dict(configured_primary="mimo", active_engine="mimo", last_probe_ok=True)),
              vad=NS(enabled=True), pipeline=object(),
              app=NS(state=NS(device_auth=NS(token="fixture", degraded=False))),
              cfg=NS(tts_primary="mimo"), TTSHealth=TTSHealth, HealthResponse=HealthResponse)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), "health", "exec"), ns)
    result = ns["health"]().model_dump()
    assert result["status"] == "ok" and result["llm"] == "mimo"
    assert result["providers"]["asr"]["input_mode"] == "cloud_buffered"
    assert result["providers"]["asr"]["last_cloud_call_ok"] is None
    assert result["providers"]["llm"]["tools_available"] is False
    provider.last_call_ok = False
    assert ns["health"]().status == "degraded"
    provider.last_call_ok = True
    assert ns["health"]().status == "ok"


def test_batch_asr_uses_async_interface_and_clears_ram(provider, monkeypatch):
    raw = base64.b64decode(mimo_asr._payload(bytes(32))["messages"][0]["content"][0]["input_audio"]["data"].split(",")[1])
    seen = []
    async def final(stream):
        assert len(stream.pcm) == 32
        seen.append(stream)
        return "fixture"
    monkeypatch.setattr(provider, "final_async", final)
    assert run(provider.transcribe_async(io.BytesIO(raw))) == "fixture"
    assert seen[0].closed and not seen[0].pcm


def test_deepseek_request_cap_and_thinking_are_pinned():
    captured = []
    sdk = NS(chat=NS(completions=NS(create=lambda **kw: captured.append(kw))))
    mimo_llm._PinnedClient(sdk, "deepseek-chat").create(model="mimo-v2.6-pro", max_tokens=128)
    assert captured[0]["model"] == "deepseek-chat" and captured[0]["max_tokens"] == 128
    assert "max_completion_tokens" not in captured[0]
    assert captured[0]["extra_body"] == {"thinking": {"type": "disabled"}}
