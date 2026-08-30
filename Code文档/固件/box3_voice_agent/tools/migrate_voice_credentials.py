"""One-time migration of legacy BOX-3 WiFi credentials to ignored local JSON."""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tempfile
from typing import Callable, NamedTuple


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "examples" / "voice_agent" / "main" / "voice_agent.c"
DEFAULT_OUTPUT = ROOT / "voice_agent.local.json"


class MigrationError(RuntimeError):
    """The legacy source could not be migrated without risking data loss."""


class MigrationResult(NamedTuple):
    wifi_count: int
    output_path: Path


_BLOCK_PATTERN = re.compile(
    r"DEFAULT_WIFI_CREDS\s*\[[^\]]*\]\s*=\s*\{(?P<body>.*?)\};",
    re.DOTALL,
)
_STRING = r'"(?:\\.|[^"\\])*"'
_NUMBER = r"(?:0[xX][0-9A-Fa-f]+|[0-9]+)"
_AUTH_VALUE = rf"(?:{_NUMBER}|[A-Za-z_]\w*)"
_ENTRY_PATTERN = re.compile(
    rf"\{{\s*(?P<ssid>{_STRING})\s*,\s*"
    rf"(?P<password>{_STRING})\s*,\s*"
    rf"(?P<priority>{_NUMBER})\s*,\s*"
    rf"(?P<auth_type>{_AUTH_VALUE})\s*\}}"
)


def _resolve_auth_type(source_text: str, value: str) -> int:
    if re.fullmatch(_NUMBER, value):
        return int(value, 0)
    definition = re.search(
        rf"^\s*#define\s+{re.escape(value)}\s+(?P<number>{_NUMBER})\b",
        source_text,
        re.MULTILINE,
    )
    if definition is None:
        raise MigrationError("legacy auth_type macro is not a numeric definition")
    return int(definition.group("number"), 0)


def parse_legacy_credentials(source_text: str) -> list[dict[str, object]]:
    block = _BLOCK_PATTERN.search(source_text)
    if block is None:
        raise MigrationError("DEFAULT_WIFI_CREDS block not found")

    credentials = []
    for match in _ENTRY_PATTERN.finditer(block.group("body")):
        credentials.append(
            {
                "ssid": ast.literal_eval(match.group("ssid")),
                "password": ast.literal_eval(match.group("password")),
                "priority": int(match.group("priority"), 0),
                "auth_type": _resolve_auth_type(
                    source_text, match.group("auth_type")
                ),
            }
        )
    if not 1 <= len(credentials) <= 8:
        raise MigrationError("legacy credential count must be between 1 and 8")
    return credentials


def set_current_user_only_acl(path: Path) -> None:
    identity_result = subprocess.run(
        ["whoami"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    identity = identity_result.stdout.strip()
    if identity_result.returncode != 0 or not identity:
        raise MigrationError("unable to determine current Windows identity")
    acl_result = subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"{identity}:F"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if acl_result.returncode != 0:
        raise MigrationError("unable to restrict local config ACL")


def migrate_credentials(
    source_path: Path,
    output_path: Path,
    *,
    token_factory: Callable[[], str] = lambda: secrets.token_urlsafe(32),
    acl_setter: Callable[[Path], None] = set_current_user_only_acl,
) -> MigrationResult:
    source = Path(source_path)
    output = Path(output_path)
    if output.exists():
        raise MigrationError("local config already exists; refusing to overwrite")

    try:
        source_text = source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MigrationError("unable to read legacy source") from exc
    credentials = parse_legacy_credentials(source_text)
    token = token_factory()
    if not isinstance(token, str) or not token:
        raise MigrationError("token generator returned an empty value")

    payload = {"wifi": credentials, "device_token": token}
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        descriptor, temp_name = tempfile.mkstemp(
            prefix=".voice-agent-local-", suffix=".tmp", dir=output.parent
        )
        temp_path = Path(temp_name)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        acl_setter(temp_path)
        os.replace(temp_path, output)
        temp_path = None
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise

    return MigrationResult(wifi_count=len(credentials), output_path=output)


def source_is_clean(source_path: Path) -> bool:
    try:
        text = Path(source_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise MigrationError("unable to read source for credential check") from exc
    markers = ("DEFAULT_WIFI_CREDS", "WIFI_PASS", "WIFI_SSID")
    return not any(marker in text for marker in markers)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check-source-clean", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        if args.check_source_clean:
            clean = source_is_clean(args.source)
            print(f"source credential markers: {'absent' if clean else 'present'}")
            return 0 if clean else 1
        result = migrate_credentials(args.source, args.output)
    except MigrationError as exc:
        print(f"migration failed: {exc}")
        return 1
    print(f"migration complete: wifi_entries={result.wifi_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
