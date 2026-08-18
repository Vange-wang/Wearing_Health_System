# -*- coding: utf-8 -*-
"""voicebridge.local mDNS 广播（电脑侧）

让 BOX-3 通过固定域名 http://voicebridge.local:8710 找到本机语音服务，
不再依赖写死的 IP。电脑换 WiFi / IP 变化都不影响，只要和设备同一局域网。

依赖：zeroconf（pip install zeroconf）
常驻运行，随 voice-bridge 一起启动（自启 bat 同时拉起本脚本）。
"""
import logging
import socket
import time

from zeroconf import Zeroconf, ServiceInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s mdns %(message)s")
log = logging.getLogger("mdns")

SERVICE_TYPE = "_voicebridge._tcp.local."
HOSTNAME = "voicebridge.local."
PORT = 8710
CHECK_INTERVAL_SECONDS = 5  # 网络/IP 检测间隔


def get_local_ip() -> str | None:
    """取默认路由网卡的 IP（排除 WSL 虚拟网卡 / loopback）。

    返回 None 表示网络未就绪（拿不到局域网 IP）。
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 不真正发包，只是借路由表找出对外网卡
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        if ip.startswith("127.") or ip.startswith("169.254"):
            return None
        return ip
    except OSError:
        return None
    finally:
        s.close()


def main() -> None:
    """常驻广播：循环检测局域网 IP，IP 变化时自动重新广播。

    解决两个缺陷：
    1. 开机自启时 WiFi 未就绪 → 不再 60 秒后退出，持续等待网络就绪后广播；
    2. 电脑切换 WiFi / IP 变化 → 自动 unregister 旧 IP、register 新 IP，
       设备始终能解析到当前正确的 voicebridge.local。
    """
    zc = Zeroconf()
    info: ServiceInfo | None = None
    last_ip: str | None = None
    log.info("mDNS 常驻广播启动，每 %d 秒检测一次网络", CHECK_INTERVAL_SECONDS)
    try:
        while True:
            ip = get_local_ip()
            try:
                if ip and ip != last_ip:
                    # 首次拿到 IP，或 IP 发生变化 →（重新）注册
                    if info is not None:
                        zc.unregister_service(info)
                        log.info("IP 变化 %s -> %s，重新广播", last_ip, ip)
                    info = ServiceInfo(
                        SERVICE_TYPE,
                        "voicebridge." + SERVICE_TYPE,
                        addresses=[socket.inet_aton(ip)],
                        port=PORT,
                        server=HOSTNAME,
                        properties={b"app": b"voice-bridge"},
                    )
                    zc.register_service(info)
                    log.info("广播 voicebridge.local -> %s (端口 %d)", ip, PORT)
                    last_ip = ip
                elif ip is None and last_ip is not None:
                    # 网络断开 → 撤销广播，等网络恢复后重新广播
                    log.warning("局域网 IP 丢失（网络断开），暂停 mDNS 广播")
                    if info is not None:
                        zc.unregister_service(info)
                        info = None
                    last_ip = None
            except Exception as exc:  # 网络切换瞬间 socket 可能报错，等下一轮重试
                log.warning("mDNS 广播操作异常：%s（下一轮重试）", exc)
            time.sleep(CHECK_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        log.info("收到停止信号")
    finally:
        if info is not None:
            zc.unregister_service(info)
        zc.close()


if __name__ == "__main__":
    main()
