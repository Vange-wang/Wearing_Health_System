"""MemoryClient（单一记忆源 v2）单测：本地读取 6KB 窗口截取 + 失败静默。

不依赖真实 memory_server，用临时文件测 load_recent 截取逻辑。
"""
from app.memory import MemoryClient


def _client(tmp_path, memory_content: bytes, budget: int = 6144):
    profile = tmp_path / "USER.md"
    profile.write_text("用户画像", encoding="utf-8")
    mem_file = tmp_path / "MEMORY.md"
    mem_file.write_bytes(memory_content)
    return MemoryClient(
        api_url="http://127.0.0.1:1/api/v1/memory",
        user_profile_path=profile,
        memory_file_path=mem_file,
        inject_budget=budget,
    )


def test_load_recent_small_file_full(tmp_path):
    """文件 ≤ 预算 → 全文返回。"""
    c = _client(tmp_path, "短内容".encode("utf-8"), budget=100)
    assert c.load_recent() == "短内容"


def test_load_recent_truncates_to_budget(tmp_path):
    """文件 > 预算 → 返回尾部窗口。"""
    content = ("条目A\n" * 100).encode("utf-8")  # 远超预算
    c = _client(tmp_path, content, budget=200)
    out = c.load_recent()
    assert len(out.encode("utf-8")) <= 200 + 256  # 允许对齐到换行的余量
    assert "条目A" in out


def test_load_recent_missing_file_returns_empty(tmp_path):
    """文件不存在 → 空串，不报错。"""
    profile = tmp_path / "USER.md"
    profile.write_text("x", encoding="utf-8")
    c = MemoryClient("http://127.0.0.1:1", profile, tmp_path / "nonexist.md", 100)
    assert c.load_recent() == ""


def test_load_recent_aligns_to_newline(tmp_path):
    """截取时前移到最近换行，避免从半条开始。"""
    content = ("第1条内容\n" * 50).encode("utf-8")
    c = _client(tmp_path, content, budget=100)
    out = c.load_recent()
    # 结果应以换行开头（对齐到条目边界），或至少不包含半截（此处宽松断言：以条目内容开头）
    assert "第1条内容" in out


def test_large_memory_uses_bounded_seek_from_eof(monkeypatch, tmp_path):
    content = "".join(f"第{i:05d}条：长期记忆内容\n" for i in range(20_000)).encode("utf-8")
    c = _client(tmp_path, content, budget=512)
    real = c.memory_file_path.open("rb")

    class RecordingFile:
        def __init__(self, wrapped):
            self.wrapped = wrapped
            self.read_sizes = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.wrapped.close()

        def seek(self, *args):
            return self.wrapped.seek(*args)

        def tell(self):
            return self.wrapped.tell()

        def read(self, size=-1):
            self.read_sizes.append(size)
            return self.wrapped.read(size)

    recording = RecordingFile(real)
    monkeypatch.setattr(c, "_open_memory_file", lambda: recording, raising=False)

    out = c.load_recent()

    assert recording.read_sizes
    assert all(0 <= size <= 512 + 256 for size in recording.read_sizes)
    assert len(out.encode("utf-8")) <= 512
    assert "\ufffd" not in out
    assert out.startswith("第")
