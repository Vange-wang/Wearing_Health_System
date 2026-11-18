"""Fake-only publisher lifecycle; never opens sockets or executes native queries."""
import subprocess
from types import SimpleNamespace as NS
import sys

import pytest

from service_control import discovery


@pytest.mark.parametrize("first_timeout", [False, True])
def test_timeout_keeps_publisher_and_next_query_recovers(monkeypatch, caplog, first_timeout):
    calls = []
    class Stop:
        count = 0
        def is_set(self): return self.count >= 3
        def wait(self, seconds):
            assert seconds == 5
            calls.append("wait")
            self.count += 1
    stop = Stop()
    class ZC:
        def __init__(self, **kwargs): calls.append("create")
        def register_service(self, info): calls.append("register")
        def unregister_service(self, info): calls.append("unregister")
        def close(self): calls.append("close")
    monkeypatch.setitem(sys.modules, "zeroconf", NS(Zeroconf=ZC, ServiceInfo=lambda *a, **kw: object()))
    def adapters():
        if stop.count == (0 if first_timeout else 1):
            raise subprocess.TimeoutExpired(["private-argument-omitted"], 8)
        return []
    monkeypatch.setattr(discovery, "adapters", adapters)
    monkeypatch.setattr(discovery, "choose_lan", lambda *a: {"selected": {"address": "192.0.2.3"}})
    class Settings:
        def read_text(self, **kwargs): return "{}"
    discovery.advertise(NS(settings=Settings()), stop)
    assert calls.count("create") == calls.count("register") == 1
    assert calls[-2:] == ["unregister", "close"]
    assert "private-argument-omitted" not in caplog.text
    assert "stage=adapters category=TimeoutExpired" in caplog.text
    if not first_timeout:
        assert calls == ["create", "register", "wait", "wait", "wait", "unregister", "close"]


def test_unrelated_identity_exception_is_not_swallowed(monkeypatch):
    monkeypatch.setitem(sys.modules, "zeroconf", NS(Zeroconf=lambda **kw: pytest.fail("no sockets"), ServiceInfo=object))
    class Settings:
        def read_text(self, **kw): return "{}"
    def denied(): raise RuntimeError("identity verification failed")
    monkeypatch.setattr(discovery, "adapters", denied)
    with pytest.raises(RuntimeError):
        discovery.advertise(NS(settings=Settings()), NS(is_set=lambda: False))
