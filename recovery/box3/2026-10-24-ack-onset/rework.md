# ACK候选v2：P1局部返工

仅修独立复核01唯一P1：真实会话失效后，下一帧写拒绝被误报overflow并取消ACK。v1完整保留，manifest各成员重新核验未变。四源白名单不扩；相对v1只修改voice_agent.c及voice_v2_runtime.inc，wake_engine.c/.h逐字不变。实装四源仍与before相同。

## 修正

- 真实v2_invalidate_session接收调用generation，并匹配当前generation、turn、session、origin后退休该轮输入及撤销registered；立即generation-checked stop_capture。没有延后会话失效，没有继续假装写入成功，没有释放ACK、duplex或TX。
- 新增锁内retired_generation标记（uint32_t，4 bytes）。重注册不能复活旧轮；新代允许重新绑定，旧代失效回调不能退休当前轮。
- v2_capture_write返回bool及本次拒绝原因。失效/旧代拒绝只退休输入；实际append失败仍走原overflow/cancel。分类与append处于同一锁内，避免随后发生的网络变化把已观察到的容量失败重新归类。正常写入仍用原V2槽。
- 原ACK自然完成/上传调用人等待清理、真正取消与满载行为保留。新增音频存储0 bytes；相对v1仅4 bytes静态控制数据和少量局部bool/输出指针。目标ABI栈、首字开销仍未测。

## 最小复验

已读取独立最终报告，确认只有该P1，无扩大修复范围。

1. 在v2测试目录用v1同源复制体运行独立focused_failure反例，原样得到 wake_cancelled=1，证据independent-reproduced-v1.json。
2. 真实失效函数现纳入11段逐字生产函数提取；VF_INVALIDATE不再为空。原反例相同条件得到：registered=0、ack_protected=1、ack_lease_held=1、next_capture_accepted=0、wake_cancelled=0，并严格断言capture已停止、ACK保护/租约仍在。只把缺陷断言改为要求正确行为，未放宽输入拒绝与资源保护断言。
3. 普通及VOICE_V2_FAILURE_DIAGNOSTICS两分支均编译/执行通过；failure-matrix.json四项结果为exit0，编译stderr空。
4. 实际v2_voice_round接缝复验：上传早于ACK完成、完整400ms样本、回复晚于ACK、网络失败不误取消ACK、取消等待不盗租约、真正V2满载仍明确取消；新增同代退休、重注册仍拒绝旧输入、新代可写、旧代失效与写入不影响新capture，均通过。
5. wake_engine及双工源/测试未改，其已通过的24项状态回归、onset及mic_ref用例作为逐字相同影响集的继承证据保留，未声称重新执行。没有重做无关材料。

诊断分支首次测试因日志替身不消费参数触发-Werror；修正替身消费参数后通过，未改生产逻辑或放宽警告。最终证据以failure-matrix.json为准，较早单次结果只作过程记录。

## 工件与边界

source-map.json：实装before/v1/v2映射；v1-to-v2.diff：局部返工；candidate.diff：实装到v2完整差异。tests/extract_slices.py生成生产原文接缝，tests/run_failure_matrix.py为最小复验入口。测试仍替换平台、网络传输和声学算法边界，证明实际C状态链与租约规则，不证明ESP抢占时序或真人效果。

状态：P1_HOST_COUNTEREXAMPLE_GREEN / INDEPENDENT_RECHECK_PENDING / TARGET_NOT_RUN / FIRST_WORD_OPEN。未投影SDK、构建ESP、刷写、COM、操作服务；没有设备首字不劣化证据，不能宣布完成或正式交付。
