"""C 版聊天语气的配置与提示词公共 seam 回归。"""

from app.config import Config
from app.llm import HEALTH_SYSTEM_POLICY, SYSTEM_PROMPT
from app.tts import create_tts


def test_c_tone_config_flows_to_edge_tts(tmp_path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """tts:
  primary: edge
  edge_voice: zh-CN-XiaoxiaoNeural
  edge_rate: +5%
  edge_pitch: +3Hz
""",
        encoding="utf-8",
    )

    cfg = Config(config_path)
    tts = create_tts(cfg)

    assert cfg.tts_edge_rate == "+5%"
    assert cfg.tts_edge_pitch == "+3Hz"
    assert tts.primary.voice == "zh-CN-XiaoxiaoNeural"
    assert tts.primary.rate == "+5%"
    assert tts.primary.pitch == "+3Hz"


def test_c_tone_prompt_keeps_daily_chat_lively_and_health_clear() -> None:
    assert "第一句直接回答" in SYSTEM_PROMPT
    assert "每次最多一个轻语气词" in SYSTEM_PROMPT
    assert "1~2 句" in SYSTEM_PROMPT

    assert "禁止卖萌" in HEALTH_SYSTEM_POLICY
    assert "波浪号" in HEALTH_SYSTEM_POLICY
    assert "夸张感叹" in HEALTH_SYSTEM_POLICY
    assert "不得弱化" in HEALTH_SYSTEM_POLICY
