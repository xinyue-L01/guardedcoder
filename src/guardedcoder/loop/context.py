from __future__ import annotations

from collections.abc import Sequence

from guardedcoder.models.envelope import Envelope
from guardedcoder.models.task import TaskBudget
from guardedcoder.security.redact import redact_text


def build_context(
    *,
    task_description: str,
    envelope: Envelope,
    budget: TaskBudget,
    observations: Sequence[object] = (),
    memories: Sequence[object] = (),
) -> list[dict[str, str]]:
    system = redact_text(
        "Reply with one JSON object for a single tool action or finish."
    )
    parts = [
        redact_text(task_description),
        (
            f"read_paths={list(envelope.read_paths)} "
            f"write_paths={list(envelope.write_paths)} "
            f"max_steps={envelope.max_steps}"
        ),
        f"remaining_steps={budget.remaining_steps}",
    ]
    for memory in memories:
        content = redact_text(str(getattr(memory, "content", memory)))
        label = getattr(memory, "trust_label", "")
        parts.append(f"memory[{label}]: {content}" if label else f"memory: {content}")
    for item in observations:
        body = getattr(item, "body", None)
        if body is None:
            body = getattr(item, "stdout", item)
        parts.append(f"observation: {redact_text(str(body))}")
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": redact_text("\n".join(parts))},
    ]
