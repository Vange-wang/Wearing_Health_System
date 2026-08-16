"""首帧语音延迟拆解测量（2026-08-16 延迟优化查证）。

测量目标：把 pipeline tts_first_ms（报告值 ~1111ms，实测波动大）拆成
「WSS 建连 + speech.config」与「ssml 发出 → 首个 audio chunk」两段，
并验证「WSS 预连接 + ssml 延迟发送」协议在 edge-tts 7.2.8 DRM 下可行。

  A. 生产路径：EdgeTTS.stream_synthesize 首段 WAV 产出耗时（= tts_first_ms 口径）
  B. 原生 Communicate：冷启动 → 首个 audio chunk 到达（含建连）
  C. 预连接模拟：建 WSS + 发 speech.config（计 t_open），等 0.5s
     （模拟 LLM 首句还在生成）再发 ssml，测「ssml 发出 → 首 chunk」净耗时

用法：venv/Scripts/python.exe measure_first_audio.py [轮数，默认5]
"""
import asyncio
import ssl
import sys
import time
from xml.sax.saxutils import escape

import aiohttp
import certifi

sys.path.insert(0, ".")
from app.tts import EdgeTTS  # noqa: E402
import edge_tts  # noqa: E402
from edge_tts.communicate import (  # noqa: E402
    connect_id,
    date_to_string,
    get_headers_and_data,
    mkssml,
    ssml_headers_plus_data,
)
from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL  # noqa: E402
from edge_tts.drm import DRM  # noqa: E402

TEXT = "嗯，最近睡得还不错哦，继续保持呀！"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
SSL_CTX = ssl.create_default_context(cafile=certifi.where())


def speech_config_msg() -> str:
    return (
        f"X-Timestamp:{date_to_string()}\r\n"
        "Content-Type:application/json; charset=utf-8\r\n"
        "Path:speech.config\r\n\r\n"
        '{"context":{"synthesis":{"audio":{"metadataoptions":{'
        '"sentenceBoundaryEnabled":"true","wordBoundaryEnabled":"false"'
        "},"
        '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"'
        "}}}}\r\n"
    )


# 与生产 wire 格式一致：纯文本（edge-tts 7.2.8 已移除自定义 SSML，不可用 build_ssml，
# 否则 SSML 标记被 escape 成正文朗读、时长×10——zcode 复核数据更正）
_comm = edge_tts.Communicate(
    TEXT,
    voice="zh-CN-XiaoxiaoNeural",
    rate="-5%",
    pitch="+0Hz",
)
WIRE_SSML = mkssml(_comm.tts_config, escape(list(_comm.texts)[0].decode()))


def stats(xs):
    xs = [round(x * 1000) for x in xs]
    return f"min={min(xs)}ms avg={round(sum(xs)/len(xs))}ms max={max(xs)}ms"


async def measure_production(tts):
    """A：生产路径首段（stream_synthesize 首个 yield）。"""
    t0 = time.perf_counter()
    async for _seg in tts.stream_synthesize(TEXT):
        return time.perf_counter() - t0
    return None


async def measure_native():
    """B：原生 Communicate 冷启动 → 首 audio chunk（含建连+config+ssml）。"""
    t0 = time.perf_counter()
    comm = edge_tts.Communicate(
        TEXT,
        voice="zh-CN-XiaoxiaoNeural",
        rate="-5%",
        pitch="+0Hz",
    )
    first_audio = None
    total = 0
    async for ch in comm.stream():
        if ch["type"] == "audio":
            total += len(ch["data"])
            if first_audio is None:
                first_audio = time.perf_counter() - t0
    return first_audio, time.perf_counter() - t0, total


async def measure_preconnect(wait_s: float):
    """C：预连接建 WSS + speech.config，wait 后发 ssml → 首 audio chunk。

    返回 (t_open 建连耗时, ssml→首chunk 净耗时, 首chunk字节数)。
    """
    t0 = time.perf_counter()
    async with aiohttp.ClientSession(trust_env=False) as session:
        async with session.ws_connect(
            f"{WSS_URL}&ConnectionId={connect_id()}"
            f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
            f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}",
            compress=15,
            headers=DRM.headers_with_muid(WSS_HEADERS),
            ssl=SSL_CTX,
        ) as ws:
            t_open = time.perf_counter() - t0
            await ws.send_str(speech_config_msg())
            await asyncio.sleep(wait_s)  # 模拟「LLM 首句还在生成」
            t1 = time.perf_counter()
            await ws.send_str(
                ssml_headers_plus_data(connect_id(), date_to_string(), WIRE_SSML)
            )
            first_audio = None
            got = 0
            first_size = 0
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.BINARY and len(msg.data) >= 2:
                    hlen = int.from_bytes(msg.data[:2], "big")
                    params, data = get_headers_and_data(msg.data, hlen)
                    if params.get(b"Path") == b"audio" and data:
                        if first_audio is None:
                            first_audio = time.perf_counter() - t1
                            first_size = len(data)
                        got += len(data)
                        if got > 8000:
                            break
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    d = msg.data.encode("utf-8")
                    params, _ = get_headers_and_data(d, d.find(b"\r\n\r\n"))
                    if params.get(b"Path") == b"turn.end":
                        break
            return t_open, first_audio, first_size


async def main():
    tts = EdgeTTS("zh-CN-XiaoxiaoNeural")
    a_first, b_audio, b_total, c_open, c_after = [], [], [], [], []
    fails = 0
    for i in range(N):
        try:
            fa = await measure_production(tts)
            fb, tb, sz = await measure_native()
            co, ca, cs = await measure_preconnect(0.5)
            if fa is None or fb is None or ca is None:
                raise RuntimeError(f"空结果 A={fa} B={fb} C={ca}")
            a_first.append(fa)
            b_audio.append(fb)
            b_total.append(tb)
            c_open.append(co)
            c_after.append(ca)
            print(
                f"[{i+1}] A生产首段={fa*1000:.0f}ms | B冷启动首chunk={fb*1000:.0f}ms"
                f" 整句={tb*1000:.0f}ms({sz}B) | C预连接建连={co*1000:.0f}ms"
                f" ssml后首chunk={ca*1000:.0f}ms({cs}B)",
                flush=True,
            )
        except Exception as e:
            fails += 1
            print(f"[{i+1}] FAIL: {type(e).__name__}: {e}", flush=True)
        await asyncio.sleep(0.4)

    ok = N - fails
    if ok:
        print(f"\n== {ok} 轮汇总（{fails} 失败）==")
        print(f"A 生产路径首段(tts_first口径): {stats(a_first)}")
        print(f"B 冷启动首chunk(含建连):       {stats(b_audio)}")
        print(f"B 整句完成:                    {stats(b_total)}")
        print(f"C 预连接建连(可被LLM等待吸收): {stats(c_open)}")
        print(f"C ssml发出→首chunk(净等待):    {stats(c_after)}")


if __name__ == "__main__":
    asyncio.run(main())
