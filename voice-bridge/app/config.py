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
        self.tts_edge_probe_timeout = float(tts.get("edge_probe_timeout", 3))
        self.tts_probe_interval_s = int(tts.get("probe_interval_s", 300))  # 需求1：周期探活间隔

        vad = self._data.get("vad", {})
        self.vad_enabled = bool(vad.get("enabled", True))
        self.vad_rms_threshold = float(vad.get("rms_threshold", 0.005))
        self.vad_min_speech_frames = int(vad.get("min_speech_frames", 10))

        pipeline = self._data.get("pipeline", {})
        self.pipeline_sentence_max_chars = int(pipeline.get("sentence_max_chars", 50))
        self.pipeline_max_frame_bytes = int(pipeline.get("max_frame_bytes", 8 * 1024 * 1024))
        self.pipeline_comfort_text = pipeline.get("comfort_text", "好的，我查一下。")
        self.pipeline_sentence_gap_ms = int(pipeline.get("sentence_gap_ms", 300))
        # 慢路径安抚语池（query，随机轮换，启动时预合成缓存）。快路径 ack 已删除。
        ack_cfg = pipeline.get("acknowledgements", {})
        if isinstance(ack_cfg, dict):
            self.pipeline_ack_query = [str(s) for s in ack_cfg.get("query", [])]
        else:
            # 兼容旧格式（扁平列表 → 全部归为 query 安抚语）
            self.pipeline_ack_query = [str(s) for s in ack_cfg]

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

        # 单一记忆源（v2）：Hermes 记忆为唯一正本。
        # 注入 = 本地读 USER.md（全文）+ MEMORY.md（最近部分）；写/删走 memory_server HTTP。
        memory = self._data.get("memory", {})
        self.memory_api_url = memory.get("api_url", "http://127.0.0.1:8781/api/v1/memory")
        self.memory_inject_budget = int(memory.get("inject_budget", 6144))  # 注入窗口字节预算（6KB）
        # MEMORY.md 本地路径（与 USER.md 同目录，Hermes 侧唯一正本）
        self.memory_file_path = Path(
            memory.get("file_path", str(Path.home() / ".hermes" / "memories" / "MEMORY.md"))
        ).expanduser()

        # 路由判定
        router = self._data.get("router", {})
        self.router_tool_keywords = [str(k) for k in router.get("tool_keywords", [
            "查快递", "写文件", "发邮件", "定时", "搜网页", "搜索", "查天气", "查一下", "帮我查",
        ])]
        self.router_skill_keywords = [str(k) for k in router.get("skill_keywords", [])]
        # BLE 健康数据路由（P3 DATA）：心率/血氧核心词 → 模板直答，排在 RAG 前
        self.router_data_keywords = [str(k) for k in router.get("data_keywords", ["心率", "血氧"])]
        # ASR 近音词归一（P3 修：血氧 → 血阳/学养/学样 同音误识别；血压不归一语义不同）
        self.router_asr_normalize = {str(k): str(v) for k, v in router.get("asr_normalize", {}).items()}

        # BLE 健康监测（立项 Spec §5/§6）：阈值预警 + 数据新鲜度
        health = self._data.get("health", {})
        self.health_hr_high = float(health.get("hr_high", 100))
        self.health_hr_low = float(health.get("hr_low", 50))
        self.health_hr_low_night = float(health.get("hr_low_night", 45))
        self.health_spo2_low = float(health.get("spo2_low", 95))
        self.health_night_start = int(health.get("night_start", 23))
        self.health_night_end = int(health.get("night_end", 6))
        self.health_alert_consecutive = int(health.get("alert_consecutive", 3))
        self.health_alert_cooldown_s = float(health.get("alert_cooldown_s", 600))
        self.health_data_stale_seconds = float(health.get("data_stale_seconds", 300))
        # P4 微信预警推送（Spec §5.3/§5.4）
        self.health_wechat_chat_id = str(health.get("wechat_chat_id", ""))
        self.health_wechat_daily_limit = int(health.get("wechat_daily_limit", 5))
        self.health_wechat_push_enabled = bool(health.get("wechat_push_enabled", True))

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
