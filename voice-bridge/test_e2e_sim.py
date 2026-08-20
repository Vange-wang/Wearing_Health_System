# -*- coding: utf-8 -*-
"""模拟 box3 的端到端测试：edge-tts 合成语音 → PCM → voice-bridge → 响应帧。"""
import asyncio
import struct
import time
import edge_tts
import miniaudio
import httpx

VOICE = "zh-CN-XiaoxiaoNeural"
BASE = "http://127.0.0.1:8710"


async def synth_pcm(text: str) -> bytes:
    """用 edge-tts 合成中文语音，解码为 16kHz/16bit/mono PCM。带重试。"""
    for attempt in range(3):
        try:
            comm = edge_tts.Communicate(text, VOICE)
            mp3 = b""
            async for chunk in comm.stream():
                if chunk["type"] == "audio":
                    mp3 += chunk["data"]
            decoded = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16,
                                       nchannels=1, sample_rate=16000)
            return struct.pack(f"<{len(decoded.samples)}h", *decoded.samples)
        except Exception as e:
            print(f"  [synth] 第{attempt+1}次失败: {e}")
            if attempt < 2:
                await asyncio.sleep(2)
            else:
                raise


def parse_response(data: bytes) -> list:
    """解析响应：4 字节大端长度 + WAV 载荷，循环。"""
    frames, pos = [], 0
    while pos + 4 <= len(data):
        flen = struct.unpack(">I", data[pos:pos+4])[0]
        pos += 4
        if flen == 0 or flen > 8*1024*1024:
            break
        if pos + flen > len(data):
            break
        frames.append(data[pos:pos+flen])
        pos += flen
    return frames


async def test_voice(pcm: bytes, label: str):
    """用预合成 PCM 模拟一次 box3 语音请求。"""
    print(f"\n{'='*60}")
    print(f"[{label}] PCM: {len(pcm)} bytes ({len(pcm)/16000/2:.1f}s)")

    t1 = time.time()
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{BASE}/api/v1/voice/stream",
            content=pcm,
            headers={"Content-Type": "application/octet-stream"},
        )
    elapsed = time.time() - t1
    print(f"[{label}] HTTP {resp.status_code}, {len(resp.content)} bytes, 耗时 {elapsed:.2f}s")

    if resp.status_code != 200:
        print(f"[{label}] ❌ FAIL: {resp.text[:300]}")
        return False

    frames = parse_response(resp.content)
    wav_total = sum(len(f) for f in frames)
    print(f"[{label}] 响应帧: {len(frames)} 个, WAV 总量: {wav_total} bytes")

    if not frames:
        print(f"[{label}] ❌ FAIL: 无音频帧")
        return False

    print(f"[{label}] ✅ PASS (端到端 {elapsed:.2f}s, {len(frames)} 帧)")
    return True


async def main():
    print("=== voice-bridge 端到端模拟测试 ===")

    # 健康检查
    async with httpx.AsyncClient(timeout=5) as c:
        h = (await c.get(f"{BASE}/api/v1/health")).json()
    print(f"Health: {h['status']}, tts.last_probe_ok={h['tts'].get('last_probe_ok')}")
    if h["status"] != "ok":
        print("服务不健康，终止"); return

    # 先生成全部测试音频（避免 edge-tts 间歇断连）
    print("\n--- 预合成测试音频 ---")
    t_synth = time.time()
    pcm_hello = await synth_pcm("你好")
    print(f"  '你好': {len(pcm_hello)} bytes")
    pcm_weather = await synth_pcm("今天广州天气怎么样")
    print(f"  '今天广州天气怎么样': {len(pcm_weather)} bytes")
    print(f"  合成总耗时: {time.time()-t_synth:.2f}s")

    # 测试 1：快路径（闲聊）
    ok1 = await test_voice(pcm_hello, "快路径-闲聊")

    # 测试 2：慢路径（天气查询，命中 tool_keywords）
    ok2 = await test_voice(pcm_weather, "慢路径-天气查询")

    # 汇总
    print(f"\n{'='*60}")
    print("=== 测试汇总 ===")
    for label, ok in [("快路径-闲聊", ok1), ("慢路径-天气查询", ok2)]:
        print(f"  {label}: {'✅ PASS' if ok else '❌ FAIL'}")


if __name__ == "__main__":
    asyncio.run(main())
