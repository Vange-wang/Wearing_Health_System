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
    # 开机自启时 WiFi 可能未就绪（拿不到局域网 IP），等待最多 60 秒
    ip = None
    for _ in range(60):
        ip = get_local_ip()
        if ip:
            break
        time.sleep(1)
    if not ip:
        log.warning("60 秒内未拿到局域网 IP，无法广播 mDNS（设备将连不上）")
        return
    log.info("广播 voicebridge.local -> %s (端口 %d)", ip, PORT)

    zc = Zeroconf()
    info = ServiceInfo(
        SERVICE_TYPE,
        "voicebridge." + SERVICE_TYPE,
        addresses=[socket.inet_aton(ip)],
        port=PORT,
        server=HOSTNAME,
        properties={b"app": b"voice-bridge"},
    )
    try:
        zc.register_service(info)
        log.info("mDNS 广播已启动，按 Ctrl+C 停止")
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        log.info("收到停止信号")
    finally:
        zc.unregister_service(info)
        zc.close()


if __name__ == "__main__":
    main()
