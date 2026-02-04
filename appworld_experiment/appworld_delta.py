"""Delta operations produced by the ACE Curator."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Literal, Optional


OperationType = Literal["ADD", "UPDATE", "TAG", "REMOVE"]


@dataclass
class DeltaOperation:
    """Single mutation to apply to the playbook."""

    type: OperationType
    section: str
    content: Optional[str] = None
    tip_id: Optional[str] = None
    scenario_tags: List[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, payload: Dict[str, object]) -> "DeltaOperation":
        return cls(
            type=str(payload["type"]),
            section=str(payload.get("section", "")),
            content=payload.get("content") and str(payload["content"]),
            tip_id=payload.get("tip_id")
            and str(payload.get("tip_id")),  # type: ignore[arg-type]
            scenario_tags=payload.get("scenario_tags", []),
        )

    def to_json(self) -> Dict[str, object]:
        data: Dict[str, object] = {"type": self.type, "section": self.section}
        if self.content is not None:
            data["content"] = self.content
        if self.tip_id is not None:
            data["tip_id"] = self.tip_id
        if self.scenario_tags:
            data["scenario_tags"] = self.scenario_tags
        return data


@dataclass
class DeltaBatch:
    """Bundle of curator reasoning and operations."""

    reasoning: str
    operations: List[DeltaOperation] = field(default_factory=list)

    @classmethod
    def from_json(cls, payload: Dict[str, object]) -> "DeltaBatch":
        ops_payload = payload.get("operations")
        operations = []
        if isinstance(ops_payload, Iterable):
            for item in ops_payload:
                if isinstance(item, dict):
                    operations.append(DeltaOperation.from_json(item))
        return cls(reasoning=str(payload.get("reasoning", "")), operations=operations)

    def to_json(self) -> Dict[str, object]:
        return {
            "reasoning": self.reasoning,
            "operations": [op.to_json() for op in self.operations],
        }
