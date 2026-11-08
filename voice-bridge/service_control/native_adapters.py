"""Read-only IPv4 adapters via IP Helper, without CIM or PowerShell.

ABI: Microsoft IP_ADAPTER_ADDRESSES / IP_ADAPTER_UNICAST_ADDRESS / MIB_IF_ROW2.
No configuration changes, socket creation, SSID, physical-address logging or fallback.
"""
import ctypes as C
from ctypes import wintypes as W
import ipaddress
import socket


class GUID(C.Structure):
    _fields_ = [("a", W.ULONG), ("b", W.USHORT), ("c", W.USHORT), ("d", W.BYTE * 8)]


class IF_ROW(C.Structure):
    _fields_ = [
        ("InterfaceLuid", C.c_ulonglong), ("InterfaceIndex", W.ULONG),
        ("InterfaceGuid", GUID), ("Alias", W.WCHAR * 257), ("Description", W.WCHAR * 257),
        ("PhysicalAddressLength", W.ULONG), ("PhysicalAddress", W.BYTE * 32),
        ("PermanentPhysicalAddress", W.BYTE * 32), ("Mtu", W.ULONG), ("Type", W.ULONG),
        ("TunnelType", C.c_int), ("MediaType", C.c_int), ("PhysicalMediumType", C.c_int),
        ("AccessType", C.c_int), ("DirectionType", C.c_int), ("Flags", W.BYTE),
        ("OperStatus", C.c_int), ("AdminStatus", C.c_int), ("MediaConnectState", C.c_int),
        ("NetworkGuid", GUID), ("ConnectionType", C.c_int),
    ] + [(name, C.c_ulonglong) for name in (
        "TransmitLinkSpeed", "ReceiveLinkSpeed", "InOctets", "InUcastPkts", "InNUcastPkts",
        "InDiscards", "InErrors", "InUnknownProtos", "InUcastOctets", "InMulticastOctets",
        "InBroadcastOctets", "OutOctets", "OutUcastPkts", "OutNUcastPkts", "OutDiscards",
        "OutErrors", "OutUcastOctets", "OutMulticastOctets", "OutBroadcastOctets", "OutQLen",
    )]


class ADAPTER_PREFIX(C.Structure):
    _fields_ = [("Length", W.ULONG), ("IfIndex", W.ULONG), ("Next", C.c_void_p),
                ("AdapterName", C.c_void_p), ("FirstUnicast", C.c_void_p)]


class SOCKET_ADDRESS(C.Structure):
    _fields_ = [("address", C.c_void_p), ("length", C.c_int)]


class UNICAST_PREFIX(C.Structure):
    _fields_ = [("Length", W.ULONG), ("Flags", W.ULONG), ("Next", C.c_void_p),
                ("Address", SOCKET_ADDRESS), ("PrefixOrigin", C.c_int),
                ("SuffixOrigin", C.c_int), ("DadState", C.c_int),
                ("ValidLifetime",W.ULONG),("PreferredLifetime",W.ULONG),
                ("LeaseLifetime",W.ULONG),("OnLinkPrefixLength",W.BYTE)]


def physical_up(row):
    # HardwareInterface + ConnectorPresent, not Filter/Endpoint/Paused/LowPower;
    # require Ethernet or WLAN and an authenticated, media-connected up interface.
    return (row.Type in (6, 71) and row.TunnelType == 0 and row.OperStatus == 1
            and row.AdminStatus == 1 and row.MediaConnectState == 1
            and row.Flags & 0x05 == 0x05 and row.Flags & 0xFA == 0)


def _inside(buffer, address, length):
    start = C.addressof(buffer)
    if not address or length < 0 or not start <= address <= start + C.sizeof(buffer) - length:
        raise ValueError("native adapter pointer outside response")
    return address


def _chain(buffer, address, cls):
    visited = set()
    while address:
        if address in visited or len(visited) >= 4096:
            raise ValueError("native adapter chain invalid")
        visited.add(address)
        value = cls.from_address(_inside(buffer, address, C.sizeof(cls)))
        if value.Length < C.sizeof(cls):
            raise ValueError("native adapter structure version invalid")
        _inside(buffer, address, value.Length)
        yield value
        address = value.Next


def adapters():
    if C.sizeof(W.ULONG) != 4 or C.sizeof(W.WCHAR) != 2 or C.sizeof(IF_ROW) != 1352:
        raise OSError("native adapter ABI unavailable")
    library = C.WinDLL("iphlpapi", use_last_error=True)
    get = library.GetAdaptersAddresses
    get.argtypes = [W.ULONG, W.ULONG, C.c_void_p, C.c_void_p, C.POINTER(W.ULONG)]
    get.restype = W.ULONG
    get_row = library.GetIfEntry2
    get_row.argtypes = [C.POINTER(IF_ROW)]
    get_row.restype = W.ULONG
    size = W.ULONG(15360)
    for attempt in range(3):
        if not 1 <= size.value <= 4 * 1024 * 1024:
            raise OSError("native adapter response exceeds bound")
        buffer = C.create_string_buffer(size.value)
        code = get(socket.AF_INET, 0x2E, None, buffer, C.byref(size))
        if code == 111:  # ERROR_BUFFER_OVERFLOW: topology changed or more adapters.
            continue
        if code == 232:  # ERROR_NO_DATA: no IPv4 adapters.
            return []
        if code:
            raise OSError("native adapter query failed")
        break
    else:
        raise OSError("native adapter topology changed repeatedly")
    output = []
    for adapter in _chain(buffer, C.addressof(buffer), ADAPTER_PREFIX):
        if not adapter.IfIndex:
            continue
        row = IF_ROW()
        row.InterfaceIndex = adapter.IfIndex
        if get_row(C.byref(row)) or row.InterfaceIndex != adapter.IfIndex:
            raise OSError("native adapter identity unavailable")
        if not physical_up(row):
            continue
        for unicast in _chain(buffer, adapter.FirstUnicast, UNICAST_PREFIX):
            if unicast.DadState != 4:  # IpDadStatePreferred
                continue
            if unicast.Address.length < 16:
                raise ValueError("native IPv4 address truncated")
            address = _inside(buffer, unicast.Address.address, unicast.Address.length)
            raw = C.string_at(address, 16)
            if int.from_bytes(raw[:2], "little") != socket.AF_INET:
                continue
            ip = ipaddress.IPv4Address(raw[4:8])
            if ip.is_loopback or ip.is_link_local or ip.is_unspecified or ip.is_multicast:
                continue
            if unicast.OnLinkPrefixLength>32:raise ValueError('native IPv4 prefix invalid')
            output.append(dict(index=int(adapter.IfIndex), address=str(ip), prefix_length=int(unicast.OnLinkPrefixLength), name=row.Alias,
                               description=row.Description, physical=True, up=True))
    return output
