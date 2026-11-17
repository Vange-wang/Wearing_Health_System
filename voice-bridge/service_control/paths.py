"""Stable project/user scope, with explicitly isolated test namespaces."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path


@dataclass(frozen=True)
class ControlPaths:
    project: Path
    state_dir: Path
    sid: str
    namespace: str = "production"

    @property
    def scope(self):
        material = f"{os.path.normcase(str(self.project.resolve()))}|{self.sid}|{self.namespace}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    @property
    def pipe(self):
        return "\\\\.\\pipe\\voice-control-" + self.scope

    @property
    def mutex(self):
        return "Local\\voice-control-" + self.scope

    @property
    def snapshot(self):
        return self.state_dir / "status.json"

    @property
    def ledger(self):
        return self.state_dir / "created.json"

    @property
    def gui(self):
        return self.state_dir / "window.json"

    @property
    def settings(self):
        return self.state_dir / "settings.json"
