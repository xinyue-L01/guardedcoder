from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

SCHEMA_VERSION = "1"


def compute_fingerprint(
    *,
    schema_version: str,
    task_id: str,
    envelope_hash: str,
    base_commit: str,
    worktree_identity: str,
    normalized_action: Mapping[str, Any],
) -> str:
    payload = {
        "schema_version": schema_version,
        "task_id": task_id,
        "envelope_hash": envelope_hash,
        "base_commit": base_commit,
        "worktree_identity": worktree_identity,
        "normalized_action": normalized_action,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
