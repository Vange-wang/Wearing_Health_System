"""Memory HTTP contract against fixture-only authenticated handlers."""
import json
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import pytest
from app.memory import MemoryClient


@pytest.fixture
def fixture_api():
    state = {"requests": [], "codes": [], "body": {"ok": True, "removed": 0}}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self): self.respond()
        def do_DELETE(self): self.respond()
        def respond(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state["requests"].append((self.command, self.headers.get("Authorization"), body))
            code = state["codes"].pop(0) if state["codes"] else 200 if self.headers.get("Authorization") == "Bearer fixture-only-key" else 401
            self.send_response(code)
            if code == 302: self.send_header("Location", "http://127.0.0.1:1/secret-target")
            self.end_headers()
            self.wfile.write(state["body"] if isinstance(state["body"], bytes) else json.dumps(state["body"]).encode())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try: yield f"http://127.0.0.1:{server.server_port}/api/v1/memory", state
    finally: server.shutdown(); server.server_close(); thread.join(1)


def client(tmp_path, api, key="fixture-only-key"):
    value = MemoryClient(api, tmp_path / "fixture-profile", tmp_path / "fixture-memory")
    value._api_key = key  # also allows the original adapter to run the RED handler
    return value


def test_authenticated_add_and_idempotent_existing(tmp_path, fixture_api):
    api, state = fixture_api; c = client(tmp_path, api)
    assert c.add_fact("fixture", "synthetic fact")
    state["body"] = {"ok": True, "added": False}
    assert c.add_fact("fixture", "synthetic fact")
    assert len(state["requests"]) == 2
    assert all(r[1] == "Bearer fixture-only-key" for r in state["requests"])


@pytest.mark.parametrize("method", ["add", "remove"])
def test_no_anonymous_write_when_key_missing(tmp_path, fixture_api, method):
    api, state = fixture_api; c = client(tmp_path, api, None)
    assert (c.add_fact("fixture", "synthetic") if method == "add" else c.remove_by_keyword("synthetic")) in (False, 0)
    assert not state["requests"]
    assert c.operation_result.status == "auth_unconfigured"


@pytest.mark.parametrize("code", [401, 403])
@pytest.mark.parametrize("method", ["add", "remove"])
def test_auth_rejection_one_attempt_no_secret_logs(tmp_path, fixture_api, caplog, method, code):
    api, state = fixture_api; state["codes"] = [code, code]
    c = client(tmp_path, api)
    assert not (c.add_fact("private_category", "private_fixture_fact") if method == "add"
                else c.remove_by_keyword("private_fixture_keyword"))
    assert len(state["requests"]) == 1
    assert c.operation_result.status == "auth_rejected"
    assert c.operation_result.http_status == code
    assert all(secret not in caplog.text for secret in ("fixture-only-key", "private_fixture_fact", "private_fixture_keyword", "private_category"))


@pytest.mark.parametrize("body", [b"not-json", {"ok": False}, {}, {"ok": True, "removed": -1}, {"ok": True, "removed": True}])
def test_delete_bad_response_never_invents_removal(tmp_path, fixture_api, body):
    api, state = fixture_api; state["body"] = body; c = client(tmp_path, api)
    assert c.remove_by_keyword("fixture") == 0
    assert c.operation_result.status == "invalid_response"
    assert len(state["requests"]) == 1


def test_delete_zero_is_completed_no_match(tmp_path, fixture_api):
    api, state = fixture_api; c = client(tmp_path, api)
    assert c.remove_by_keyword("fixture") == 0
    assert c.operation_result.status == "no_match"
    state["body"] = {"ok": True, "removed": 2}
    assert c.remove_by_keyword("fixture") == 2
    assert c.operation_result.status == "success"


def test_server_failure_original_two_attempt_budget(tmp_path, fixture_api, monkeypatch):
    api, state = fixture_api; state["codes"] = [500, 200]
    sleeps = []; monkeypatch.setattr("app.memory.time.sleep", sleeps.append)
    c = client(tmp_path, api)
    assert c.add_fact("fixture", "synthetic")
    assert len(state["requests"]) == 2 and sleeps == [.3]
    assert c.operation_result.attempts == 2


def test_redirect_does_not_forward_bearer(tmp_path, fixture_api):
    api, state = fixture_api; state["codes"] = [302]
    c = client(tmp_path, api)
    assert not c.add_fact("fixture", "synthetic")
    assert len(state["requests"]) == 1
    assert c.operation_result.status == "http_rejected"


def test_env_proxy_is_ignored(tmp_path, fixture_api, monkeypatch):
    api, state = fixture_api
    for name in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
        monkeypatch.setenv(name, "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", ""); monkeypatch.setenv("no_proxy", "")
    assert client(tmp_path, api).add_fact("fixture", "synthetic")
    assert len(state["requests"]) == 1


def test_nonlocal_target_rejected_before_send(tmp_path, monkeypatch):
    c = client(tmp_path, "http://example.invalid/api/v1/memory")
    def forbidden(*args, **kwargs): raise AssertionError("must not send")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    assert not c.add_fact("fixture", "synthetic")
    assert c.operation_result.status == "endpoint_invalid"


def test_constructor_injects_existing_key(tmp_path, fixture_api):
    api, state = fixture_api
    c = MemoryClient(api, tmp_path / "profile", tmp_path / "memory", api_key="fixture-only-key")
    assert c.add_fact("fixture", "synthetic")
    assert state["requests"][0][1] == "Bearer fixture-only-key"


def test_network_failure_two_attempts_no_error_repr(tmp_path, monkeypatch, caplog):
    import urllib.error
    c = client(tmp_path, "http://127.0.0.1:1/api/v1/memory")
    calls, sleeps = [], []
    def unavailable(*args, **kwargs):
        calls.append(True); raise urllib.error.URLError("fixture-only-key private_fixture_fact")
    monkeypatch.setattr(c._opener, "open", unavailable)
    monkeypatch.setattr("app.memory.time.sleep", sleeps.append)
    assert not c.add_fact("fixture", "private_fixture_fact")
    assert calls == [True, True] and sleeps == [.3]
    assert c.operation_result.status == "network_error"
    assert "fixture-only-key" not in caplog.text and "private_fixture_fact" not in caplog.text
