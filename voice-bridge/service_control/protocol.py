"""Strict, bounded local management commands. No executable payloads."""
import json
import re

MAX_REQUEST_BYTES = 4096
COMMANDS = frozenset({"ensure", "status", "retry", "stop"})


class ProtocolError(ValueError):
    pass


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate field")
        result[key] = value
    return result


def parse_request(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_REQUEST_BYTES:
        raise ProtocolError("request size")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_object)
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ProtocolError("invalid UTF-8/JSON") from error
    if not isinstance(value, dict) or set(value) != {"schema_version", "request_id", "command"}:
        raise ProtocolError("request fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ProtocolError("schema version")
    if not isinstance(value["request_id"], str) or not re.fullmatch(r"[A-Za-z0-9-]{1,64}", value["request_id"]):
        raise ProtocolError("request ID")
    if not isinstance(value["command"], str) or value["command"] not in COMMANDS:
        raise ProtocolError("command")
    return value


def encode_request(request_id, command):
    raw = json.dumps({"schema_version": 1, "request_id": request_id, "command": command}, separators=(",", ":")).encode("utf-8")
    parse_request(raw)
    return raw
