# agent.md — Hermes × zcode × codex 协作规范（v1.7，2026-08-19）

> # 🚨🚨🚨 最高铁律（Vange 亲定，违反即返工）🚨🚨🚨
>
> **所有决定都不能以牺牲首字输出延迟为代价——除非后续可以百分百确定补回来或者优化更多。**
>
> 任何方案、设计、改动（记忆系统、搜索、路由、TTS、上下文等一切功能）必须先过这一关：
> 首字延迟（用户开口到听到第一个字的时长）是体验生命线，不可为任何功能收益而牺牲；
> 只有在能确定性补偿或净优化更多的前提下才允许偏离。此条优先级高于本文件一切其他条款。

> **本文件是 Hermes、zcode、codex、WorkBuddy 四方在本项目中的协作运行时规范。四方每次开工前必须读取本文件。**
> 与 `AGENTS.md` 的分工：`AGENTS.md` 管项目结构/文档优先级/开发纪律；本文件管**协作流程、模型守卫、交接与审查机制**。冲突时以本文件为准（本文件由 Vange 亲定）。

---

## 1. 角色与模型守卫（违反即停工）

| 角色 | 职责 | 强制模型 | 非对应模型时 |
|---|---|---|---|
| **zcode（智谱 AI）** | **开发员（全权接管，2026-08-19 起）**：代码开发、自测、部署、集成、技术查证、方案设计 | 智谱 GLM（zcode 环境自带） | — |
| **codex（OpenAI Codex）** | **复杂任务（2026-08-19 Vange 定）**：高难度编码、疑难问题定位、深度实现 | OpenAI Codex（CLI 环境自带） | — |
| **Hermes** | 代码审查方：审代码、出审查报告、放行 | **DS V4 Pro**（`deepseek-v4-pro`） | 禁止用其他模型出审查结论；审查调用必须带 `--model deepseek-v4-pro` |
| **WorkBuddy** | **暂停（2026-08-19 Vange 判定）**：完成 CosyVoice 部署收尾后停止一切事务 | — | — |

> **模型守卫（2026-08-19 更新）**：WorkBuddy 已暂停，开发由 zcode 全权接管（智谱 GLM）；Hermes 审查必须用 deepseek-v4-pro。原「动工前核实 Kimi K3」条款随 WorkBuddy 暂停废止。

- Hermes 审查调用（**invocation-only 覆盖，不改默认 profile**）：
  ```bash
  hermes chat --model deepseek-v4-pro --resume 20260814_154943_ca2e6f -q "<审查请求>" -Q
  ```
- ✅ 已验证（2026-08-11）：`deepseek-v4-pro` 在 Hermes 中可用（实测返回正常）。
- Hermes 默认模型当前为 `deepseek-v4-flash`（日常对话可用），**审查必须显式切 v4-pro**。

## 2. 沟通桥梁（Session 铁律）

- **常驻 Session**（除非 Vange 明确说"新开 session"，否则永远在同一个 session 里交接）：
  - Hermes 侧：`20260814_154943_ca2e6f`（WorkBuddy↔Hermes 协作线程（5）·v0.2 修订期）
  - WorkBuddy 侧：当前与 Vange 的对话线程（WorkBuddy 记忆目录 `.workbuddy/memory/` 保证跨会话连续）
- 常用命令：
  ```bash
  hermes chat --resume 20260814_154943_ca2e6f                    # 交互式恢复（Vange 侧边栏/终端用）
  hermes chat --resume 20260814_154943_ca2e6f -q "<消息>" -Q     # 单轮交接（WorkBuddy 用）
  hermes sessions list                                            # 查会话
  hermes sessions export --session-id <ID> --format md <路径>     # 归档会话
  ```
- 每轮交接必须是**有界包裹（bounded packet）**：上下文摘要 + 交付物路径 + 待确认问题。禁止甩一个文件路径就完事。

### 2.1 任务单（Task Packet）— 交接标准化（v1.1 新增）

每个任务的首次交接必须带任务单，**缺项不接**：

```
任务ID：T-YYYYMMDD-序号（例：T-20260811-01）
需求来源：Spec 条目编号（例：Spec v0.1 §5 / §6）
任务内容：一句话目标 + 非目标（明确不做的事）
交付物：文件路径清单
DoD（完成定义）：可测的验收标准（见 §3.2）
优先级：P0 阻塞 / P1 正常 / P2 低
```

- **非目标（Non-goals）必须写明**——防范围蔓延，是防返工的第一道闸。
- 任务单随交接消息一起发出；对方确认收到后再开工。

## 3. 工作流：开发 → 审查 → 返工 → 放行（最多 3 轮）

```
Vange 下达任务（WorkBuddy 或 Hermes 侧均可）
   │
   ▼
DEV_IN_PROGRESS（WorkBuddy 开发，Kimi K3）
   │ 完成 + 自测通过 + 交付清单
   ▼
REVIEW_PENDING（Hermes 审查，deepseek-v4-pro）
   │
   ├── REVIEW_PASS ──────────────► 合入，任务关闭 ✅
   ├── REVIEW_CONDITIONAL_PASS ──► 非阻断 Open Issues 登记后放行 ✅（带遗留项清单）
   └── REWORK_REQUIRED ─────────► WorkBuddy 按报告逐条修复 → 重新提交 → 再审（轮次 +1）
                                   └── 第 3 轮仍未通过 ──► REVIEW_LIMIT_REACHED，停止并上报 Vange 决策
```

**硬性规则：**

1. **审查轮次上限 = 3 轮**（沿用 vange-workflow `MAX_REVIEW_ROUNDS = 3`）。不因返工、换文件、补测而重置计数。
2. **Hermes 每轮审查必须一次性给出全部可发现的实质问题（SERIOUS 批次）**，禁止挤牙膏式分轮抛问题。
3. **WorkBuddy 提交前自查清单**（防止无用功返工，这是大忌）：
   - [ ] 已读对应 Spec，确认无未覆盖需求（未覆盖 → 先补 Spec 再动手）
   - [ ] 已通读上一轮审查报告，确认无漏修项
   - [ ] 自测跑通（含实测打点数据，禁止"应该没问题"）
   - [ ] 交付物路径明确、代码格式/命名一致
4. **有条件通过** = 剩余项均为 NON_SERIOUS（措辞/风格/非阻断优化），登记为 Open Issues 后放行，不触发返工。
5. 每轮审查报告**落盘**：`协同工作文档/审查报告/YYYY-MM-DD-审查-第N轮.md`，WorkBuddy 返工时以该文件为准逐条回应（修复 + 证据）。
6. Hermes 只审查不写业务代码；WorkBuddy 只开发不自我审查。职责边界不可逾越。

### 3.1 状态词汇表（v1.1 新增）— 交接汇报必须带状态前缀

```
[WORKFLOW_ACTIVE]          工作流进行中
[DEV_IN_PROGRESS]          WorkBuddy 开发中（Kimi K3）
[DEV_DONE]                 WorkBuddy 交付待审（附任务单 + 自查清单 + 实测数据）
[REVIEW_PENDING]           Hermes 审查中（deepseek-v4-pro）
[REWORK_REQUIRED]          返工中（第N轮）
[REVIEW_PASS]              审查通过 ✅
[REVIEW_CONDITIONAL_PASS]  有条件通过（登记 Open Issues 后放行）
[REVIEW_LIMIT_REACHED]     3 轮未过，停止，上报 Vange 决策
[USER_PAUSED]              Vange 暂停（唯一合法停止状态）
```

汇报格式：`[状态] 一句话结论 + 关键证据路径`。双方一眼对齐，不再问"现在到哪了"。

### 3.2 DoD 前置确认（v1.1 新增）— 开工前对齐完成定义

- WorkBuddy **动手前**必须确认任务单中 DoD 可测且双方认可（可验证的行为/数据，禁止"代码能跑"这类模糊表述）。
- **没有 DoD 的任务 = 没定义清楚**：先补 DoD（或写进 Spec）再开工，这是防无用功的根本手段。
- DoD 变更需 Vange 或 Hermes 同意；变更后返工轮次不重置，但该变更点不计入 SERIOUS 返工。

### 3.3 轮次计数与 Open Issues（OI = Open Issue）登记（v1.1 新增，v1.2 修订）

- 审查报告标题固定格式：`YYYY-MM-DD-审查-第N轮.md`，N 只增不减，不因返工/换文件/补测重置。
- **有条件通过** → 遗留项登记 `协同工作文档/审查报告/Open-Issues.md`：
  | 编号 | 描述 | 严重度 | 状态 | 责任方 |
  |---|---|---|---|---|
  | OI-001 | …… | NON_SERIOUS | open / closed | WorkBuddy / Hermes |
- **OI 关闭自动化（v1.2，Vange 亲定）**：审核确认无问题、达到验收标准后，责任方自行决定关闭，**无需 Vange 逐条决策**。
  - 关闭流程：责任方完成修复 → 提交对方（Hermes）验证确认 → 标记 closed（含关闭日期）。
  - Vange 只介入：阻塞项、方向变更（如推进下一阶段）、或双方对关闭有分歧时。
- 后续任务交接时随附未关闭的 Open Issues 清单，确保遗留项不丢失。

### 3.4 交接响应与阻塞规则（v1.1 新增）

- 交接（含审查请求）发出后 **15 分钟内无响应** → 重发一次并 @Vange；仍无响应 → 记录 blocker，先做不依赖该交接的准备工作，不空等。
- 阻塞记录格式（沿用 vange-workflow）：`阻塞点 / 责任方 / 最小解锁输入 / 恢复触发器`。
- 任何角色遇到 Spec 未覆盖情况：**先停下来**，写进 Spec 或问 Vange/Hermes，禁止擅自决策（v0.1 尤其如此）。

## 4. vange-workflow 五条硬不变式（本项目全量适用）

1. **THINK_BEFORE_ACTING**：材料决策前先想清楚目标/非目标/约束/依赖/验收/回滚/证据；未知且影响决策必须查清，否则果断行动。
2. **Persist to acceptance**：计划、返工、阻塞、超时都不是完成。只有 Vange 明确暂停/取消才停；否则保持状态继续推进。
3. **Roles isolated**：路由/追踪/验收/关门由流程控制；任何角色不得自我批准、不得接管他人职责。
4. **Use only authorized workers**：交接只用已注册的现有线程（本文件 §2 的 session），**擅自新建线程/会话需 Vange 明确授权**。
5. **Require evidence before closure**：交付必须有归属明确的证据（实测数据、报告、路径）。`WORKFLOW_COMPLETE` 前必须全部 gate 通过。

## 5. 工作区文件管理（Vange 亲定：做好文件/文件夹管理）

| 目录/文件 | 职责 | 纪律 |
|---|---|---|
| `agent.md` | 本协作规范 | 变更需 Vange 同意，双方开工必读 |
| `规划文档/Spec文档/` | 功能 Spec（最高裁决） | 命名 `YYYY-MM-DD-功能名-spec.md`；未覆盖需求先补 Spec |
| `规划文档/技术验证/` | 选型结论与风险 | 只记结论与数据 |
| `规划文档/里程碑文档/` | 阶段交付计划 | 每阶段交付前更新 |
| `Code文档/` | 代码结构、开发员记录、自测报告 | `v0.1自测报告.md` 等按阶段命名 |
| `协同工作文档/` | 交接记录、审查报告、会话存档 | **子目录 `审查报告/`**（命名 `YYYY-MM-DD-审查-第N轮.md`，遗留项 `Open-Issues.md`）；**子目录 `会话存档/`**（协作线程导出/初始化记录，命名 `YYYY-MM-DD-协作线程N-...`）；裁决/交接清单直接放本目录根 |
| `总负责人文档/` | Hermes 决策记录 | 架构/选型决策落盘 |
| `voice-bridge/` | v0.1 唯一代码目录 | `venv/`、`models/`、`.env` 一律 gitignore，不入库 |

### 5.1 文件命名后缀（2026-08-17 新增，Vange 亲定）

三个 Agent 产出的文件，文件名末尾（扩展名前）统一加角色后缀：

| 后缀 | 角色 | 职责 |
|---|---|---|
| `_hm` | Hermes | 大脑 / 审查方：Spec 起草、审查报告、裁决对齐 |
| `_zc` | zcode（智谱 AI） | 技术查证 / 方案设计 / 代码开发 |
| `_cdx` | codex（OpenAI Codex） | 复杂任务：高难度编码、疑难问题 |
| `_wb` | WorkBuddy | **暂停**（2026-08-19 起，开发职责移交 zcode） |

- 示例：`2026-08-17-首字延迟优化查证_wb.md`、`2026-08-16-人设与情感化提示词_hm.md`、`xxx_zc.md`
- 从 2026-08-17 起新产出文件必须带后缀；已有文件不强制改名。

**通用纪律：**
- 交接物必须给出**绝对路径**；临时文件不落项目根目录（用 `.tmp/` 或系统临时目录）。
- 模型文件、密钥、venv 永不入库；`.env` 从 `~/.hermes/.env` 复制，不入库。
- git 提交信息遵循语义化（`feat:` / `fix:` / `docs:` / `chore:`），一次提交一个逻辑变更。

---

## 变更记录

- **v1.0**（2026-08-11）：初版。Vange 亲定 5 条：角色模型守卫 / Session 铁律 / 3 轮审查工作流 / vange-workflow 五条不变式 / 文件管理。
- **v1.1**（2026-08-11）：Vange 要求"适当优化"。新增 §2.1 任务单模板、§3.1 状态词汇表、§3.2 DoD 前置、§3.3 轮次计数与 Open Issues 登记、§3.4 交接响应与阻塞规则。核心目标：防无用功返工。
- **v1.2**（2026-08-11）：Vange 亲定 OI 关闭自动化——审核确认无问题、达到验收标准后责任方自行关闭，无需 Vange 逐条决策。
- **v1.3**（2026-08-15）：Vange 强化模型守卫——WorkBuddy 每次代码开发动工前必须先向 Vange 核实模型（Kimi K3），确认后动工；同时固化「每次审查必须落盘审查报告」纪律。
- **v1.4**（2026-08-16）：Vange 拍板——Kimi K3 无额度，WorkBuddy 代码开发暂用 **deepseek-v4-pro**（恢复 Kimi K3 额度后切回）。
- **v1.5**（2026-08-17）：新增第三个角色 zcode（智谱 AI）+ 文件命名后缀规范（`_hm` / `_zc` / `_wb`）。
- **v1.6**（2026-08-19）：Vange 判定——WorkBuddy 暂停（完成 CosyVoice 部署收尾后停止一切事务），开发职责全权移交 zcode；原「动工前核实 Kimi K3」条款废止。详见 `协同工作文档/2026-08-19-角色变更通知-WB暂停-zcode接管_hm.md`。
- **v1.7**（2026-08-19）：新增角色 codex（OpenAI Codex）——**负责复杂任务**（高难度编码、疑难问题、深度实现），产出文件后缀 `_cdx`。协作方更新为 Hermes × zcode × codex（+ WorkBuddy 暂停保留）。
- **v1.8**（2026-08-21）：Vange 亲定**最高铁律**（文件顶部 🚨 标注）——「所有决定都不能以牺牲首字输出延迟为代价，除非后续可以百分百确定补回来或者优化更多」。优先级高于本文件一切其他条款，四方开工必读。

*本规范由 Vange 于 2026-08-11 下达，Hermes 起草维护（2026-08-19 起），Hermes/zcode 知悉后生效。版本变更需 Vange 同意。*
