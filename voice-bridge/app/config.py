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

        tts = self._data.get("tts", {})
        self.tts_primary = tts.get("primary", "edge")
        self.tts_edge_voice = tts.get("edge_voice", "zh-CN-XiaoxiaoNeural")
        self.tts_fallback = tts.get("fallback", "piper")
        self.tts_piper_model = BASE_DIR / tts.get("piper_model", "models/piper/zh_CN-huayan-medium.onnx")
        self.tts_piper_config = BASE_DIR / tts.get("piper_config", "models/piper/zh_CN-huayan-medium.onnx.json")

        llm = self._data.get("llm", {})
        self.llm_base_url = llm.get("base_url", "https://api.deepseek.com")
        self.llm_model = llm.get("model", "deepseek-chat")
        self.llm_api_key_env = llm.get("api_key_env", "DEEPSEEK_API_KEY")

        self.log_level = self._data.get("log", {}).get("level", "INFO")

    def deepseek_api_key(self) -> str | None:
        """读取 DeepSeek API key：环境变量优先，其次项目 .env。"""
        key = os.environ.get(self.llm_api_key_env)
        if key:
            return key
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == self.llm_api_key_env:
                    return v.strip().strip('"').strip("'")
        return None


def load_config(path: Path | None = None) -> Config:
    return Config(path or (BASE_DIR / "config.yaml"))
