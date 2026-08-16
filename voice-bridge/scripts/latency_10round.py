"""方向1+3 落地后 10 轮复测（延迟拆解 + 混合语料）。

口径说明：
- open_ms = 松开按键 → 服务端首帧（X-Timing 头）
- llm_ttft_ms = LLM 首 token 耗时
- tts_first_ms = 首句 TTS 首段产出耗时（预连接下从 worker 起算，不含建连，因建连已并行吸收）
"""
import asyncio
import io
import json
import sys
import wave

import httpx

sys.path.insert(0, ".")
from app.tts import EdgeTTS

# 混合语料：闲聊/问候/健康/多句回答
SENTENCES = [
    "讲个笑话给我听",        # 闲聊（多句）
    "你好",                 # 问候
    "发烧到三十九度怎么办",    # 健康
    "你会唱歌吗",            # 闲聊
    "早上好",               # 问候
    "头疼怎么办",            # 健康
    "推荐一部好看的电影",      # 闲聊（多句）
    "今天感觉怎么样",         # 闲聊
    "我最近睡眠不好",         # 健康
    "明天适合出去玩吗",        # 闲聊
]

ROUNDS = int(sys.argv[1]) if len(sys.argv) > 1 else 10


async def send(tts, text):
    wav = await tts.synthesize(text)
    with wave.open(io.BytesIO(wav)) as w:
        pcm = w.readframes(w.getnframes())
    CHUNK = 3200

    async def gen():
        for i in range(0, len(pcm), CHUNK):
            yield pcm[i:i + CHUNK]
        yield b"\x00\x00" * 3200

    async with httpx.AsyncClient(trust_env=False, timeout=120.0) as client:
        async with client.stream(
            "POST",
            "http://127.0.0.1:8710/api/v1/voice/stream",
            content=gen(),
            headers={"Content-Type": "application/octet-stream"},
        ) as resp:
            xt = json.loads(resp.headers.get("X-Timing") or "{}")
            await resp.aread()
    return xt


async def main():
    tts = EdgeTTS()
    rows = []
    print(f"{'#':>2} {'句子':18s} {'route':11s} {'open_ms':>7s} {'llm_ttft':>8s} {'tts_first':>9s}")
    print("-" * 66)
    for i in range(ROUNDS):
        text = SENTENCES[i % len(SENTENCES)]
        xt = await send(tts, text)
        o = xt.get("open_ms") or -1
        l = xt.get("llm_ttft_ms") or -1
        tf = xt.get("tts_first_ms") or -1
        route = xt.get("route") or "?"
        rows.append((o, l, tf))
        print(f"{i+1:>2} {text:18s} {route:11s} {o:>7d} {l:>8d} {tf:>9d}")

    os_ = [r[0] for r in rows if r[0] > 0]
    ls = [r[1] for r in rows if r[1] > 0]
    ts = [r[2] for r in rows if r[2] > 0]

    def stat(xs):
        return f"min={min(xs)} avg={round(sum(xs)/len(xs))} max={max(xs)}"

    print()
    print(f"== {len(rows)} 轮汇总 ==")
    print(f"open_ms:   {stat(os_)}")
    print(f"llm_ttft:  {stat(ls)}")
    print(f"tts_first: {stat(ts)}")
    print(f"open_ms ≤2000 达标: {sum(1 for x in os_ if x <= 2000)}/{len(os_)}")


if __name__ == "__main__":
    asyncio.run(main())
