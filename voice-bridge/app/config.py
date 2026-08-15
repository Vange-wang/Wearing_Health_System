"""配置加载（config.yaml + 环境变量 + .env）。

- config.yaml：服务/模型/引擎配置（Spec §7 结构）
- DeepSeek key：环境变量 DEEPSEEK_API_KEY（Spec §7 llm.api_key_env）；
  未设置时尝试读取项目根 .env（不入库）
- 不引入 python-dotenv 等未列依赖，.env 用最小解析器读
"""
import os
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent  # voice-bridge/


class Config:
    def __init__(self, path: Path):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        self._data = data or {}

        srv = self._data.get("server", {})
        self.server_host = srv.get("host", "0.0.0.0")
        self.server_port = int(srv.get("port", 8710))

        asr = self._data.get("asr", {})
        self.asr_model_dir = BASE_DIR / asr.get("model_dir", "models/sherpa-onnx-sense-voice-zh")
        self.asr_sample_rate = int(asr.get("sample_rate", 16000))
        # v0.4 A2：流式 ASR 模型（zipformer streaming）
        self.asr_streaming_model_dir = BASE_DIR / asr.get(
            "streaming_model_dir",
            "models/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20",
        )

        tts = self._data.get("tts", {})
        self.tts_primary = tts.get("primary", "edge")
        self.tts_edge_voice = tts.get("edge_voice", "zh-CN-XiaoxiaoNeural")
        self.tts_fallback = tts.get("fallback", "piper")
        self.tts_piper_model = BASE_DIR / tts.get("piper_model", "models/piper/zh_CN-huayan-medium.onnx")
        self.tts_piper_config = BASE_DIR / tts.get("piper_config", "models/piper/zh_CN-huayan-medium.onnx.json")
        self.tts_edge_probe_timeout = float(tts.get("edge_probe_timeout", 3))

        vad = self._data.get("vad", {})
        self.vad_enabled = bool(vad.get("enabled", True))
        self.vad_rms_threshold = float(vad.get("rms_threshold", 0.005))
        self.vad_min_speech_frames = int(vad.get("min_speech_frames", 10))

        pipeline = self._data.get("pipeline", {})
        self.pipeline_sentence_max_chars = int(pipeline.get("sentence_max_chars", 50))
        self.pipeline_max_frame_bytes = int(pipeline.get("max_frame_bytes", 8 * 1024 * 1024))
        self.pipeline_comfort_text = pipeline.get("comfort_text", "好的，我查一下。")

        llm = self._data.get("llm", {})
        # 慢路径 = Hermes API Server（v0.3 起）
        self.llm_api_server_url = llm.get("api_server_url", "http://127.0.0.1:8780/v1")
        self.llm_model = llm.get("model", "hermes-agent")
        self.llm_api_key_env = llm.get("api_key_env", "HERMES_API_KEY")

        # 轻量通道 = DeepSeek 裸模型（长期 RAG，A1 修订「分路」）
        lw = self._data.get("lightweight", {})
        self.lw_base_url = lw.get("base_url", "https://api.deepseek.com")
        self.lw_model = lw.get("model", "deepseek-chat")
        self.lw_api_key_env = lw.get("api_key_env", "DEEPSEEK_API_KEY")
        self.user_profile_path = Path(
            lw.get("user_profile_path", str(Path.home() / ".hermes" / "memories" / "USER.md"))
        ).expanduser()

        # RAG 知识库
        rag = self._data.get("rag", {})
        self.rag_knowledge_dir = BASE_DIR / rag.get("knowledge_dir", "knowledge")
        self.rag_top_k = int(rag.get("top_k", 3))
        self.rag_score_threshold = float(rag.get("score_threshold", 0.0))

        # 路由判定
        router = self._data.get("router", {})
        self.router_tool_keywords = [str(k) for k in router.get("tool_keywords", [
            "查快递", "写文件", "发邮件", "定时", "搜网页", "搜索", "查天气", "查一下", "帮我查",
        ])]
        self.router_skill_keywords = [str(k) for k in router.get("skill_keywords", [])]

        self.log_level = self._data.get("log", {}).get("level", "INFO")

    def llm_api_key(self) -> str | None:
        """读取 Hermes API key：环境变量优先，其次项目 .env。"""
        return self._read_key(self.llm_api_key_env)

    def lightweight_api_key(self) -> str | None:
        """读取 DeepSeek key（轻量通道）：环境变量优先，其次项目 .env。"""
        return self._read_key(self.lw_api_key_env)

    def _read_key(self, env_name: str) -> str | None:
        key = os.environ.get(env_name)
        if key:
            return key
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == env_name:
                    return v.strip().strip('"').strip("'")
        return None


def load_config(path: Path | None = None) -> Config:
    return Config(path or (BASE_DIR / "config.yaml"))
