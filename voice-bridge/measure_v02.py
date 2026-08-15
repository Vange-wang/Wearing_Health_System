"""v0.2 三句实测（Spec §9.3）：POST /voice/chat/stream，测 open_ms + 流式可感。"""
import io
import json
import struct
import time

import httpx

BASE = "http://127.0.0.1:8710"
FILES = [
    ("01-今天天气怎么样", "../Code文档/v0.1自测报告/audio/01-今天天气怎么样.wav"),
    ("02-帮我查一下心率", "../Code文档/v0.1自测报告/audio/02-帮我查一下心率.wav"),
    ("03-你叫什么名字", "../Code文档/v0.1自测报告/audio/03-你叫什么名字.wav"),
]


def parse_frames(data: bytes) -> int:
    n = 0
    off = 0
    while off < len(data):
        if off + 4 > len(data):
            break
        (length,) = struct.unpack(">I", data[off : off + 4])
        off += 4 + length
        n += 1
    return n


results = []
for name, path in FILES:
    with open(path, "rb") as f:
        audio = f.read()

    with httpx.Client(timeout=60.0, trust_env=False) as client:
        with client.stream(
            "POST",
            f"{BASE}/api/v1/voice/chat/stream",
            files={"audio": (path.split("/")[-1], audio, "audio/wav")},
        ) as resp:
            status = resp.status_code
            timing = json.loads(resp.headers.get("x-timing", "{}"))
            # 流式逐块读取，测首字节与末字节间隔
            first_at = last_at = None
            buf = io.BytesIO()
            for chunk in resp.iter_bytes():
                now = time.perf_counter()
                if first_at is None:
                    first_at = now
                last_at = now
                buf.write(chunk)
            stream_gap_ms = round((last_at - first_at) * 1000) if first_at else 0
            frames = parse_frames(buf.getvalue())

    results.append({
        "name": name,
        "status": status,
        "open_ms": timing.get("open_ms"),
        "asr_ms": timing.get("asr_ms"),
        "llm_ttft_ms": timing.get("llm_ttft_ms"),
        "tts_first_ms": timing.get("tts_first_ms"),
        "stream_gap_ms": stream_gap_ms,
        "frames": frames,
    })
    print(json.dumps(results[-1], ensure_ascii=False))

opens = [r["open_ms"] for r in results if r["open_ms"] is not None]
print("OPEN_MS_AVG =", round(sum(opens) / len(opens), 1) if opens else "n/a")
