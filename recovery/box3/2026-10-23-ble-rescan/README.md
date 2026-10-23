# BOX3 蓝牙恢复：实装验证 2026-10-23

用户批准刷入后，应用2cbeb954...已写入并校验成功。BOX3启动先直连保存地址，超时rc13后走原退避并重新扫描；扫描命中、保存发现地址、连接成功、发现综合服务及特征、订阅完成、接收帧及上传成功均有同轮设备日志。由此确认蓝牙连接和数据传输恢复。

语音源码及其他main文件与修改前哈希一致，启动实读阈值0.620，语音服务重新注册成功；PC配置和检测器固件未改。用户的实际语音健康查询与有效测量尚待反馈，不将初始化就绪等同真人验收。

配套源码和固件：5b83d13a5d3909523860b696148c22e7b949cf9a。当前工件recovery/box3/2026-10-23-ble-rescan/voice_agent.bin；旧工件recovery/box3/2026-10-21-wake-threshold/voice_agent.bin。安装日志见同目录installation-receipt.json；验证见installed-validation.json。Git记录不含测量值或原始声音。
