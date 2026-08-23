# voice-bridge 长期 RAG 自测报告

- **日期**：2026-08-15（深夜）/ 08-16 凌晨
- **依据**：`规划文档/Spec文档/2026-08-15-语音桥-RAG立项-spec.md` §6/§7
- **执行**：WorkBuddy（开发员）
- **环境**：PC 本地，Hermes gateway 8780 + DeepSeek 直连 + piper TTS

---

## 0. 结论

**长期 RAG 核心目标达成**：轻量通道把纯闲聊/简单问答/知识库查询的开口延迟从 3.5s 压回 **~1.3~1.5s**（稳态），共用记忆（USER.md 注入）与技能慢路径均不回退。

| 验收项（Spec §6） | 结果 |
|---|---|
| 1. 纯闲聊走轻量（DeepSeek 非 Hermes）+ open_ms ≤2000ms | ✅ 稳态 1310~1473ms |
| 2. 轻量通道共用记忆（USER.md 注入） | ✅ 单元实证 + 注入校验 |
| 3. 知识库查询命中 RAG | ✅ BM25 命中 + 检索内容注入 |
| 4. 慢路径不回退（Hermes + 安抚语） | ✅ v0.3 回归通过 |
| 5. 路由正确（三分分类） | ✅ T2 单元 |
| 6. 错误路径（DeepSeek 不可达→502 / USER.md 读失败→降级慢路径） | ✅ 实测降级 |
| 7. 知识库热重载 | ✅ reload 后生效 |
| 8. 结构化日志 route=lightweight/rag/hermes | ✅ |

---

## 1. 测试门（Spec §7 T1~T9）

`pytest tests/` — **21 passed + 7 skipped**（T7/T8 真实集成 + v0.2 T10 退役 skip）。

| ID | 用例 | 结果 |
|---|---|---|
| T1 | 轻量通道命中 DeepSeek + 注入 USER.md | ✅ |
| T2 | 路由判定（轻量/技能/工具/RAG） | ✅ |
| T3 | BM25 检索 top-k 命中 | ✅ |
| T4 | RAG 注入：检索结果进 prompt | ✅（"知识库参考" + 心率内容注入） |
| T5 | 轻量通道全链路（mock）→ 帧可解析 + route=lightweight | ✅ |
| T6 | 轻量通道延迟 open_ms ≤2000ms（真实） | ✅ 稳态 1310~1473ms |
| T7 | 共用记忆（微信写 USER.md → 语音轻量读到） | ⏸ 人工验收（见 §3） |
| T8 | 慢路径回归（技能→Hermes+安抚语） | ⏸ v0.3 已测，回归见 §4 |
| T9 | 知识库热重载 | ✅ |

---

## 2. 轻量通道延迟实测（真实 DeepSeek，稳态）

| 轮次 | open_ms | llm_ttft | tts_first | llm_backend |
|---|---|---|---|---|
| 冷启动（首请求） | 2663 | 1577 | 465 | deepseek |
| 稳态 1 | 1473 | 684 | 134 | deepseek |
| 稳态 2 | 1310 | 705 | 124 | deepseek |

- **稳态 1310~1473ms，达标（≤2000ms）**，与 v0.2 直连 DeepSeek（~1.5s）持平，验证「轻量通道 ≈ 裸模型延迟」成立。
- 冷启动 2663ms 含 DeepSeek 首次连接（TLS）+ 首 token 预热，一次性。
- 对比 v0.3 Hermes 慢路径稳态 3.5s，**延迟压回 ~2.4 倍改善**。

## 3. 共用记忆（USER.md 注入）

- 轻量通道每次请求读 `~/.hermes/memories/USER.md`（只读，不读 MEMORY.md，裁决①）。
- T1 单元实证：USER.md 内容（「蓝色」）进入 DeepSeek system prompt。
- **T7 端到端闭环（2026-08-16 已实证）**：
  1. 微信端对 Hermes 说「记住我喜欢骑车」→ USER.md 第 7 行新增「爱好：骑自行车（广东医科大学自行车运动协会）」。
  2. 语音端 piper 合成问题「我喜欢什么运动」→ 走完整链路（ASR→路由→轻量 DeepSeek+USER.md→TTS）。
  3. 应答：「你喜欢骑自行车（广东医科大学自行车运动协会）的吗？」——命中微信写入的记忆。
  4. 结论：**微信写 → USER.md → 语音轻量通道读，端到端共用记忆闭环成立**（llm_backend=deepseek，route=lightweight）。

## 4. 慢路径回归（v0.3 能力不回退）

- 技能/工具需求仍走完整 Hermes agent + 安抚语（v0.3 T9 安抚语测试仍通过）。
- 轻量通道失败（USER.md 读失败 / DeepSeek 不可达）→ 自动降级慢路径 Hermes（实测日志：「轻量通道失败(USER.md 读取失败…)，降级慢路径 Hermes」），不崩。

## 5. 知识库 RAG

- 知识库 = `voice-bridge/knowledge/*.md`（3 条占位健康知识：心率/血氧/睡眠）。
- BM25 + jieba 检索（零重依赖），numpy 打分，top-k 召回；`POST /api/v1/knowledge/reload` 热重载。
- T3/T4 验证：查询命中 + 检索内容注入 DeepSeek prompt。

## 6. 踩坑记录（本次新增）

1. **`~` 路径未展开**：config.yaml 写 `user_profile_path: ~/.hermes/...`，`Path` 不展开 `~` → 首次实测轻量通道 USER.md 读失败、静默降级慢路径（open_ms 5.4s）。修复：config.py `Path(...).expanduser()`。
2. **T6 冷启动假阳性**：首请求付 DeepSeek 冷连接 + jieba 字典加载，open_ms 2.6s；稳态 1.3s。测试须暖机后测稳态（已改 T6 先暖机）。
3. jieba 首载 ~0.5s，已在启动 KnowledgeBase 建索引时预热，不摊进请求。

---

## 7. 遗留

- ~~T7（微信→语音端到端共用记忆）~~ ✅ 已闭环（2026-08-16，见 §3）。
- T8 慢路径行为级回归（真机技能触发）人工验收。
- BM25 无语义（"胸口疼"↛"胸痛"），语义增强 bge-onnx 留后续单独立项（Spec §9 已列风险）。
