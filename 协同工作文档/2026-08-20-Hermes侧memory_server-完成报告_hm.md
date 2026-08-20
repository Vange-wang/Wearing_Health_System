# Hermes 侧 memory_server 完成报告（单一记忆源 v2）

- **实施方**：Hermes · 2026-08-20 · 依据 `规划文档/技术验证/2026-08-20-单一记忆源-三端共享方案_hm.md`（v2）
- **结论**：Hermes 侧四项全部完成并验证：① memory_server.py 服务 ✅ ② 配置调优 ✅ ③ 存量迁移 ✅ ④ 接口全链路自测 ✅。待 zcode 侧 voice-bridge 改造对接。

---

## 一、交付物

### 1. `~/.hermes/scripts/memory_server.py`（核心，8781 独立小服务）

| 接口 | 功能 | 验证 |
|---|---|---|
| `GET /api/v1/memory` | 返回 USER.md + MEMORY.md 合并全文 | ✅ HTTP 200 |
| `POST /api/v1/memory/fact` | 写入语音事实到 MEMORY.md（去重 + 容量裁剪） | ✅ 落盘成功 + 去重 deduped=true |
| `DELETE /api/v1/memory/fact?keyword=X` | USER.md 字段级删 + MEMORY.md 事实段删 | ✅ 删除 1 条验证 |

**安全设计**（关键）：
- MEMORY.md 删除**只删「语音事实格式」段落**（`YYYY-MM-DD | 类别 | 事实 | 关键词`），Hermes 笔记段落（自由文本）绝不触碰——防止误删 Hermes 自己的记忆；
- USER.md 字段级删除（段内按片段匹配，只删含关键词的小块，保留同段其他字段）；
- 写入加锁（threading.Lock，防与 Hermes memory 工具并发写冲突）；
- 仅监听 127.0.0.1 + Bearer token 鉴权（读 .env 的 API_SERVER_KEY，与 voice-bridge HERMES_API_KEY 同源）；
- 去重：关键词重叠度（<3 个 0.8 / ≥3 个 0.6）+ 子串兜底；
- 容量：8000 字符，超限只裁事实段落最旧条目（Hermes 笔记不动）。

### 2. 配置调优

`memory.memory_char_limit: 2200 → 8000`（`hermes config set` 已生效，config.yaml:370 确认）。

### 3. 存量迁移

`voice-bridge/memory/user_facts.md` 2 条 → MEMORY.md：
- `2026-08-20 | 物品 | 用户的单车是FACTOR OSTRO VAM | FACTOR,OSTRO,VAM,单车`（MEMORY.md:41）
- `2026-08-20 | 学校 | 用户是广东医科大学的学生 | 广东医科大学,大学`（MEMORY.md:43）
- 旧文件待 zcode 改造时删除（voice-bridge/memory/ 目录含 .gitignore）。

### 4. 启动脚本

`~/.hermes/scripts/memory_server.cmd`（miniconda python 后台运行入口）。

## 二、验证记录

| 测试 | 结果 |
|---|---|
| GET /api/v1/memory | ✅ 200，返回双文件内容 |
| POST 事实（中文，文件 body） | ✅ written=true，MEMORY.md 落盘 |
| POST 同关键词再发 | ✅ deduped=true（去重生效） |
| DELETE keyword=memory_server | ✅ memory_md_removed=1，文件确认删除 |
| 存量迁移 2 条 | ✅ 均 written=true，MEMORY.md 41/43 行确认 |

**已知注意**（非 bug）：
- git-bash curl 传中文 keyword 会 GBK 乱码（`ÁÙÊ±²âÊÔ`）→ 服务端按 UTF-8 解析失败 → 删除 0 条。**voice-bridge 用 Python httpx/requests 调用不受影响**（自动 UTF-8）；zcode 若用 curl 测试需 URL 编码（`%E4%B8%B4...`）。
- 服务当前以后台进程运行（PID 37496）；重启入口 `memory_server.cmd`。

## 三、待办（zcode 侧）

1. voice-bridge 改造（任务单 `zcode_handoff/2026-08-20-单一记忆源改造-任务单_hm.md`）；
2. 对接后删除 `voice-bridge/memory/` 旧目录；
3. 首字对比测试（改造前后 llm_ttft ≤ +50ms）→ 送 Hermes 审查。

---

*Hermes（deepseek-v4-pro）· 2026-08-20 · 后缀 _hm 遵循 agent.md v1.7 §5.1*
