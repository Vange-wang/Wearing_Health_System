"""Selected physical-interface advertising with explicit old-ad removal."""
import json
import logging
import socket
import subprocess
from .checks import choose_lan
from .processes import adapters

logger = logging.getLogger("voice-control.mdns")


def advertise(paths, stop):
    from zeroconf import Zeroconf, ServiceInfo
    zc = info = old_address = None
    try:
        while not stop.is_set():
            try:
                selection=json.loads(paths.settings.read_text(encoding="utf-8")).get("interface_index")
                if type(selection) is not int:selection=None
            except (OSError,ValueError,AttributeError):selection=None
            try:
                selected=choose_lan(adapters(),selection)
                address=selected.get("selected",{}).get("address")
            except subprocess.TimeoutExpired:
                # A transient native query timeout says nothing about whether
                # the previously advertised physical interface disappeared.
                # Keep that advertisement; never convert this into readiness.
                logger.warning("mdns transient failure stage=adapters category=TimeoutExpired")
                stop.wait(5)
                continue
            except (OSError,ValueError):address=None
            if address != old_address:
                if zc is not None:
                    try:
                        if info is not None:zc.unregister_service(info)
                    finally:zc.close()
                    zc=info=None
                old_address=None
                if address:
                    zc=Zeroconf(interfaces=[address])
                    info=ServiceInfo("_voicebridge._tcp.local.","voicebridge._voicebridge._tcp.local.",
                                     addresses=[socket.inet_aton(address)],port=8710,server="voicebridge.local.",
                                     properties={b"app":b"voice-bridge"})
                    zc.register_service(info);old_address=address
            stop.wait(5)  # original mDNS network-change cadence; no voice dependency
    finally:
        if zc is not None:
            try:
                if info is not None:zc.unregister_service(info)
            finally:zc.close()
