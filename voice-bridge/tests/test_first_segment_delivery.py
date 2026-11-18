"""Offline event-gated regressions for immediate audio and sentence boundaries.

Use the normal asyncio loop; no providers, credentials or network are used.
Timeouts bound a broken implementation, not a latency benchmark.
"""
import asyncio

import pytest

from app import pipeline as pipeline_module
from app.caption_protocol import CAPTION_MARKER
from app.pipeline import StreamingPipeline, TimingRecord, decode_frame
from app.router import Router
from app.tts import TTSError, wrap_pcm_as_wav


def wav(value):
    return wrap_pcm_as_wav(bytes([value, 0]) * 160, 16000)


class Reply:
    def __init__(self, parts):
        self.parts = iter(parts)
        self.commits = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.parts)

    def commit_history(self):
        self.commits += 1

    def close(self):
        self.closed = True


class LLM:
    name = "offline-fixture"
    stats = {}

    def __init__(self, parts):
        self.reply = Reply(parts)
        self.memories = []

    def stream_chat(self, text):
        return self.reply

    def extract_memory_async(self, user, reply):
        self.memories.append((user, reply))


def make_pipeline(tts, parts=("第一句。",), *, workers=1, gap_ms=0):
    llm = LLM(parts)
    pipe = StreamingPipeline(
        None, llm, tts, None, lightweight_llm=llm,
        router=Router(tool_keywords=[], skill_keywords=[]),
        tts_workers=workers, sentence_gap_ms=gap_ms,
    )
    pipe._commit_last_round("旧问题", "旧回答。", "lightweight")
    return pipe, llm, pipe._read_last_round()


async def collect(pipe, timing=None):
    return [frame async for frame in pipe.run_text("普通问题", timing)]


def audio_payloads(frames):
    result = []
    for frame in frames:
        if frame.startswith(CAPTION_MARKER):
            continue
        payload, remainder = decode_frame(frame)
        assert payload and not remainder  # no internal empty markers on the wire
        result.append(payload)
    return result


def test_first_audio_arrives_while_second_segment_is_blocked():
    async def exercise():
        class TTS:
            def __init__(self):
                self.waiting = asyncio.Event()
                self.release = asyncio.Event()
                self.closed = False

            async def stream_synthesize(self, text):
                try:
                    yield wav(1)
                    self.waiting.set()
                    await self.release.wait()
                    yield wav(2)
                finally:
                    self.closed = True

        tts = TTS()
        pipe, llm, _ = make_pipeline(tts)
        stream = pipe.run_text("普通问题")
        first = asyncio.create_task(anext(stream))
        try:
            await asyncio.wait_for(tts.waiting.wait(), 2)
            frame = await asyncio.wait_for(asyncio.shield(first), 1)
            assert not tts.release.is_set()
            assert audio_payloads([frame]) == [wav(1)]
            tts.release.set()
            assert audio_payloads([f async for f in stream]) == [wav(2)]
            assert llm.reply.commits == 1 and len(llm.memories) == 1
        finally:
            tts.release.set()
            if not first.done():
                first.cancel()
            await asyncio.gather(first, return_exceptions=True)
            await stream.aclose()
        assert tts.closed and llm.reply.closed

    asyncio.run(exercise())


@pytest.mark.parametrize("captions", [False, True])
def test_parallel_sentences_keep_order_and_exactly_one_boundary_gap(monkeypatch, captions):
    gaps = []
    original_sleep = asyncio.sleep

    async def record_gap(delay):
        gaps.append(delay)
        await original_sleep(0)

    monkeypatch.setattr(pipeline_module.asyncio, "sleep", record_gap)

    async def exercise():
        second_done = asyncio.Event()

        class TTS:
            async def stream_synthesize(self, text):
                if text == "第一句。":
                    yield wav(1)
                    await second_done.wait()
                    yield wav(2)
                else:
                    yield wav(3)
                    yield wav(4)
                    second_done.set()

        pipe, llm, _ = make_pipeline(TTS(), ("第一句。", "第二句。"), workers=2, gap_ms=37)
        timing = TimingRecord()
        timing.captions_enabled = captions
        frames, seen_gaps = [], []
        async for frame in pipe.run_text("普通问题", timing):
            frames.append(frame)
            if not frame.startswith(CAPTION_MARKER):
                seen_gaps.append(len(gaps))
        assert audio_payloads(frames) == [wav(1), wav(2), wav(3), wav(4)]
        assert gaps == [.037] and seen_gaps == [0, 0, 1, 1]
        assert timing["chunk_count"] == 4 and timing["sentence_count"] == 2
        if captions:
            assert [f.startswith(CAPTION_MARKER) for f in frames] == [False, True, False, False, True, False]
        else:
            assert len(frames) == 4
        assert llm.reply.commits == 1

    asyncio.run(asyncio.wait_for(exercise(), 3))


@pytest.mark.parametrize("failure", ["none", "before_first", "after_first", "close"])
def test_preconnect_fallback_and_failure_markers_finish_following_sentence(failure):
    async def exercise():
        class Preconnect:
            def __init__(self):
                self.closes = 0

            async def stream_synthesize(self, text):
                if failure == "before_first":
                    raise TTSError("fixture before first")
                yield wav(1)
                if failure == "after_first":
                    raise TTSError("fixture after first")

            async def close(self):
                self.closes += 1
                if failure == "close":
                    raise TTSError("fixture close")

        class TTS:
            def __init__(self):
                self.pre = Preconnect()
                self.calls = []

            async def open_preconnect(self):
                return self.pre

            async def stream_synthesize(self, text):
                self.calls.append(text)
                yield wav(1 if text == "第一句。" else 2)

        tts = TTS()
        pipe, llm, snapshot = make_pipeline(tts, ("第一句。", "第二句。"))
        frames = await asyncio.wait_for(collect(pipe), 2)
        assert audio_payloads(frames) == [wav(1), wav(2)]
        assert tts.calls == (["第一句。", "第二句。"] if failure == "before_first" else ["第二句。"])
        assert tts.pre.closes >= 1 and llm.reply.closed
        if failure in {"after_first", "close"}:
            assert llm.reply.commits == 0 and llm.memories == []
            assert pipe._read_last_round() == snapshot
        else:
            assert llm.reply.commits == 1 and len(llm.memories) == 1

    asyncio.run(exercise())


@pytest.mark.parametrize("emit_first", [False, True])
def test_regular_stream_failure_never_replays_or_commits(emit_first):
    async def exercise():
        class TTS:
            calls = 0

            async def stream_synthesize(self, text):
                self.calls += 1
                if emit_first:
                    yield wav(1)
                raise TTSError("fixture incomplete")

        tts = TTS()
        pipe, llm, snapshot = make_pipeline(tts)
        frames = await asyncio.wait_for(collect(pipe), 2)
        assert audio_payloads(frames) == ([wav(1)] if emit_first else [])
        assert tts.calls == 1
        assert llm.reply.commits == 0 and llm.memories == []
        assert pipe._read_last_round() == snapshot and llm.reply.closed

    asyncio.run(exercise())


@pytest.mark.parametrize("cancel_pending_read", [False, True])
def test_cancel_after_first_audio_closes_stream_and_preserves_snapshot(cancel_pending_read):
    async def exercise():
        closed = asyncio.Event()
        waiting = asyncio.Event()

        class TTS:
            async def stream_synthesize(self, text):
                try:
                    yield wav(1)
                    waiting.set()
                    await asyncio.Event().wait()
                finally:
                    closed.set()

        pipe, llm, snapshot = make_pipeline(TTS())
        timing = TimingRecord()
        stream = pipe.run_text("普通问题", timing)
        try:
            assert audio_payloads([await asyncio.wait_for(anext(stream), 2)]) == [wav(1)]
            await asyncio.wait_for(waiting.wait(), 2)
            if cancel_pending_read:
                pending = asyncio.create_task(anext(stream))
                await asyncio.sleep(0)
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            await asyncio.wait_for(stream.aclose(), 2)
            await asyncio.wait_for(closed.wait(), 2)
            quiescent = asyncio.Event()
            timing.resources.when_quiescent(quiescent.set)
            await asyncio.wait_for(quiescent.wait(), 2)
            assert timing.resources.pending_sync == 0
            assert llm.reply.commits == 0 and llm.memories == []
            assert pipe._read_last_round() == snapshot and llm.reply.closed
        finally:
            await stream.aclose()

    asyncio.run(exercise())
