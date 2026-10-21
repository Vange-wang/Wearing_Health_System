# BOX-3 语音唤醒（免按键对话）继任 Spec v1.18

- **起草/当前 owner**：Codex / N3 · 2026-09-03 · v1.18 · 后缀 `_cdx`
- **性质**：v0.4 之后正式功能继任 Spec（ISSUE-0004 预制词部分），完整自包含；旧 `_hm` v1.11 保留为历史输入，不改写
- **周期标识**：`T-20260902-BOX3-WAKE-SPEC-CDX-C1` / `SCOPE-CDX-C1-BOX3-WAKE-SPEC`
- **依据与授权锚点**：
  - 历史 codex 审查链（含 timeout 分离新周期第 3/3 轮 `2026-09-02-BOX3语音唤醒Spec与任务单-timeout分离新周期-第3轮_cdx.md`，SHA-256 `fa926505e68cee0fd4de190a92c768a960a3e2f7fa3eadd10a5ae2174e3b065e`，历史结论保持 `DOCUMENT_REVIEW_LIMIT_REACHED`）
  - Vange 红线授权（_hm 决策文件 SHA-256 `9dafca03b8b9513272256b22b881fe858ff1528e5b251a487bbfe129a5fa5297`）
  - Vange timeout 分离授权（_cdx 决策文件 SHA-256 `b63cd7882a98382499c9e27b4b233d905fc3068cbcf819e3c8e5abb244683ea8`，原话「行，那就这样」）
  - Vange Codex 接管授权（`2026-09-02-BOX3语音唤醒-Codex接管一次性补齐-Vange决策_cdx.md`，SHA-256 `5235528b4f9d825c2ddc2c1d7f30b687faad02b11a45568f2ebc142040f6dded`，原话「不交给hermes了，你一次性搞齐」）
  - Vange 资源条款修订授权（2026-09-03，针对 `2026-09-03-BOX3语音唤醒-真机烧录回滚与资源门审查报告_cdx.md` 所列“80KB capture ring 改放 PSRAM + 32KB 绝对门改为按键版可达基线退化门”，原话「确认」）
  - Vange 第二次资源条款修订授权（2026-09-03，针对 `2026-09-03-BOX3语音唤醒-PSRAM资源修订与真机复验报告_cdx.md` 所列“hold 16KiB + 段 B pre-roll 9.6KiB 迁入 PSRAM，容量/状态机/按键接管上界/全部延迟红线不变”，原话「确认」）
  - Vange A+C 即时反馈与提速授权（2026-09-03）：本地晓晓音色短句池 `我在/咋啦/嗯呐/到/来啦` 每轮随机选择且不连续重复；短句期间并行预建本轮 HTTP/ASR 流；视觉最终改为复用现有 😄，仅设备实际收音期间大小呼吸变化，其他时间静止。原话依次为「A+C，但是不能只有我在一种回复……」「随机采用」「确认」「还是别加了……就笑脸大小动就好了」「听的时候才大小动，没听的时候不动」
  - 本地 esp-sr 1.9.5 实测
- **状态**：`HUMAN_TAIL_SMOKE_PASS / RESOURCE_GATE_BLOCKED / FORMAL_MATRIX_PENDING`（COM5 五分区写入与启动通过；Vange 按指示以正常语速完整说出「喵喵同学」后反馈「现在可以了」，据此仅确认单轮人工尾音冒烟不再提前播放 ACK。串口随后显示语音桥恢复为 `vb=1`，但本轮未抓到对应 `model_hit/triggered/ack_first_pcm` 完整切片，亦未执行慢速/拖尾、多轮、T1~T4 或长稳矩阵。`resource:ready internal_free=6699 largest=3072` 仍低于 §7.3 的 `10916/5376` 阻塞门，正式矩阵前必须诊断，禁止把单轮人工结果写成完整验收）
- **v1.11→v1.12 修订映射**：到顶遗留 S02→§5.2/§8/§9.1，响应 200ms 可取消 poll + 30s 连续无进展 timeout + EAGAIN/部分读取状态机；S04→§9.2，固定 M01~M06 误唤醒矩阵与 30min 最低分母；同时明确15s仅为采集/上传语音时长上限
- **v1.12→v1.13 修订映射**：2026-09-03 真机烧录证明原内部 `.bss` 布局导致 Wi-Fi/BLE/关键任务分配失败；capture ring 容量与按键接管上界不变，仅将 80KB ring 改为启动期一次性 PSRAM 分配，并把不可达的 32KB 绝对连续块门改为按键版实测基线的 70% 阻塞下限。
- **v1.13→v1.14 状态映射**：80KB capture ring 已确认在 PSRAM，静态 D/IRAM 回落至 `231358B`；但模型加载后、创建 talk/capture 任务前仅余 `internal_free=1431B/largest=1152B`，任务创建失败，最终 `131B/108B`，未达到 `10916B/5376B`。候选已判失败并整片回滚；本版只记录失败事实和停点，不擅自批准下一轮资源架构。
- **v1.14→v1.15 修订映射**：Vange 确认将 wake_engine 的 `hold 16KiB + 段 B pre-roll 9.6KiB` 合并为启动期一次性 PSRAM 有界分配；两段逻辑分区、容量、清零、锁、全局样本序号及状态机语义不变。I2S/DMA scratch、WakeNet 输入块与 capture/WakeNet/talk 关键任务栈继续保留内部 RAM。热路径禁止 malloc/free；PSRAM 分配或地址能力校验失败即阻断并回滚；必须用同轮按键/唤醒实测证明首字红线未退化。
- **v1.15→v1.16 修订映射**：Vange 确认 A+C 即时反馈与提速：WakeNet 命中先进入 `ACK_PLAYING` 并播放本地随机短句；短句结束后才进入 `WAIT_SPEECH`，此时复用现有 😄 开始大小呼吸动画，直到收音结束立即停止，3s 静默计时亦从 ACK 结束起算。wake capture generation 在 ACK 期建立，同一 talk_task 并行预建 chunked HTTP 请求，使 voice-bridge 提前创建本轮流式 ASR；失败或过期须关闭并无缝回退原按需建连。正式 T4 起点、门限及全部健康/BLE红线不变。
- **v1.17→v1.18 修订映射**：Vange 连续人工复现「你好小智」未说完即被 ACK 抢话；源码核对确认首次 `WAKENET_DETECTED` 直接进入 `ACK_PLAYING`，无尾音结束门。Vange 确认新增 `WAKE_TAIL_CONFIRM`：模型命中后继续丢弃麦克风帧，连续 80ms RMS<S/3 才确认并播放 ACK；300ms 内未形成该静音窗则拒绝候选、清理预连接并回 IDLE，禁止强制抢话。预连接仍从模型首次命中启动，正式 T4 不变。落地词改为 esp-sr 1.9.5 预制「喵喵同学」`wn9_miaomiaotongxue_tts`。

---

## 1. 目标与非目标

### 目标
1. 免按键语音对话：说 **「喵喵同学」** → 尾音结束确认 → 本地 ACK → 自动录音 → 提问 → 设备端说完判定 → 回复（T4 中位 ≤1.8s）→ 播放，全程不按键；
2. 按键模式保留，双模并存，**按键任意状态优先、首音零丢字**；按键路径行为零变化（首音快路径 + 上传期 30s 基线 + 响应期连续 30s 无可观测网络进展 timeout）；
3. 唤醒词可换位（`#define` + 独立模型目录 + sdkconfig 打包配置）。
4. WakeNet 首次命中后先确认尾音：连续 80ms RMS<S/3 才形成 `wake_confirmed`；确认后≤100ms输出随机本地短句首个PCM。短句结束后再接收问题，收音期间复用现有 😄 做轻量大小呼吸动画；预连接从模型首次命中并行启动。

### 非目标（本期不做）
- 自定义词「小V/小V小V」实装（issue #88 + 路线 B，§11）；服务端语义「说完」判定（§11）；barge-in/AFE/AEC（v2）；esp-sr V2/WakeNet10；休眠态唤醒；电池功耗；
- voice-bridge 任何改动、新增服务端预热接口、帧协议改动、告警/SpO2 质量门放宽、按键/既有路径行为变化；
- 不追求 T4 <1.6s（Vange 接受 1.8s 档）。

### 落地词裁决（Vange 2026-09-02）
落地 = 「喵喵同学」`wn9_miaomiaotongxue_tts`（esp-sr 1.9.5 现成，Kconfig `SR_WN_WN9_MIAOMIAOTONGXUE_TTS`，模型源文件合计 291,013B，元数据 DET_MODE_90/95 阈值 0.644/0.648）；旧「你好小智」`wn9_nihaoxiaozhi_tts` 仅保留为 v1.17 历史候选；最终目标「小V」仍需单独自定义训练，不得用 `wn9_customword` 名称冒充。

---

## 2. 冻结项（红线）

| # | 冻结 |
|---|---|
| F1 | esp-sr 冻结 1.9.5；managed_components 只读（IDF 生成） |
| F2 | voice-bridge 零改动；帧协议不变（零扩展）；BLE 8 字节帧不变 |
| F3 | 唤醒前 PCM 仅本地易失有界缓冲（段 A ≤1s / 段 B pre-roll 300ms / hold 16KiB / capture 2.5s=40000样本/80KB）；capture 由 audio_session 单独一次性 PSRAM 分配，hold+pre-roll 由 wake_engine 合并一次性 PSRAM 分配并逻辑分区；不上传/不落盘/不输出原始音频日志；I2S/DMA scratch、WakeNet 输入块与关键任务栈保持内部 RAM；放弃/超时/取消后 memset 清零；热路径禁止 malloc/free |
| F4 | 语音唤醒启用期自动 Light Sleep（3min）关闭（互斥；USB 供电期） |
| F5 | 不以放宽告警质量门/复用旧值/固定等待掩盖问题；不宣称医疗诊断 |
| F6 | **T4 中位 ≤1.8s（绝对）、P95 ≤2.5s（绝对）**；预算容差 ≤50ms；两门仅 Vange 可改 |
| F7 | 按键上传期 timeout=30000ms（基线）/ 唤醒上传期=2000ms；响应期两模式均为**连续30000ms无可观测网络进展 timeout**，200ms仅为可取消 poll 粒度；header完整返回或body读到正字节时重置无进展计时（Vange授权口径） |
| F8 | **W 唯一冻结值 = 300ms**（无 330 档） |
| F9 | ACK 为本地交互反馈，不得计作正式回答首字、不得改变 T4 起点；本地短句自身不得上传，ACK 播放期不得把扬声器回录送入 VAD/ASR |
| F10 | 短句池固定为 `我在/咋啦/嗯呐/到/来啦`，统一 `zh-CN-XiaoxiaoNeural`，随机选择且不连续重复；任何资源/预连接失败只允许回退原链路，不得阻塞按键或放宽门限 |

---

## 3. 审查裁决汇总（全周期自包含）

| 项 | 状态 | 落点 |
|---|---|---|
| 预审 S-01~S-09、复审 R2/R3、新周期 NC1~NC3、实质变更 R2C1/R2C2、timeout 分离第 1 轮 | 已闭环项保持 | §4~§9 |
| R3C1-S02 按键接管/响应 timeout | Codex接管后闭环 | §5.2/§8/§9.1 |
| R3C1-S04 唤醒率与误唤醒条件表 | Codex接管后闭环 | §9.2 |
| R3C1-S05 hold 归属 + 锁 | 保持闭环 | §5.1/§5.2 |
| R3C1-R2-N01 措辞 | 保持闭环 | 继任任务单 |

---

## 4. 架构与逐样本时间线

### 4.1 逐样本时间线（16k/16bit mono）

| 段 | 起止 | 用途 | 去向 |
|---|---|---|---|
| A 检测环 | …→ model_hit 帧 | 喂 WakeNet（≤1s 环形 FIFO） | 永不进上传；model_hit 整体丢弃清零 |
| A2 尾音确认 | model_hit → wake_confirmed / candidate_rejected | 连续80ms RMS<S/3确认；300ms无静音窗则拒绝；预连接并行 | 全部麦克风帧丢弃，零上传、零pre-roll、零hold |
| ACK 本地反馈 | wake_confirmed → 本地短句结束 | 随机短句本地播放；复用 model_hit 时预建的 HTTP/ASR 流；屏幕静止 | 麦克风帧丢弃、零上传；不计入 T4 |
| B WAIT_SPEECH/收音 | ACK 结束 → speech_end | 复用现有 😄 做大小呼吸；pre-roll防截首音；3s静默计时从ACK结束起算 | 从上传游标（F−200ms）起进上传；收音结束立即停动画 |
| C 对话上传流 | 上传游标 → vad_end → 0chunk | chunked POST 边说边传 | 服务端流式 ASR |
| H hold_buffer | vad_end 后 → 窗满或恢复 | 保存确认窗内恢复语音 | 恢复→补入；窗满→丢弃 |

### 4.2 架构图

```
双麦 stereo(16k) → 混音 mono
  ├─ IDLE：chunksize 缓冲 → esp_wn detect() → model_hit → WAKE_TAIL_CONFIRM（begin_capture 经 talk_task，mode=wake）
  │     → 同期由 talk_task 预建 chunked HTTP；尾音帧仅用于80ms静音窗，全部丢弃、零上传
  │     ├─ 300ms内连续80ms RMS<S/3 → wake_confirmed → ACK_PLAYING → 本地随机短句（确认后首 PCM≤100ms、总长≤500ms；屏幕静止）
  │     └─ 300ms仍无静音窗 → candidate_rejected → close/cleanup → IDLE（无ACK、无上传）
  │     → ACK_DONE → WAIT_SPEECH（现有😄开始大小呼吸）→ 段 B pre-roll（300ms）→ first_speech → 复用预建请求或按需建连上传（游标 F−200ms，上传期 timeout 2000ms）→ speech_end停动画
  │          ├─ 3s 无 speech → 清零 → IDLE（零语音上传）
  │          └─ 段结束检测（RMS<S/3 连续 ≥80ms）→ vad_end：producer 停写主 ring→写 hold；consumer 并行排空
  │               ├─ 窗内恢复 → hold 补入→恢复主 ring→继续
  │               ├─ 窗满 ring=0 且 in_flight=0 → 丢 hold → 0chunk → 响应期（200ms 可取消 poll；连续 30s 无进展才超时）→ 播放 → IDLE
  │               └─ 窗满失速 → cancel→write 返回（≤2s）后关连接→http 失败→IDLE
  └─ 按键模式：Boot PRESS_DOWN → 现有链路（mode=key，上传期 30s 基线；响应 200ms 可取消 poll + 连续 30s 无可观测进展 deadline）；任意状态按 Boot 立即接管（§5.2.6）
```

---

## 5. 状态机、说完判定与并发契约

### 5.1 状态机单一真源 + 模块边界 + 锁契约（R3C1-S05 落点）

**单一真源 = `wake_engine.c/.h`**：持有 `IDLE/WAKE_TAIL_CONFIRM/ACK_PLAYING/WAIT_SPEECH/UPLOADING/PLAYING` 状态转移、尾音确认、说完判定、**hold_buffer、段 B pre-roll、backlog 计量、trigger_mode**（这些对象的存储、读写、锁**全部在 wake_engine 内**）。`wake_ack.c/.h` 只提供短句清单、可注入随机选择与本地 WAV 播放，不得复制状态机。

**`audio_session.c/.h` 仅通用音频缓冲原语**：prebuffer/live ring 读写、begin/complete、generation、cancel 标志、audio_session 内部锁。**不持有 hold/pre-roll/backlog，不提供「hold 相关原语」**（删除 v1.10 的矛盾表述）。

单向 API：`wake_engine → audio_session` 调用 begin/complete/read/write（缓冲原语）；`audio_session → wake_engine` 不直接调用，仅通过事件/回调（释放内部锁后投递）上抛。

**锁契约（跨模块绝不嵌套持锁）**：
- `wake_engine` 调用 `audio_session` 任何 API **前必须释放全部 wake_engine 锁**；
- `audio_session` 上抛事件/回调**必须在其内部锁释放后投递**；
- wake_engine 内部锁：`state_lock`（状态机）、`pre_roll_lock`、`hold_lock`、`backlog_lock`——**四个锁互不嵌套**（同一函数至多持一个 wake_engine 内部锁，持锁期间禁止调用 audio_session/HTTP/I2S 阻塞 API）；
- audio_session 内部锁仅保护 prebuffer/ring/generation/cancel 原子性，**不跨模块持有**；
- 该规则目标：无锁序反转、无死锁。

**owner 契约**：begin_capture 按键回调直调（现有快路径）/ wake 经队列由 talk_task 调；complete_capture 唯一 owner=talk_task；generation 唯一递增点=begin_capture；key/wake 同帧 key 优先。ACK task 仅在 talk_task 完成 generation bind 后获通知；ACK 使用 TALK 播放租约，按键可在下一 PCM 块边界取消。P4 alert 不与 ACK 重叠，沿用 TALK 优先于 alert 的既有租约语义。

### 5.2 说完判定 + 缓冲 + backlog + timeout + 按键接管（R3C1-S02/S05 落点）

1. **语音活动跟踪**（wake_engine，10ms 帧 160 样本 RMS）：first_speech RMS≥S 连续 ≥100ms；段结束 RMS<S/3 连续 ≥80ms；窗内恢复 RMS≥S 连续 ≥60ms；
2. **段 B 滚动 pre-roll（wake_engine 内）**：300ms=4800 样本滚动环（保最新、满弃最旧）；ACK结束进入 WAIT_SPEECH 时清零启动；尾音确认期间禁止写入；no_speech/放弃/取消 memset；`pre_roll_lock`；全局 sample 序号；阻塞自测 ACK_DONE 后 0.1/0.5/2.9s 开口 → HTTP 首样本=F−200ms；
3. **hold_buffer（wake_engine 内）**：512ms=8192 int16 样本=16KiB；与段 B pre-roll 合并为启动期一次性 PSRAM 分配后的独立逻辑分区；vad_end 后 producer 停写主 ring 改写入 hold；窗内恢复 → hold 按序补入 → 恢复主 ring；窗满未恢复 → memset 丢弃；溢出（>512ms）→ 判未恢复走窗满；`hold_lock`；逐样本测试恢复词首样本不丢；
4. **backlog（wake_engine 内）**：`ring_pending + in_flight_bytes + framing_pending`；三字段 `backlog_lock` 内原子；窗满成功 = 全 0；失速 = 任一 >0；event group 通知；日志 `wake:backlog(...)`；受控测试「ring=0 但 in_flight>0」必走失速；
5. **分阶段 timeout（Vange 授权）**：
   - mode=wake 上传期（PCM 块 + 0chunk）`esp_http_client_set_timeout_ms(2000)`；mode=key 上传期 30000ms 基线；
   - **响应期（两模式）保持现行30s无进展timeout，200ms仅为可取消poll**：0chunk成功后设置 `esp_http_client_set_timeout_ms(200)`；每次 `fetch_headers/read` poll前后检查cancel；维护 `last_progress_us`。header阶段以0chunk完成为初始进度点，`fetch_headers()`完整返回时刷新；body阶段每次 `read` 返回正字节时刷新。仅当 `now-last_progress_us >= 30000ms` 才响应超时。持续有可观测进展的长响应允许总时长超过30s，按键基线语义不变；
   - **返回值与部分读取状态机（阻塞）**：`-ESP_ERR_HTTP_EAGAIN`=本次200ms内未形成对调用方可见的进展，保留HTTP client内部parser、已收frame header字节数、目标payload长度与已收payload字节数，检查cancel/30s无进展deadline后继续。ESP-IDF公开接口不暴露EAGAIN轮次内收到的部分header字节数，因此该轮不刷新外部`last_progress_us`，但部分header必须由HTTP client内部parser跨poll保留；`0`仅在协议已完整结束时为正常EOF，否则为截断失败；其他负值为硬错误；body正值累加到当前frame/payload并刷新`last_progress_us`。禁止因一次EAGAIN清空、重开请求或把部分帧当完整帧；
6. **按键接管全四阶段契约（R3C1-S02 落点，覆盖上传 write / fetch_headers / 响应 read / PLAYING）**：
   - key_down（任意 wake 阶段）→ 现有 PRESS_DOWN 路径 begin_capture（generation++、置 cancel）；
   - cancel 生效延迟（有界）：上传 write 阶段 ≤2s（write 返回后检查）；fetch_headers/响应 read 阶段 ≤200ms（poll边界前后检查）；PLAYING 阶段在下一播放块边界生效，并记录实测时长；
   - **consumer 交接**：talk_task 在 cancel 生效点立即中止旧 wake 轮（close HTTP / 停播放），随即开始消费新 key 轮缓冲；**key_down → 新 key 轮开始消费 ≤2.5s 上界**（2s write 最坏 + 200ms read 分片 + 300ms close/调度余量）；
   - **capture 缓冲容量 =2.5s = 40000 样本（80KB，PSRAM）**：`audio_session_init()` 启动期通过 `MALLOC_CAP_SPIRAM|MALLOC_CAP_8BIT` 一次性零初始化，失败即阻断启动并回滚；运行热路径只做有界顺序读写和清零，不 malloc/free。I2S/DMA scratch、WakeNet 输入块与 capture/WakeNet/talk 关键任务栈仍在内部 RAM；hold+pre-roll 按 v1.15 单独合并分配到 PSRAM。容量和按键接管语义不变，覆盖上述已含300ms关闭/调度余量的 2.5s 接管上界；若实测接管超过2.5s即判失败，不得靠丢弃首音规避；
   - **generation 隔离（阻塞）**：旧 wake consumer 中止后不得读/上传新 key generation 的 PCM；旧响应/播放须先校验 generation 仍当前才可继续，否则丢弃；**旧轮零续播、两轮 PCM 不串代**；
   - **逐阶段受控测试（阻塞）**：分别在 wake 上传 write 阻塞、fetch_headers 阻塞、响应 read 阻塞、PLAYING 四阶段注入 key_down → 断言按键首样本零丢、buffer overflow=0、旧轮零续播、两轮 PCM 不串代；
7. **失败率门**：总轮含失败轮；backlog_stall+HTTP_FAIL ≤10%；有效成功 N≥10。
8. **ACK + 预连接契约**：
   - WakeNet 命中仅置 `WAKE_TAIL_CONFIRM`、`begin_pending` 与 `MODEL_HIT`；talk_task 建立并绑定 capture generation 后立即以 wake 2s timeout 预建同一条 chunked POST，但不得通知 ACK task；尾音确认帧只进入 `wake_engine_process_frame()`，固定 `ROUTE_DROP`，不写 audio_session、pre-roll 或 hold；
   - `WAKE_TAIL_CONFIRM` 使用 10ms 帧：RMS<S/3 连续8帧（80ms）才置 `TRIGGERED/wake_confirmed` 并进入 `ACK_PLAYING`；任一 RMS≥S/3 帧把低帧计数清零。自 model_hit 起满30帧（300ms）仍未确认，置 `CANDIDATE_REJECTED`、请求停止本轮 capture、关闭 prepared HTTP 并回 IDLE，不播放ACK；按键在该状态仍最高优先级并执行同样清理；
   - `TRIGGERED` 由 capture_task 转发给 ACK task，generation 必须与 model_hit 时绑定的 capture generation 相同；服务端 `stream_idle_timeout_seconds=5`，尾音确认≤0.3s、ACK≤0.5s且后续静默门3s，正常窗口不得触发服务端 idle timeout；
   - ACK task 从五句池随机选取；候选索引必须排除上一轮索引，其余四项等概率。音频为 SPIFFS 内 16kHz/16-bit/mono WAV，本地流式读写 codec，禁止运行期 TTS、禁止整文件动态加载、热路径禁止 malloc/free；
   - ACK 播放期间 `wake_engine_process_frame()` 仅推进全局样本序号并丢弃麦克风帧，不累计静默、不喂 VAD、不写 pre-roll；ACK 成功或资源失败均调用唯一 `ack_complete` 转入 `WAIT_SPEECH`，清空帧拼接残留后再启动3s计时；
   - 预建请求只归属于绑定 generation：speech_start 后复用；失败则清理并走原 `voice_round` 建连；no_speech、key takeover、generation过期均在既有界限内 close+cleanup，禁止跨轮复用；预连接不得改变服务器、认证、body或帧协议；
   - 交互视觉不新增图片：`ACK_PLAYING`保持当前图片静止；仅 wake 模式进入 `WAIT_SPEECH` 后把现有 `emoji_u1f604.png` 设为 360ms 往返的轻量缩放动画，贯穿真实收音期；`SPEECH_END/no_speech/失败/按键接管`立即停止并恢复100%缩放及最近健康 Emoji。状态任务不得在动画期覆盖图片；按键模式视觉零变化。

### 5.3 容忍停顿与同帧优先级
P_tol=300ms（阻塞 DoD）：停顿 ≤300ms 恢复语音经 hold 完整保留零截断零丢字；同帧窗满优先；301~450ms 记录区；>450ms 物理必截。

### 5.4 触发模式契约（保持）
trigger_mode 枚举 `{WAKE, KEY}`；触发源设置、voice_round 只读；按轮生命周期、不跨轮残留；带 generation 过期；timeout 切换时序（建连后首个 write 前按 mode 设上传期、0chunk 后切响应分片模式）；禁 2s 泄漏到按键轮；日志 `wake:mode`。

---

## 6. 首字门限与预算（闭合）

### 6.1 门限与打点
- T1 命中→capture ready：<100ms；
- T2 起点 = 最后连续 RMS≥S/3 帧的下一帧；终点 = 0chunk write 完成返回；**预算 = 80+300+10 = ≤390ms（W 唯一 300）**；
- 阈值语义：RMS≥S/3 = 有效语音段；first_speech 用 S；S/3~S 尾音属语音段内部不计 T2；
- T3 起点 = 服务端收到 0chunk → 服务端首帧；
- **T4 中位 ≤1.8s、P95 ≤2.5s（绝对）**；容差 ≤50ms；
- 尾音/ACK/视觉独立指标：`model_hit→wake_confirmed` 仅记录不作为体验延迟通过口径；连续80ms尾静音形成确认，确认后 `wake_confirmed→ACK首个codec PCM ≤100ms`，即自然说完后的首PCM目标≤180ms；ACK总长≤500ms；`ACK_DONE→笑脸动画启动 ≤100ms`、收音结束→动画停止≤100ms。这些指标与 T4 分开报告，禁止用 ACK 代替 T4；
- 时钟：固件 esp_timer + 服务端 UTC；主口径 = 固件打点 → codec 首 PCM；机制校验：同轮同测唤醒−按键 ≤390ms；
- Pass/Fail：超门 FAIL → 定位 → 仍超回 Vange；禁降门/改起点/只报中位。

### 6.2 预算表（W 唯一 300；基线 = 2026-09-01 实测中位 1391.754 / P95 2037.571）

| W | T2(80+W+10) | 中位预算 | vs 1.8s | P95 预算 | vs 2.5s | P_tol |
|---|---:|---:|---:|---:|---:|---:|
| **300（唯一冻结）** | 390ms | 1781.754 | 余 18.246 | 2427.571 | 余 72.429 | 300ms |

---

## 7. 模型生命周期 / 隐私 / 资源

### 7.1 esp-sr 1.9.5 初始化/销毁/降级（保持）
sdkconfig.defaults：仅启用 `CONFIG_SR_WN_WN9_MIAOMIAOTONGXUE_TTS=y`、`CONFIG_USE_MULTINET=n`，移除旧「你好小智」选项；`model` 分区 512K；`srmodels.bin` ≤512K + 单一模型清单证据。运行期：`esp_srmodel_init("model")`→NULL→`esp_srmodel_filter()`→`esp_wn_handle_from_name()`→`create()`→采样率/通道校验→`get_samp_chunksize()`；失败→降级按键日志 `wake:model_load_failed:<step>`；退出 `destroy()`+deinit；日志记录模型名/分区/chunksize。

### 7.2 隐私（零语音上传）
静默段/放弃轮零 `POST /api/v1/voice/stream`、零语音 PCM；`GET /api/v1/health/alert`（P4 每 30s）为预期保留；三类证据按路径+方法+payload 过滤；时间戳对齐；原始 PCM 零上传零持久化。

### 7.3 资源安全门（含缓冲预算）

| 项 | 阻塞阈值 | 测量 |
|---|---|---|
| capture/WakeNet/talk 任务栈余量 | high-water 余量 ≥512 字节 | `uxTaskGetStackHighWaterMark()` |
| 内部 heap 可达基线门 | 按键版 ready 基线：free=15595B、largest=7680B；候选 ready 及 20 轮/1h 观测最小值分别 ≥10916B、≥5376B（基线 70%），且零 allocation/task-create failure、无持续下降趋势 | `heap_caps_get_free_size(INTERNAL)` / `heap_caps_get_largest_free_block(INTERNAL)`；固定 ready 打点 + 每轮/长稳水位 |
| capture 缓冲扩展（2.5s=80KB） | PSRAM 一次性分配=80000B；内部 `.bss` 不得保留 80KB ring；分配失败阻断且可回滚 | map/nm diff + 启动 caps/字节数日志 + 回滚验证 |
| hold_buffer（16KiB）+ 段 B pre-roll（9600B） | wake_engine 启动期合并一次性 PSRAM 分配=25984B并逻辑分区；内部 `.bss` 不得保留两块数组；失败阻断且可回滚 | map/nm diff + 启动 caps/分区字节数日志 + 回滚验证 |
| WakeNet 每帧最坏耗时 | < 帧周期（chunksize/16000 s） | detect() 前后 esp_timer |
| ring / hold overflow | = 0 | 写前水位计数 |
| missed frame | = 0 | 帧计数连续性 |
| ACK 资源 | 5个 WAV 均为16kHz/16-bit/mono、单句≤500ms；视觉只复用既有128×128 RGBA笑脸；storage.bin仍≤1MiB | 构建前资产脚本 + `storage.bin` 字节数/SHA |
| ACK 运行资源 | 禁止整句常驻内部 RAM；ACK task 栈 high-water≥512B；内部 heap仍满足既有70%门 | map/nm + 真机日志 |

采样：长稳 1h 每 5min + 峰值；基线 = 按键模式固件；失败 → 修复 → 重测。

---

## 8. 超时与参数唯一值

| 参数 | 冻结值 | owner/权限 |
|---|---|---|
| S | 初值 500，标定 [200,2000] | Codex 标定，Vange 确认 |
| end 门限 | S/3 | 同 S |
| 段结束检测 | RMS<S/3 连续 ≥80ms | 冻结 |
| 确认窗 W | **300ms（唯一，禁升 330）** | 冻结 |
| 回升取消 | RMS≥S 连续 ≥60ms | 冻结 |
| first_speech | RMS≥S 连续 ≥100ms | 冻结 |
| pre_roll | 200ms；段 B 滚动环 300ms | 冻结 |
| hold_buffer | 512ms=16KiB（wake_engine PSRAM 合并块内独立分区） | 容量冻结；存储位置按 Vange 2026-09-03 第二次「确认」修订 |
| capture 缓冲总量 | 2.5s=40000 样本=80KB，PSRAM 启动期一次性分配 | 容量冻结；存储位置按 Vange 2026-09-03「确认」修订（覆盖已含300ms余量的按键接管上界） |
| 静默放弃 | 3s | 冻结 |
| 单次采集/上传语音时长上限 | 15s（不含响应读取与播放） | 冻结 |
| 唤醒上传期 timeout | 2000ms（mode=wake） | 冻结（Vange 授权） |
| 按键上传期 timeout | 30000ms（基线不变） | 冻结（Vange 授权） |
| 响应期 timeout | 连续无可观测网络进展 30000ms；200ms poll + cancel 检查；header完整返回或body正字节重置无进展计时 | 冻结（保持按键基线；poll打断 ≤200ms） |
| 按键接管消费上界 | ≤2.5s（write 2s + read 分片 200ms + 余量 300ms） | 冻结 |
| 失败率门 | backlog_stall+HTTP_FAIL ≤10% | 冻结 |
| 门限 F6 | 中位 ≤1.8s / P95 ≤2.5s（容差 ≤50ms） | 仅 Vange 可改 |
| 唤醒尾音确认 | 连续80ms RMS<S/3；总等待≤300ms；超时拒绝而非强制ACK | Vange 2026-09-03 确认；禁止抢话 |
| ACK首音/总长 | wake_confirmed后≤100ms / ≤500ms | 独立于 T4；自然说完后首PCM目标≤180ms |
| 收音笑脸动画 | ACK_DONE后≤100ms启动；真实收音结束后≤100ms停止；非收音期静止 | Vange 2026-09-03 最终视觉口径 |
| ACK短句池 | 我在/咋啦/嗯呐/到/来啦；随机且不连续重复 | Vange 2026-09-03 确认 |

---

## 9. 可测 DoD

### 9.1 功能与截断（阻塞）

1. 免按键：喊「喵喵同学」→ 不抢尾音地播放随机ACK → 自动录音 → 提问 → 回复 T4 门限内到达 → 播放，循环 5 次稳定；启动日志必须为 `wake model=wn9_miaomiaotongxue_tts`，srmodels只含该单一WakeNet模型且≤512KiB；
2. 静默放弃：3s 无 speech → 零语音上传 → 回 IDLE；
3. 截断（P_tol=300ms 阻塞）：停顿 ≤300ms 完整问句 N≥10 → 截断率 0% 且恢复词首样本不丢（selftest + ASR 文本）；301~450ms ≥5 → 诚实记录（禁删数据）；语料表冻结；
4. 可靠性门：总轮含失败轮；backlog_stall+HTTP_FAIL ≤10%；有效成功 N≥10；
5. 受控阻塞测试：模拟「ring=0 但 in_flight>0」→ 必走失速；「全 0」→ 正常 0chunk；
6. 段 B 逐样本测试：ACK_DONE 后 0.1/0.5/2.9s 开口 → HTTP 首样本 = F−200ms；
7. **按键接管四阶段回归（阻塞）**：wake 上传 write 阻塞 / fetch_headers 阻塞 / 响应 read 阻塞 / PLAYING 四阶段各注入 key_down → 按键首样本零丢、buffer overflow=0、旧轮零续播、两轮 PCM 不串代；
8. timeout 分离/响应续读回归：按键受控写阻塞 2~30s → 仍按30s基线；唤醒失速 ≤2s；响应poll取消≤200ms；完整header在201ms后才返回仍成功；多个body正字节间隔<30s仍成功；总响应>30s但持续有可观测进展仍完整；部分header由HTTP内部parser跨EAGAIN保留，部分4字节帧头/WAV payload由应用层跨EAGAIN保留，均无重复无丢字；header连续30s不完整须超时；EAGAIN、完整EOF、截断EOF、硬错误各走唯一分支；日志 `wake:mode` 核对；
9. 端点：长句（>5s）收尾完整；backlog 快照随 T2；连续多轮 5 次稳定；
10. 播放中不唤醒；按键打断回归；按键全回归（首音快路径 + 上传 30s 基线 + 响应连续 30s 无可观测进展基线）；
11. 首字：T1~T4 分段 + 同轮同测对照（§6.1）。
12. **尾音确认与ACK行为（阻塞）**：固定公共 seam=`wake_engine_process_frame()` + `wake_engine_take_events()/state/take_stop_request`。宿主先红后绿覆盖：model_hit后7个低帧不得TRIGGERED，第8个低帧才进入ACK；中途高帧重置；30帧无80ms静音窗必须拒绝且无ACK；尾音确认期间全部ROUTE_DROP；TAIL_CONFIRM按键接管。宿主随机注入证明ACK仅来自五句池且永不连续重复；真机正常语速N≥10、刻意慢速N≥5、拖长尾音N≥3均不得在发声期间播放ACK，记录 `model_hit/tail_confirmed或candidate_rejected/ack_first_pcm/ack_done`；确认后首PCM≤100ms、总长≤500ms；尾音确认与ACK期间上传PCM=0。
13. **ACK故障/接管/视觉（阻塞）**：缺失WAV、打开失败、播放失败均≤500ms进入WAIT_SPEECH且可正常提问；ACK_PLAYING按键接管N≥3，旧ACK下一PCM块边界停止、按键首音零丢；alert与ACK不重叠；ACK期间笑脸静止，ACK_DONE后≤100ms开始大小呼吸，speech_end/no_speech/失败后≤100ms停止并恢复最近健康Emoji；非收音期观察≥1min不得自行缩放。
14. **预连接（阻塞）**：成功时同generation复用且首个上传块不重复/不丢；连接失败、服务端拒绝、no_speech、key takeover、generation过期分别证明关闭清理并回退/结束；不得出现跨轮请求；同轮N≥10分别记录 preconnect_ms/used/fallback 与 T4，只有 T4 不退化才允许保留。

### 9.2 唤醒率/漏唤醒/误唤醒（固定可执行矩阵）

**必测条件表（每位参与者 × 每行 = N=10，独立过门）**：

| 条件 ID | 距离 | 方向 | 音量 | 类别 | 每参与者门限 |
|---|---|---|---|---|---|
| C01 | 0.5m | 正面 0° | 正常（~60dB@1m） | 主场景 | ≥9/10 |
| C02 | 1.0m | 正面 0° | 正常 | 主场景 | ≥9/10 |
| C03 | 1.0m | **左 45°**（麦克风法线左偏，冻结单侧） | 正常 | 主场景 | ≥9/10 |
| C04 | 1.0m | 正面 0° | 轻（~45dB） | 挑战 | ≥7/10 |
| C05 | 2.0m | 正面 0° | 正常 | 挑战 | ≥7/10 |

- **老人声覆盖**：不设「老人声」为独立条件行——验收集必须含老人参与者，老人在 C01~C05 的逐条件通过率即老人声覆盖（老人任一条件失败 → 该条件 FAIL）；
- 参与者数 `P ≥ 3`（老人 1、女声 1、至少 1 名未标定的老人或女声）；标定集 2 人语料不重叠；匿名 ID 映射 hash 冻结；
- **总分母 = P × 5 × 10**（P=3 时最低 = 150 次尝试，全部记录成功/失败）；
- 任一参与者任一条件失败 → 该条件 FAIL（禁汇总平均）；全局汇总仅描述统计；
- 成功 = 唤醒后3s内出 `wake:speech_start`。

**误唤醒必测场景表（固定最低集合；每行独立执行5min）：**

| ID | 刺激源与操作 | 设备状态 | 声级/距离 | 允许误唤醒 |
|---|---|---|---|---:|
| M01 | 安静，无主动发声；记录环境本底 | IDLE | 记录dBA | ≤1/5min |
| M02 | 两人自然聊天，固定语料不含精确唤醒词 | IDLE | BOX-3处55~65dBA，主说话人约1m | ≤1/5min |
| M03 | 电视或手机播放固定中文人声语料，不含精确唤醒词；记录语料SHA-256 | IDLE | BOX-3处55~65dBA，声源约1m | ≤1/5min |
| M04 | 设备自身普通回答TTS连续播放；记录文本/音频标识 | PLAYING | 设备既有音量 | **0/5min** |
| M05 | P4 alert语音连续/循环播放；记录alert_id与播放次数 | PLAYING/ALERT | 设备既有音量 | **0/5min** |
| M06 | 固定非语音环境声序列：风扇、键盘、餐具碰撞；记录源与顺序 | IDLE | BOX-3处55~70dBA，声源约1m | ≤1/5min |

- 误唤醒定义：未人工说出、且固定播放语料不含精确「喵喵同学」时产生新的wake generation或语音POST；两者任一发生均计1次，同一次触发不重复计数。`candidate_rejected` 单独计候选拒绝率，不计成功唤醒，但必须保留分母与日志。
- 固定最低总时长 = `6 × 5min = 30min`；六行必须全部执行并逐行过门，不得合并平均、删失败轮或用长稳环境音替代。
- 证据字段：场景ID、固件/参数hash、设备状态、声源/语料hash、dBA与测点、距离、开始/结束时间、wake generation计数、`POST /api/v1/voice/stream`计数、对应日志范围、失败时间点。

### 9.3 长稳
≥1h（BLE 连接 + 间歇环境音）无 watchdog/溢出/断连；20 轮循环；资源门（§7.3）全达标。

---

## 10. 标定与验收隔离（保持）
标定集 2 人 + 专用语料 → 标定 S → 参数冻结（记录 S/W/固件 hash）→ 独立验收集（≥3 人含未标定老人/女声，语料不重叠）；任何参数改动全量作废重跑；P95=nearest-rank（N=10 取第 10 值）；异常轮计入可靠性分母单独报告；原始字段含参与者匿名 ID。

---

## 11. 后续门（不阻塞 §1-10）
- 「小V」：issue #88 收录申请（附项目链接；4 音节优先；Vange 授权后提交）+ 路线 B 中文自定义唤醒词一键训练开源工具（独立立项）；
- 服务端语义「说完」判定：后续方案，需双向通道，单独立项验证；
- v2：AFE/AEC + barge-in；休眠态唤醒 ISSUE-0005 仲裁；
- ISSUE-0004：保持 Open；关闭 = 自定义训练路线B走通 + 完整证据包 + Vange 最终验收。

---

## 12. 失败分支决策表

| 失败项 | 触发 | 分支动作 |
|---|---|---|
| 模型加载/打包失败 | §7.1 / srmodels.bin >512K | 降级按键；日志；回 Spec |
| T4 超门 | §6.1 | 定位 → 仍超回 Vange；禁降门 |
| ACK首音/总长或笑脸动画启停超门 | §6.1 / §9.1 | 定位SPIFFS、显示锁或任务调度；不得占用正式T4预算 |
| ACK资源/播放失败 | §5.2 / §9.1 | 记录失败并立即进入WAIT_SPEECH；禁止卡死或静默结束整轮 |
| 尾音确认超300ms | §5.2 / §9.1 | 拒绝候选、无ACK、无上传、清理预连接并回IDLE；禁止强制抢话 |
| 预连接失败/过期 | §5.2 / §9.1 | close+cleanup，同轮回退原按需建连；跨轮复用为阻塞缺陷 |
| ≤300ms 停顿被截/丢字 | §9.1.3 | 实现 bug → 修复重测 |
| 失败率门超 10% | §9.1.4 | 定位 → 修复重测 → 仍超回 Spec |
| backlog 失速 | §5.2 | 中止本轮（≤2s）→ 计入可靠性分母 |
| 按键接管丢字/串代 | §9.1.7 | 缓冲容量/锁/generation bug → 修复重测 |
| 响应分片 cancel 打断超 200ms | §9.1.8 | 定位分片粒度 → 修复重测 |
| 按键受控阻塞回归失败 | §9.1.8 | 定位 timeout 泄漏 → 修复重测 |
| 资源门超阈值 | §7.3 | 修复 → 重测；结构性失败回 Spec |
| 误唤醒/漏唤醒超标 | §9.2 | 一轮标定 → 复测 → 仍超回 Spec |
| 按键/回归失败 | 回归矩阵 | 修复重测（按键零变化铁项） |
| 任一 SERIOUS 一轮无效 | — | 回滚按键基线，保留现场日志回 Spec |

---

## 13. 基线冻结与历史关系

| 文件 | SHA-256 |
|---|---|
| 旧Spec v1.11（历史输入） | a4bcd03fef27bc7990e26a1c2dc2d27e01fc7ce94a924b411429001aa50f2fd4 |
| 旧任务单 v12（历史输入） | 1a6e8a77d8c7493dcacc0733ae11ff396be225d1fd993e2368894b99fb8ff4e0 |
| 继任Spec v1.13 / 继任任务单 / ISSUE-0004 | 由Codex自核报告记录最终hash；本文不写自指hash |
| 红线授权（_hm） | 9dafca03b8b9513272256b22b881fe858ff1528e5b251a487bbfe129a5fa5297（未改） |
| timeout 分离授权（_cdx） | b63cd7882a98382499c9e27b4b233d905fc3068cbcf819e3c8e5abb244683ea8（未改） |

---

## 14. 回滚与基线

- 允许写入见继任任务单File Map；禁止整树reset/覆盖comp_check/其他工程/voice-bridge；
- 用户确认前只允许文档补齐。确认后方可实施；实现产出按继任任务单验收，最终由Vange验收。Hermes不参与本次文档补齐，不得伪称Hermes审查通过。

---

*Codex / N3 · 2026-09-03 · v1.18 · Task T-20260902-BOX3-WAKE-SPEC-CDX-C1 · Scope SCOPE-CDX-C1-BOX3-WAKE-SPEC · 后缀 _cdx 遵循 agent.md §5.1*

## 2026-10-21 普通距离漏唤醒：单阈值现场实验

当前直连配套已由真人在20厘米处确认唤醒并完整回答，Git标签box3-20261021-near-voice-pass；普通距离一次仍无模型命中，连接/会话与read/detect正常。本实验仅在保屏R20诊断ON基线上，保留DET_MODE_90，在wake_engine_init完成模型创建后使用现有WN9接口对word1请求set_det_threshold(...,0.620f,1)，初始化读取原值与设置后值并记录数字结果。元数据0.644不是当前实机读数；实际默认以本次日志为准。

不改模型/分区/通道/输入增益/音频映射、ASR输入、尾音确认、按键、屏幕、网络、等待或问答状态机。不增加每帧计算、推理调用、任务、配置系统或自动重试。接口不可用或设置失败时保留原模型能力，不为此关闭语音。新日志只允许word/before_milli/requested_milli/set/after_milli数字，初始化执行一次。

目标是可回退的单参数识别对照，不预先宣称改善；较低阈值可能增加误唤醒。开发员交一文件候选与最小差异，由原独立角色复核一次；Root沿现有SDK增量构建，限300秒无自动重试，保留原已会回答的app二进制。新工件可核对后再由用户确认安装。实机先核屏幕、连接及阈值结果，再做原距离单次唤醒/短问，并观察安静时误触发；首字计量与原版本分开报告。

本实验暂停准入（2026-10-21）：用户明确最初也很靠近说，不能以远近距离差异支持调阈值；另报告听到两次回答。Root停止阈值候选继续推进，未SDK/未刷写。先确认输入次数和播放→续听交接，保留当前能答话版本。

恢复离线准备（2026-10-21）：用户将重复回答明确降为次要问题，主要目标仍是近距离也发生的间歇漏唤醒。现仅恢复上述0.620单阈值候选的独立源差异复核与一次SDK增量编译，作为可回退参数实验；不以距离差异或阈值根因已证实为依据。固件安装仍待新二进制就绪后用户确认，当前现场版本不动。
