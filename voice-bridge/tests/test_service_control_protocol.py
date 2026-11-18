import json
import pytest
from service_control.protocol import ProtocolError, encode_request, parse_request


@pytest.mark.parametrize("command", ["ensure", "status", "retry", "stop"])
def test_fixed_commands(command):
    assert parse_request(encode_request("a-123", command))["command"] == command


@pytest.mark.parametrize("identifier", ["", "a"*65, "命令", "x_y", "../x", "x\n"])
def test_request_id_boundary(identifier):
    with pytest.raises(ProtocolError): encode_request(identifier, "ensure")


@pytest.mark.parametrize("identifier", ["x", "a"*64])
def test_request_id_valid_boundary(identifier):
    assert parse_request(encode_request(identifier, "ensure"))["request_id"] == identifier


@pytest.mark.parametrize("raw", [b"", b"x"*4097, b"\xff", b"{", b"null", b"[]",
    b'{"schema_version":1,"schema_version":1,"request_id":"a","command":"ensure"}',
    b'{"schema_version":true,"request_id":"a","command":"ensure"}',
    b'{"schema_version":2,"request_id":"a","command":"ensure"}',
    b'{"schema_version":1,"request_id":"a","command":"shell"}',
    b'{"schema_version":1,"request_id":"a","command":"ensure","path":"cmd.exe"}',
    b'{"schema_version":1,"command":"ensure"}'])
def test_malformed_has_no_dispatchable_command(raw):
    with pytest.raises(ProtocolError): parse_request(raw)


def test_4096_still_requires_valid_schema():
    raw = encode_request("id", "ensure")
    assert parse_request(raw + b" "*(4096-len(raw)))["command"] == "ensure"
    with pytest.raises(ProtocolError): parse_request(b"x"*4096)
