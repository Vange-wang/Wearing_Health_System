"""预连接（方向1）关键路径测试。

覆盖 zcode 复核指出的零测试覆盖项：
1. 首句 claim 预连接（原子性：仅首句用，后续句用时建连）
2. 预连接首段失败 → 回退用时建连重合成
3. 轻量通道降级慢路径 → 预连接禁用 + 未消费连接收尾关闭
4. open_preconnect 失败（返回 None）→ 直接用时建连
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline import StreamingPipeline
from app.router import Router
from app.vad import VADGate
from app.asr import ASRBase
from app.llm import LLMBase, LLMError
from app.tts import TTSBase, TTSError, wrap_pcm_as_wav


class _FakeASR(ASRBase):
    def transcribe(self, wav_path):
        return "今天天气怎么样"


class _FakeLLM(LLMBase):
    name = "deepseek"

    def __init__(self, texts=None, fail=False):
        self._texts = texts if texts is not None else ["天气不错。"]
        self._fail = fail
        self.stats = {"tool_seen": False, "first_chunk_ms": 1, "first_content_ms": 1}

    def chat(self, t):
        return ""

    def stream_chat(self, t):
        if self._fail:
            raise LLMError("轻量通道失败")
        return iter(self._texts)


class _FakePreconn:
    """模拟预建连接对象（对应 _EdgePreconnect 的接口）。"""

    def __init__(self, fail=False):
        self._fail = fail
        self.used = 0
        self.closed = False

    async def stream_synthesize(self, text, min_segment_samples=800, later_min_segment_samples=4800):
        self.used += 1
        if self._fail:
            raise TTSError("预连接首段失败")
        yield wrap_pcm_as_wav(b"\x00\x00" * 160, 16000)

    async def close(self):
        self.closed = True


class _FakeTTS(TTSBase):
    name = "edge"

    def __init__(self, preconn, open_fail=False):
        self._preconn = preconn
        self._open_fail = open_fail
        self.stream_calls = 0

    async def synthesize(self, text):
        return wrap_pcm_as_wav(b"\x00\x00" * 160, 16000)

    async def open_preconnect(self, timeout=2.0):
        if self._open_fail:
            return None
        return self._preconn

    async def stream_synthesize(self, text, min_segment_samples=800):
        self.stream_calls += 1
        yield wrap_pcm_as_wav(b"\x00\x00" * 160, 16000)


def _make_pipeline(tts, llm=None, lightweight_llm=None):
    return StreamingPipeline(
        asr=_FakeASR(),
        llm=llm or _FakeLLM(),
        tts=tts,
        vad=VADGate(enabled=False),
        lightweight_llm=lightweight_llm if lightweight_llm is not None else _FakeLLM(),
        router=Router(tool_keywords=[], skill_keywords=[]),
    )


def _run(p, text):
    async def collect():
        frames = []
        async for f in p.run_text(text):
            frames.append(f)
        return frames

    return asyncio.run(collect())


def test_first_sentence_uses_preconn_only():
    """首句 claim 预连接，后续句用时建连（原子性：仅首句能 claim 到）。"""
    pre = _FakePreconn()
    tts = _FakeTTS(pre)
    p = _make_pipeline(tts, lightweight_llm=_FakeLLM(texts=["天气不错。", "适合出门。"]))
    frames = _run(p, "今天天气怎么样")
    assert frames
    assert pre.used == 1          # 首句走了预连接
    assert tts.stream_calls == 1  # 第二句用时建连（claim 已 used）
    assert pre.closed is True     # 预连接用完关闭


def test_preconn_first_seg_fail_falls_back():
    """预连接首段失败 → 回退用时建连重合成，不丢首句。"""
    pre = _FakePreconn(fail=True)
    tts = _FakeTTS(pre)
    p = _make_pipeline(tts)
    frames = _run(p, "今天天气怎么样")
    assert frames
    assert pre.used == 1          # 尝试过预连接
    assert tts.stream_calls == 1  # 回退用时建连
    assert pre.closed is True


def test_preconn_disabled_on_downgrade_and_closed():
    """轻量通道失败降级慢路径 → 预连接禁用 + 未消费连接收尾关闭。"""
    pre = _FakePreconn()
    tts = _FakeTTS(pre)
    # lightweight_llm 抛 LLMError → 降级 self.llm（慢路径）
    p = _make_pipeline(tts, llm=_FakeLLM(), lightweight_llm=_FakeLLM(fail=True))
    frames = _run(p, "今天天气怎么样")
    assert frames
    assert pre.used == 0          # 降级后未 claim 预连接
    assert pre.closed is True     # 收尾关闭未消费连接（无泄漏）


def test_preconn_open_fail_uses_normal_path():
    """open_preconnect 返回 None → 直接用时建连，无异常。"""
    pre = _FakePreconn()
    tts = _FakeTTS(pre, open_fail=True)
    p = _make_pipeline(tts)
    frames = _run(p, "今天天气怎么样")
    assert frames
    assert pre.used == 0          # open 失败，pre 未返回
    assert tts.stream_calls == 1  # 用时建连
