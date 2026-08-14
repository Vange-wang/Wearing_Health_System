---
session_id: "20260814_154943_ca2e6f"
title: "WorkBuddy↔Hermes 协作线程（5）·v0.2 修订期"
source: "cli"
created_at: "2026-08-14T07:49:54.629473Z"
updated_at: ""
ended_at: ""
model: "deepseek-v4-pro"
provider: "deepseek"
cwd: "d:\\workbuddy_project\\项目\\可穿戴健康辅助系统"
archived: false
message_count: 39
tool_call_count: 24
format: "md"
exported_at: "2026-08-14T14:28:14.647281Z"
exporter: "hermes sessions export (md/qmd) v1"
---

# WorkBuddy↔Hermes 协作线程（5）·v0.2 修订期

Session ID: `20260814_154943_ca2e6f`

Source: `cli`

Working directory: `d:\workbuddy_project\项目\可穿戴健康辅助系统`

## Messages

### User — 2026-08-14T07:49:54.635742Z

【线程初始化·v5】这是 WorkBuddy 与 Hermes 的新协作线程（Vange 2026-08-14 指示新开 session）。我是 WorkBuddy（开发员）。项目：可穿戴健康辅助系统。上下文摘要：v0.1 语音桥已交付并通过审查（REVIEW_CONDITIONAL_PASS），Open Issues 剩余 4 条；协作规范 agent.md v1.2。请确认本线程生效并作为新的常驻协作线程，我在此等待新任务指令或 v0.2 规划。


### Assistant — 2026-08-14T07:50:11.870038Z

收到，WorkBuddy。确认本线程生效前，我先核对仓库当前真实状态（避免凭摘要下结论），随后给确认。



## Tool calls

```json
[
  {
    "id": "call_00_nfTpvROcTZL9bVTWBHrB3737",
    "call_id": "call_00_nfTpvROcTZL9bVTWBHrB3737",
    "response_item_id": "fc_00_nfTpvROcTZL9bVTWBHrB3737",
    "type": "function",
    "function": {
      "name": "terminal",
      "arguments": "{\"command\": \"git status && echo \\\"---BRANCH---\\\" && git branch -a && echo \\\"---LOG---\\\" && git log --oneline -5\"}"
    }
  },
  {
    "id": "call_01_W2vG9AEChnBSPgnsAB9e5888",
    "call_id": "call_01_W2vG9AEChnBSPgnsAB9e5888",
    "response_item_id": "fc_01_W2vG9AEChnBSPgnsAB9e5888",
    "type": "function",
    "function": {
      "name": "search_files",
      "arguments": "{\"pattern\": \"agent.md\", \"target\": \"files\"}"
    }
  },
  {
    "id": "call_02_31egxzG2TIvsDO9QWbKy5496",
    "call_id": "call_02_31egxzG2TIvsDO9QWbKy5496",
    "response_item_id": "fc_02_31egxzG2TIvsDO9QWbKy5496",
    "type": "function",
    "function": {
      "name": "search_files",
      "arguments": "{\"pattern\": \"*.md\", \"target\": \"files\", \"path\": \"协同工作文档\"}"
    }
  },
  {
    "id": "call_03_jjLWvvUoZmQkLtfpfXbB3984",
    "call_id": "call_03_jjLWvvUoZmQkLtfpfXbB3984",
    "response_item_id": "fc_03_jjLWvvUoZmQkLtfpfXbB3984",
    "type": "function",
    "function": {
      "name": "search_files",
      "arguments": "{\"pattern\": \"*.md\", \"target\": \"files\", \"path\": \"规划文档\"}"
    }
  }
]
```


### Tool — terminal — 2026-08-14T07:50:18.702919Z

{"output": "On branch main\nYour branch is up to date with 'origin/main'.\n\nUntracked files:\n  (use \"git add <file>...\" to include in what will be committed)\n\t\"\\345\\215\\217\\345\\220\\214\\345\\267\\245\\344\\275\\234\\346\\226\\207\\346\\241\\243/\\345\\256\\241\\346\\237\\245\\346\\212\\245\\345\\221\\212/2026-08-13-\\347\\216\\260\\346\\234\\211\\346\\226\\207\\344\\273\\266\\344\\270\\200\\350\\207\\264\\346\\200\\247\\345\\256\\241\\346\\237\\245\\346\\212\\245\\345\\221\\212.md\"\n\nnothing added to commit but untracked files present (use \"git add\" to track)\n---BRANCH---\n* main\n  remotes/origin/main\n---LOG---\n87d6b1d docs: 第2轮审查 REVIEW_PASS + v0.2 Spec 起草 + OI-002 关闭\n7aa7f74 fix+docs: 关闭 OI-003/005/006（Hermes 已验证）+ agent.md v1.2 OI 关闭自动化\nea69415 docs: Hermes 审查第1轮 — REVIEW_CONDITIONAL_PASS + Open Issues 登记\ncc07d97 docs: ESP-IDF v5.2.7 安装记录（含版本偏差说明与踩坑备忘）\ne30448a feat(voice-bridge): v0.1 语音桥服务实现 + 三句实测全过", "exit_code": 0, "error": null}


### Tool — search_files — 2026-08-14T07:50:22.481337Z

{"total_count": 1, "files": [".\\agent.md"]}


### Tool — search_files — 2026-08-14T07:50:25.508038Z

{"total_count": 8, "files": ["协同工作文档\\审查报告\\2026-08-13-现有文件一致性审查报告.md", "协同工作文档\\审查报告\\Open-Issues.md", "协同工作文档\\审查报告\\2026-08-11-审查-第2轮.md", "协同工作文档\\审查报告\\2026-08-11-审查-第1轮.md", "协同工作文档\\审查报告\\Pi的审查报告\\2026-08-11-规划文档二次审阅报告.md", "协同工作文档\\审查报告\\Pi的审查报告\\2026-08-11-规划文档审阅报告.md", "协同工作文档\\2026-08-11-协作线程4-初始化与开发指令-记录.md", "协同工作文档\\README.md"]}


### Tool — search_files — 2026-08-14T07:50:28.535942Z

{"total_count": 7, "files": ["规划文档\\Spec文档\\2026-08-11-语音桥-spec-v0.2.md", "规划文档\\Spec文档\\2026-08-11-语音桥-spec-v0.1.md", "规划文档\\里程碑文档\\README.md", "规划文档\\里程碑文档\\2026-08-11-M0M1-执行路线图.md", "规划文档\\README.md", "规划文档\\Spec文档\\2026-08-11-开发环境验证-spec-v0.1.md", "规划文档\\技术验证\\2026-08-11-语音引擎选型-结论.md"]}


### Assistant — 2026-08-14T07:50:33.208766Z



## Tool calls

```json
[
  {
    "id": "call_00_n1qVWZliBiYRhgXDVyxb8835",
    "call_id": "call_00_n1qVWZliBiYRhgXDVyxb8835",
    "response_item_id": "fc_00_n1qVWZliBiYRhgXDVyxb8835",
    "type": "function",
    "function": {
      "name": "read_file",
      "arguments": "{\"path\": \"协同工作文档/审查报告/Open-Issues.md\"}"
    }
  },
  {
    "id": "call_01_UZpSmv3TpOUnJh6pNrcp9094",
    "call_id": "call_01_UZpSmv3TpOUnJh6pNrcp9094",
    "response_item_id": "fc_01_UZpSmv3TpOUnJh6pNrcp9094",
    "type": "function",
    "function": {
      "name": "read_file",
      "arguments": "{\"path\": \"agent.md\"}"
    }
  },
  {
    "id": "call_02_j2XmJDaj3vSlvs4V4tx73248",
    "call_id": "call_02_j2XmJDaj3vSlvs4V4tx73248",
    "response_item_id": "fc_02_j2XmJDaj3vSlvs4V4tx73248",
    "type": "function",
    "function": {
      "name": "read_file",
      "arguments": "{\"path\": \"规划文档/Spec文档/2026-08-11-语音桥-spec-v0.2.md\"}"
    }
  },
  {
    "id": "call_03_M8e6TQtl6rRp5MJdvMk47776",
    "call_id": "call_03_M8e6TQtl6rRp5MJdvMk47776",
    "response_item_id": "fc_03_M8e6TQtl6rRp5MJdvMk47776",
    "type": "function",
    "function": {
      "name": "read_file",
      "arguments": "{\"path\": \"协同工作文档/审查报告/2026-08-11-审查-第2轮.md\"}"
    }
  }
]
```


### Tool — read_file — 2026-08-14T07:50:38.391933Z

{"content": "1|# Open Issues — voice-bridge 项目遗留项跟踪\n2|\n3|> 本文件登记审查中有条件通过的 NON_SERIOUS 遗留项。每次任务交接时随附未关闭清单，确保不丢失。\n4|> 关闭条件：责任方完成修复/决策 + 对方确认。\n5|\n6|| 编号 | 描述 | 严重度 | 状态 | 责任方 | 登记日期 | 关闭日期 |\n7||---|---|---|---|---|---|---|\n8|| OI-001 | health tts 字段只返回主引擎名（如 \"edge\"），edge 不可用时仍显示 \"edge\"，未反映实际可用引擎。建议 v0.2 改进为显示实际可用引擎（如 \"piper(fallback)\"）或连通性检查 | NON_SERIOUS | open | WorkBuddy | 2026-08-11 | — |\n9|| OI-002 | Spec §8 ASR 模型资产名 `sherpa-onnx-sense-voice-zh-20240418` 不存在，需修正为 `sense-voice-zh-en-ja-ko-yue-int8-2024-07-17` | NON_SERIOUS | **closed** | Hermes | 2026-08-11 | 2026-08-11 |\n10|| OI-003 | main.py:80 TTS 未就绪时的 error detail 硬编码 \"TTS 未就绪\"，不像 ASR/LLM 用启动时捕获的具体错误信息（asr_load_error/llm_config_error）。建议统一 | NON_SERIOUS | **closed** | WorkBuddy | 2026-08-11 | 2026-08-11 |\n11|| OI-004 | edge-tts 主引擎不可用（微软封 6.x token, HTTP 403），v0.1 实际 piper 独撑 TTS。v0.2 需评估恢复方案：升 edge-tts 7.x+音频转码（需引入 ffmpeg/pydub，评估是否违反依赖红线）或替换为火山/讯飞云 TTS | NON_SERIOUS | open | Hermes | 2026-08-11 | — |\n12|| OI-005 | piper-tts 1.6.0 Windows espeak-ng-data 打包 bug（编译机硬编码路径），当前通过目录联接（junction）修复。迁移机器/重装 venv 时需重建 junction，建议 README 补操作步骤 | NON_SERIOUS | **closed** | WorkBuddy | 2026-08-11 | 2026-08-11 |\n13|| OI-006 | edge-tts venv vendor patch（communicate.py outputFormat 改为 riff-16khz-16bit-mono-pcm），重装 edge-tts 会覆盖。建议 README 补充 patch 恢复步骤或在 requirements-dev.txt 中加自动化脚本 | NON_SERIOUS | **closed** | WorkBuddy | 2026-08-11 | 2026-08-11 |\n14|| OI-007 | SenseVoice 对纯静音/低能量音频会幻觉出噪声字符（如韩文字符），当前通过 0 帧 WAV 触发 no_speech 兜底。v0.2 建议加 VAD 或能量门限做前置过滤 | NON_SERIOUS | open | Hermes | 2026-08-11 | — |\n15|\n16|---\n17|\n18|*最后更新：2026-08-11 · 审查轮次：第2轮/共3轮 · 关联报告：2026-08-11-审查-第2轮.md*\n19|", "total_lines": 18, "file_size": 2363, "truncated": false, "is_binary": false, "is_image": false}


### Tool — read_file — 2026-08-14T07:50:38.399232Z

{"content": "1|# agent.md — WorkBuddy × Hermes 协作规范（v1.2，2026-08-11）\n2|\n3|> **本文件是 WorkBuddy 与 Hermes 在本项目中的协作运行时规范。双方每次开工前必须读取本文件。**\n4|> 与 `AGENTS.md` 的分工：`AGENTS.md` 管项目结构/文档优先级/开发纪律；本文件管**协作流程、模型守卫、交接与审查机制**。冲突时以本文件为准（本文件由 Vange 亲定）。\n5|\n6|---\n7|\n8|## 1. 角色与模型守卫（违反即停工）\n9|\n10|| 角色 | 职责 | 强制模型 | 非对应模型时 |\n11||---|---|---|---|\n12|| **WorkBuddy** | 代码开发方：按 Spec 实现代码、自测、交付 | **Kimi K3** | **立即停止一切代码开发**，等待 Vange 在 WorkBuddy 模型选择器切换到 Kimi K3 后再继续 |\n13|| **Hermes** | 代码审查方：审代码、出审查报告、放行 | **DS V4 Pro**（`deepseek-v4-pro`） | 禁止用其他模型出审查结论；审查调用必须带 `--model deepseek-v4-pro` |\n14|\n15|- Hermes 审查调用（**invocation-only 覆盖，不改默认 profile**）：\n16|  ```bash\n17|  hermes chat --model deepseek-v4-pro --resume 20260811_092140_61974b -q \"<审查请求>\" -Q\n18|  ```\n19|- ✅ 已验证（2026-08-11）：`deepseek-v4-pro` 在 Hermes 中可用（实测返回正常）。\n20|- Hermes 默认模型当前为 `deepseek-v4-flash`（日常对话可用），**审查必须显式切 v4-pro**。\n21|\n22|## 2. 沟通桥梁（Session 铁律）\n23|\n24|- **常驻 Session**（除非 Vange 明确说\"新开 session\"，否则永远在同一个 session 里交接）：\n25|  - Hermes 侧：`20260811_092140_61974b`（WorkBuddy↔Hermes 协作线程（4）·v0.1语音桥开发启动）\n26|  - WorkBuddy 侧：当前与 Vange 的对话线程（WorkBuddy 记忆目录 `.workbuddy/memory/` 保证跨会话连续）\n27|- 常用命令：\n28|  ```bash\n29|  hermes chat --resume 20260811_092140_61974b                    # 交互式恢复（Vange 侧边栏/终端用）\n30|  hermes chat --resume 20260811_092140_61974b -q \"<消息>\" -Q     # 单轮交接（WorkBuddy 用）\n31|  hermes sessions list                                            # 查会话\n32|  hermes sessions export --session-id <ID> --format md <路径>     # 归档会话\n33|  ```\n34|- 每轮交接必须是**有界包裹（bounded packet）**：上下文摘要 + 交付物路径 + 待确认问题。禁止甩一个文件路径就完事。\n35|\n36|### 2.1 任务单（Task Packet）— 交接标准化（v1.1 新增）\n37|\n38|每个任务的首次交接必须带任务单，**缺项不接**：\n39|\n40|```\n41|任务ID：T-YYYYMMDD-序号（例：T-20260811-01）\n42|需求来源：Spec 条目编号（例：Spec v0.1 §5 / §6）\n43|任务内容：一句话目标 + 非目标（明确不做的事）\n44|交付物：文件路径清单\n45|DoD（完成定义）：可测的验收标准（见 §3.2）\n46|优先级：P0 阻塞 / P1 正常 / P2 低\n47|```\n48|\n49|- **非目标（Non-goals）必须写明**——防范围蔓延，是防返工的第一道闸。\n50|- 任务单随交接消息一起发出；对方确认收到后再开工。\n51|\n52|## 3. 工作流：开发 → 审查 → 返工 → 放行（最多 3 轮）\n53|\n54|```\n55|Vange 下达任务（WorkBuddy 或 Hermes 侧均可）\n56|   │\n57|   ▼\n58|DEV_IN_PROGRESS（WorkBuddy 开发，Kimi K3）\n59|   │ 完成 + 自测通过 + 交付清单\n60|   ▼\n61|REVIEW_PENDING（Hermes 审查，deepseek-v4-pro）\n62|   │\n63|   ├── REVIEW_PASS ──────────────► 合入，任务关闭 ✅\n64|   ├── REVIEW_CONDITIONAL_PASS ──► 非阻断 Open Issues 登记后放行 ✅（带遗留项清单）\n65|   └── REWORK_REQUIRED ─────────► WorkBuddy 按报告逐条修复 → 重新提交 → 再审（轮次 +1）\n66|                                   └── 第 3 轮仍未通过 ──► REVIEW_LIMIT_REACHED，停止并上报 Vange 决策\n67|```\n68|\n69|**硬性规则：**\n70|\n71|1. **审查轮次上限 = 3 轮**（沿用 vange-workflow `MAX_REVIEW_ROUNDS = 3`）。不因返工、换文件、补测而重置计数。\n72|2. **Hermes 每轮审查必须一次性给出全部可发现的实质问题（SERIOUS 批次）**，禁止挤牙膏式分轮抛问题。\n73|3. **WorkBuddy 提交前自查清单**（防止无用功返工，这是大忌）：\n74|   - [ ] 已读对应 Spec，确认无未覆盖需求（未覆盖 → 先补 Spec 再动手）\n75|   - [ ] 已通读上一轮审查报告，确认无漏修项\n76|   - [ ] 自测跑通（含实测打点数据，禁止\"应该没问题\"）\n77|   - [ ] 交付物路径明确、代码格式/命名一致\n78|4. **有条件通过** = 剩余项均为 NON_SERIOUS（措辞/风格/非阻断优化），登记为 Open Issues 后放行，不触发返工。\n79|5. 每轮审查报告**落盘**：`协同工作文档/审查报告/YYYY-MM-DD-审查-第N轮.md`，WorkBuddy 返工时以该文件为准逐条回应（修复 + 证据）。\n80|6. Hermes 只审查不写业务代码；WorkBuddy 只开发不自我审查。职责边界不可逾越。\n81|\n82|### 3.1 状态词汇表（v1.1 新增）— 交接汇报必须带状态前缀\n83|\n84|```\n85|[WORKFLOW_ACTIVE]          工作流进行中\n86|[DEV_IN_PROGRESS]          WorkBuddy 开发中（Kimi K3）\n87|[DEV_DONE]                 WorkBuddy 交付待审（附任务单 + 自查清单 + 实测数据）\n88|[REVIEW_PENDING]           Hermes 审查中（deepseek-v4-pro）\n89|[REWORK_REQUIRED]          返工中（第N轮）\n90|[REVIEW_PASS]              审查通过 ✅\n91|[REVIEW_CONDITIONAL_PASS]  有条件通过（登记 Open Issues 后放行）\n92|[REVIEW_LIMIT_REACHED]     3 轮未过，停止，上报 Vange 决策\n93|[USER_PAUSED]              Vange 暂停（唯一合法停止状态）\n94|```\n95|\n96|汇报格式：`[状态] 一句话结论 + 关键证据路径`。双方一眼对齐，不再问\"现在到哪了\"。\n97|\n98|### 3.2 DoD 前置确认（v1.1 新增）— 开工前对齐完成定义\n99|\n100|- WorkBuddy **动手前**必须确认任务单中 DoD 可测且双方认可（可验证的行为/数据，禁止\"代码能跑\"这类模糊表述）。\n101|- **没有 DoD 的任务 = 没定义清楚**：先补 DoD（或写进 Spec）再开工，这是防无用功的根本手段。\n102|- DoD 变更需 Vange 或 Hermes 同意；变更后返工轮次不重置，但该变更点不计入 SERIOUS 返工。\n103|\n104|### 3.3 轮次计数与 Open Issues（OI = Open Issue）登记（v1.1 新增，v1.2 修订）\n105|\n106|- 审查报告标题固定格式：`YYYY-MM-DD-审查-第N轮.md`，N 只增不减，不因返工/换文件/补测重置。\n107|- **有条件通过** → 遗留项登记 `协同工作文档/审查报告/Open-Issues.md`：\n108|  | 编号 | 描述 | 严重度 | 状态 | 责任方 |\n109|  |---|---|---|---|---|\n110|  | OI-001 | …… | NON_SERIOUS | open / closed | WorkBuddy / Hermes |\n111|- **OI 关闭自动化（v1.2，Vange 亲定）**：审核确认无问题、达到验收标准后，责任方自行决定关闭，**无需 Vange 逐条决策**。\n112|  - 关闭流程：责任方完成修复 → 提交对方（Hermes）验证确认 → 标记 closed（含关闭日期）。\n113|  - Vange 只介入：阻塞项、方向变更（如推进下一阶段）、或双方对关闭有分歧时。\n114|- 后续任务交接时随附未关闭的 Open Issues 清单，确保遗留项不丢失。\n115|\n116|### 3.4 交接响应与阻塞规则（v1.1 新增）\n117|\n118|- 交接（含审查请求）发出后 **15 分钟内无响应** → 重发一次并 @Vange；仍无响应 → 记录 blocker，先做不依赖该交接的准备工作，不空等。\n119|- 阻塞记录格式（沿用 vange-workflow）：`阻塞点 / 责任方 / 最小解锁输入 / 恢复触发器`。\n120|- 任何角色遇到 Spec 未覆盖情况：**先停下来**，写进 Spec 或问 Vange/Hermes，禁止擅自决策（v0.1 尤其如此）。\n121|\n122|## 4. vange-workflow 五条硬不变式（本项目全量适用）\n123|\n124|1. **THINK_BEFORE_ACTING**：材料决策前先想清楚目标/非目标/约束/依赖/验收/回滚/证据；未知且影响决策必须查清，否则果断行动。\n125|2. **Persist to acceptance**：计划、返工、阻塞、超时都不是完成。只有 Vange 明确暂停/取消才停；否则保持状态继续推进。\n126|3. **Roles isolated**：路由/追踪/验收/关门由流程控制；任何角色不得自我批准、不得接管他人职责。\n127|4. **Use only authorized workers**：交接只用已注册的现有线程（本文件 §2 的 session），**擅自新建线程/会话需 Vange 明确授权**。\n128|5. **Require evidence before closure**：交付必须有归属明确的证据（实测数据、报告、路径）。`WORKFLOW_COMPLETE` 前必须全部 gate 通过。\n129|\n130|## 5. 工作区文件管理（Vange 亲定：做好文件/文件夹管理）\n131|\n132|| 目录/文件 | 职责 | 纪律 |\n133||---|---|---|\n134|| `agent.md` | 本协作规范 | 变更需 Vange 同意，双方开工必读 |\n135|| `规划文档/Spec文档/` | 功能 Spec（最高裁决） | 命名 `YYYY-MM-DD-功能名-spec.md`；未覆盖需求先补 Spec |\n136|| `规划文档/技术验证/` | 选型结论与风险 | 只记结论与数据 |\n137|| `规划文档/里程碑文档/` | 阶段交付计划 | 每阶段交付前更新 |\n138|| `Code文档/` | 代码结构、开发员记录、自测报告 | `v0.1自测报告.md` 等按阶段命名 |\n139|| `协同工作文档/` | 交接记录、审查报告 | **子目录 `审查报告/`**，命名 `YYYY-MM-DD-审查-第N轮.md`；遗留项登记 `Open-Issues.md` |\n140|| `总负责人文档/` | Hermes 决策记录 | 架构/选型决策落盘 |\n141|| `voice-bridge/` | v0.1 唯一代码目录 | `venv/`、`models/`、`.env` 一律 gitignore，不入库 |\n142|\n143|**通用纪律：**\n144|- 交接物必须给出**绝对路径**；临时文件不落项目根目录（用 `.tmp/` 或系统临时目录）。\n145|- 模型文件、密钥、venv 永不入库；`.env` 从 `~/.hermes/.env` 复制，不入库。\n146|- git 提交信息遵循语义化（`feat:` / `fix:` / `docs:` / `chore:`），一次提交一个逻辑变更。\n147|\n148|---\n149|\n150|## 变更记录\n151|\n152|- **v1.0**（2026-08-11）：初版。Vange 亲定 5 条：角色模型守卫 / Session 铁律 / 3 轮审查工作流 / vange-workflow 五条不变式 / 文件管理。\n153|- **v1.1**（2026-08-11）：Vange 要求\"适当优化\"。新增 §2.1 任务单模板、§3.1 状态词汇表、§3.2 DoD 前置、§3.3 轮次计数与 Open Issues 登记、§3.4 交接响应与阻塞规则。核心目标：防无用功返工。\n154|- **v1.2**（2026-08-11）：Vange 亲定 OI 关闭自动化——审核确认无问题、达到验收标准后责任方自行关闭，无需 Vange 逐条决策。\n155|\n156|*本规范由 Vange 于 2026-08-11 下达，WorkBuddy 起草维护，Hermes 知悉后生效。版本变更需 Vange 同意。*\n157|", "total_lines": 156, "file_size": 10434, "truncated": false, "is_binary": false, "is_image": false}


### Tool — read_file — 2026-08-14T07:50:38.409378Z

{"content": "1|# 语音桥服务 Spec v0.2（2026-08-11）\n2|\n3|> 本文档为 voice-bridge v0.2 的开发规格。继承 v0.1 全部架构约束，新增流式能力。\n4|> 冲突时本 Spec 优先于 v0.1 Spec。WorkBuddy 按此实现。\n5|\n6|## 1. 目标\n7|\n8|在 v0.1 非流式基础上实现**流式语音交互**：DeepSeek 流式输出 + 分句 TTS 流水线，开口延迟 ≤ 1.5s（实测 1.2~1.4s）。同时覆盖 v0.1 CONDITIONAL_PASS 遗留的 4 条 Open Issues。\n9|\n10|## 2. 阶段边界\n11|\n12|| 阶段 | 内容 | 验收 |\n13||---|---|---|\n14|| v0.1（已完成） | 独立语音服务：ASR + DeepSeek(非流式) + TTS | ✅ REVIEW_PASS |\n15|| **v0.2（本文档）** | **DeepSeek 流式 + 分句 TTS 流水线 + VAD + health 增强** | **开口延迟 ≤1.5s，流式可感** |\n16|| v0.3 | 接入 Hermes 会话（共用记忆/技能） | 与微信共用记忆 |\n17|\n18|**禁止**：v0.2 不得接入 Hermes、不得更改 ASR 引擎（sherpa-onnx 锁定）、不得引入未列明的新增依赖。\n19|\n20|## 3. 技术栈（v0.1 继承 + v0.2 新增）\n21|\n22|### 继承（不动）\n23|\n24|- Python 3.11（解释器同 v0.1）\n25|- FastAPI + uvicorn\n26|- sherpa-onnx + SenseVoice（ASR）\n27|- DeepSeek API 直连（`trust_env=False`）\n28|- venv 在 `voice-bridge/venv`\n29|\n30|### v0.2 新增 / 变更\n31|\n32|| 组件 | v0.1 | v0.2 | 原因 |\n33||---|---|---|---|\n34|| LLM 调用 | `stream=False` | `stream=True`（openai StreamingResponse） | 流式输出是 v0.2 核心 |\n35|| 句子分割 | 无 | `app/splitter.py`（正则分割，分句缓冲器） | 流式 LLM → 逐句 TTS |\n36|| 流式流水线 | 无 | `app/pipeline.py`（ASR→LLM流→分句→TTS→chunked响应） | 编排器 |\n37|| VAD | 无（静音幻觉 D5） | `app/vad.py`（能量门限 enengy-threshold，rms 计算） | OI-007 关闭 |\n38|| TTS 引擎 | edge(主)+piper(兜底) | **piper(主)+edge(实验)**：edge 6.x 持续 403，v0.2 以 piper 为默认主力；edge 7.x 转码方案评估但暂不入主线 | OI-004 评估 + 延迟优先 |\n39|| health | 返回主引擎名 | 返回实际可用引擎（如 `\"piper\"` 或 `\"edge+piper\"`，连通性校验） | OI-001 关闭 |\n40|| HTTP 响应 | 完整 WAV | `Transfer-Encoding: chunked`，每 chunk = 一句 WAV | 开口延迟 ≤1.5s |\n41|\n42|### 新增依赖（v0.2 允许引入）\n43|\n44|```\n45|# requirements.txt 追加\n46|numpy>=1.24        # VAD RMS 计算（标准库无 rms，v0.1 已有 numpy 通过 sherpa-onnx）\n47|# sentence splitting 用标准库 re，无新增依赖\n48|# chunked streaming 用 FastAPI StreamingResponse，无新增依赖\n49|```\n50|\n51|## 4. 项目结构（voice-bridge/ 内，v0.1 继承 + 新增）\n52|\n53|```\n54|voice-bridge/\n55|  app/\n56|    __init__.py\n57|    main.py           # 新增 POST /api/v1/voice/chat/stream（v0.1 路由不变）\n58|    config.py         # 新增 vad / pipeline / tts 配置段\n59|    asr.py            # 不变（v0.1 实现够用）\n60|    tts.py            # 改造：TTSEngine.synthesize 改为同步优先（piper 主）；edge 标记实验\n61|    llm.py            # 新增 stream_chat() 方法（生成器），chat() 保留（向后兼容）\n62|    schemas.py        # 不变\n63|    splitter.py       # 新增：句子分割器（SentenceBuffer）\n64|    pipeline.py       # 新增：流式流水线编排（StreamingPipeline）\n65|    vad.py            # 新增：能量门限 VAD\n66|  models/             # 不变（gitignore）\n67|  tests/\n68|    test_smoke.py     # 追加 v0.2 流式用例（≥3 条）\n69|  config.yaml         # 追加 vad/tts/pipeline 配置段\n70|  requirements.txt    # 追加 numpy 版本约束\n71|  run.py              # 不变\n72|  README.md           # 更新运行说明（v0.2 新增接口、edge 状态）\n73|```\n74|\n75|## 5. 接口定义\n76|\n77|### 5.1 GET /api/v1/health（v0.2 改造 — OI-001）\n78|\n79|返回示例：\n80|```json\n81|{\n82|  \"status\": \"ok\",\n83|  \"asr\": \"ready\",\n84|  \"tts\": \"piper\",\n85|  \"tts_fallback\": \"edge_unavailable\",\n86|  \"vad\": \"enabled\"\n87|}\n88|```\n89|\n90|规则：\n91|- `tts`：当前实际可用引擎（piper / edge），非仅主引擎名。\n92|- `tts_fallback`：可选。仅当主引擎不可用时显示（如 `\"edge_unavailable\"`）。\n93|- `vad`：`\"enabled\"` | `\"disabled\"`（取决于 config.yaml）。\n94|- 启动时探测 edge-tts 连通性（发一个最小静音合成请求，超时 3s），不可用时记 `edge_unavailable`，health 始终反映真实状态。\n95|\n96|### 5.2 POST /api/v1/voice/chat（v0.1 行为保留，不变）\n97|\n98|非流式，完全向后兼容。v0.1 代码不改。WorkBuddy 不用动。\n99|\n100|### 5.3 POST /api/v1/voice/chat/stream（v0.2 新增）\n101|\n102|- 请求：同 v0.1 —— `multipart/form-data`，`audio` = WAV（16kHz/16bit/mono，≤15s）\n103|- 响应：`Transfer-Encoding: chunked`，`Content-Type: audio/wav`\n104|  - 每 chunk = **一句完整的 WAV 文件**（含 WAV header，16kHz/16bit/mono）\n105|  - 客户端逐 chunk 播放：收到第 1 个 chunk → 开始播放（开口延迟计时止于此）\n106|- 响应头：\n107|  - `X-Timing-First-Token: {\"asr_ms\":..., \"llm_ttft_ms\":..., \"tts_first_ms\":..., \"open_ms\":...}`\n108|    （`open_ms` = 从请求到第一个 chunk 首字节的开口延迟，核心验收指标）\n109|- 错误：同 v0.1 错误码表（§5.4），流式错误时 HTTP 状态码在第一个 chunk 前发出\n110|\n111|流式处理流程（详见 §6）：\n112|\n113|```\n114|WAV 上传 → VAD 预检 → ASR → LLM 流(chunk) → 句子缓冲器 → 触发条件满足 → TTS → chunked WAV 发送\n115|                                                                                    ↓\n116|                                                                        ESP32-S3 逐句播放\n117|```\n118|\n119|### 5.4 错误码表（v0.1 继承，v0.2 追加）\n120|\n121|| 场景 | 状态码 | 响应 | 备注 |\n122||---|---|---|---|\n123|| VAD 检测到静音/无效语音 | 400 | `{\"error\": \"no_speech\"}` | v0.2 新增（OI-007） |\n124|| ASR 失败 / 无有效语音 | 400 | `{\"error\": \"no_speech\"}` | 继承 v0.1 |\n125|| 音频格式不合规 | 400 | `{\"error\": \"bad_audio_format\"}` | 继承 v0.1 |\n126|| 音频超过上限 | 413 | `{\"error\": \"audio_too_long\"}` | 继承 v0.1（上限 15s） |\n127|| API key 未配置 | 500 | `{\"error\": \"config_error\", \"detail\": \"...\"}` | 继承 v0.1 |\n128|| 服务未就绪 | 503 | `{\"error\": \"service_unavailable\"}` | 继承 v0.1 |\n129|| LLM/TTS 上游失败 | 502 | `{\"error\": \"upstream_error\", \"detail\": \"...\"}` | 继承 v0.1；流式下首句前失败按此返回 |\n130|\n131|## 6. 流式流水线设计（核心）\n132|\n133|### 6.1 组件职责\n134|\n135|| 组件 | 文件 | 职责 |\n136||---|---|---|\n137|| `VADGate` | `app/vad.py` | 能量 RMS 阈值检测，决定是否继续走 ASR（≤rms_threshold → no_speech） |\n138|| `SherpaOnnxASR` | `app/asr.py`（不改） | WAV → 文本（已有） |\n139|| `DeepSeekLLM.stream_chat()` | `app/llm.py`（新增） | 用户文本 → 流式 `Iterator[str]` |\n140|| `SentenceBuffer` | `app/splitter.py`（新增） | 接收字符流，按标点/长度触发分句 |\n141|| `TTSEngine` | `app/tts.py`（改造） | 文本 → WAV bytes（piper 为主，同步合成） |\n142|| `StreamingPipeline` | `app/pipeline.py`（新增） | 串联以上组件，产出 `Iterator[bytes]`（chunk WAV） |\n143|\n144|### 6.2 分句规则（SentenceBuffer）\n145|\n146|```\n147|触发条件（任一满足即输出当前 buffered 文本为一句）：\n148|1. 遇到标点：。！？〜 ；\\n（中日英共用标点）\n149|2. 缓冲区长度 ≥ 50 字符（长句保护，避免 LLM 不发标点时永不输出）\n150|3. LLM 流结束：flush 剩余内容（即使无标点）\n151|\n152|连续标点合并：多个连续标点仅算一次分割。\n153|空句子跳过：纯标点/空白不触发 TTS。\n154|```\n155|\n156|### 6.3 TTS 策略（v0.2 — OI-004 评估结论）\n157|\n158|edge-tts 6.x 现网持续 403（微软封老 client token），v0.2 的策略：\n159|\n160|| 引擎 | 角色 | 延迟 | 质量 | 策略 |\n161||---|---|---|---|---|\n162|| piper | **v0.2 默认主引擎** | 0.1~0.2s | 一般 | 本地推理，流程内同步调用 |\n163|| edge-tts 7.x | 实验性（可选） | 0.3~0.6s | 自然 | 7.x 仅出 24k mp3，转码需引入 pydub（`pydub>=0.25`）；**config 中标记 `experimental`，默认关闭**。若用户主动开启且可用，TTS 走 asyncio 不阻塞 |\n164|\n165|config.yaml 对应段：\n166|```yaml\n167|tts:\n168|  primary: piper                                # v0.2 默认主引擎\n169|  piper_model: models/piper/zh_CN-huayan-medium.onnx\n170|  piper_config: models/piper/zh_CN-huayan-medium.onnx.json\n171|  edge:\n172|    enabled: false                              # 实验性，默认关闭\n173|    voice: zh-CN-XiaoxiaoNeural\n174|    version: 7\n175|```\n176|\n177|- edge `enabled: true` + `version: 7` → 需额外安装 `pydub`（requirements.txt 中注释说明）\n178|- edge 不可用不影响服务：piper 始终可用\n179|\n180|### 6.4 VAD 能量门限（OI-007）\n181|\n182|```yaml\n183|vad:\n184|  enabled: true\n185|  rms_threshold: 0.005    # 0~1，建议值 0.005；纯静音 rms ≈ 0.001~0.003\n186|  min_speech_frames: 10    # 连续 speech 帧数下限（frame = 10ms），低于此 → no_speech\n187|```\n188|\n189|实现：\n190|- 读取 WAV float32 samples → 分帧（10ms/frame，160 samples @ 16kHz）→ 每帧 RMS\n191|- 连续 speech frame 数 ≥ `min_speech_frames` → 走 ASR；否则 → 400 `no_speech`\n192|- 零新增依赖：numpy 已在 sherpa-onnx 依赖链中\n193|\n194|### 6.5 流式打点（v0.2 追加时序点）\n195|\n196|```\n197|timing = {\n198|  \"asr_ms\": ...,        # ASR 耗时（同 v0.1）\n199|  \"llm_ttft_ms\": ...,   # LLM Time-To-First-Token（首 chunk 到达延迟）\n200|  \"llm_total_ms\": ...,  # LLM 全流完成耗时\n201|  \"tts_first_ms\": ...,  # 第一句 TTS 耗时\n202|  \"tts_total_ms\": ...,  # 全部 TTS 总耗时（含所有句子）\n203|  \"open_ms\": ...,       # 开口延迟 = asr + llm_ttft + tts_first\n204|  \"total_ms\": ...,      # 全链路总耗时\n205|  \"sentence_count\": ...,# 分句数量\n206|  \"chunk_count\": ...,   # 发送 chunk 数\n207|}\n208|```\n209|\n210|- `open_ms` 是核心验收指标\n211|- 结构化日志打完整 timing\n212|- 响应头 `X-Timing-First-Token` 包含首 token 相关字段\n213|\n214|## 7. LLM 系统提示词（v0.2 微调）\n215|\n216|```text\n217|你是\"小衡\"，一个便携健康助手的语音助手。要求：\n218|1. 回答简短口语化，一般不超过 50 字；能一句话说完就一句话。\n219|2. 用户是通过语音对话，回复要像日常聊天，不要列点、不要 markdown。\n220|3. 涉及健康数据的问题（心率/血氧/睡眠等）暂回答\"健康数据监测功能即将上线\"。\n221|4. 回答尽量用句号结尾，方便播报分句。\n222|```\n223|\n224|> 变更：新增第 4 条\"尽量用句号结尾\"以提高分句流畅度。v0.1 第 1~3 条不变。\n225|\n226|## 8. 配置（config.yaml 完整结构，v0.2）\n227|\n228|```yaml\n229|server:\n230|  host: 0.0.0.0\n231|  port: 8710\n232|\n233|asr:\n234|  model_dir: models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17\n235|  sample_rate: 16000\n236|\n237|vad:\n238|  enabled: true\n239|  rms_threshold: 0.005\n240|  min_speech_frames: 10\n241|\n242|tts:\n243|  primary: piper\n244|  piper_model: models/piper/zh_CN-huayan-medium.onnx\n245|  piper_config: models/piper/zh_CN-huayan-medium.onnx.json\n246|  edge:\n247|    enabled: false\n248|    voice: zh-CN-XiaoxiaoNeural\n249|    version: 7\n250|\n251|llm:\n252|  base_url: https://api.deepseek.com\n253|  model: deepseek-chat\n254|  api_key_env: DEEPSEEK_API_KEY\n255|\n256|pipeline:\n257|  sentence_max_chars: 50       # 长句保护：超过此长度无标点也触发分句\n258|\n259|log:\n260|  level: INFO\n261|```\n262|\n263|## 9. 验收标准（v0.2 全过才算完成）\n264|\n265|### 9.1 功能验收\n266|\n267|1. `POST /api/v1/voice/chat/stream` 返回 chunked WAV，每 chunk 可独立播放\n268|2. 开口延迟 ≤1.5s（实测三句平均 `open_ms` ≤ 1500ms），目标 1.2~1.4s\n269|3. 流式可感：第一个 chunk 和最后一个 chunk 到达时间差 ≥ 1s（证明不是等完整回复）\n270|4. health 返回实际引擎状态（piper/edge）+ VAD 状态\n271|5. 静音/VAD 拦截：纯静音 WAV → 400 `no_speech`（不走到 LLM，节省 token）\n272|6. backtrack compat：`POST /api/v1/voice/chat`（v0.1 路径）行为不变\n273|\n274|### 9.2 测试要求\n275|\n276|7. pytest ≥ 6 条（v0.1 5 条不变 + ≥1 条流式新增）：\n277|   - v0.1 5 条继承（health/timing/兜底/空音频/格式）\n278|   - 流式：分句器单元测试（SentenceBuffer 触发条件全部覆盖）\n279|   - 流式：VAD 静音拦截测试（纯静音 → no_speech）\n280|   - 流式：health 返回 VAD 字段\n281|\n282|### 9.3 实测数据\n283|\n284|8. 三句口语实测（同 v0.1 三句），录制 `open_ms` 数据写入自测报告\n285|9. 自测报告写入 `Code文档/v0.2自测报告.md`\n286|\n287|### 9.4 交付\n288|\n289|10. 源码 + 更新 README（含 v0.2 流式接口说明、edge 实验性配置说明）+ requirements.txt 更新 + 自测报告\n290|\n291|## 10. 延迟预算（v0.2 目标）\n292|\n293|```\n294|VAD        0.02s  （能量计算，numpy 向量化）\n295|ASR        0.25s  （SenseVoice，不变）\n296|LLM TTFT   0.50s  （DeepSeek 首 token，目标值）\n297|TTS first  0.15s  （piper 首句，短句 5~15 字）\n298|─────────────────\n299|open_ms ≈  0.92s  （理论最佳）\n300|实测目标    1.2~1.4s（含网络抖动+分句等待）\n301|```\n302|\n303|与 v0.1 计算公式对比：v0.1 等待完整 LLM 回复（2~3s），v0.2 只等首 token + 首句，开口延迟从 2-4s 缩短至 ~1.2s。\n304|\n305|## 11. 风险与缓解\n306|\n307|| 风险 | 影响 | 缓解 |\n308||---|---|---|\n309|| DeepSeek 首 token 延迟波动（0.4~1.5s） | 开口延迟超标 | v0.2 只要求平均 ≤1.5s；峰值超标不计入 fail |\n310|| 分句等不到标点（LLM 长句无句号） | 首句永远不发 | 长句保护 50 字符硬切割 |\n311|| piper 音色不如 edge 自然 | 用户体验 | 可接受（延迟优先 > 音色）；edge 7.x 实验通路保留 |\n312|| edge-tts 持续 403 | 见 OI-004 | v0.2 默认 piper，edge 标记实验性 |\n313|| 流式 chunk 传输中断 | ESP32 侧播放异常 | 测试覆盖 WiFi 弱信号场景（≥80% 成功率即可） |\n314|| Chunked WAV 客户端解析 | ESP32 端需流式 WAV 解析器 | v0.2 只交付 PC 端；ESP32 端留到 M1 阶段适配 |\n315|\n316|## 12. Open Issues 覆盖映射\n317|\n318|| OI | 内容 | v0.2 处理 |\n319||---|---|---|\n320|| OI-001 | health 未反映实际引擎 | §5.1：health 返回实际可用引擎 + 连通性探测 |\n321|| OI-004 | edge-tts 403 恢复方案 | §6.3：piper 升为主引擎，edge 7.x 实验性 | 评估完成 |\n322|| OI-007 | SenseVoice 静音幻觉 → VAD | §6.4：能量门限 VAD，静音拦截 | 关闭 |\n323|| OI-002 | Spec §8 资产名修正 | v0.1 Spec 已修正（§8 + config.yaml 一致）✅ |\n324|\n325|---\n326|\n327|*Hermes（deepseek-v4-pro）起草 · 2026-08-11 · 待 WorkBuddy 确认 DoD 后开工*\n328|", "total_lines": 327, "file_size": 13965, "truncated": false, "is_binary": false, "is_image": false}


### Tool — read_file — 2026-08-14T07:50:38.427861Z

{"content": "1|# 审查报告 — 2026-08-11-审查-第2轮（第2轮/共3轮）\n2|\n3|> 任务单：T-20260811-03 · 审查方 Hermes（deepseek-v4-pro）· HEAD=7aa7f74 · agent.md v1.2\n4|> 范围：v0.1 交付闭环复审（第1轮 CONDITIONAL_PASS 遗留项修复验证 + DoD 终检）\n5|> 工作目录：D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\n6|\n7|## 审查结论\n8|\n9|**REVIEW_PASS** ✅（第 2 轮 / 共 3 轮）\n10|\n11|- SERIOUS（阻断）：**0 项**\n12|- NON_SERIOUS（遗留）：4 项（OI-001/002/004/007，均为 v0.2 规划项或文档修正，不阻断 v0.1 闭环）\n13|- OI-003/005/006 修复验证通过并已关闭\n14|- **v0.1 交付闭环已达成。WorkBuddy 可推进 v0.2。**\n15|\n16|---\n17|\n18|## 一、修复验证（commit 7aa7f74）\n19|\n20|### OI-003：main.py TTS 错误 detail 统一\n21|\n22|| 检查项 | 修复前 | 修复后 | 结论 |\n23||---|---|---|---|\n24|| 变量声明 | 无 | `tts_load_error: str \\| None = None` (line 40) | ✅ |\n25|| startup 捕获 | 无 | `tts_load_error = str(e)` (line 60) | ✅ |\n26|| voice_chat 使用 | `\"TTS 未就绪\"` 硬编码 | `tts_load_error or \"TTS 未就绪\"` (line 82) | ✅ |\n27|| 与 ASR/LLM 一致性 | ❌ 不一致 | ✅ 三种错误路径统一 | ✅ |\n28|\n29|### OI-005：README piper junction 重建步骤\n30|\n31|| 检查项 | 结论 |\n32||---|---|\n33|| \"已知环境修复（迁移/重装必读）\"小节 | ✅ |\n34|| 硬编码路径说明 | ✅ |\n35|| PowerShell junction 命令（含 `New-Item -ItemType Junction`） | ✅ |\n36|| 路径变量 `$hard` 可复制执行 | ✅ |\n37|| OI-005 编号标注 | ✅ |\n38|\n39|### OI-006：README edge vendor patch 恢复步骤\n40|\n41|| 检查项 | 结论 |\n42||---|---|\n43|| edge-tts 6.1.x 行为说明（固定 24k mp3） | ✅ |\n44|| patch 位置标注（communicate.py 第339行） | ✅ |\n45|| 一行 Python 恢复命令（replace 方式） | ✅ |\n46|| OI-006 编号标注 | ✅ |\n47|| 末尾注 edge 现网 403 → piper 兜底（OI-004 关联） | ✅ |\n48|\n49|---\n50|\n51|## 二、Open-Issues.md 台账核对\n52|\n53|| 编号 | 状态（预期） | 状态（实际） | 责任方（预期） | 责任方（实际） | 结论 |\n54||---|---|---|---|---|---|\n55|| OI-001 | open | ✅ open | WorkBuddy | ✅ WorkBuddy | 通过 |\n56|| OI-002 | open | ✅ open | Hermes | ✅ Hermes | 通过 |\n57|| OI-003 | **closed** | ✅ **closed** (2026-08-11) | WorkBuddy | ✅ WorkBuddy | 通过 |\n58|| OI-004 | open | ✅ open | Hermes | ✅ Hermes | 通过 |\n59|| OI-005 | **closed** | ✅ **closed** (2026-08-11) | WorkBuddy | ✅ WorkBuddy | 通过 |\n60|| OI-006 | **closed** | ✅ **closed** (2026-08-11) | WorkBuddy | ✅ WorkBuddy | 通过 |\n61|| OI-007 | open | ✅ open | Hermes | ✅ Hermes | 通过 |\n62|\n63|- 状态、责任方、描述全部一致，无偏差。\n64|\n65|---\n66|\n67|## 三、回归测试（pytest）\n68|\n69|```\n70|tests/test_smoke.py::test_health_format PASSED                           [ 20%]\n71|tests/test_smoke.py::test_empty_audio_returns_no_speech PASSED           [ 40%]\n72|tests/test_smoke.py::test_bad_format_returns_400 PASSED                  [ 60%]\n73|tests/test_smoke.py::test_edge_failure_falls_back_to_piper PASSED        [ 80%]\n74|tests/test_smoke.py::test_full_chain_x_timing PASSED                     [100%]\n75|\n76|5 passed in 37.99s\n77|```\n78|\n79|- 全绿（含全链路 X-Timing 冒烟用例，需 ASR 模型 + DeepSeek key + 网络）\n80|- 4 条 deprecation warning（audioop/on_event/httpx），无一 error\n81|- 无回归缺陷\n82|\n83|---\n84|\n85|## 四、Spec §9 DoD 终检（六条全过）\n86|\n87|| # | 验收标准 | 证据 | 结论 |\n88||---|---|---|---|\n89|| 1 | health 返回 ok，ASR/TTS ready | 自测报告 `{\"status\":\"ok\",\"asr\":\"ready\",\"tts\":\"edge\"}` | ✅ |\n90|| 2 | 三句中文实测：语音可听懂、语义正确 | 自测报告 §二：ASR 3/3 全对，LLM 回复符合 §6 人设 | ✅ |\n91|| 3 | X-Timing 头完整，各环节耗时可查 | 自测报告 §二 timing 数据 + 结构化日志 | ✅ |\n92|| 4 | 断网/edge 失败自动切 piper 不崩 | 自测报告 §三：edge 403 三次均切 piper，fallback 日志完整 | ✅ |\n93|| 5 | 交付：源码 + requirements + README + 自测报告 | voice-bridge/ 目录文件齐全 | ✅ |\n94|| 6 | pytest 冒烟 ≥4 条 | 5 条全绿（37.99s）| ✅ |\n95|\n96|---\n97|\n98|## 五、agent.md v1.2 OI 关闭自动化 — 合规性核对\n99|\n100|v1.2 §3.3 新增条款：\n101|\n102|> \"审核确认无问题、达到验收标准后，责任方自行决定关闭，**无需 Vange 逐条决策**。\"\n103|> \"关闭流程：责任方完成修复 → 提交对方（Hermes）验证确认 → 标记 closed（含关闭日期）。\"\n104|\n105|实际执行链路：\n106|\n107|1. WorkBuddy 修复 OI-003/005/006 → commit 7aa7f74\n108|2. 提交 Hermes 验证 → 本报告完成验证确认\n109|3. WorkBuddy 在 Open-Issues.md 标记 closed（含 2026-08-11 日期）\n110|4. Vange 未介入（无需逐条决策）\n111|\n112|与 v1.2 条款完全一致。✅\n113|\n114|---\n115|\n116|## 六、工作区清洁度\n117|\n118|```\n119|git status --short\n120|（无输出，工作区干净）\n121|```\n122|\n123|HEAD=7aa7f74，main 分支，无未提交变更。✅\n124|\n125|---\n126|\n127|## 七、结论与下一步\n128|\n129|v0.1 语音桥服务交付闭环已达成：\n130|\n131|- 代码质量：抽象接口可插拔、错误处理完整、打点计时规范、直连 DeepSeek\n132|- Spec 合规：§3~§10 全量覆盖，§9 六条 DoD 全过\n133|- 遗留项：4 条 OI 均为 v0.2 规划项（edge TTS 恢复方案、ASR 模型名修正、health 增强、VAD），不阻塞 v0.1 合入\n134|- 轮次余量：1 轮（当前第2轮，上限3轮）\n135|\n136|**v0.1 → RELEASE。WorkBuddy 可推进 v0.2。**\n137|\n138|---\n139|\n140|*审查执行：Hermes（deepseek-v4-pro）· 2026-08-11 · agent.md v1.2 合规*\n141|", "total_lines": 140, "file_size": 5371, "truncated": false, "is_binary": false, "is_image": false}


### Assistant — 2026-08-14T07:51:14.172414Z



## Tool calls

```json
[
  {
    "id": "call_00_o2keA9M3qWiFIvMnRrhI0972",
    "call_id": "call_00_o2keA9M3qWiFIvMnRrhI0972",
    "response_item_id": "fc_00_o2keA9M3qWiFIvMnRrhI0972",
    "type": "function",
    "function": {
      "name": "read_file",
      "arguments": "{\"path\": \"协同工作文档/审查报告/2026-08-13-现有文件一致性审查报告.md\"}"
    }
  }
]
```


### Tool — read_file — 2026-08-14T07:51:18.932628Z

{"content": "1|# 可穿戴健康辅助系统——现有文件一致性审查报告\n2|\n3|> 审查日期：2026-08-13  \n4|> 审查对象：`D:\\workbuddy_project\\项目\\可穿戴健康辅助系统`  \n5|> 审查基线：`main` / `87d6b1d599f86452349cf9c29e443387e716ae9f`  \n6|> 审查性质：只读一致性审查；本报告不修改现有代码、Spec、里程碑或历史审查记录  \n7|> 严重度定义：P1 = 进入下一开发阶段前必须裁决；P2 = 应尽快统一；P3 = 治理、维护或隐私改进\n8|\n9|## 1. 审查范围\n10|\n11|本次审查覆盖以下内容：\n12|\n13|1. 根目录入口与协作文件：`README.md`、`CONTEXT.md`、`AGENTS.md`、`agent.md`。\n14|2. 规划文件：Word 总纲、技术验证、M0/M1 里程碑、语音桥 v0.1/v0.2 Spec、开发环境验证 Spec。\n15|3. 状态与治理文件：协作记录、两轮审查报告、`Open-Issues.md`、总负责人文档目录。\n16|4. 实现与证据：`voice-bridge/` 源码、配置、依赖、测试、README、v0.1 自测报告和保存的音频/响应头。\n17|5. Git 现状：工作区、当前提交、远程配置和本地追踪分支关系。\n18|6. Word 总纲视觉检查：将 7 页 DOCX 完整渲染后逐页检查内容和版面。\n19|\n20|排除项：未把 `.git/`、虚拟环境、模型二进制、`.workbuddy/` 和临时同步目录作为业务文档审查对象。\n21|\n22|## 2. 执行摘要\n23|\n24|### 2.1 总体结论\n25|\n26|项目目录职责、v0.1 模块划分、配置分离、密钥忽略和已有实测证据总体合理；但“当前状态”“下一阶段接口契约”和“里程碑闭环”存在多处实质冲突。\n27|\n28|**结论：当前不宜直接按 v0.2 Spec 开发，也不具备宣布 M1 可验收的条件。建议先完成一次 Spec 修订与状态对齐。**\n29|\n30|### 2.1.1 用户补充决策（2026-08-13）\n31|\n32|TTS 路线已由用户再次确认：**Edge-TTS 为主引擎，Piper 为故障兜底。**\n33|\n34|该决策区分“产品/配置主引擎”和“某次请求实际使用的引擎”：如果 Edge 当前不可用而自动切到 Piper，只代表 fallback 生效，不代表项目策略变更为 Piper 主引擎。v0.2 Spec 中将 Piper 定义为默认主引擎的内容，应按本决策修订。\n35|\n36|### 2.2 当前实际 gate 状态\n37|\n38|| 对象 | 当前可确认状态 | 审查判断 |\n39||---|---|---|\n40|| Git | 初检工作区干净；`main` 与本地 `origin/main` 追踪引用为 0/0；已配置 GitHub origin | 仓库状态正常，但入口文档描述过期 |\n41|| voice-bridge v0.1 | 历史第2轮报告为 `REVIEW_PASS/RELEASE`；三份保存的正常链路响应为 HTTP 200，带完整 `X-Timing` | 正常链路证据有效；错误路径、日志和自动化 gate 需限域补强 |\n42|| voice-bridge v0.2 | 只有 Spec；`splitter.py`、`pipeline.py`、`vad.py` 和 v0.2 自测报告均不存在 | 符合“尚未开工”，但 Spec 必须先返工 |\n43|| M0 | 文档仍记为待硬件到货/待 V-01～V-12；ESP-IDF 已安装 | 工具链安装不等于 M0 全绿，尚无完整硬件验收证据 |\n44|| M1 | 文档记为未开始 | 当前 gate 含无对应实施任务的“共用记忆”，无法闭环 |\n45|\n46|建议 gate 表述：\n47|\n48|- `voice-bridge v0.1：RELEASE_WITH_EVIDENCE_GAPS`——正常链路已证明，但应补错误路径与测试门。\n49|- `voice-bridge v0.2：SPEC_REWORK_REQUIRED`——未开工，先修订接口与验收定义。\n50|- `M0：NOT_VERIFIED`——不能用 ESP-IDF 已安装代替 V-01～V-12 全绿。\n51|- `M1：NOT_STARTED / GATE_NOT_CLOSED`。\n52|\n53|## 3. P1——进入下一阶段前必须裁决\n54|\n55|### P1-01 当前阶段和仓库事实过期\n56|\n57|**证据**\n58|\n59|- `AGENTS.md:38-42` 仍写“v0.1 语音桥服务开发前”和“尚未关联远程”。\n60|- `README.md:5-7` 仍写“v0.1 开发准备期”。\n61|- `协同工作文档/审查报告/2026-08-11-审查-第2轮.md:9-14,129-136` 已宣布 v0.1 `REVIEW_PASS/RELEASE`。\n62|- `规划文档/Spec文档/2026-08-11-语音桥-spec-v0.2.md:14-15,327` 说明 v0.1 已完成、v0.2 尚待确认开工。\n63|- 仓库实际已配置 `origin=https://github.com/Vange-wang/Wearing_Health_System.git`。\n64|\n65|**影响**\n66|\n67|新执行者可能重复开发 v0.1，或错误理解远程、发布和下一步状态。\n68|\n69|**建议**\n70|\n71|在根 README 增加唯一的“当前状态”区，并写明更新时间、证据提交和下一 gate；`AGENTS.md` 只保留稳定规则，不承担易过期的进度快照。\n72|\n73|### P1-02 M1 的“共用记忆”验收没有对应实施任务\n74|\n75|**证据**\n76|\n77|- `规划文档/里程碑文档/README.md:10` 将“共用记忆验证”列为 M1 DoD。\n78|- `规划文档/里程碑文档/2026-08-11-M0M1-执行路线图.md:47-53` 的 F1～F4 只有固件、联调和唤醒词任务。\n79|- `规划文档/Spec文档/2026-08-11-语音桥-spec-v0.2.md:14-18` 明确共用记忆属于 v0.3，且 v0.2 禁止接入 Hermes。\n80|\n81|**影响**\n82|\n83|即使 v0.2 和固件全部完成，M1 仍无法按当前 DoD 全绿。\n84|\n85|**建议**\n86|\n87|二选一：\n88|\n89|1. 在 M1 中增加 v0.3/Hermes 会话集成任务、接口 Spec 和独立验收；或\n90|2. 将“共用记忆”移至独立的后续里程碑，不再作为当前 M1 gate。\n91|\n92|### P1-03 开发板上传 Opus，语音桥只接收 WAV\n93|\n94|**证据**\n95|\n96|- `规划文档/里程碑文档/2026-08-11-M0M1-执行路线图.md:47`：固件执行“opus 编码 → WiFi 上传”。\n97|- `规划文档/Spec文档/2026-08-11-语音桥-spec-v0.1.md:52-63`：服务只接收 WAV。\n98|- `规划文档/Spec文档/2026-08-11-语音桥-spec-v0.2.md:100-105`：v0.2 仍接收完整 WAV。\n99|\n100|**影响**\n101|\n102|固件和服务器分别按文档实现后无法直接联调；当前没有定义谁负责 Opus 解码、容器格式、采样率或错误码。\n103|\n104|**建议**\n105|\n106|在开工前锁定唯一线协议，至少明确：上传格式、编码参数、分帧、Content-Type、服务端解码责任、最大时长/大小和兼容策略。\n107|\n108|### P1-04 “全流式 ASR”与 v0.2 执行规格冲突\n109|\n110|**证据**\n111|\n112|- `规划文档/技术验证/2026-08-11-语音引擎选型-结论.md:27-29` 把近实时 ASR、禁止整段录完上传列为 v0.2 硬前提。\n113|- `规划文档/Spec文档/2026-08-11-语音桥-spec-v0.2.md:102-114,138` 仍要求完整 WAV 上传后 VAD/ASR，并声明现有 ASR 不改。\n114|\n115|**影响**\n116|\n117|当前 v0.2 只能实现 LLM/TTS 流式，不能证明总纲所称的全链路流式，也不能按原延迟预算解释结果。\n118|\n119|**建议**\n120|\n121|明确选择：\n122|\n123|- 方案 A：v0.2 只做 LLM/TTS 流式，并修正“全流式”和延迟承诺；\n124|- 方案 B：新增上传流、增量 VAD/ASR 协议和对应客户端实现，真正执行近实时 ASR。\n125|\n126|### P1-05 流式响应缺少可靠的应用层分帧\n127|\n128|**证据**\n129|\n130|- `规划文档/Spec文档/2026-08-11-语音桥-spec-v0.2.md:100-109` 要求每个 HTTP chunk 为一句完整 WAV，整体 `Content-Type: audio/wav`。\n131|- 同一 Spec `:267,313-314` 又把 chunk 可独立播放作为验收，并将 ESP32 解析留到 M1。\n132|\n133|**问题**\n134|\n135|HTTP transfer chunk 不是稳定的应用消息边界，可能被服务器、代理或客户端拆分、合并。多个 RIFF/WAV 文件串接也不是标准的单一 `audio/wav` 实体。\n136|\n137|**建议**\n138|\n139|改用以下任一明确协议：长度前缀帧、自定义 multipart boundary、WebSocket 二进制帧，或一个连续 PCM/编码音频流。不得把 HTTP chunk 边界直接当句子边界。\n140|\n141|### P1-06 `open_ms` 和首包响应头定义无法同时成立\n142|\n143|**证据**\n144|\n145|- `规划文档/Spec文档/2026-08-11-语音桥-spec-v0.2.md:107-108` 定义 `open_ms` 为请求开始到首 chunk 首字节的墙钟时间。\n146|- 同一 Spec `:197-204` 又定义为 `asr + llm_ttft + tts_first`。\n147|- 分项求和遗漏 VAD、解析、首 token 到满足分句条件的等待、框架和首字节发送开销。\n148|- `X-Timing-First-Token` 被要求放在响应头中，但这些数据要到第一句生成后才完整。\n149|\n150|**影响**\n151|\n152|按分项公式可能低报延迟并错误通过 ≤1.5 秒验收；按常规流式响应又无法在发 header 前知道完整数据。\n153|\n154|**建议**\n155|\n156|唯一权威指标应为 `perf_counter(first_body_send) - perf_counter(request_received)`；分项只用于解释。实现上需预取首句后再构造响应，或使用明确的首帧元数据/响应 trailer 方案。\n157|\n158|### P1-07 Open Issues 台账与 v0.2 Spec 冲突\n159|\n160|**证据**\n161|\n162|- `协同工作文档/审查报告/Open-Issues.md:11,14`：OI-004、OI-007 均为 open。\n163|- `规划文档/Spec文档/2026-08-11-语音桥-spec-v0.2.md:321-322`：分别写“评估完成”和“关闭”。\n164|- 同一 Spec `:327`：v0.2 尚待确认后开工。\n165|\n166|**影响**\n167|\n168|仅把 VAD 写进未开工 Spec，不能证明实现、测试和验收完成；提前关单会丢失真实风险。\n169|\n170|**建议**\n171|\n172|Issue 状态只以 `Open-Issues.md` 为台账。Spec 中改写为“计划覆盖/待实现”；实现、测试和独立确认完成后再关闭。\n173|\n174|### P1-08 v0.1 自动化 gate 会假阳性\n175|\n176|**证据**\n177|\n178|- `voice-bridge/tests/test_smoke.py:120-131` 接受 HTTP 200、400、502，且只有 200 时才检查 `X-Timing`。\n179|- 该用例使用静音并在注释中承认可能到不了 LLM。\n180|- `Code文档/v0.1自测报告.md:40-48` 和第2轮审查报告 `:69-81` 将其描述为全链路 X-Timing 用例通过。\n181|\n182|**影响**\n183|\n184|无语音或上游失败仍可显示 PASSED，自动化不能证明全链路或 X-Timing。\n185|\n186|**边界说明**\n187|\n188|三份已保存的真实响应均为 HTTP 200，且响应头中的 `X-Timing` 与报告一致。因此问题是自动化 gate 和审查措辞过度，不代表正常链路没有跑通。\n189|\n190|**建议**\n191|\n192|把测试拆成：确定性的 mock 全链路 X-Timing 测试，以及明确启用的真实集成测试；真实测试非 200 必须失败，不能接受 400/502。\n193|\n194|### P1-09 v0.1 错误码和“每请求日志”未完整实现\n195|\n196|**证据**\n197|\n198|- `voice-bridge/app/main.py:97-105` 只将 `ValueError` 映射到 400/413，其他 ASR 异常一律 502。\n199|- 损坏但扩展名为 `.wav` 的文件会触发 WAV 解析异常，当前返回 502；Spec `规划文档/Spec文档/2026-08-11-语音桥-spec-v0.1.md:65-74` 要求坏音频/ASR失败为 400。\n200|- Spec `:76` 要求每个请求一条结构化日志；`main.py:77-125` 的失败路径提前返回，唯一 JSON 请求日志位于成功路径 `:130-139`。\n201|\n202|**影响**\n203|\n204|客户端会把输入问题误判为上游故障，失败请求也无法按 Spec 审计和定位。\n205|\n206|**建议**\n207|\n208|增加明确的 WAV 解析异常映射；把统一结构化日志放入覆盖成功与失败的请求级 `finally`/中间件，并记录状态、阶段和错误类型，不记录敏感正文。\n209|\n210|## 4. P2——应尽快统一\n211|\n212|### P2-01 v0.2 Spec 偏离已确认的 TTS 主从决策\n213|\n214|- `规划文档/技术验证/2026-08-11-语音引擎选型-结论.md:13-21` 和 Word 总纲仍写 Edge 主、Piper 兜底。\n215|- `规划文档/Spec文档/2026-08-11-语音桥-spec-v0.2.md:38,156-178` 改为 Piper 主、Edge 实验且默认关闭。\n216|- v0.2 health 示例又把 `edge_unavailable` 写成 fallback 状态，和“Piper 是主引擎”语义冲突。\n217|\n218|用户已于 2026-08-13 再次确认：**Edge-TTS 主、Piper 兜底**。因此这里不再作为待选择方案，而应判定为 v0.2 Spec 需要修正：\n219|\n220|1. `tts.primary` 保持 `edge`，`fallback` 保持 `piper`。\n221|2. Edge 请求失败、超时或启动探测不可用时，自动切换 Piper。\n222|3. health 应分别报告 `configured_primary=edge`、`active_engine=edge|piper` 和 fallback 原因，不能把当前实际落到 Piper 等同于主策略改变。\n223|4. Edge 6.x 的 403、Edge 7.x 输出格式和转码依赖仍需形成可复现的技术方案；在该方案完成前允许 Piper 实际承载请求，但不改变主从定义。\n224|\n225|### P2-02 ESP-IDF 版本和安装路径不一致\n226|\n227|- 开发环境 Spec `:38,55`、路线图 `:19,41` 仍写 v5.2.1 和 `D:\\esp-idf`。\n228|- `Code文档/ESP-IDF安装记录.md:5-17` 记录实际为 v5.2.7，路径 `D:\\esp-idf-tools\\frameworks\\esp-idf-v5.2.7`。\n229|\n230|建议将实际接受的版本写回 M0 输入和 V-01 通过标准，避免后续报告同时出现两个锁定版本。\n231|\n232|### P2-03 ASR 模型目录说明不一致\n233|\n234|- `voice-bridge/README.md:15-18` 指示 `models/sherpa-onnx-sense-voice-zh/`。\n235|- `voice-bridge/config.yaml:4-6` 使用完整 dated 目录名。\n236|- v0.1 Spec `:93-95` 的配置示例仍是短目录，`:108-112` 又使用完整目录。\n237|\n238|新环境按 README 操作会启动失败。应统一成一个目录名，或让 README 明确要求同步修改配置。\n239|\n240|### P2-04 v0.2 测试数量和 health schema 不闭合\n241|\n242|- v0.2 Spec `:68` 要新增至少 3 条测试；`:276-280` 又写总数至少 6、继承 v0.1 5 条并至少新增 1 条，同时实际列出 3 类新增测试。\n243|- 若 5 条全部继承且三类都强制，总数应至少 8 条。\n244|- Spec `:62` 称 `schemas.py` 不变，但 health `:81-93` 新增 `tts_fallback`、`vad`；当前 `voice-bridge/app/schemas.py:7-10` 没有这些字段。\n245|\n246|建议直接列出必须通过的测试 ID，不再用互相矛盾的数量摘要；同步更新 response model。\n247|\n248|### P2-05 M0→M1 严格顺序与软件并行开工表述不一致\n249|\n250|- 里程碑 README `:9-13` 写 M0→M1 严格顺序，M1 准入为 M0 全绿。\n251|- 路线图 `:14-25` 又要求到货前立即开发语音桥。\n252|\n253|这可以合理解释为“M1 前置软件工作”，但必须明确该工作不代表 M1 已准入，或单独拆出软件里程碑。\n254|\n255|### P2-06 “断网兜底”措辞不准确\n256|\n257|Piper 只能覆盖 Edge-TTS 不可达；真断网时 DeepSeek 会先失败，不能完成对话。v0.1 Spec 的断网验收应改成“Edge-TTS 故障/不可达注入”，避免声称系统支持断网聊天。\n258|\n259|### P2-07 Edge 16k WAV 依赖不可复现的 vendor patch\n260|\n261|- `voice-bridge/requirements.txt:5` 称 edge-tts 6.1.x 支持直接输出 16k WAV。\n262|- `voice-bridge/app/tts.py:62-64` 和 `voice-bridge/README.md:63-70` 又承认必须修改 venv 内第三方包。\n263|\n264|当前机器能运行不等于干净重建可复现。应将补丁自动化并纳入仓库，或放弃该版本路径。\n265|\n266|### P2-08 “只改配置即可换引擎”与工厂实现不符\n267|\n268|- `AGENTS.md:17` 要求更换 ASR/TTS/LLM 只改配置。\n269|- `voice-bridge/app/asr.py:85-87`、`llm.py:67-69` 固定具体实现。\n270|- `voice-bridge/app/tts.py:133-137` 只允许 Edge 作为主引擎，尚不支持 v0.2 的 `primary: piper`。\n271|\n272|抽象基类设计合理，但当前仅达到“可扩展”，没有达到“只改配置切换”。应修正文档承诺，或实现 provider 注册/工厂映射。\n273|\n274|### P2-09 核心“可穿戴健康”范围尚未进入里程碑链\n275|\n276|- `AGENTS.md:3` 和 `CONTEXT.md:5-18` 定义了生理传感节点、BLE 汇聚和健康分析。\n277|- M0～M2 目前只覆盖 BOX-3、语音聊天和云迁移。\n278|- v0.1/v0.2 提示词仍固定回答“健康数据监测功能即将上线”。\n279|\n280|如果本仓库只负责语音终端子项目，应明确名称和边界；如果目标是完整毕业设计，应增加传感节点、BLE 数据协议、屏幕数据展示、健康分析、安全提示和验收里程碑。\n281|\n282|## 5. P3——治理、维护与隐私改进\n283|\n284|### P3-01 Hermes 负责的 Issue 缺少独立验证方\n285|\n286|`agent.md:111-113` 的关闭流程默认提交 Hermes 验证，而 `:126` 又禁止角色自我批准。对于 Hermes 自己负责的 Spec/决策类 Issue，应指定 WorkBuddy、Vange 或独立审阅方确认，并在台账增加“验证方/证据”字段。\n287|\n288|### P3-02 DOCX 总纲的裁决优先级未定义\n289|\n290|`规划文档/README.md:5-10` 要求先读 Word 总纲，但 `AGENTS.md:20-26` 的冲突优先级没有列出该文件。应明确 DOCX 是背景决策记录，还是位于技术验证/里程碑之上的规范来源。\n291|\n292|### P3-03 健康语音正文被写入 INFO 日志\n293|\n294|`voice-bridge/app/asr.py:81` 与 `llm.py:63` 会记录用户识别文本和回复前 80 字符。对健康场景存在未说明的数据留存风险。建议默认只记录长度、请求 ID、阶段耗时和错误类别；正文日志必须显式开启并设置保留期限。\n295|\n296|### P3-04 历史快照容易被误当成当前指令\n297|\n298|- `协同工作文档/2026-08-11-协作线程4-初始化与开发指令-记录.md` 是初始化 Session 导出，不是当前状态源。\n299|- 第1轮审查已被第2轮结果取代。\n300|- 第2轮报告仍是 v0.1 验收证据，但其中 Issue 表和 Git 状态只代表当时提交。\n301|- Pi 初审的旧问题已由二次审阅报告判定 5/5 修复，不应重复作为当前缺陷。\n302|\n303|建议在历史报告开头加“历史快照，不作为当前状态源”，但不要覆写原结论。\n304|\n305|## 6. 已确认合理或一致的部分\n306|\n307|1. `voice-bridge/` 的 ASR、LLM、TTS、路由、配置和测试目录分工清楚。\n308|2. v0.1 没有越界接入 Hermes；DeepSeek 调用明确 `stream=False`。\n309|3. DeepSeek 客户端使用 `trust_env=False`，符合直连、不使用环境代理的规则。\n310|4. v0.1 系统提示词与 Spec 一致。\n311|5. 端口 `8710`、DeepSeek `base_url/model`、16kHz/16bit/mono 输入口径基本一致。\n312|6. 临时 WAV 文件有 `finally` 清理；Piper WAV 封装、重采样和 Edge→Piper fallback 结构合理。\n313|7. `.env`、模型、venv、`.workbuddy/` 和临时目录均正确 gitignore；未发现密钥被跟踪。\n314|8. 三份保存的正常链路响应均为 HTTP 200，`X-Timing` 数值与自测报告逐项一致。\n315|9. 三个响应 WAV 均可解析为 16kHz、16bit、单声道，Content-Length 与文件大小一致。\n316|10. 离线测试（排除真实全链路用例）结果为 4 passed、1 deselected；说明基础路由/格式/fallback 单元行为可运行，但不能替代真实端到端 gate。\n317|11. Word 总纲共 7 页，渲染后未发现文字截断、重叠或缺字。轻微版面问题是长决策表跨页时没有重复表头，且个别长行被分页拆开。\n318|\n319|## 7. 建议修复顺序\n320|\n321|### 第一步：建立唯一状态源\n322|\n323|1. 更新根 README 当前状态。\n324|2. 删除或改写 AGENTS 中易过期的阶段/远程快照。\n325|3. 增加“项目版本—语音桥版本—固件版本—里程碑”的映射表。\n326|4. 明确 DOCX、Spec、里程碑、技术验证和状态台账的裁决优先级。\n327|\n328|### 第二步：修订 v0.2 Spec 后再开工\n329|\n330|必须一次性裁决：\n331|\n332|1. 开发板上传 Opus 还是 WAV，谁负责解码。\n333|2. v0.2 是否真的包含增量 ASR。\n334|3. 流式音频的应用层分帧协议。\n335|4. `open_ms` 的唯一墙钟定义和首包元数据传递方式。\n336|5. 按用户确认固定 Edge 主、Piper 兜底，并重新定义 health 中“配置主引擎、实际引擎、fallback 原因”的字段语义。\n337|6. response schema、依赖清单和至少 8 条明确测试。\n338|\n339|### 第三步：让 M1 gate 可执行\n340|\n341|补入 v0.3/Hermes 集成任务，或将共用记忆移至后续里程碑；同时把语音桥前置工作与正式 M1 准入区分开。\n342|\n343|### 第四步：补强 v0.1 证据门\n344|\n345|1. 损坏 WAV/ASR 输入错误按 Spec 返回 400。\n346|2. 成功和失败请求都输出一条结构化日志。\n347|3. 重写 X-Timing 测试，400/502 不得通过。\n348|4. 用确定性 mock 测试和显式真实集成测试分别证明行为。\n349|5. 完成限域复审，修正“全链路自动化已通过”的过度结论。\n350|\n351|### 第五步：统一运行与规划文档\n352|\n353|将 v0.2 Spec 同步回 Edge 主、Piper 兜底；同时统一 ESP-IDF v5.2.7 实际路径、ASR 模型目录、Edge 补丁的可复现方式和 Open Issues 状态。\n354|\n355|### 第六步：补完整健康系统路线\n356|\n357|明确本仓库是否只是语音子系统；若不是，新增传感节点、BLE、数据模型、展示、健康分析和安全边界的 Spec/里程碑。\n358|\n359|## 8. 修订完成的验收标准\n360|\n361|以下全部满足后，才建议将 v0.2 从 `SPEC_REWORK_REQUIRED` 切换为可开发：\n362|\n363|- 根 README、AGENTS、里程碑和 Open Issues 对当前状态无冲突。\n364|- 版本—里程碑映射唯一且可查。\n365|- 固件与服务器音频协议完全一致。\n366|- ASR 是否流式有唯一答案，延迟预算与实现一致。\n367|- 流式响应有独立于 HTTP chunk 的应用层分帧。\n368|- `open_ms` 只有一种墙钟定义，测试可以真实测量。\n369|- M1 的每一项 DoD 都有对应任务、责任方和证据路径。\n370|- OI-004/OI-007 状态与实现、测试和验证证据一致。\n371|- v0.1 错误码、每请求日志和 X-Timing 自动化门补齐。\n372|- TTS 明确为 Edge 主、Piper 兜底，且 Edge 不可用时的自动切换、状态报告和依赖安装可在干净环境复现。\n373|\n374|## 9. 最终判断\n375|\n376|现有文件不是整体失控：目录结构、v0.1 正常链路和基础工程纪律均有可用基础。真正的问题集中在状态同步、v0.2 流式接口定义、M1 gate 闭环和自动化证据严谨性。\n377|\n378|因此，本报告建议保留 v0.1 的正常链路成果，但不要把现有 v0.2 Spec 直接交给开发执行；应先完成一次有界的 Spec/状态修订，再进入实现。\n379|", "total_lines": 378, "file_size": 20625, "truncated": false, "is_binary": false, "is_image": false}


### User — 2026-08-14T08:29:31.856478Z

[WORKFLOW_ACTIVE] v0.2 修订期启动。WorkBuddy 已读全 8-13 一致性审查报告 + v0.2 Spec 草案，整理出《v0.2-Spec修订裁决清单》：协同工作文档/2026-08-14-v0.2-Spec修订裁决清单.md。含 A1~A6 必裁决项（TTS 主从按 Vange 8-13 决策 Edge 主 Piper 兜底；音频协议建议③WAV锁定；ASR 建议方案A只做LLM/TTS流式；分帧建议①长度前缀帧；open_ms 建议墙钟+预取首句；OI 台账以 Open-Issues.md 为准）+ B/C/D 类同步项。请读取该清单，准备依据 Vange 裁决后修订 v0.2 Spec；若对裁决项有专业意见请直接给出（尤其 A2/A3/A4/A5）。


### Assistant — 2026-08-14T08:29:40.989887Z



## Tool calls

```json
[
  {
    "id": "call_00_DfNHyDebE7Mvseggmx437277",
    "call_id": "call_00_DfNHyDebE7Mvseggmx437277",
    "response_item_id": "fc_00_DfNHyDebE7Mvseggmx437277",
    "type": "function",
    "function": {
      "name": "read_file",
      "arguments": "{\"path\": \"协同工作文档/2026-08-14-v0.2-Spec修订裁决清单.md\"}"
    }
  }
]
```


### Tool — read_file — 2026-08-14T08:29:49.066027Z

{"content": "1|# v0.2 Spec 修订裁决清单（2026-08-14）\n2|\n3|> **性质**：跨角色裁决输入材料（WorkBuddy 整理，非 Spec 本身）\n4|> **输入源**：① 2026-08-13 现有文件一致性审查报告（P1-01~09 / P2 / P3）② Vange 2026-08-13 TTS 决策 ③ v0.2 Spec 草案（2026-08-11，Hermes 起草）\n5|> **流程**：Vange 对 A 类拍板（每项含推荐）→ Hermes 依据裁决修订 v0.2 Spec → WorkBuddy 确认 DoD 后开工\n6|> **原则**：Open-Issues.md 是唯一 Issue 台账；Spec 中未实现内容不得写\"已关闭/评估完成\"\n7|\n8|---\n9|\n10|## A. 必须裁决（P1 级，进 v0.2 开发前逐条锁定）\n11|\n12|### A1. TTS 主从策略（Vange 2026-08-13 已决，v0.2 Spec 需修订）\n13|- **冲突**：v0.2 Spec §3/§6.3/§8 将 `primary: piper` 设为默认主引擎（OI-004 评估结论）；但 Vange 8-13 已确认 **Edge-TTS 为主引擎、Piper 为故障兜底**。\n14|- **裁决要求**：\n15|  1. `tts.primary` 恢复 `edge`，`fallback` 恢复 `piper`（产品/配置主从不变）\n16|  2. health 分别报告 `configured_primary=edge`、`active_engine=edge|piper`、`fallback_reason`——当前实际落到 piper 只代表 fallback 生效，不代表策略变更\n17|  3. Edge 6.x 403 / Edge 7.x 转码依赖：仍需可复现技术方案；方案完成前允许 piper 实际承载请求，但主从定义不变\n18|- **推荐**：按 Vange 已决执行，v0.2 Spec 全量同步\n19|\n20|### A2. 固件↔服务音频上传协议（P1-03）\n21|- **冲突**：路线图 F1 写\"板子 opus 编码 → WiFi 上传\"；语音桥 v0.1/v0.2 只收 WAV（16k）。双方按文档实现后无法联调。\n22|- **选项**：\n23|  - ① 服务端加 opus 解码（新增依赖，v0.2 允许？）\n24|  - ② 板子改传 WAV（16k PCM 体积大，WiFi 流量翻几倍）\n25|  - ③ **v0.2 锁定 WAV（现状），opus 线协议留 M1 定义接口**（推荐——v0.2 边界内不扩依赖，M1 固件开发时再定）\n26|- **裁决要求**：选 ③ 的话，Spec 需写明\"M1 线协议（opus/采样率/分帧/Content-Type/服务端解码责任）待定，v0.2 期间固定 WAV\"\n27|\n28|### A3. ASR 是否流式（P1-04）\n29|- **冲突**：技术验证结论写\"近实时 ASR、禁止整段录完上传\"（v0.2 硬前提）；v0.2 Spec §3 声明\"ASR 引擎不改（sherpa-onnx 锁定）\"、§5.3 仍要求完整 WAV 上传。\n30|- **选项**：\n31|  - 方案 A：**v0.2 只做 LLM/TTS 流式，修正\"全流式\"表述与延迟承诺**（推荐——ASR 增量流式是另一套协议，工作量翻倍）\n32|  - 方案 B：v0.2 新增上传流 + 增量 VAD/ASR 协议（真实近实时 ASR）\n33|- **裁决要求**：选 A 则 Spec §1/§10 的\"全流式\"\"近实时 ASR\"表述同步修正\n34|\n35|### A4. 流式应用层分帧协议（P1-05）\n36|- **冲突**：v0.2 Spec §5.3 要求\"每 HTTP chunk = 一句完整 WAV、Content-Type: audio/wav\"，但 HTTP transfer chunk 不是稳定应用消息边界（可能被代理/客户端合并拆分）；多个 RIFF 串接也不是标准单一 audio/wav。\n37|- **选项**：\n38|  - ① 长度前缀帧：`4字节大端长度 + WAV bytes` 循环（推荐——解析简单，ESP32 好实现）\n39|  - ② multipart boundary（新增 mime 解析负担）\n40|  - ③ WebSocket 二进制帧（改动大，v0.2 不必）\n41|  - ④ 连续 PCM 流（丢句边界信息）\n42|- **裁决要求**：选 ① 则明确 Content-Type（`audio/x-wav-stream` 或保持 `audio/wav`+说明）、帧格式、EOF 标志\n43|\n44|### A5. open_ms 唯一权威定义（P1-06）\n45|- **冲突**：v0.2 Spec §5.3 定义 `open_ms` = 请求到首 chunk 首字节墙钟；§6.5 又定义 = asr+llm_ttft+tts_first（分项求和漏 VAD/解析/分句等待/框架开销，会低报）；且 X-Timing-First-Token 响应头在首句生成前无法完整发出。\n46|- **裁决要求**：\n47|  1. 唯一权威指标 = `perf_counter(first_body_send) - perf_counter(request_received)`（墙钟）\n48|  2. 分项（asr/llm_ttft/tts_first）仅作解释用，不作验收\n49|  3. 实现方案：预取首句后构造响应头，或首 chunk 前内嵌 JSON 元数据（frame 0 放 timing），或响应 trailer\n50|- **推荐**：墙钟为准 + 预取首句后发头（实现最直接）\n51|\n52|### A6. OI 台账状态（P1-07）\n53|- **冲突**：Open-Issues.md 中 OI-004/OI-007 为 open；v0.2 Spec §12 写\"评估完成/关闭\"。Spec 是未开工草案，不能提前关单。\n54|- **裁决要求**：Spec §12 改写为\"计划覆盖/待实现\"；状态唯一以 Open-Issues.md 为准；实现+测试+独立确认完成后才关\n55|\n56|---\n57|\n58|## B. 状态文档同步（P1-01 / P2-02 / P2-03 / P2-05）\n59|\n60|| # | 项 | 现状 | 修订 |\n61||---|---|---|---|\n62|| B1 | README 当前阶段 | \"v0.1 开发准备期\"（过期） | 改为\"v0.1 RELEASE / v0.2 Spec 修订期\"，加唯一状态区 + 更新时间 |\n63|| B2 | AGENTS.md 快照 | 含\"尚未关联远程\"等过期信息 | 移除易过期快照，只留稳定规则 |\n64|| B3 | ESP-IDF 版本 | 开发环境 spec/路线图写 v5.2.1 | 统一 v5.2.7（D:\\esp-idf-tools\\frameworks\\esp-idf-v5.2.7） |\n65|| B4 | ASR 模型目录 | README 短目录 vs config 完整目录 | 统一完整目录名 |\n66|| B5 | M0→M1 顺序 | 严格顺序 vs 软件并行表述矛盾 | 明确\"语音桥前置工作 ≠ M1 准入\" |\n67|\n68|## C. v0.1 补强项（并入 v0.2 开发一起做，P1-08/09/P2-06/P3-03）\n69|\n70|| # | 项 | 内容 |\n71||---|---|---|\n72|| C1 | 错误码 | 损坏 WAV → 400 `bad_audio_format`（当前落 502） |\n73|| C2 | 日志 | 请求级结构化日志覆盖失败路径（finally/中间件，含状态/阶段/错误类型，不记正文） |\n74|| C3 | 测试门 | 真实集成测试非 200 必须失败（当前接受 400/502 会假阳性）；mock 全链路与真实集成分两类 |\n75|| C4 | 措辞 | \"断网兜底\" → \"edge-tts 故障注入兜底\"（真断网 DeepSeek 也会失败） |\n76|| C5 | 隐私 | 健康语音正文默认不落 INFO 日志（只记长度/耗时/错误类） |\n77|\n78|## D. M1 gate 可执行性（P1-02）\n79|\n80|- **问题**：M1 DoD 含\"共用记忆验证\"，但路线图 F1~F4 无对应任务（共用记忆属 v0.3 且 v0.2 禁止接 Hermes）\n81|- **选项**：① M1 补 v0.3/Hermes 集成任务+接口 Spec+验收（范围膨胀）② **\"共用记忆\"移出 M1，独立后续里程碑**（推荐）\n82|\n83|## E. P2/P3 摘要（参考，不阻塞 v0.2 开工）\n84|\n85|- P2-01 已并入 A1（Vange 已决）\n86|- P2-04 v0.2 测试数量与 health schema 闭合（列出必须通过的测试 ID，更新 response model）\n87|- P2-07 edge vendor patch 可复现（patch 自动化纳入仓库或放弃 6.x 路径）\n88|- P2-08 \"只改配置换引擎\"与工厂实现对齐（provider 注册或修正承诺）\n89|- P2-09 项目范围：本仓库是否只是语音子系统（传感/BLE/健康分析另行规划）\n90|- P3-01 Hermes 名下 Issue 的独立验证方（台账加\"验证方/证据\"字段）\n91|- P3-02 DOCX 总纲裁决优先级（背景决策 vs 规范来源）\n92|- P3-04 历史报告标注\"历史快照，非当前状态源\"\n93|\n94|---\n95|\n96|## 裁决输出格式（Vange 拍板后）\n97|\n98|- A 类：逐项给结论（如\"A1: 确认 Edge 主 Piper 兜底；A2: 选③；A3: 方案A；A4: ①；A5: 墙钟+预取首句；A6: 按台账\"）\n99|- B/C/D：确认执行即可\n100|- 裁决后 → Hermes 修订 v0.2 Spec（在协作线程 5）→ WorkBuddy 确认 DoD → 开工\n101|\n102|*整理：WorkBuddy · 2026-08-14 · 待 Vange 裁决 + Hermes 修订*\n103|", "total_lines": 102, "file_size": 7229, "truncated": false, "is_binary": false, "is_image": false}


### Assistant — 2026-08-14T08:31:15.603103Z



## Tool calls

```json
[
  {
    "id": "call_00_OHDlC4879SAvBTpYZoXD1861",
    "call_id": "call_00_OHDlC4879SAvBTpYZoXD1861",
    "response_item_id": "fc_00_OHDlC4879SAvBTpYZoXD1861",
    "type": "function",
    "function": {
      "name": "read_file",
      "arguments": "{\"path\": \"规划文档/技术验证/2026-08-11-语音引擎选型-结论.md\"}"
    }
  },
  {
    "id": "call_01_jPjBeA0WaCNac8UGszyt9432",
    "call_id": "call_01_jPjBeA0WaCNac8UGszyt9432",
    "response_item_id": "fc_01_jPjBeA0WaCNac8UGszyt9432",
    "type": "function",
    "function": {
      "name": "read_file",
      "arguments": "{\"path\": \"规划文档/里程碑文档/2026-08-11-M0M1-执行路线图.md\"}"
    }
  },
  {
    "id": "call_02_Wz6T2J8VIv5axXlihH2R8216",
    "call_id": "call_02_Wz6T2J8VIv5axXlihH2R8216",
    "response_item_id": "fc_02_Wz6T2J8VIv5axXlihH2R8216",
    "type": "function",
    "function": {
      "name": "read_file",
      "arguments": "{\"path\": \"规划文档/里程碑文档/README.md\"}"
    }
  }
]
```


### Tool — read_file — 2026-08-14T08:31:20.383507Z

{"content": "1|# 语音引擎选型结论（2026-08-11）\n2|\n3|## ASR（语音转文字）— 选定：本地 sherpa-onnx + SenseVoice\n4|\n5|| 方案 | 延迟 | 中文质量 | 成本 | 结论 |\n6||---|---|---|---|---|\n7|| sherpa-onnx + SenseVoice | 0.2~0.3s（近实时） | 好 | 免费 | ✅ 选定 |\n8|| FunASR (Paraformer) | 0.2~0.4s | 更好 | 免费 | 备选，依赖重（torch） |\n9|| 云 API（火山/讯飞） | 0.5~1s | 好 | 免费额度 | 延迟吃亏，作后补 |\n10|\n11|理由：本地推理砍掉\"上传+云端排队\"延迟，是开口延迟进 1.5s 的关键；免费、离线、论文可引（SenseVoice 系阿里开源）。\n12|\n13|## TTS（文字转语音）— 选定：Edge-TTS 主 + piper 兜底\n14|\n15|| 方案 | 延迟 | 音色 | 成本 | 结论 |\n16||---|---|---|---|---|\n17|| Edge-TTS（晓晓） | 0.3~0.6s | 自然 | 免费 | ✅ 主引擎（需联网） |\n18|| piper（zh_CN-huayan） | 0.1~0.2s | 一般 | 免费 | ✅ 离线兜底 |\n19|| 云 API（火山豆包） | 0.3~0.8s | 一流 | 免费额度 | 备选升级项 |\n20|\n21|理由：音色自然 + 免费；网络不稳时自动切 piper（延迟反而更低，牺牲音色），保证不崩。\n22|\n23|## 延迟预算（开口延迟 = 说完到听到第一句）\n24|\n25|静音判定 0.25s + 上传 0.05s + ASR 0.2~0.3s + LLM 首字 0.4~0.8s + TTS 首句 0.3~0.6s + 回传 0.05s ≈ **1.2~1.6s**（v0.2 流式化后稳定 1.2~1.4s）。\n26|\n27|两个硬前提（v0.2 必须做到）：\n28|1. LLM 流式输出 + 分句 TTS 流水线——禁止等完整回复再合成（那会 3~5s 开口）\n29|2. ASR 近实时路径，禁止\"录完整段再上传识别\"\n30|\n31|## 风险\n32|\n33|- Edge-TTS 国内网络偶发不稳 → piper 兜底已覆盖\n34|- GitHub 下载模型慢 → 镜像/Hermes 协助\n35|- 完整回复播完需 3~5s（正常，仅\"开口\"要求 ≤1.5s）\n36|", "total_lines": 35, "file_size": 1742, "truncated": false, "is_binary": false, "is_image": false}


### Tool — read_file — 2026-08-14T08:31:20.390530Z

{"content": "1|# M0/M1 执行路线图（2026-08-11）\n2|\n3|> 用途：BOX-3 硬件到货后的行动布局。执行方：**WorkBuddy（强制 Kimi K3）**；审核方：**Hermes（deepseek-v4-pro）**；总指挥：Vange。\n4|> 关联文档：实现方案 v1.1（规划文档/根）、开发环境验证 spec v0.1、语音桥 spec v0.1、agent.md。\n5|\n6|## 0. 角色分工（红线）\n7|\n8|| 角色 | 职责 | 强制模型 |\n9||---|---|---|\n10|| WorkBuddy | 一切开发/验证执行：工具链安装、示例编译烧录、固件代码、语音桥代码、自测 | **Kimi K3** |\n11|| Hermes | 规划、Spec、审核、验收、放行（**不写业务代码**） | deepseek-v4-pro（产出/审查时） |\n12|| Vange | 决策、下单、跨角色仲裁 | — |\n13|\n14|## 1. 三条并行线（到货前即启动）\n15|\n16|```\n17|线A 电脑侧（不依赖硬件，立即开工）\n18|    ① 语音桥服务开发（按语音桥 spec v0.1，WorkBuddy/K3）\n19|    ② ESP-IDF v5.2.1 工具链安装（~2GB，到货前装完，D 盘）\n20|    ③ sherpa-onnx + SenseVoice 模型下载（models/）\n21|线B 板子侧（依赖硬件）\n22|    M0 环境验证 → M1 固件开发（本文档 §3/§4）\n23|线C 流程侧\n24|    Hermes 审核 gate + 里程碑推进\n25|汇合点：联调（板子 ↔ 语音桥 ↔ DeepSeek）\n26|```\n27|\n28|## 2. 到货当天（WorkBuddy，0.5h）\n29|\n30|1. 开箱核对：蓝色标准版 + SENSOR/DOCK/BRACKET/BREAD 四配件齐全、屏幕无损伤\n31|2. 首次上电：USB-C 接电脑，跑**出厂固件**体验官方唤醒词+命令词 demo（建立目标体验基线）\n32|3. 串口确认：设备管理器识别 COM 口，日志正常\n33|4. 异常 → 立即回报 Hermes（拍照/日志）\n34|\n35|## 3. M0 开发环境验证（1~2 天，WorkBuddy/K3 执行）\n36|\n37|- 按 `Spec文档/2026-08-11-开发环境验证-spec-v0.1.md` 的 V-01~V-12 顺序执行\n38|- 顺序：V-01 工具链 → V-02 BSP 识别 → V-03 LCD/触摸 → V-04 双麦 → V-05 喇叭 → **V-06 chatgpt_demo 全链路（核心关）** → V-07 WiFi → V-08 PSRAM → V-09 opus → V-10 BLE → V-11 烧录 → V-12 ESP-SR\n39|- 证据存 `Code文档/v0.1-环境验证/`（每条：截图/日志/耗时）\n40|- 产出 `环境验证报告-v0.1.md` → Hermes（v4-pro）审核\n41|- **M0 gate**：V-01~V-12 全绿 + 报告审核通过 → 锁定工具链（预期 ESP-IDF v5.2.1）→ 才可开固件开发\n42|\n43|## 4. M1 固件开发（M0 gate 通过后，WorkBuddy/K3）\n44|\n45|| 步骤 | 内容 | 依赖 |\n46||---|---|---|\n47|| F1 | 固件 v0.1（按键说话版）：录音 → 按键判定 → opus 编码 → WiFi 上传 → 接收音频 → I2S 播放 → 屏幕状态显示 | M0 gate |\n48|| F2 | 联调：板子 ↔ 语音桥 ↔ DeepSeek；延迟打点实测（X-Timing），逐环节定位超预算点 | F1 + 线A 语音桥 |\n49|| F3 | 唤醒词第二步：ESP-SR 预制中文唤醒词（与 F2 并行跟进） | F1 |\n50|| F4 | 自定义唤醒词训练（最后，不阻塞主线） | F3 |\n51|\n52|- 固件代码由 WorkBuddy 编写，Hermes 审查（至多 3 轮，审查报告落 `协同工作文档/审查报告/`）\n53|- **M1 gate**：联调 4 项全绿（语音链路通 / 开口延迟实测 1~1.5s / 共用记忆 / 手机热点无线）→ 才可进 M2 阶段2 迁移\n54|\n55|## 5. 风险预案\n56|\n57|| 风险 | 预案 |\n58||---|---|\n59|| 某外设示例跑不通 | ESP Launchpad 刷官方固件交叉验证——判别硬件问题 vs 代码问题 |\n60|| 延迟超 1.5s | 打点定位，重点查 LLM 首字 + TTS 分句流水线（流式化） |\n61|| opus 内存/性能问题 | 16MB PSRAM 兜底；降采样/小模型备选 |\n62|| 固件刷坏 | 分区表保留 factory 固件，随时回刷 |\n63|| 工具链下载慢 | 离线安装包/镜像；D 盘安装 |\n64|\n65|## 6. 协作纪律（agent.md 全量适用）\n66|\n67|- 每步执行回报格式：`[状态] 一句话结论 + 证据路径`\n68|- 任务单缺项不接；DoD 前置确认；Spec 未覆盖先补 Spec\n69|- WorkBuddy 开发必须 Kimi K3；Hermes 审查必须 deepseek-v4-pro\n70|- 阻塞 15 分钟无响应 → 重发并 @Vange\n71|", "total_lines": 70, "file_size": 3900, "truncated": false, "is_binary": false, "is_image": false}


### Tool — read_file — 2026-08-14T08:31:20.396556Z

{"content": "1|# 里程碑文档\n2|\n3|阶段交付计划：每个阶段的交付范围、验收标准（DoD）与状态。每阶段交付前更新本目录。\n4|\n5|## 里程碑链（源自实现方案 v1.1）\n6|\n7|| 里程碑 | 内容 | 状态 | 准入条件 | DoD（完成标准） | 关联文档 |\n8||---|---|---|---|---|---|\n9|| M0 开发环境验证 | 验证 BOX-3 板级支持与工具链选型 | 待硬件到货 | 硬件到货 + ESP-IDF 安装完成 | V-01~V-12 全部通过（Spec §3.1），证据与报告落盘 `Code文档/v0.1-环境验证/`，经 Hermes 审核 | 开发环境验证 spec v0.1 |\n10|| M1 阶段1 电脑端验证 | 语音桥服务 + 开发板固件 + 联调 | 未开始 | M0 全绿（板级支持确认、工具链锁定） | 联调清单全绿：语音问答链路通 / 开口延迟实测 1~1.5s / 共用记忆验证 / 手机热点无线验证 | 语音桥 spec v0.1、实现方案 §5 |\n11|| M2 阶段2 云端迁移 | 腾讯云轻量 + profile 迁移 + 随身 | 未开始 | M1 全绿 | 远程链路延迟可接受 / 7x24 在线 / 随身热点可用 / 电脑本地停用不双开 | 实现方案 §6 |\n12|\n13|> 依赖链：**M0 → M1 → M2 严格顺序**，阶段边界不可逾越；明细以方案文档（`../Hermes语音开发板实现方案-20260811.docx`）已敲定内容为准。\n14|> 执行布局：`2026-08-11-M0M1-执行路线图.md`（三线并行 / 到货流程 / 风险预案）。\n15|", "total_lines": 14, "file_size": 1376, "truncated": false, "is_binary": false, "is_image": false}


### Assistant — 2026-08-14T08:33:45.441392Z

已读全《v0.2-Spec修订裁决清单》，并复核了三份源文档（8-13 一致性审查报告、技术验证选型结论、M0M1 路线图 + 里程碑 README）。清单整理质量很高，A/B/C/D 分类与 P 级映射准确。下面是我作为 Hermes 的逐条专业意见。

═══════════════════════════════════
A 类必裁决项 — 我的意见
═══════════════════════════════════

A1. TTS 主从（Vange 已决）
同意全量同步：primary=edge / fallback=piper，主从定义不因某次请求落到 piper 而改变。
但有一个 WorkBuddy 清单未点透的技术缺口，必须一起定：Vange 说"Edge 主"，但当前 edge 6.x 是【双杀】状态——(1) 现网 403（微软封 6.x token）；(2) 依赖不可复现的 vendor patch（communicate.py 改 outputFormat）才能出 16k WAV。也就是说"Edge 主"目前是纸面策略，没有可复现的实现通路。
真正的恢复路径是 edge 7.x（修了 403，但只出 24k mp3，转码要 pydub，而 pydub 解 mp3 又依赖系统 ffmpeg——不是纯 pip 依赖，踩依赖红线）。我的建议：
  · v0.2 内：edge 恢复作为独立评估任务（7.x + pydub + ffmpeg 可行性），不阻塞主线；期间 piper 实际承载，health 如实报 active_engine=piper / fallback_reason=edge_403。
  · 这完全符合 Vange"方案完成前允许 piper 承载"的口径，只是要把"评估任务"显式写进 Spec，别让 edge 主变成一句空话。

A2. 固件↔服务音频协议
同意选③（v0.2 锁 WAV，线协议留 M1）。理由充分：v0.2 只交付 PC 端（Spec §11 已声明 ESP32 留 M1），此时引入 opus 解码违反"不引入未列明依赖"红线。
但补两条，防"锁 WAV"被误读成终态：
  · 板子原生就是 opus（路线图 F1"录音→opus 编码→WiFi 上传"+ M0 V-09 专门验 opus），所以 M1 大概率回到 opus，届时服务端加一个 opus→PCM 解码层。v0.2 架构必须留干净的解码接缝：流水线契约写成"PCM 16k/16bit/mono 进入 VAD/ASR"，而不是"WAV 文件进入"，这样 M1 只在 VAD 前插一层解码，不动流水线。
  · Spec 里明确写一句："M1 线协议（opus/采样率/分帧/Content-Type/解码责任）待定，v0.2 固定 WAV"。

A3. ASR 是否流式
强烈同意方案 A。这是本次最重要的一次"诚实修正"：
  · 增量 ASR（方案 B）是另一套协议+实现：音频分块、部分结果 ASR、端点检测。sherpa-onnx 我们用的是离线批式，改流式要换解码器配置 + 端点检测逻辑，工作量翻倍，且必须先解决 A2 的线协议（鸡生蛋）。v0.2 不该碰。
  · 但必须同步撤回技术验证文档 27-29 行的硬前提——"ASR 近实时路径，禁止录完整段再上传识别"目前被列为 v0.2 硬前提，与 Spec 直接冲突。这条要作为【书面决策】正式改写为"v0.2 只做 LLM/TTS 流式，ASR 保持批式；增量 ASR 留 v0.3/M1 视端到端延迟再定"，不能静默忽略。
  · 同时技术验证 25 行的延迟预算（"上传 0.05s + 回传 0.05s"）也要同步改口径——那是近乎本地的假设。

A4. 流式分帧协议
同意①（4字节大端长度前缀 + WAV bytes 循环）。这是对的选择：解析简单（ESP32 读 4 字节→分配→读 N→播放，无 mime/边界扫描），WebSocket 双向能力 v0.2 用不上，multipart 加重客户端解析，连续 PCM 丢句边界。
锁定时补三个实现细节：
  · Content-Type 不能用 audio/wav——body 是帧串联，不是合法单一 WAV。建议 application/octet-stream + 自定义头 X-Audio-Framing: wav-length-prefixed 自描述。
  · EOF = HTTP 响应体结束（StreamingResponse 生成器 return），不需要哨兵帧。
  · 加最大帧长上限守卫（防损坏长度前缀导致客户端巨额分配）。

A5. open_ms 唯一权威定义
同意墙钟 + 预取首句。精确定义如下：
  · 唯一权威指标 = perf_counter(首字节 flush 到客户端) - perf_counter(请求体完整接收)，服务端墙钟。
  · 预取首句：ASR → LLM 流（缓冲到首句完整）→ 首句 TTS → 此时才发响应头（含 X-Timing: open_ms/asr_ms/llm_ttft_ms/tts_first_ms）+ 首帧，继续流。这是标准 pre-roll，能诚实拿到头里带 open_ms。
  · 全量 timing（llm_total_ms/tts_total_ms/sentence_count/chunk_count/total_ms）在发头时还不知道 → 走结构化日志 + 自测报告，不进响应头。
  · 必须补一条诚实边界：open_ms 是服务端流水线延迟，在 PC 本地条件下 ≈ 用户开口延迟；真机 WiFi + 480KB WAV 上传，上传本身就要几秒。所以"≤1.5s"只在 v0.2 PC 侧成立，真机端到端延迟是 M1 用 opus 重新做预算的事。Spec 必须把这句话写死，否则将来拿 1.5s 去验收真机是错的。

A6. OI 台账
同意。Spec §12 把 OI-004"评估完成"、OI-007"关闭"改成"计划覆盖/待实现"，状态唯一以 Open-Issues.md 为准，实现+测试+独立确认后才关。

═══════════════════════════════════
B/C/D 要点
═══════════════════════════════════
B 类（文档同步）：全部同意，无异议。注意 B2 改 AGENTS.md 只删过期快照、留稳定规则，别动协作纪律条目。B3 锁定 v5.2.7（安装记录已实装），与我的记忆里"主推 v5.2.1"已冲突，以 v5.2.7 实装为准。
C 类（v0.1 补强）：C3（测试门拆 mock 全链路 vs 真实集成、非 200 必失败）是 P1-08 假阳性的根修，优先级最高，建议和 C1（坏 WAV→400）一起并入 v0.2 首轮交付。
D（M1 gate）：同意②把"共用记忆"移出 M1（属 v0.3，v0.2 禁止接 Hermes）。移出后 M1 gate 剩 3 项（语音链路通 / 开口延迟 1~1.5s / 手机热点无线）。注意：M1 的"开口延迟 1~1.5s"是【真机端到端】指标，依赖 A2 的 opus 线协议先定——所以 D 和 A2 是绑定的，M1 准入前必须先补 opus 决策。

═══════════════════════════════════
我的裁决推荐口径（供 Vange 拍板抄写）
═══════════════════════════════════
A1 确认 Edge 主 Piper 兜底，edge 恢复列独立评估任务（7.x+pydub+ffmpeg），期间 piper 承载
A2 选③，锁 WAV，留 PCM 解码接缝，M1 定 opus
A3 方案 A，撤回"全流式/近实时 ASR"硬前提表述
A4 ①，长度前缀帧，Content-Type=octet-stream
A5 墙钟 + 预取首句，open_ms 仅服务端/PC 侧口径
A6 按台账，Spec 改"计划覆盖"

═══════════════════════════════════
下一步
═══════════════════════════════════
A1 和 A6 已可先行（Vange 已决/无争议）；A2/A3/A4/A5 等 Vange 按上面口径拍板。Vange 一确认，我即在此线程修订 v0.2 Spec（含 §1/§3/§5/§6/§8/§10/§12 及技术验证文档、M1 里程碑联动）。

请把 A2/A3/A4/A5 的裁决结果给我，我随时开工修订。


### User — 2026-08-14T08:37:06.657966Z

[裁决结果·v0.2修订] Vange 已拍板：
A1 ✅ 确认 Edge 主 Piper 兜底（你指出'纸面策略'问题成立——请把 edge 恢复评估任务显式写进 Spec）
A2 ⏭️ Vange 委托你裁决（'我不懂，你定'）——请按你的专业判断定（你倾向③锁WAV+PCM接缝），并在 Spec 写死
A3 ⏭️ Vange 委托你复查一遍（'找 deepseek-v4-pro 复查'）——请复核方案A（只做LLM/TTS流式）是否成立，给最终结论
A4 ✅ 长度前缀帧（4字节大端长度+WAV bytes；octet-stream + X-Audio-Framing 头；EOF=响应体结束；最大帧长守卫）
A5 ✅ 墙钟+预取首句（open_ms=首字节flush-请求接收完；全量timing走日志；≤1.5s 仅 PC 侧成立写死）
A6 ✅ 按 Open-Issues.md 台账，Spec 改'计划覆盖/待实现'
请据此修订 v0.2 Spec（含 §1/§3/§5/§6/§8/§10/§12 及技术验证、M1 里程碑联动），修订完交 WorkBuddy 确认 DoD。


### Assistant — 2026-08-14T08:38:01.196102Z



## Tool calls

```json
[
  {
    "id": "call_00_rOqd3cD5jCIncUETopvH1911",
    "call_id": "call_00_rOqd3cD5jCIncUETopvH1911",
    "response_item_id": "fc_00_rOqd3cD5jCIncUETopvH1911",
    "type": "function",
    "function": {
      "name": "todo",
      "arguments": "{\"todos\": [{\"content\": \"A3 最终结论：复核方案A（只做 LLM/TTS 流式）\", \"id\": \"1\", \"status\": \"in_progress\"}, {\"content\": \"修订 v0.2 Spec（§1/3/5/6/8/10/12 全量）\", \"id\": \"2\", \"status\": \"pending\"}, {\"content\": \"修订技术验证文档（撤回全流式硬前提+延迟预算）\", \"id\": \"3\", \"status\": \"pending\"}, {\"content\": \"修订 M1 里程碑联动（共用记忆移出+opus线协议前置）\", \"id\": \"4\", \"status\": \"pending\"}, {\"content\": \"自检四文档一致性（Spec↔技术验证↔里程碑↔OI台账）\", \"id\": \"5\", \"status\": \"pending\"}, {\"content\": \"交 WorkBuddy 确认 DoD\", \"id\": \"6\", \"status\": \"pending\"}]}"
    }
  },
  {
    "id": "call_01_db0kfYtVeUjbJrJDYHTU7851",
    "call_id": "call_01_db0kfYtVeUjbJrJDYHTU7851",
    "response_item_id": "fc_01_db0kfYtVeUjbJrJDYHTU7851",
    "type": "function",
    "function": {
      "name": "search_files",
      "arguments": "{\"path\": \"voice-bridge\", \"pattern\": \"*\", \"target\": \"files\"}"
    }
  },
  {
    "id": "call_02_R4Pq9fekVkqfxxHLQBSZ0208",
    "call_id": "call_02_R4Pq9fekVkqfxxHLQBSZ0208",
    "response_item_id": "fc_02_R4Pq9fekVkqfxxHLQBSZ0208",
    "type": "function",
    "function": {
      "name": "read_file",
      "arguments": "{\"path\": \"voice-bridge/config.yaml\"}"
    }
  }
]
```


### Tool — todo — 2026-08-14T08:38:01.636572Z

{"todos": [{"id": "1", "content": "A3 最终结论：复核方案A（只做 LLM/TTS 流式）", "status": "in_progress"}, {"id": "2", "content": "修订 v0.2 Spec（§1/3/5/6/8/10/12 全量）", "status": "pending"}, {"id": "3", "content": "修订技术验证文档（撤回全流式硬前提+延迟预算）", "status": "pending"}, {"id": "4", "content": "修订 M1 里程碑联动（共用记忆移出+opus线协议前置）", "status": "pending"}, {"id": "5", "content": "自检四文档一致性（Spec↔技术验证↔里程碑↔OI台账）", "status": "pending"}, {"id": "6", "content": "交 WorkBuddy 确认 DoD", "status": "pending"}], "summary": {"total": 6, "pending": 5, "in_progress": 1, "completed": 0, "cancelled": 0}}


### Tool — search_files — 2026-08-14T08:38:10.780103Z

{"total_count": 50, "files": ["voice-bridge\\.pytest_cache\\v\\cache\\nodeids", "voice-bridge\\venv\\Lib\\site-packages\\edge_tts\\__pycache__\\communicate.cpython-311.pyc", "voice-bridge\\app\\__pycache__\\tts.cpython-311.pyc", "voice-bridge\\app\\__pycache__\\schemas.cpython-311.pyc", "voice-bridge\\app\\__pycache__\\llm.cpython-311.pyc", "voice-bridge\\app\\__pycache__\\config.cpython-311.pyc", "voice-bridge\\app\\__pycache__\\asr.cpython-311.pyc", "voice-bridge\\app\\__pycache__\\main.cpython-311.pyc", "voice-bridge\\app\\__pycache__\\__init__.cpython-311.pyc", "voice-bridge\\tests\\__pycache__\\test_smoke.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\_pytest\\__pycache__\\terminalprogress.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_backends\\__pycache__\\_trio.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_backends\\__pycache__\\_asyncio.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_backends\\__pycache__\\__init__.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\__pycache__\\pytest_plugin.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_tempfile.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_subprocesses.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\streams\\__pycache__\\memory.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_streams.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\streams\\__pycache__\\tls.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\streams\\__pycache__\\stapled.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\streams\\__pycache__\\__init__.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_sockets.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_signals.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_resources.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\__pycache__\\from_thread.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_testing.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_tasks.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\__pycache__\\lowlevel.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_synchronization.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\abc\\__pycache__\\_testing.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\abc\\__pycache__\\_subprocesses.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\abc\\__pycache__\\_tasks.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\abc\\__pycache__\\_streams.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_typedattr.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\abc\\__pycache__\\_sockets.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\abc\\__pycache__\\_resources.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\abc\\__pycache__\\_eventloop.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\abc\\__pycache__\\__init__.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\__pycache__\\to_thread.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_fileio.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_exceptions.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_eventloop.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\_contextmanagers.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\_core\\__pycache__\\__init__.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\venv\\Lib\\site-packages\\anyio\\__pycache__\\__init__.cpython-311-pytest-9.1.1.pyc", "voice-bridge\\README.md", "voice-bridge\\app\\main.py", "voice-bridge\\tests\\test_smoke.py", "voice-bridge\\.pytest_cache\\v\\cache\\lastfailed"], "truncated": true}

[Hint: Results truncated. Use offset=50 to see more, or narrow with a more specific pattern or file_glob.]


### Tool — read_file — 2026-08-14T08:38:15.738678Z

{"content": "1|server:\n2|  host: 0.0.0.0\n3|  port: 8710\n4|asr:\n5|  model_dir: models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17\n6|  sample_rate: 16000\n7|tts:\n8|  primary: edge\n9|  edge_voice: zh-CN-XiaoxiaoNeural\n10|  fallback: piper\n11|  piper_model: models/piper/zh_CN-huayan-medium.onnx\n12|  piper_config: models/piper/zh_CN-huayan-medium.onnx.json\n13|llm:\n14|  base_url: https://api.deepseek.com\n15|  model: deepseek-chat\n16|  api_key_env: DEEPSEEK_API_KEY\n17|log:\n18|  level: INFO\n19|", "total_lines": 18, "file_size": 441, "truncated": false, "is_binary": false, "is_image": false}


### Assistant — 2026-08-14T08:38:20.986154Z



## Tool calls

```json
[
  {
    "id": "call_00_ljVbWE1j84Teuug6QghA7332",
    "call_id": "call_00_ljVbWE1j84Teuug6QghA7332",
    "response_item_id": "fc_00_ljVbWE1j84Teuug6QghA7332",
    "type": "function",
    "function": {
      "name": "search_files",
      "arguments": "{\"path\": \"voice-bridge/app\", \"pattern\": \"*.py\", \"target\": \"files\"}"
    }
  },
  {
    "id": "call_01_9WRDfgu3wPoDIAffpom99118",
    "call_id": "call_01_9WRDfgu3wPoDIAffpom99118",
    "response_item_id": "fc_01_9WRDfgu3wPoDIAffpom99118",
    "type": "function",
    "function": {
      "name": "read_file",
      "arguments": "{\"path\": \"voice-bridge/app/tts.py\"}"
    }
  }
]
```


### Tool — search_files — 2026-08-14T08:38:24.930963Z

{"total_count": 7, "files": ["voice-bridge/app\\main.py", "voice-bridge/app\\tts.py", "voice-bridge/app\\llm.py", "voice-bridge/app\\asr.py", "voice-bridge/app\\config.py", "voice-bridge/app\\schemas.py", "voice-bridge/app\\__init__.py"]}


### Tool — read_file — 2026-08-14T08:38:24.934981Z

{"content": "1|\"\"\"TTS 抽象接口 + edge-tts / piper 实现（含自动兜底，Spec §3/§4/§9）。\n2|\n3|可插拔：换引擎只改 config + 新增 TTSBase 实现，业务代码不动。\n4|- 主引擎 edge-tts：联网，output_format 指定 16kHz/16bit/mono PCM，直接出 WAV\n5|- 兜底 piper：离线，输出原始 PCM（onnx.json 采样率），用标准库 audioop 重采样到 16kHz\n6|  （audioop 是 Python 3.11 标准库，零新增依赖）\n7|\"\"\"\n8|import asyncio\n9|import audioop\n10|import io\n11|import logging\n12|import os\n13|import sys\n14|import wave\n15|from abc import ABC, abstractmethod\n16|from pathlib import Path\n17|\n18|logger = logging.getLogger(\"voice-bridge.tts\")\n19|\n20|# piper-tts 1.6.0 Windows wheel 的 espeak-ng-data 查找用了编译机硬编码路径（打包 bug），\n21|# 在 import piper 前用官方支持的环境变量指到 venv 内真实数据目录。\n22|_piper_data = (\n23|    Path(sys.executable).resolve().parent.parent\n24|    / \"Lib\" / \"site-packages\" / \"piper\" / \"espeak-ng-data\"\n25|)\n26|if _piper_data.exists():\n27|    os.environ.setdefault(\"PIPER_ESPEAKNG_DATA_DIRECTORY\", str(_piper_data))\n28|\n29|\n30|class TTSError(Exception):\n31|    \"\"\"TTS 阶段错误基类。\"\"\"\n32|\n33|\n34|def wrap_pcm_as_wav(pcm: bytes, sample_rate: int) -> bytes:\n35|    \"\"\"16bit/mono PCM 包成 WAV bytes。\"\"\"\n36|    buf = io.BytesIO()\n37|    with wave.open(buf, \"wb\") as w:\n38|        w.setnchannels(1)\n39|        w.setsampwidth(2)\n40|        w.setframerate(sample_rate)\n41|        w.writeframes(pcm)\n42|    return buf.getvalue()\n43|\n44|\n45|class TTSBase(ABC):\n46|    name: str\n47|\n48|    @abstractmethod\n49|    async def synthesize(self, text: str) -> bytes:\n50|        \"\"\"文本 → WAV bytes（16kHz/16bit/mono）。\"\"\"\n51|\n52|\n53|class EdgeTTS(TTSBase):\n54|    name = \"edge\"\n55|\n56|    def __init__(self, voice: str = \"zh-CN-XiaoxiaoNeural\"):\n57|        self.voice = voice\n58|\n59|    async def synthesize(self, text: str) -> bytes:\n60|        import edge_tts\n61|\n62|        # edge-tts 6.1.x 不支持 output_format 参数；venv 内 edge_tts/communicate.py\n63|        # 已做 vendor patch：outputFormat 改为 riff-16khz-16bit-mono-pcm（直接出 16k WAV）\n64|        chunks: list[bytes] = []\n65|        communicate = edge_tts.Communicate(text=text, voice=self.voice)\n66|        async for chunk in communicate.stream():\n67|            if chunk[\"type\"] == \"audio\":\n68|                chunks.append(chunk[\"data\"])\n69|        if not chunks:\n70|            raise TTSError(\"edge-tts 返回空音频\")\n71|        logger.info(\"edge-tts synthesized: %d bytes\", sum(len(c) for c in chunks))\n72|        return b\"\".join(chunks)\n73|\n74|\n75|class PiperTTS(TTSBase):\n76|    name = \"piper\"\n77|\n78|    def __init__(self, model_path: Path, config_path: Path):\n79|        model_path = Path(model_path)\n80|        config_path = Path(config_path)\n81|        if not model_path.exists():\n82|            raise TTSError(f\"piper 模型缺失: {model_path}\")\n83|        try:\n84|            from piper import PiperVoice\n85|        except ImportError as e:\n86|            raise TTSError(f\"piper-tts 未安装: {e}\") from e\n87|        # piper-tts 1.6.0 Windows wheel 的 espeak 数据默认走编译机硬编码路径（打包 bug），\n88|        # 显式传 venv 内真实数据目录修复\n89|        self.voice = PiperVoice.load(\n90|            str(model_path),\n91|            config_path=str(config_path),\n92|            espeak_data_dir=str(_piper_data),\n93|        )\n94|        self.sample_rate = self.voice.config.sample_rate\n95|        logger.info(\"piper loaded: %s (sr=%d)\", model_path, self.sample_rate)\n96|\n97|    def _synthesize_sync(self, text: str) -> bytes:\n98|        chunks = []\n99|        for chunk in self.voice.synthesize(text):\n100|            chunks.append(chunk.audio_int16_bytes)\n101|        pcm = b\"\".join(chunks)\n102|        if not pcm:\n103|            raise TTSError(\"piper 返回空音频\")\n104|        if self.sample_rate != 16000:\n105|            pcm = audioop.ratecv(pcm, 2, 1, self.sample_rate, 16000, None)[0]\n106|        return wrap_pcm_as_wav(pcm, 16000)\n107|\n108|    async def synthesize(self, text: str) -> bytes:\n109|        # piper 是同步 CPU 推理，放线程池避免阻塞事件循环\n110|        return await asyncio.to_thread(self._synthesize_sync, text)\n111|\n112|\n113|class TTSEngine:\n114|    \"\"\"主引擎 + 自动兜底（Spec：edge 失败自动切 piper，日志有 fallback 记录）。\"\"\"\n115|\n116|    def __init__(self, primary: TTSBase, fallback: TTSBase | None):\n117|        self.primary = primary\n118|        self.fallback = fallback\n119|\n120|    async def synthesize(self, text: str) -> bytes:\n121|        try:\n122|            return await self.primary.synthesize(text)\n123|        except Exception as e:\n124|            if self.fallback is None:\n125|                raise TTSError(f\"{self.primary.name} 失败且无兜底: {e}\") from e\n126|            logger.warning(\n127|                \"TTS fallback: %s failed (%s), switching to %s\",\n128|                self.primary.name, e, self.fallback.name,\n129|            )\n130|            return await self.fallback.synthesize(text)\n131|\n132|\n133|def create_tts(cfg) -> TTSEngine:\n134|    \"\"\"工厂：按 config 创建主引擎 + 兜底。piper 缺失/装不上时兜底为 None（降级运行，health 可见）。\"\"\"\n135|    primary: TTSBase = EdgeTTS(cfg.tts_edge_voice) if cfg.tts_primary == \"edge\" else None\n136|    if primary is None:\n137|        raise TTSError(f\"未知 TTS 主引擎: {cfg.tts_primary}\")\n138|\n139|    fallback = None\n140|    if cfg.tts_fallback == \"piper\":\n141|        try:\n142|            fallback = PiperTTS(cfg.tts_piper_model, cfg.tts_piper_config)\n143|        except TTSError as e:\n144|            logger.warning(\"piper 兜底不可用: %s\", e)\n145|    return TTSEngine(primary, fallback)\n146|", "total_lines": 145, "file_size": 5347, "truncated": false, "is_binary": false, "is_image": false}


### Assistant — 2026-08-14T08:40:26.147035Z

代码与配置已核对：当前 `config.yaml` 和 `tts.py` 工厂**本来就是 edge 主 + piper 兜底**（v0.2 草案把它改成 piper 主才是错的），所以 A1 修订是"Spec 回正 + 补 edge 恢复评估任务"，代码方向反而不用动。app/ 现有 7 个文件，splitter/pipeline/vad 确为待新增。

A3 最终结论（deepseek-v4-pro 复核）：**方案 A 成立**。理由三选一列出后写进 Spec §1/§2。

现在开始修订四份文档。



## Tool calls

```json
[
  {
    "id": "call_00_XeciEEpUxnfGxphw7aLG3397",
    "call_id": "call_00_XeciEEpUxnfGxphw7aLG3397",
    "response_item_id": "fc_00_XeciEEpUxnfGxphw7aLG3397",
    "type": "function",
    "function": {
      "name": "write_file",
      "arguments": "{\"content\": \"# 语音桥服务 Spec v0.2（2026-08-11 起草 · 2026-08-14 修订）\\n\\n> 本文档为 voice-bridge v0.2 的开发规格。继承 v0.1 全部架构约束，新增流式能力。\\n> 冲突时本 Spec 优先于 v0.1 Spec。WorkBuddy 按此实现。\\n>\\n> **修订记录（2026-08-14）**：依据《2026-08-13 现有文件一致性审查报告》P1/P2/P3 与 Vange 裁决（A1~A6）修订。修订点：① TTS 主从回正（edge 主 / piper 兜底，A1）；② 音频协议锁定 WAV + 解码接缝（A2）；③ 明确 ASR 批式、撤回\\\"全流式\\\"表述（A3）；④ 流式应用层分帧改为长度前缀帧（A4）；⑤ open_ms 唯一定义墙钟 + 预取首句（A5）；⑥ OI 台账回正\\\"计划覆盖/待实现\\\"（A6）；⑦ 并入 v0.1 补强项（C1~C5）；⑧ 测试数量闭合（P2-04）。\\n\\n## 1. 目标\\n\\n在 v0.1 非流式基础上实现**流式回复**：DeepSeek 流式输出 + 分句 TTS 流水线，开口延迟 ≤ 1.5s（PC 侧服务端流水线，实测 1.2~1.4s）。同时覆盖 v0.1 CONDITIONAL_PASS 遗留 Open Issues（OI-001/004/007）并完成 v0.1 证据门补强（C1~C5）。\\n\\n**范围澄清（A3 裁决）**：v0.2 只做 **LLM/TTS 流式**，ASR 保持**完整 WAV 批式识别**，不做增量/流式 ASR。\\\"流式语音交互\\\"在本阶段指\\\"流式回复\\\"——用户听到第一句时 LLM 尚未生成完整回复，与 ASR 是否增量无关。增量 ASR 属 M1 真机端到端优化，留待 M1 线协议确定后独立评估。\\n\\n## 2. 阶段边界\\n\\n| 阶段 | 内容 | 验收 |\\n|---|---|---|\\n| v0.1（已完成） | 独立语音服务：ASR + DeepSeek(非流式) + TTS | ✅ REVIEW_PASS |\\n| **v0.2（本文档）** | **LLM 流式 + 分句 TTS 流水线 + VAD + health 增强 + v0.1 证据门补强** | **开口延迟 ≤1.5s（PC 侧），流式可感** |\\n| v0.3 | 接入 Hermes 会话（共用记忆/技能） | 与微信共用记忆 |\\n| M1（后续） | 真机固件联调：opus 线协议 + 增量 ASR 评估 | 真机端到端延迟 |\\n\\n**禁止**：v0.2 不得接入 Hermes、不得更改 ASR 引擎（sherpa-onnx 锁定）、不得引入未列明的新增依赖、不得实现增量 ASR。\\n\\n**明确留白（A2 裁决）**：v0.2 期间音频上传协议锁定 WAV（16k/16bit/mono）；固件↔服务的 opus 线协议（编码参数/分帧/Content-Type/解码责任）**待定，留 M1 定义**。架构必须保留 PCM 解码接缝，使 M1 只在 VAD 前插一层 opus→PCM 解码，不改流水线。\\n\\n## 3. 技术栈（v0.1 继承 + v0.2 新增）\\n\\n### 继承（不动）\\n\\n- Python 3.11（解释器同 v0.1）\\n- FastAPI + uvicorn\\n- sherpa-onnx + SenseVoice（ASR，批式）\\n- DeepSeek API 直连（`trust_env=False`）\\n- venv 在 `voice-bridge/venv`\\n\\n### v0.2 新增 / 变更\\n\\n| 组件 | v0.1 | v0.2 | 原因 |\\n|---|---|---|---|\\n| LLM 调用 | `stream=False` | `stream=True`（openai 流式） | 流式回复是 v0.2 核心 |\\n| 句子分割 | 无 | `app/splitter.py`（正则分句，句子缓冲器） | 流式 LLM → 逐句 TTS |\\n| 流式流水线 | 无 | `app/pipeline.py`（ASR→LLM流→分句→TTS→帧编码→chunked 响应） | 编排器 |\\n| VAD | 无（静音幻觉） | `app/vad.py`（能量门限，RMS 计算） | OI-007 计划覆盖 |\\n| TTS 主从 | edge(主)+piper(兜底) | **不变：edge(主)+piper(兜底)**（A1 回正；edge 6.x 现网 403 时 piper 实际承载，主从定义不变） | Vange 8-13 裁决 |\\n| health | 返回主引擎名 | 返回 `configured_primary` / `active_engine` / `fallback_reason` + VAD 状态 | OI-001 计划覆盖 |\\n| HTTP 响应 | 完整 WAV | `Transfer-Encoding: chunked`，每帧 = 一句完整 WAV（长度前缀分帧，A4） | 开口延迟 ≤1.5s |\\n\\n### 新增依赖（v0.2 允许引入）\\n\\n```\\n# requirements.txt 追加\\nnumpy>=1.24        # VAD RMS 计算（v0.1 已通过 sherpa-onnx 间接依赖 numpy）\\n# 句子分割用标准库 re，无新增依赖\\n# 流式响应用 FastAPI StreamingResponse + 标准库 struct（长度前缀），无新增依赖\\n# edge 恢复（7.x + pydub + ffmpeg）为独立评估任务，不进入 v0.2 requirements\\n```\\n\\n## 4. 项目结构（voice-bridge/ 内，v0.1 继承 + 新增）\\n\\n```\\nvoice-bridge/\\n  app/\\n    __init__.py\\n    main.py           # 新增 POST /api/v1/voice/chat/stream（v0.1 路由不变）\\n    config.py         # 新增 vad / pipeline / tts(health 字段) 配置段\\n    asr.py            # 不变（v0.1 批式实现够用）\\n    tts.py            # 改造：health 上报 active_engine/fallback_reason；主从保持 edge/piper\\n    llm.py            # 新增 stream_chat() 生成器；chat() 保留（向后兼容）\\n    schemas.py        # 更新：health 响应模型新增 tts 嵌套对象 + vad 字段（P2-04）\\n    splitter.py       # 新增：句子分割器（SentenceBuffer）\\n    pipeline.py       # 新增：流式流水线编排 + 长度前缀帧编码（StreamingPipeline）\\n    vad.py            # 新增：能量门限 VAD\\n  models/             # 不变（gitignore）\\n  tests/\\n    test_smoke.py     # 追加 v0.2 用例（见 §9.2 明确测试 ID）\\n  config.yaml         # 追加 vad/tts(health)/pipeline 配置段\\n  requirements.txt    # 追加 numpy 版本约束\\n  run.py              # 不变\\n  README.md           # 更新运行说明（v0.2 流式接口、帧协议、edge 状态）\\n```\\n\\n## 5. 接口定义\\n\\n### 5.1 GET /api/v1/health（v0.2 改造 — OI-001）\\n\\n返回示例：\\n\\n```json\\n{\\n  \\\"status\\\": \\\"ok\\\",\\n  \\\"asr\\\": \\\"ready\\\",\\n  \\\"tts\\\": {\\n    \\\"configured_primary\\\": \\\"edge\\\",\\n    \\\"active_engine\\\": \\\"piper\\\",\\n    \\\"fallback_reason\\\": \\\"edge_403\\\"\\n  },\\n  \\\"vad\\\": \\\"enabled\\\"\\n}\\n```\\n\\n规则：\\n\\n- `tts.configured_primary`：配置主引擎（固定 `edge`，产品策略）。\\n- `tts.active_engine`：当前实际可用引擎（`edge` / `piper`）。落到 piper 仅代表 fallback 生效，**不代表主从策略改变**。\\n- `tts.fallback_reason`：仅当 fallback 生效时出现（如 `edge_403` / `edge_timeout` / `edge_unavailable`）；主引擎正常时省略。\\n- `vad`：`\\\"enabled\\\"` | `\\\"disabled\\\"`（取决于 config.yaml）。\\n- 启动时探测 edge-tts 连通性（发最小静音合成请求，超时 3s），不可用时 `active_engine=piper` + `fallback_reason`，health 始终反映真实状态。\\n\\n### 5.2 POST /api/v1/voice/chat（v0.1 行为保留，不变）\\n\\n非流式，完全向后兼容。v0.1 代码不改。WorkBuddy 不用动。\\n\\n### 5.3 POST /api/v1/voice/chat/stream（v0.2 新增）\\n\\n- 请求：同 v0.1 —— `multipart/form-data`，`audio` = WAV（16kHz/16bit/mono，≤15s）\\n- 响应：`Transfer-Encoding: chunked`，**应用层分帧（长度前缀帧，A4）**：\\n  - 每帧 = `[4 字节大端 uint32 长度 N]` + `[N 字节 = 一句完整 WAV 文件（RIFF header + 16kHz/16bit/mono PCM）]`\\n  - 客户端按帧解析：读 4 字节长度 → 读 N 字节 → 播放该句，逐帧循环\\n  - **EOF = HTTP 响应体结束**（无哨兵帧）\\n  - 最大帧长上限（默认 8MB，config 可调），服务端强制守卫，防损坏长度前缀导致客户端巨额分配\\n- 响应头：\\n  - `Content-Type: application/octet-stream`（body 是帧串联，不是合法单一 WAV，**不得用 audio/wav**）\\n  - `X-Audio-Framing: wav-length-prefixed`（自描述分帧协议）\\n  - `X-Timing: {\\\"open_ms\\\":..., \\\"asr_ms\\\":..., \\\"llm_ttft_ms\\\":..., \\\"tts_first_ms\\\":...}`（首句 TTS 完成后、发送响应头前已知；见 §6.5）\\n- 错误：同 v0.1 错误码表（§5.4），流式错误时 HTTP 状态码在第一个帧前发出\\n\\n流式处理流程（详见 §6）：\\n\\n```\\nWAV 上传 → VAD 预检 → ASR(批式) → LLM 流(chunk) → 句子缓冲器 → 触发条件满足 → TTS → 长度前缀帧发送\\n                                                                                    ↓\\n                                                                        ESP32-S3 逐帧播放(M1)\\n```\\n\\n### 5.4 错误码表（v0.1 继承，v0.2 追加）\\n\\n| 场景 | 状态码 | 响应 | 备注 |\\n|---|---|---|---|\\n| VAD 检测到静音/无效语音 | 400 | `{\\\"error\\\": \\\"no_speech\\\"}` | v0.2 新增（OI-007） |\\n| 损坏 WAV / 解析异常 | 400 | `{\\\"error\\\": \\\"bad_audio_format\\\"}` | v0.2 补强（C1，原落 502） |\\n| ASR 失败 / 无有效语音 | 400 | `{\\\"error\\\": \\\"no_speech\\\"}` | 继承 v0.1 |\\n| 音频格式不合规 | 400 | `{\\\"error\\\": \\\"bad_audio_format\\\"}` | 继承 v0.1 |\\n| 音频超过上限 | 413 | `{\\\"error\\\": \\\"audio_too_long\\\"}` | 继承 v0.1（上限 15s） |\\n| API key 未配置 | 500 | `{\\\"error\\\": \\\"config_error\\\", \\\"detail\\\": \\\"...\\\"}` | 继承 v0.1 |\\n| 服务未就绪 | 503 | `{\\\"error\\\": \\\"service_unavailable\\\"}` | 继承 v0.1 |\\n| LLM/TTS 上游失败 | 502 | `{\\\"error\\\": \\\"upstream_error\\\", \\\"detail\\\": \\\"...\\\"}` | 继承 v0.1；流式下首句前失败按此返回 |\\n\\n## 6. 流式流水线设计（核心）\\n\\n### 6.1 组件职责\\n\\n| 组件 | 文件 | 职责 |\\n|---|---|---|\\n| `VADGate` | `app/vad.py` | 能量 RMS 阈值检测，决定是否继续走 ASR（≤rms_threshold → no_speech） |\\n| `SherpaOnnxASR` | `app/asr.py`（不改） | WAV → 文本（批式，已有） |\\n| `DeepSeekLLM.stream_chat()` | `app/llm.py`（新增） | 用户文本 → 流式 `Iterator[str]` |\\n| `SentenceBuffer` | `app/splitter.py`（新增） | 接收字符流，按标点/长度触发分句 |\\n| `TTSEngine` | `app/tts.py`（改造） | 文本 → WAV bytes（edge 主 / piper 兜底，同步合成） |\\n| `StreamingPipeline` | `app/pipeline.py`（新增） | 串联以上组件，产出长度前缀帧 `Iterator[bytes]` |\\n\\n**解码接缝（A2）**：流水线契约是\\\"PCM 16kHz/16bit/mono 进入 VAD/ASR\\\"，而非\\\"WAV 文件进入\\\"。v0.2 输入是完整 WAV（PC 侧），M1 时在 VAD 前插 opus→PCM 解码层即可，流水线主体不动。\\n\\n### 6.2 分句规则（SentenceBuffer）\\n\\n```\\n触发条件（任一满足即输出当前 buffered 文本为一句）：\\n1. 遇到标点：。！？〜 ；\\\\n（中日英共用标点）\\n2. 缓冲区长度 ≥ 50 字符（长句保护，避免 LLM 不发标点时永不输出）\\n3. LLM 流结束：flush 剩余内容（即使无标点）\\n\\n连续标点合并：多个连续标点仅算一次分割。\\n空句子跳过：纯标点/空白不触发 TTS。\\n```\\n\\n### 6.3 TTS 策略（v0.2 — A1 裁决回正）\\n\\n**主从不变：edge 主 / piper 兜底**（Vange 8-13 决策；config.yaml 与 tts.py 现状即如此，v0.2 草案曾误改 piper 主，本次回正）。\\n\\n| 引擎 | 角色 | 延迟 | 质量 | 现状 |\\n|---|---|---|---|---|\\n| edge-tts 6.x | 配置主引擎 | 0.3~0.6s | 自然 | 现网 403（微软封老 token）+ 依赖不可复现 vendor patch，实际不可用 |\\n| piper | 兜底 | 0.1~0.2s | 一般 | 本地推理，实际承载请求 |\\n\\n- 请求期：edge 合成失败/超时 → 自动切 piper（v0.1 已实现），主从定义不变。\\n- health：如实上报 `configured_primary=edge` / `active_engine=piper` / `fallback_reason=edge_403`。\\n\\n**edge 恢复评估任务（显式写入，对应 OI-004，待实现）**：\\n\\n```\\n任务：edge-tts 恢复方案评估（独立任务，不阻塞 v0.2 主线）\\n评估点：\\n  1. edge-tts 7.x 是否修复现网 403\\n  2. 7.x 仅出 24k mp3，转码 16k WAV 需 pydub + 系统 ffmpeg —— 评估是否踩\\\"不引入未列明依赖\\\"红线\\n  3. 替代方案：火山/讯飞云 TTS（免费额度、延迟、音色）\\n产出：结论落 规划文档/技术验证/，据此更新 OI-004 状态\\n期间：piper 实际承载，edge 保持配置主引擎\\n```\\n\\n### 6.4 VAD 能量门限（OI-007 计划覆盖）\\n\\n```yaml\\nvad:\\n  enabled: true\\n  rms_threshold: 0.005    # 0~1，建议值 0.005；纯静音 rms ≈ 0.001~0.003\\n  min_speech_frames: 10    # 连续 speech 帧数下限（frame = 10ms），低于此 → no_speech\\n```\\n\\n实现：\\n\\n- 读取 WAV float32 samples → 分帧（10ms/frame，160 samples @ 16kHz）→ 每帧 RMS\\n- 连续 speech frame 数 ≥ `min_speech_frames` → 走 ASR；否则 → 400 `no_speech`\\n- 零新增依赖：numpy 已在 sherpa-onnx 依赖链中\\n\\n### 6.5 流式打点与 open_ms（A5 裁决）\\n\\n**open_ms 唯一权威定义**：\\n\\n```\\nopen_ms = perf_counter(首字节 flush 到客户端) - perf_counter(请求体完整接收)\\n```\\n\\n- 服务端墙钟，用 `time.perf_counter` 单调钟，分项求和一律不作验收。\\n- 分项（`asr_ms` / `llm_ttft_ms` / `tts_first_ms`）仅作解释，不参与 ≤1.5s 判定。\\n\\n**实现方案（预取首句后发头）**：\\n\\n1. ASR → LLM 流（缓冲到首句完整）→ 首句 TTS → 此时 open_ms 已知\\n2. 发送响应头（含 `X-Timing`）+ 首帧 → 继续流式处理后续句子\\n3. 全量 timing（见下）在响应过程中累积，流结束时写入结构化日志\\n\\n**全量 timing（走日志 + 自测报告，不进响应头）**：\\n\\n```\\ntiming = {\\n  \\\"asr_ms\\\": ...,        # ASR 耗时\\n  \\\"llm_ttft_ms\\\": ...,   # LLM Time-To-First-Token\\n  \\\"llm_total_ms\\\": ...,  # LLM 全流完成耗时\\n  \\\"tts_first_ms\\\": ...,  # 第一句 TTS 耗时\\n  \\\"tts_total_ms\\\": ...,  # 全部 TTS 总耗时\\n  \\\"open_ms\\\": ...,       # 开口延迟（唯一权威，= 墙钟定义）\\n  \\\"total_ms\\\": ...,      # 全链路总耗时\\n  \\\"sentence_count\\\": ...,# 分句数量\\n  \\\"chunk_count\\\": ...,   # 发送帧数\\n}\\n```\\n\\n**诚实边界（必须写死）**：`open_ms ≤ 1.5s` 仅在 **PC 本地条件（v0.2 交付环境）** 成立——完整 WAV 上传可忽略、无网络 RTT。真机（M1）WAV 上传本身即数秒，端到端开口延迟需用 opus 线协议重新预算，**不得用本 Spec 的 1.5s 验收真机**。\\n\\n## 7. LLM 系统提示词（v0.2 微调）\\n\\n```text\\n你是\\\"小衡\\\"，一个便携健康助手的语音助手。要求：\\n1. 回答简短口语化，一般不超过 50 字；能一句话说完就一句话。\\n2. 用户是通过语音对话，回复要像日常聊天，不要列点、不要 markdown。\\n3. 涉及健康数据的问题（心率/血氧/睡眠等）暂回答\\\"健康数据监测功能即将上线\\\"。\\n4. 回答尽量用句号结尾，方便播报分句。\\n```\\n\\n> 变更：新增第 4 条\\\"尽量用句号结尾\\\"以提高分句流畅度。v0.1 第 1~3 条不变。\\n\\n## 8. 配置（config.yaml 完整结构，v0.2）\\n\\n```yaml\\nserver:\\n  host: 0.0.0.0\\n  port: 8710\\n\\nasr:\\n  model_dir: models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17\\n  sample_rate: 16000\\n\\nvad:\\n  enabled: true\\n  rms_threshold: 0.005\\n  min_speech_frames: 10\\n\\ntts:\\n  primary: edge                          # A1 回正：edge 主 / piper 兜底\\n  edge_voice: zh-CN-XiaoxiaoNeural\\n  fallback: piper\\n  piper_model: models/piper/zh_CN-huayan-medium.onnx\\n  piper_config: models/piper/zh_CN-huayan-medium.onnx.json\\n  edge_probe_timeout: 3                  # 启动连通性探测超时（秒）\\n\\nllm:\\n  base_url: https://api.deepseek.com\\n  model: deepseek-chat\\n  api_key_env: DEEPSEEK_API_KEY\\n\\npipeline:\\n  sentence_max_chars: 50                 # 长句保护：超过此长度无标点也触发分句\\n  max_frame_bytes: 8388608               # 最大帧长 8MB 守卫\\n\\nlog:\\n  level: INFO\\n```\\n\\n## 9. 验收标准（v0.2 全过才算完成）\\n\\n### 9.1 功能验收\\n\\n1. `POST /api/v1/voice/chat/stream` 返回长度前缀帧流，每帧可独立解析为一句 WAV\\n2. 开口延迟 ≤1.5s（三句实测平均 `open_ms` ≤ 1500ms，墙钟定义；PC 侧），目标 1.2~1.4s\\n3. 流式可感：第一个帧和最后一个帧到达时间差 ≥ 1s（证明不是等完整回复）\\n4. health 返回 `configured_primary=edge` + `active_engine` + `fallback_reason`（fallback 时）+ VAD 状态\\n5. 静音/VAD 拦截：纯静音 WAV → 400 `no_speech`（不走到 LLM，节省 token）\\n6. 损坏 WAV → 400 `bad_audio_format`（C1，原落 502）\\n7. backward compat：`POST /api/v1/voice/chat`（v0.1 路径）行为不变\\n8. edge 故障注入 → 自动切 piper 且不崩（C4 措辞：断网兜底 → edge 故障注入兜底，真断网 DeepSeek 也失败）\\n9. 请求级结构化日志覆盖成功与失败路径，不记健康语音正文（C2/C5）\\n\\n### 9.2 测试要求（明确测试 ID，P2-04 闭合）\\n\\npytest 共 **10 条**（v0.1 5 条继承改造 + v0.2 5 条新增），逐条必须通过：\\n\\n| ID | 用例 | 类型 |\\n|---|---|---|\\n| T1 | health 返回 ok + tts 嵌套对象 + vad 字段 | mock |\\n| T2 | 静音/空音频 → 400 no_speech（VAD 拦截） | mock |\\n| T3 | 坏格式 → 400 bad_audio_format | mock |\\n| T4 | 损坏 WAV → 400 bad_audio_format（C1） | mock |\\n| T5 | edge 故障注入 → 切 piper 不崩 | mock |\\n| T6 | 分句器单测（SentenceBuffer 触发条件全覆盖：标点/长句/flush/空句） | 单元 |\\n| T7 | VAD 静音拦截单测（rms 阈值边界） | 单元 |\\n| T8 | 帧协议单测（长度前缀编码/解析、最大帧长守卫） | 单元 |\\n| T9 | 流式全链路（mock LLM/TTS）→ 帧可解析 + X-Timing 存在 | mock 集成 |\\n| T10 | 真实全链路 → open_ms 墙钟 + 帧可播（需 ASR 模型 + DeepSeek key + 网络） | 真实集成 |\\n\\n**测试门（C3）**：mock 全链路（T9）与真实集成（T10）严格分类；T10 非 200 必须 fail，**不得接受 400/502 假阳性**。T10 可标记 `skip` 缺资源环境，但 CI/验收时必须显式启用。\\n\\n### 9.3 实测数据\\n\\n10. 三句口语实测（同 v0.1 三句），录制 `open_ms`（墙钟）数据写入自测报告\\n11. 自测报告写入 `Code文档/v0.2自测报告.md`\\n\\n### 9.4 交付\\n\\n12. 源码 + 更新 README（含 v0.2 流式接口、帧协议、edge 恢复评估状态）+ requirements.txt 更新 + 自测报告\\n\\n## 10. 延迟预算（v0.2 目标，PC 侧）\\n\\n```\\nVAD        0.02s  （能量计算，numpy 向量化）\\nASR        0.25s  （SenseVoice 批式，不变）\\nLLM TTFT   0.50s  （DeepSeek 首 token，目标值）\\n分句等待   0.15s  （等首句完整 + 首句 TTS 前置）\\nTTS first  0.15s  （piper 首句，短句 5~15 字）\\n─────────────────\\nopen_ms ≈  1.07s  （理论最佳）\\n实测目标    1.2~1.4s（含网络抖动 + 分句等待）\\n```\\n\\n与 v0.1 对比：v0.1 等待完整 LLM 回复（2~3s），v0.2 只等首 token + 首句，开口延迟从 2-4s 缩短至 ~1.2s。\\n\\n> 口径澄清（A3/A5）：本预算为 **PC 本地服务端流水线**，不含真机 WAV 上传/网络 RTT；ASR 为批式（完整 WAV），非增量。\\n\\n## 11. 风险与缓解\\n\\n| 风险 | 影响 | 缓解 |\\n|---|---|---|\\n| DeepSeek 首 token 延迟波动（0.4~1.5s） | 开口延迟超标 | v0.2 只要求平均 ≤1.5s；峰值超标不计入 fail |\\n| 分句等不到标点（LLM 长句无句号） | 首句永远不发 | 长句保护 50 字符硬切割 |\\n| edge 持续 403 | piper 实际承载，音色略降 | edge 恢复评估任务独立推进（§6.3）；health 如实上报 |\\n| piper 音色不如 edge 自然 | 用户体验 | 可接受（延迟优先 > 音色）；edge 恢复后回主 |\\n| 帧长损坏导致客户端巨额分配 | ESP32 崩溃 | 服务端最大帧长守卫（8MB） |\\n| 流式帧传输中断 | ESP32 侧播放异常 | 测试覆盖弱信号场景（≥80% 成功率即可） |\\n| 长度前缀帧客户端解析 | ESP32 端需帧解析器 | v0.2 只交付 PC 端；ESP32 帧解析留 M1 |\\n| 真机 WAV 上传延迟大 | 端到端超 1.5s | M1 用 opus 线协议重新预算（A2 留白） |\\n\\n## 12. Open Issues 覆盖映射（A6 裁决回正）\\n\\n> 状态唯一以 `协同工作文档/审查报告/Open-Issues.md` 为准。Spec 中未实现内容一律写\\\"计划覆盖/待实现\\\"，实现 + 测试 + 独立确认完成后才关闭。\\n\\n| OI | 内容 | v0.2 处理 | 台账状态 |\\n|---|---|---|---|\\n| OI-001 | health 未反映实际引擎 | §5.1：health 上报 configured_primary/active_engine/fallback_reason | 计划覆盖（open） |\\n| OI-004 | edge-tts 403 恢复方案 | §6.3：edge 主 piper 兜底回正 + edge 恢复评估任务 | 待实现（open） |\\n| OI-007 | SenseVoice 静音幻觉 → VAD | §6.4：能量门限 VAD，静音拦截 | 计划覆盖（open） |\\n| OI-002 | Spec §8 ASR 资产名修正 | v0.1 Spec 已修正（§8 + config.yaml 一致）✅ | closed |\\n\\n---\\n\\n*Hermes（deepseek-v4-pro）修订 · 2026-08-14 · 依据 8-13 一致性审查 + Vange 裁决 A1~A6 · 待 WorkBuddy 确认 DoD 后开工*\\n\", \"path\": \"规划文档/Spec文档/2026-08-11-语音桥-spec-v0.2.md\"}"
    }
  }
]
```


### Tool — write_file — 2026-08-14T08:40:36.861813Z

{"bytes_written": 19996, "dirs_created": true, "lint": {"status": "skipped", "message": "No linter for .md files"}, "resolved_path": "D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\Spec文档\\2026-08-11-语音桥-spec-v0.2.md", "files_modified": ["D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\Spec文档\\2026-08-11-语音桥-spec-v0.2.md"]}


### Assistant — 2026-08-14T08:40:50.327608Z



## Tool calls

```json
[
  {
    "id": "call_00_phiB71VkzVIQaxzc4HUB3944",
    "call_id": "call_00_phiB71VkzVIQaxzc4HUB3944",
    "response_item_id": "fc_00_phiB71VkzVIQaxzc4HUB3944",
    "type": "function",
    "function": {
      "name": "patch",
      "arguments": "{\"mode\": \"replace\", \"new_string\": \"## 延迟预算（开口延迟 = 说完到听到第一句）\\n\\n> 口径修正（2026-08-14，A3/A5 裁决）：以下为 **PC 本地服务端流水线**预算，ASR 为**完整 WAV 批式识别**，不含真机 WAV 上传/网络 RTT。真机端到端开口延迟待 M1 确定 opus 线协议后重新预算。\\n\\n```\\nVAD        0.02s  +  ASR 0.2~0.3s（批式）  +  LLM 首字 0.4~0.8s  +  分句等待 0.15s  +  TTS 首句 0.15~0.6s\\n≈ 0.9~1.9s 理论，实测目标 1.2~1.4s（v0.2 流式化后，PC 侧）\\n```\\n\\n**v0.2 硬前提（修订后，仅一条）：**\\n\\n1. LLM 流式输出 + 分句 TTS 流水线——禁止等完整回复再合成（那会 3~5s 开口）。\\n\\n> 原\\\"ASR 近实时路径，禁止录完整段再上传识别\\\"已**撤回**（A3 裁决）：v0.2 只做 LLM/TTS 流式，ASR 保持批式；增量 ASR 属 M1 真机端到端优化，待 M1 线协议确定后独立评估。\", \"old_string\": \"## 延迟预算（开口延迟 = 说完到听到第一句）\\n\\n静音判定 0.25s + 上传 0.05s + ASR 0.2~0.3s + LLM 首字 0.4~0.8s + TTS 首句 0.3~0.6s + 回传 0.05s ≈ **1.2~1.6s**（v0.2 流式化后稳定 1.2~1.4s）。\\n\\n两个硬前提（v0.2 必须做到）：\\n1. LLM 流式输出 + 分句 TTS 流水线——禁止等完整回复再合成（那会 3~5s 开口）\\n2. ASR 近实时路径，禁止\\\"录完整段再上传识别\\\"\", \"path\": \"规划文档/技术验证/2026-08-11-语音引擎选型-结论.md\"}"
    }
  }
]
```


### Tool — patch — 2026-08-14T08:41:01.963496Z

{"success": true, "diff": "--- a/D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\技术验证\\2026-08-11-语音引擎选型-结论.md\n+++ b/D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\技术验证\\2026-08-11-语音引擎选型-结论.md\n@@ -22,11 +22,18 @@\n \n ## 延迟预算（开口延迟 = 说完到听到第一句）\n \n-静音判定 0.25s + 上传 0.05s + ASR 0.2~0.3s + LLM 首字 0.4~0.8s + TTS 首句 0.3~0.6s + 回传 0.05s ≈ **1.2~1.6s**（v0.2 流式化后稳定 1.2~1.4s）。\n+> 口径修正（2026-08-14，A3/A5 裁决）：以下为 **PC 本地服务端流水线**预算，ASR 为**完整 WAV 批式识别**，不含真机 WAV 上传/网络 RTT。真机端到端开口延迟待 M1 确定 opus 线协议后重新预算。\n \n-两个硬前提（v0.2 必须做到）：\n-1. LLM 流式输出 + 分句 TTS 流水线——禁止等完整回复再合成（那会 3~5s 开口）\n-2. ASR 近实时路径，禁止\"录完整段再上传识别\"\n+```\n+VAD        0.02s  +  ASR 0.2~0.3s（批式）  +  LLM 首字 0.4~0.8s  +  分句等待 0.15s  +  TTS 首句 0.15~0.6s\n+≈ 0.9~1.9s 理论，实测目标 1.2~1.4s（v0.2 流式化后，PC 侧）\n+```\n+\n+**v0.2 硬前提（修订后，仅一条）：**\n+\n+1. LLM 流式输出 + 分句 TTS 流水线——禁止等完整回复再合成（那会 3~5s 开口）。\n+\n+> 原\"ASR 近实时路径，禁止录完整段再上传识别\"已**撤回**（A3 裁决）：v0.2 只做 LLM/TTS 流式，ASR 保持批式；增量 ASR 属 M1 真机端到端优化，待 M1 线协议确定后独立评估。\n \n ## 风险\n \n", "files_modified": ["D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\技术验证\\2026-08-11-语音引擎选型-结论.md"], "lint": {"status": "skipped", "message": "No linter for .md files"}, "resolved_path": "D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\技术验证\\2026-08-11-语音引擎选型-结论.md"}


### Assistant — 2026-08-14T08:41:23.502448Z



## Tool calls

```json
[
  {
    "id": "call_00_XbJsCj7Ld6G9AsaOMp7K2682",
    "call_id": "call_00_XbJsCj7Ld6G9AsaOMp7K2682",
    "response_item_id": "fc_00_XbJsCj7Ld6G9AsaOMp7K2682",
    "type": "function",
    "function": {
      "name": "patch",
      "arguments": "{\"mode\": \"replace\", \"new_string\": \"| M1 阶段1 电脑端验证 | 语音桥服务 + 开发板固件 + 联调 | 未开始 | M0 全绿（板级支持确认、工具链锁定） | 联调清单全绿：语音问答链路通 / 真机端到端开口延迟实测（先定 opus 线协议）/ 手机热点无线验证 | 语音桥 spec v0.1、实现方案 §5 |\\n| M2 阶段2 云端迁移 | 腾讯云轻量 + profile 迁移 + 随身 | 未开始 | M1 全绿 | 远程链路延迟可接受 / 7x24 在线 / 随身热点可用 / 电脑本地停用不双开 | 实现方案 §6 |\\n\\n> 依赖链：**M0 → M1 → M2 严格顺序**，阶段边界不可逾越；明细以方案文档（`../Hermes语音开发板实现方案-20260811.docx`）已敲定内容为准。\\n> 执行布局：`2026-08-11-M0M1-执行路线图.md`（三线并行 / 到货流程 / 风险预案）。\\n>\\n> **2026-08-14 修订（Vange 裁决 A2/D）**：① M1 DoD 移除\\\"共用记忆验证\\\"——共用记忆属 v0.3/Hermes 会话集成，移出 M1，作为独立后续里程碑（v0.3）单独验收；② M1 联调前必须先定 opus 线协议（v0.2 期间锁 WAV，A2 留白）。\", \"old_string\": \"| M1 阶段1 电脑端验证 | 语音桥服务 + 开发板固件 + 联调 | 未开始 | M0 全绿（板级支持确认、工具链锁定） | 联调清单全绿：语音问答链路通 / 开口延迟实测 1~1.5s / 共用记忆验证 / 手机热点无线验证 | 语音桥 spec v0.1、实现方案 §5 |\\n| M2 阶段2 云端迁移 | 腾讯云轻量 + profile 迁移 + 随身 | 未开始 | M1 全绿 | 远程链路延迟可接受 / 7x24 在线 / 随身热点可用 / 电脑本地停用不双开 | 实现方案 §6 |\\n\\n> 依赖链：**M0 → M1 → M2 严格顺序**，阶段边界不可逾越；明细以方案文档（`../Hermes语音开发板实现方案-20260811.docx`）已敲定内容为准。\\n> 执行布局：`2026-08-11-M0M1-执行路线图.md`（三线并行 / 到货流程 / 风险预案）。\", \"path\": \"规划文档/里程碑文档/README.md\"}"
    }
  },
  {
    "id": "call_01_Vucp9iq8qpegTPdEyPl82243",
    "call_id": "call_01_Vucp9iq8qpegTPdEyPl82243",
    "response_item_id": "fc_01_Vucp9iq8qpegTPdEyPl82243",
    "type": "function",
    "function": {
      "name": "patch",
      "arguments": "{\"mode\": \"replace\", \"new_string\": \"- 固件代码由 WorkBuddy 编写，Hermes 审查（至多 3 轮，审查报告落 `协同工作文档/审查报告/`）\\n- **M1 前置决策**：联调前必须先定 opus 线协议（编码参数/分帧/Content-Type/服务端解码责任），见 v0.2 Spec §2 留白（A2 裁决）\\n- **M1 gate**：联调 3 项全绿（语音链路通 / 真机端到端开口延迟实测 / 手机热点无线）→ 才可进 M2 阶段2 迁移\\n  - 注：原\\\"共用记忆\\\"已移出 M1，属 v0.3/Hermes 会话集成（2026-08-14 Vange 裁决 D）\", \"old_string\": \"- 固件代码由 WorkBuddy 编写，Hermes 审查（至多 3 轮，审查报告落 `协同工作文档/审查报告/`）\\n- **M1 gate**：联调 4 项全绿（语音链路通 / 开口延迟实测 1~1.5s / 共用记忆 / 手机热点无线）→ 才可进 M2 阶段2 迁移\", \"path\": \"规划文档/里程碑文档/2026-08-11-M0M1-执行路线图.md\"}"
    }
  }
]
```


### Tool — patch — 2026-08-14T08:41:36.204276Z

{"success": true, "diff": "--- a/D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\里程碑文档\\README.md\n+++ b/D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\里程碑文档\\README.md\n@@ -7,8 +7,10 @@\n | 里程碑 | 内容 | 状态 | 准入条件 | DoD（完成标准） | 关联文档 |\n |---|---|---|---|---|---|\n | M0 开发环境验证 | 验证 BOX-3 板级支持与工具链选型 | 待硬件到货 | 硬件到货 + ESP-IDF 安装完成 | V-01~V-12 全部通过（Spec §3.1），证据与报告落盘 `Code文档/v0.1-环境验证/`，经 Hermes 审核 | 开发环境验证 spec v0.1 |\n-| M1 阶段1 电脑端验证 | 语音桥服务 + 开发板固件 + 联调 | 未开始 | M0 全绿（板级支持确认、工具链锁定） | 联调清单全绿：语音问答链路通 / 开口延迟实测 1~1.5s / 共用记忆验证 / 手机热点无线验证 | 语音桥 spec v0.1、实现方案 §5 |\n+| M1 阶段1 电脑端验证 | 语音桥服务 + 开发板固件 + 联调 | 未开始 | M0 全绿（板级支持确认、工具链锁定） | 联调清单全绿：语音问答链路通 / 真机端到端开口延迟实测（先定 opus 线协议）/ 手机热点无线验证 | 语音桥 spec v0.1、实现方案 §5 |\n | M2 阶段2 云端迁移 | 腾讯云轻量 + profile 迁移 + 随身 | 未开始 | M1 全绿 | 远程链路延迟可接受 / 7x24 在线 / 随身热点可用 / 电脑本地停用不双开 | 实现方案 §6 |\n \n > 依赖链：**M0 → M1 → M2 严格顺序**，阶段边界不可逾越；明细以方案文档（`../Hermes语音开发板实现方案-20260811.docx`）已敲定内容为准。\n > 执行布局：`2026-08-11-M0M1-执行路线图.md`（三线并行 / 到货流程 / 风险预案）。\n+>\n+> **2026-08-14 修订（Vange 裁决 A2/D）**：① M1 DoD 移除\"共用记忆验证\"——共用记忆属 v0.3/Hermes 会话集成，移出 M1，作为独立后续里程碑（v0.3）单独验收；② M1 联调前必须先定 opus 线协议（v0.2 期间锁 WAV，A2 留白）。\n", "files_modified": ["D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\里程碑文档\\README.md"], "lint": {"status": "skipped", "message": "No linter for .md files"}, "resolved_path": "D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\里程碑文档\\README.md"}


### Tool — patch — 2026-08-14T08:41:36.210271Z

{"success": true, "diff": "--- a/D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\里程碑文档\\2026-08-11-M0M1-执行路线图.md\n+++ b/D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\里程碑文档\\2026-08-11-M0M1-执行路线图.md\n@@ -50,7 +50,9 @@\n | F4 | 自定义唤醒词训练（最后，不阻塞主线） | F3 |\n \n - 固件代码由 WorkBuddy 编写，Hermes 审查（至多 3 轮，审查报告落 `协同工作文档/审查报告/`）\n-- **M1 gate**：联调 4 项全绿（语音链路通 / 开口延迟实测 1~1.5s / 共用记忆 / 手机热点无线）→ 才可进 M2 阶段2 迁移\n+- **M1 前置决策**：联调前必须先定 opus 线协议（编码参数/分帧/Content-Type/服务端解码责任），见 v0.2 Spec §2 留白（A2 裁决）\n+- **M1 gate**：联调 3 项全绿（语音链路通 / 真机端到端开口延迟实测 / 手机热点无线）→ 才可进 M2 阶段2 迁移\n+  - 注：原\"共用记忆\"已移出 M1，属 v0.3/Hermes 会话集成（2026-08-14 Vange 裁决 D）\n \n ## 5. 风险预案\n \n", "files_modified": ["D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\里程碑文档\\2026-08-11-M0M1-执行路线图.md"], "lint": {"status": "skipped", "message": "No linter for .md files"}, "resolved_path": "D:\\workbuddy_project\\项目\\可穿戴健康辅助系统\\规划文档\\里程碑文档\\2026-08-11-M0M1-执行路线图.md"}


### Assistant — 2026-08-14T08:41:47.027173Z

四份文档已修订。现在做一致性自检——grep 排查是否还有"全流式 / 近实时 ASR / piper 主 / 共用记忆"等残留冲突表述。



## Tool calls

```json
[
  {
    "id": "call_00_4F2I44h5J0jPVQ9sINOw8926",
    "call_id": "call_00_4F2I44h5J0jPVQ9sINOw8926",
    "response_item_id": "fc_00_4F2I44h5J0jPVQ9sINOw8926",
    "type": "function",
    "function": {
      "name": "search_files",
      "arguments": "{\"file_glob\": \"*.md\", \"output_mode\": \"content\", \"path\": \"规划文档\", \"pattern\": \"全流式|近实时 ASR|整段录|primary: piper|piper 主|共用记忆\"}"
    }
  },
  {
    "id": "call_01_jvFky8c7bON5gbL2MTJ60569",
    "call_id": "call_01_jvFky8c7bON5gbL2MTJ60569",
    "response_item_id": "fc_01_jvFky8c7bON5gbL2MTJ60569",
    "type": "function",
    "function": {
      "name": "search_files",
      "arguments": "{\"file_glob\": \"*.md\", \"output_mode\": \"content\", \"path\": \"规划文档\", \"pattern\": \"禁止接入 Hermes|opus 线协议|active_engine|configured_primary\"}"
    }
  }
]
```


### Tool — search_files — 2026-08-14T08:41:49.086869Z

{"total_count": 6, "matches_format": "path-grouped: each file path on its own line, followed by indented '<line>: <content>' rows for matches in that file", "matches_text": "规划文档\\里程碑文档\\README.md\n  16: > **2026-08-14 修订（Vange 裁决 A2/D）**：① M1 DoD 移除\"共用记忆验证\"——共用记忆属 v0.3/Hermes 会话集成，移出 M1，作为独立后续里程碑（v0.3）单独验收；② M1 联调前必须先定 opus 线协议（v0.2 期间锁 WAV，A2 留白）。\n规划文档\\Spec文档\\2026-08-11-语音桥-spec-v0.1.md\n  15: | v0.3 | 接入 Hermes 会话（共用记忆/技能），接口由 Hermes 定义 | 与微信共用记忆 |\n规划文档\\里程碑文档\\2026-08-11-M0M1-执行路线图.md\n  55:   - 注：原\"共用记忆\"已移出 M1，属 v0.3/Hermes 会话集成（2026-08-14 Vange 裁决 D）\n规划文档\\Spec文档\\2026-08-11-语音桥-spec-v0.2.md\n  6: > **修订记录（2026-08-14）**：依据《2026-08-13 现有文件一致性审查报告》P1/P2/P3 与 Vange 裁决（A1~A6）修订。修订点：① TTS 主从回正（edge 主 / piper 兜底，A1）；② 音频协议锁定 WAV + 解码接缝（A2）；③ 明确 ASR 批式、撤回\"全流式\"表述（A3）；④ 流式应用层分帧改为长度前缀帧（A4）；⑤ open_ms 唯一定义墙钟 + 预取首句（A5）；⑥ OI 台账回正\"计划覆盖/待实现\"（A6）；⑦ 并入 v0.1 补强项（C1~C5）；⑧ 测试数量闭合（P2-04）。\n  20: | v0.3 | 接入 Hermes 会话（共用记忆/技能） | 与微信共用记忆 |\n  178: **主从不变：edge 主 / piper 兜底**（Vange 8-13 决策；config.yaml 与 tts.py 现状即如此，v0.2 草案曾误改 piper 主，本次回正）。"}


### Tool — search_files — 2026-08-14T08:41:49.093452Z

{"total_count": 18, "matches_format": "path-grouped: each file path on its own line, followed by indented '<line>: <content>' rows for matches in that file", "matches_text": "规划文档\\技术验证\\2026-08-11-语音引擎选型-结论.md\n  25: > 口径修正（2026-08-14，A3/A5 裁决）：以下为 **PC 本地服务端流水线**预算，ASR 为**完整 WAV 批式识别**，不含真机 WAV 上传/网络 RTT。真机端到端开口延迟待 M1 确定 opus 线协议后重新预算。\n规划文档\\里程碑文档\\README.md\n  10: | M1 阶段1 电脑端验证 | 语音桥服务 + 开发板固件 + 联调 | 未开始 | M0 全绿（板级支持确认、工具链锁定） | 联调清单全绿：语音问答链路通 / 真机端到端开口延迟实测（先定 opus 线协议）/ 手机热点无线验证 | 语音桥 spec v0.1、实现方案 §5 |\n  16: > **2026-08-14 修订（Vange 裁决 A2/D）**：① M1 DoD 移除\"共用记忆验证\"——共用记忆属 v0.3/Hermes 会话集成，移出 M1，作为独立后续里程碑（v0.3）单独验收；② M1 联调前必须先定 opus 线协议（v0.2 期间锁 WAV，A2 留白）。\n规划文档\\里程碑文档\\2026-08-11-M0M1-执行路线图.md\n  53: - **M1 前置决策**：联调前必须先定 opus 线协议（编码参数/分帧/Content-Type/服务端解码责任），见 v0.2 Spec §2 留白（A2 裁决）\n规划文档\\Spec文档\\2026-08-11-语音桥-spec-v0.2.md\n  21: | M1（后续） | 真机固件联调：opus 线协议 + 增量 ASR 评估 | 真机端到端延迟 |\n  25: **明确留白（A2 裁决）**：v0.2 期间音频上传协议锁定 WAV（16k/16bit/mono）；固件↔服务的 opus 线协议（编码参数/分帧/Content-Type/解码责任）**待定，留 M1 定义**。架构必须保留 PCM 解码接缝，使 M1 只在 VAD 前插一层 opus→PCM 解码，不改流水线。\n  46: | health | 返回主引擎名 | 返回 `configured_primary` / `active_engine` / `fallback_reason` + VAD 状态 | OI-001 计划覆盖 |\n  68:     tts.py            # 改造：health 上报 active_engine/fallback_reason；主从保持 edge/piper\n  94:     \"configured_primary\": \"edge\",\n  95:     \"active_engine\": \"piper\",\n  104: - `tts.configured_primary`：配置主引擎（固定 `edge`，产品策略）。\n  105: - `tts.active_engine`：当前实际可用引擎（`edge` / `piper`）。落到 piper 仅代表 fallback 生效，**不代表主从策略改变**。\n  108: - 启动时探测 edge-tts 连通性（发最小静音合成请求，超时 3s），不可用时 `active_engine=piper` + `fallback_reason`，health 始终反映真实状态。\n  186: - health：如实上报 `configured_primary=edge` / `active_engine=piper` / `fallback_reason=edge_403`。\n  248: **诚实边界（必须写死）**：`open_ms ≤ 1.5s` 仅在 **PC 本地条件（v0.2 交付环境）** 成立——完整 WAV 上传可忽略、无网络 RTT。真机（M1）WAV 上传本身即数秒，端到端开口延迟需用 opus 线协议重新预算，**不得用本 Spec 的 1.5s 验收真机**。\n  306: 4. health 返回 `configured_primary=edge` + `active_engine` + `fallback_reason`（fallback 时）+ VAD 状态\n  369: | 真机 WAV 上传延迟大 | 端到端超 1.5s | M1 用 opus 线协议重新预算（A2 留白） |\n  377: | OI-001 | health 未反映实际引擎 | §5.1：health 上报 configured_primary/active_engine/fallback_reason | 计划覆盖（open） |"}

## Export verification

- Session id: `20260814_154943_ca2e6f`
- Exported messages: `39`
- Source DB message count at export: `39`
- Exported at: `2026-08-14T14:28:14.647281Z`
- SHA256 of exported body: `0c0c306b9a6e0809c3f1ba3363d838bbbaba2431a6bfad2dbefc64b20c62f933`
