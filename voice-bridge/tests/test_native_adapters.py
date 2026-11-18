import ast
import ctypes as C
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from service_control import native_adapters as m


def physical(**changes):
    values = dict(Type=71, TunnelType=0, OperStatus=1, AdminStatus=1,
                  MediaConnectState=1, Flags=5)
    values.update(changes)
    return m.physical_up(NS(**values))


@pytest.mark.parametrize("changes", [{"Type": 131}, {"Flags": 0}, {"Flags": 7},
    {"Flags": 13}, {"Flags": 21}, {"Flags": 37}, {"Flags": 69}, {"Flags": 133},
    {"OperStatus": 2}, {"AdminStatus": 2}, {"MediaConnectState": 2}, {"TunnelType": 1}])
def test_virtual_disconnected_or_unknown_never_physical(changes):
    assert not physical(**changes)


def test_wlan_and_ethernet_need_real_hardware_flags():
    assert physical() and physical(Type=6)
    assert not physical(Type=6, Flags=0)


def test_bad_pointer_and_cycle_fail_closed():
    buffer = C.create_string_buffer(256)
    with pytest.raises(ValueError): m._inside(buffer, C.addressof(buffer) - 1, 16)
    with pytest.raises(ValueError): m._inside(buffer, C.addressof(buffer) + 250, 16)
    node = m.ADAPTER_PREFIX.from_buffer(buffer)
    node.Length = C.sizeof(node)
    node.Next = C.addressof(buffer)
    with pytest.raises(ValueError): list(m._chain(buffer, C.addressof(buffer), m.ADAPTER_PREFIX))


def test_wrong_structure_length_fails_closed():
    buffer = C.create_string_buffer(256)
    node = m.ADAPTER_PREFIX.from_buffer(buffer)
    node.Length = 1
    with pytest.raises(ValueError): list(m._chain(buffer, C.addressof(buffer), m.ADAPTER_PREFIX))


def test_native_error_never_falls_back_to_cim(monkeypatch):
    class Function:
        def __call__(self, *args): return 5
    monkeypatch.setattr(m.C, "WinDLL", lambda *a, **kw: NS(GetAdaptersAddresses=Function(), GetIfEntry2=Function()))
    with pytest.raises(OSError, match="query failed"): m.adapters()


def test_no_mutating_or_network_calls():
    source = Path(m.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"Popen", "run", "connect", "send", "sendto", "socket", "SetIfEntry", "SetIpInterfaceEntry"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden
    assert C.sizeof(m.IF_ROW) == 1352
