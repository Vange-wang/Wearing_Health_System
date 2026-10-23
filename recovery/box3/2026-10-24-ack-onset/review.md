# ACK候选v2 独立定向复核02

**PASS_FOR_INCREMENTAL_BUILD_AND_CONTROLLED_VALIDATION。唯一P1已闭合，未发现此次局部修复及相邻错误分类路径的新阻断项。Root可进入具名增量SDK构建，构建通过后按既定权限开展受控实机验证。** 此结论不是正式交付、收音真人通过或首字不劣化证明。

manifest SHA256：94a6bbbcf29e365ae231960e625ff422744b0adff1ac493293125fd18814ddfb。本轮仅P1和相邻代际/分类，不重开全方案。

## 完整性

v1/v2清单全部成员前后匹配，四份SDK当前源仍等于before；v1→v2局部diff重建一致，仅voice_agent.c和voice_v2_runtime.inc改变。wake_engine.c/.h和原onset/24项状态回归主体未修改，沿用上一轮已复跑证据，不宣称本轮重跑。所有复验在本目录replay副本，四源逐字等于固定v2；11段生产函数重新提取结果与封存production_slices.inc一致。固定候选与运行源未改。

## P1与相邻路径

- v2_invalidate_session保留真实副作用，校验generation、turn、session、origin后设置retired_generation并撤销registered，再通过generation-checked stop_capture退休输入；没有延后或吞掉网络失败，没有释放ACK播放权/duplex/TX。
- write_capture_checked区分输入退休与实际append失败。前者停止该代捕获、返回失败而不报overflow；后者仍调用原捕获溢出取消。append及本次分类在同一s_v2_lock内，之后的网络变化不重新分类已返回的append失败。
- 同代重注册仍不能复活已退休输入；新代可正常绑定。旧代invalidate必须先满足当前generation/turn身份；旧退休代写拒绝且generation-checked停止不影响新capture。
- 原ACK完整播放保护、正式回复获取自身租约、输入提前上传与等待ACK清理的结构保留；本次未改唤醒/近端门、60秒或音频缓存。

独立执行tests/run_failure_matrix.py共4种编译/执行组合（focused_failure/runtime_seam × 普通/VOICE_V2_FAILURE_DIAGNOSTICS），全部compile exit0、运行exit0、编译stderr空。真实失效反例两个分支均得到：

registered=0 ack_protected=1 ack_lease_held=1 next_capture_accepted=0 wake_cancelled=0

并断言捕获已停止、ACK保护与租约仍在。实际runtime接缝还通过：上传先于ACK完成、400ms完整PCM、回复晚于ACK、上传失败延后清理、取消不盗租约、完成/重复近端不重复移交、真实V2容量仍取消、同代恢复继续退休、新代可输入及旧代回调不影响新capture。

测试使用实际invalidate及11段生产函数、真实audio_session/V2 capture；平台/transport/播放器仍为替身，不是ESP抢占或真实声学测试。静态锁内错误分类与测试互为补充，不夸称遍历全部并发时序。

## 资源及下一门

相对v1新增uint32_t退休代次4字节静态控制量，少量局部bool/输出参数；新增音频缓存0。普通输入路径增加锁内可用性/退休标记检查；目标map、线程栈高水位、ACK/AEC/上传竞争成本未实测。

首次上传提前是结构收益，不能替代用户开口到声学首字的测量。SDK构建后受控验证应检查ACK完整与早失败、重叠句首、普通句回归、真实容量/取消、目标栈余量和首字时序；未测不能标PASS或正式宣布收音优化完成。仍须保留当前可用回退，不顺便变更发现/网络、PC、BLE、字幕或阈值。

本轮无SDK构建、COM/设备、服务/API、凭据或运行状态操作。必要复验已完成，转下一门，不继续扩大审查。
