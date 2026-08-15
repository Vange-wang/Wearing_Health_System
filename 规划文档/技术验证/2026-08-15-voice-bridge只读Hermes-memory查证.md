# voice-bridge 只读 Hermes memory 前置查证

- **日期**：2026-08-15
- **执行**：WorkBuddy（开发员）
- **依据**：`协同工作文档/审查报告/2026-08-15-v0.3复审-延迟查证裁决报告.md` §四（跳长期 RAG 的前置查证）
- **结论**：✅ **可读**。Hermes 内置记忆 = 纯 Markdown 文件，voice-bridge 可直接只读，轻量通道可行。但需 Hermes 明确「注入范围」（见 §三关键发现）。

---

## 一、结论

**voice-bridge 能只读访问 Hermes built-in memory。** 存储 = 纯 Markdown 文件，无外部 API 依赖，直接文件读取即可。

| 项 | 结论 |
|---|---|
| 存储位置 | `~/.hermes/memories/MEMORY.md` + `USER.md`（纯文本 Markdown，`§` 分隔条目） |
| 格式 | 明文 Markdown，无加密、无数据库 |
| 读取方式 | 直接 `read_text()`，零依赖 |
| 是否外部可读 | ✅ 是（同用户同盘，无需 Hermes API / CLI） |
| 写入方 | 仅 Hermes（voice-bridge 只读，不写，避免并发污染） |

**实锤**：上轮共用记忆测试写入的「最喜欢颜色：蓝色。」，实测落在 `~/.hermes/memories/USER.md:23`（`cat` + `grep 蓝色` 命中）。

---

## 二、Hermes 记忆体系（实测查清）

`hermes memory --help` 明示：**Built-in memory（MEMORY.md / USER.md）always active**；外部 provider（honcho/mem0/mem0 等 7 个）可选，当前未启用（`status` 默认 built-in only）。

| 文件 | 内容 | 性质 |
|---|---|---|
| `MEMORY.md` | Hermes 自身运维记忆：项目路径、环境配置、协作规则、客户/快递信息、技术要点 | **运维/敏感**，不该整段注入语音 |
| `USER.md` | 用户画像与偏好：语言、姓名、电话、价格偏好、协作习惯、「喜欢蓝色」等 | **用户偏好**，应注入语音上下文 |

---

## 三、关键发现（需 Hermes 明确注入范围）

内置记忆是**两个语义不同的文件**：

1. **`USER.md`（用户画像）** → 语音轻量通道应注入（用户偏好/习惯，纯闲聊时让回复更贴合）。
2. **`MEMORY.md`（Hermes 运维记忆）** → **不应整段注入**。它包含 Vange 的项目路径、快递单号、客户信息、Clash 配置等运维/半敏感内容，注入给语音模型既无意义（语音用户就是 Vange 本人，但很多条目与语音对话无关）又有泄露/污染风险。

**建议注入策略**（供 Hermes 裁决）：
- 轻量通道默认**只注入 `USER.md`**（用户画像，小、稳定、贴合）。
- `MEMORY.md` 不注入（或仅按需检索注入相关条目，等价于长期 RAG 的知识库检索）。
- 纯闲聊的「共用记忆」验收 = 语音能读到 `USER.md` 里的偏好（如「喜欢蓝色」），与微信对话共享同一份 `USER.md`。

---

## 四、轻量通道可行性（据此更新）

Hermes 裁决「跳长期 RAG」现在**成立且路径清晰**：

```
纯闲聊/简单问答 → voice-bridge 读 USER.md（只读） + 裸模型(DeepSeek) → ~1.5s
需技能/工具     → 完整 Hermes agent（先安抚）→ ~3.5s
```

- 记忆共享不破坏：voice-bridge 只读 USER.md，写入仍归 Hermes（微信侧写入 → USER.md → 语音读到）。
- 无新增依赖：文件读取用标准库，DeepSeek 裸调用用已装 openai SDK（A1 虽"停用 DeepSeek 兜底"，但此处是"轻量通道主用裸模型"，属新决策，需 Vange/Hermes 重新拍板是否允许 voice-bridge 恢复 DeepSeek 作为轻量通道模型）。

---

## 五、待裁决

1. **注入范围**：轻量通道注入 `USER.md` 即可？`MEMORY.md` 是否排除？
2. **裸模型来源**：轻量通道用 DeepSeek（需恢复 DEEPSEEK_API_KEY 引用，与 A1「彻底停用 DeepSeek」冲突，需重新拍板）还是继续 Hermes 提供的裸模型（Hermes 侧暂无轻量模式，见中期查证）。
3. 若两条都暂不拍板，则 RAG 立项挂起，v0.3 先以「安抚语 + 放宽口径」收尾。
