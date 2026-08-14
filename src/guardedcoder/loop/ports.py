from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from guardedcoder.workspace.artifact import PatchArtifact

_STUB_PATCH = (
    b"diff --git a/stub.txt b/stub.txt\n"
    b"--- a/stub.txt\n"
    b"+++ b/stub.txt\n"
    b"@@ -0,0 +1 @@\n"
    b"+stub\n"
)


class PatchArtifactPort(Protocol):
    def export(self, task: object) -> PatchArtifact: ...


@dataclass(frozen=True, slots=True)
class StubPatchArtifactPort:
    over_limit: bool = False

    def export(self, task: object) -> PatchArtifact:
        del task
        return PatchArtifact(
            body=_STUB_PATCH,
            sha256=hashlib.sha256(_STUB_PATCH).hexdigest(),
            path=Path("stub.patch"),
            over_limit=self.over_limit,
        )
