"""Reviewable execution tools: all effects mocked or synthetic temporary files."""
import asyncio
import base64
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "Code文档/测试报告/2026-10-14-Edge生产恢复候选-v1"


def module(name):
    spec = importlib.util.spec_from_file_location(name, BASE / (name + ".py"))
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def test_fixed_wheels_record_and_original_source_rollback():
    provenance = json.loads((BASE / "wheel-provenance.json").read_text(encoding="utf-8"))
    archives = []
    for item in (provenance["candidate"], provenance["rollback"]):
        data = (ROOT / item["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest().upper() == item["sha256"]
        archive = zipfile.ZipFile(io.BytesIO(data)); archives.append(archive)
        record_name = next(name for name in archive.namelist() if name.endswith(".dist-info/RECORD"))
        for name, digest, length in csv.reader(io.StringIO(archive.read(record_name).decode())):
            if not digest: assert name == record_name; continue
            content = archive.read(name)
            assert len(content) == int(length)
            assert digest == "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
    changed = [name for name in archives[0].namelist() if name.startswith("edge_tts/") and archives[0].read(name) != archives[1].read(name)]
    assert sorted(changed) == ["edge_tts/communicate.py", "edge_tts/constants.py", "edge_tts/drm.py"]
    assert archives[0].read("edge_tts/communicate.py") == archives[1].read("edge_tts/communicate.py").replace(b"trust_env=True", b"trust_env=False")
    for name in archives[1].namelist():
        if name.startswith("edge_tts/"):
            assert archives[1].read(name) == (ROOT / "voice-bridge/venv/Lib/site-packages" / name).read_bytes()


def test_identity_drift_prevents_install_without_any_pip(monkeypatch, tmp_path):
    tool = module("root_controlled_runtime_cdx")
    (tmp_path / "binding.json").write_text(json.dumps({"identity_fingerprint": "expected"}), encoding="utf-8")
    monkeypatch.setattr(tool, "bound_voice", lambda: (None, None, None, "changed"))
    monkeypatch.setattr(tool.subprocess, "run", lambda *a, **k: pytest.fail("pip must not execute"))
    with pytest.raises(AssertionError): tool.install(tmp_path)


def test_pip_install_fixed_hash_offline_only(monkeypatch, tmp_path):
    tool = module("root_controlled_runtime_cdx")
    (tmp_path / "binding.json").write_text(json.dumps({"identity_fingerprint": "same"}), encoding="utf-8")
    monkeypatch.setattr(tool, "bound_voice", lambda: (None, None, None, "same"))
    checked = []
    monkeypatch.setattr(tool, "installed_sources", lambda candidate: checked.append(candidate))
    monkeypatch.setattr(tool, "environment_versions", lambda: {"edge-tts": "synthetic", "aiohttp": "fixed"})
    calls = []
    def pip(args, **kwargs):
        calls.append(args)
        assert {"--isolated", "--no-index", "--no-deps", "--no-cache-dir", "--force-reinstall", "--require-hashes"}.issubset(args)
        assert kwargs["cwd"] == ROOT / "voice-bridge"
        assert "--upgrade" not in args
        return SimpleNamespace(returncode=0, stdout=b"SYNTHETIC_NOT_PERSISTED", stderr=b"")
    monkeypatch.setattr(tool.subprocess, "run", pip)
    result = tool.install(tmp_path)
    assert checked == [False, True] and len(calls) == 1 and result["service_reloaded"] is False
    assert "SYNTHETIC_NOT_PERSISTED" not in (tmp_path / "install.json").read_text()


def test_pipeline_probe_uses_actual_framing_but_fake_io_stays_red(monkeypatch, tmp_path):
    tool = module("root_e3_pipeline_probe_cdx")
    from app.tts import EdgeTTS, wrap_pcm_as_wav
    chunks = [wrap_pcm_as_wav((b"\xe8\x03\x18\xfc") * 500, 16000) for _ in range(3)]
    async def audio(self, text, *args, **kwargs):
        assert text == "测试"
        for chunk in chunks: yield chunk
    class Pre:
        quiescent = False
        stream_synthesize = audio
        async def close(self): self.quiescent = True
    async def pre(self, timeout=2): return Pre()
    monkeypatch.setattr(EdgeTTS, "stream_synthesize", audio)
    monkeypatch.setattr(EdgeTTS, "open_preconnect", pre)
    class Reader:
        def __init__(self): self.buffer = bytearray(); self.queue = asyncio.Queue()
        async def readexactly(self, length):
            while len(self.buffer) < length:
                data = await self.queue.get()
                if data is None: raise asyncio.IncompleteReadError(bytes(self.buffer), length)
                self.buffer.extend(data)
            value = bytes(self.buffer[:length]); del self.buffer[:length]; return value
    class Writer:
        def __init__(self, reader=None): self.reader = reader; self.closed = False
        def write(self, data): self.reader.queue.put_nowait(data)
        async def drain(self): await asyncio.sleep(0)
        def close(self):
            if self.reader is not None and not self.closed: self.reader.queue.put_nowait(None)
            self.closed = True
        async def wait_closed(self): pass
    class Server:
        sockets = [SimpleNamespace(getsockname=lambda: ("127.0.0.1", 12345))]
        def close(self): pass
        async def wait_closed(self): pass
    async def exercise():
        callback = None
        async def start(fn, *args, **kwargs):
            nonlocal callback
            callback = fn; return Server()
        async def connect(*args, **kwargs):
            reader = Reader()
            asyncio.create_task(callback(reader, Writer()))
            return None, Writer(reader)
        monkeypatch.setattr(asyncio, "start_server", start)
        monkeypatch.setattr(asyncio, "open_connection", connect)
        for name in tool.CASES:
            output = tmp_path / (name + ".json")
            assert await tool.case(name, output) == 1  # no real upstream evidence => never E3 PASS
            result = json.loads(output.read_text())
            assert result["stream_completed"] and result["frames"] == 3
            assert result["full_pcm"]["samples"] == 3000
            assert result["resources"]["pending_tasks"] == 0
            assert result["first_transport_write_seconds"] is not None
            assert result["first_transport_received_seconds"] is not None
    asyncio.run(exercise())
