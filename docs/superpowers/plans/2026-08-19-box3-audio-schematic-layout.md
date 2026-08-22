# BOX-3 Audio Schematic Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变器件、参数、网络和电气连接的前提下，把 BOX-3 合板原理图中的 ES7210、双麦克风、参考/去耦及音频电源区域重排为零重叠、文字清晰的模块化布局。

**Architecture:** 以 U1（ES7210）为中心，MIC2/MIC1 分别位于左上和左下，REF/BIAS/地址去耦位于右侧，AUD_VDD 与稳压滤波位于底部。先保存完整图页源码和对象清单，再按功能块逐块移动器件、属性和导线；每块完成后检查对象数量与网络连接，最后统一保存、目视复核并运行 DRC。

**Tech Stack:** 嘉立创 EDA 专业版 V3.2、Run API Gateway V1.0.5、EasyEDA Pro API、WebSocket Bridge

**Spec:** `规划文档/Spec文档/2026-08-19-BOX3音频原理图布局设计-spec.md`

## Global Constraints

- 仅调整原理图布局和导线几何，不改变器件、参数、网络名称或电气连接。
- 任何元件、位号、参数值、网络名和导线均不互相遮挡。
- 所有对象吸附到 0.05 inch 网格。
- 元件外框之间至少保留 30 个原理图坐标单位；功能块之间至少保留 80 个单位。
- 导线只使用水平、垂直和直角转折，不穿过元件本体或文字。
- ADC_GND 与数字 GND 的现有网络边界保持不变。
- 最终 DRC 必须为致命错误 0、错误 0、警告 0、信息 0。

---

### Task 1: 建立可回退的图页快照

**Files:**
- Create: `规划文档/硬件参考/BOX-3设计文件/backup/2026-08-19-layout-before-source.txt`
- Create: `规划文档/硬件参考/BOX-3设计文件/backup/2026-08-19-layout-before-manifest.json`
- Modify: EasyEDA 当前原理图页 `818387edb632206a`

**Interfaces:**
- Consumes: `sys_FileManager.getDocumentSource(documentId)` 返回的完整图页源码。
- Produces: 原始源码备份、器件/网络/导线数量清单、目标区域对象 ID 清单。

- [ ] **Step 1: 读取当前窗口、工程与图页标识**

调用 `dmt_Project.getCurrentProjectInfo()` 和 `dmt_SelectControl.getCurrentDocumentInfo()`，确认当前工程为 `BOX-3 AMIC-MB 合板音频原理图`、当前图页 ID 为 `818387edb632206a`。

- [ ] **Step 2: 导出完整图页源码**

调用 `sys_FileManager.getDocumentSource("818387edb632206a")`，将返回值原样保存为重排前备份。

- [ ] **Step 3: 建立对象清单**

从源码统计组件、组件属性、导线、网络端口和网络标签数量，并列出 U1、MIC1、MIC2、R1-R12、C1-C15、D1-D4 及音频电源器件的对象 ID、坐标和网络名。

- [ ] **Step 4: 验证备份可用**

重新读取备份，校验字节长度和 SHA-256；确认对象清单中的位号无重复、U1/MIC1/MIC2 均存在。

### Task 2: 重排双麦克风模拟输入区

**Files:**
- Modify: EasyEDA 图页 `818387edb632206a`

**Interfaces:**
- Consumes: Task 1 的目标对象 ID、原坐标和网络清单。
- Produces: 左上 MIC2、左下 MIC1 两个独立且上下对称的输入功能块。

- [ ] **Step 1: 布置 MIC2 功能块**

把 MIC2 放在 U1 左上方；相关偏置、耦合、滤波和 0Ω 电阻沿信号方向从左到右排列，元件外框间距至少 30，所有文字与元件至少间隔一个网格。

- [ ] **Step 2: 整理 MIC2 导线**

把 ADC_MIC2P、ADC_MIC2N、ADC_MICBIAS2、ADC_GND 导线改为短水平线和直角转折；长连接改用现有网络端口，不新增或重命名网络。

- [ ] **Step 3: 布置 MIC1 功能块**

按 MIC2 的结构把 MIC1 放在 U1 左下方；保留 MIC1 对应元件、参数和网络，纵向间距不小于一个功能块间距 80。

- [ ] **Step 4: 整理 MIC1 导线并核对连接**

把 ADC_MIC1P、ADC_MIC1N、ADC_MICBIAS1、ADC_GND 导线改为短水平线和直角转折；检查两路输入无交叉、无文字压线、无网络串接。

### Task 3: 重排 U1 周边参考与控制区

**Files:**
- Modify: EasyEDA 图页 `818387edb632206a`

**Interfaces:**
- Consumes: U1 引脚分组和 Task 1 网络清单。
- Produces: U1 右侧分层清晰的 REF、BIAS、地址、去耦与控制连接。

- [ ] **Step 1: 固定 U1 中心位置并清理周边留白**

将 U1 置于目标区域中心，四周预留至少 80 的功能块间距；位号和型号文字放在器件边界外且互不重叠。

- [ ] **Step 2: 分行布置 REF 与 BIAS 支路**

把 ADC_REFP/REFN、ADC_REF3P4P、ADC_MICBIAS1/2 对应电容与端口按引脚高度分行放在 U1 右侧，每行独立，地符号位于支路末端。

- [ ] **Step 3: 布置地址和小信号去耦支路**

把 ADC_ADDR1、ADC_ADDR0、C13-C15 及关联器件与网络端口分开排列，确保参数值、位号和网络名完整可读。

- [ ] **Step 4: 整理 I2C/I2S/时钟网络**

把 I2C_SDA、I2C_SCL、I2S_SCLK、I2S_LRCK、I2S_ADC_SDOUT、MCLK 按 U1 引脚组分层排列，短引出后使用端口，禁止跨越模拟输入区。

### Task 4: 重排音频电源与静音控制区

**Files:**
- Modify: EasyEDA 图页 `818387edb632206a`

**Interfaces:**
- Consumes: AUD_VDD、ADC_VCC33、VCC_5V、AUD_FB、MUTE 相关网络清单。
- Produces: U1 下方独立、从左到右供电流向清晰的电源功能块。

- [ ] **Step 1: 布置输入与滤波元件**

把 VCC_5V、AUD_FB、稳压/开关器件和输入滤波放在底部一行，供电流向从左到右，电源端口与地符号位于支路两端。

- [ ] **Step 2: 布置 AUD_VDD 去耦**

把 AUD_VDD 去耦电容按对应负载分组排列，每个电容的位号、容量值和地符号不重叠；重复网络名只保留必要的可见端口。

- [ ] **Step 3: 布置静音控制支路**

把 MUTE_CLK_RAW、MUTE_CLK、MUTE_PWR、MUTE_RESET_N 与其逻辑器件、电阻和电容集中成独立小块，不压住电源区域文字。

- [ ] **Step 4: 核对电源地边界**

确认 AUD_VDD、ADC_VCC33、ADC_GND、GND、VCC_5V 未被误合并，已有 0Ω 连接关系保持不变。

### Task 5: 全图文字与几何清理

**Files:**
- Modify: EasyEDA 图页 `818387edb632206a`

**Interfaces:**
- Consumes: Tasks 2-4 的完整布局。
- Produces: 无任何元件、文字、端口或导线重叠的最终图面。

- [ ] **Step 1: 统一位号与参数值位置**

逐元件检查 `Designator` 与 `Value` 属性，放在元件上方或侧方统一位置；每段文字与其他对象至少间隔一个网格。

- [ ] **Step 2: 统一网络文字位置**

网络名沿对应短引线外侧排列；同一坐标附近出现重复名称时仅隐藏冗余显示，不删除网络属性。

- [ ] **Step 3: 清理导线几何**

删除无意义折返，确保全部为水平、垂直或直角转折；导线不穿越位号、参数值、网络名、元件本体和其他功能块。

- [ ] **Step 4: 逐块目视检查**

依次放大 MIC2、MIC1、U1 右侧和底部电源四个区域，确认无元件外框相交、无文字包围框相交、无导线穿字。

### Task 6: 保存与最终验收

**Files:**
- Modify: EasyEDA 图页 `818387edb632206a`
- Create: `规划文档/硬件参考/BOX-3设计文件/backup/2026-08-19-layout-after-manifest.json`

**Interfaces:**
- Consumes: 完成重排的图页。
- Produces: 已保存的原理图、重排后清单、视觉证据和 DRC 结果。

- [ ] **Step 1: 保存并重新读取图页**

调用 `sch_Document.save()`，再调用 `sys_FileManager.getDocumentSource("818387edb632206a")` 生成重排后清单。

- [ ] **Step 2: 对比重排前后对象与网络**

比较组件数量、位号集合、Value 集合和关键网络名集合；必须完全一致，允许变化的只有坐标、可见性和导线几何。

- [ ] **Step 3: 运行 EasyEDA DRC**

运行设计规则检查，验收结果必须为致命错误 0、错误 0、警告 0、信息 0；如新增问题，按对象 ID 定位并修复后重跑。

- [ ] **Step 4: 最终视觉复核**

截取包含完整音频区域的视图并分别检查四个功能块，确认缩放至整页时文字仍可辨，放大时无对象重叠。

- [ ] **Step 5: 保存最终状态**

再次保存图页，记录完成时间、DRC 结果与重排后清单哈希。
