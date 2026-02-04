"""Playbook storage and mutation logic for ACE."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional
import logging

from .appworld_delta import DeltaBatch, DeltaOperation
from .appworld_deduplication import OllamaDeduplicator


@dataclass
class Tip:
    """Single playbook entry."""

    id: str
    section: str
    content: str
    scenario_tags: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def apply_tags(self, tags: List[str]) -> None:
        for tag in tags:
            # tag should be unique
            if tag in self.scenario_tags:
                logging.warning(f"Tag {tag} already exists for bullet {self.id}")
                continue
            self.scenario_tags.append(tag)


class Playbook:
    """Structured context store as defined by ACE."""

    def __init__(self) -> None:
        self._tips: Dict[str, Tip] = {}
        self._sections: Dict[str, List[str]] = {}
        self._next_id = 0

    # ------------------------------------------------------------------ #
    # CRUD utils
    # ------------------------------------------------------------------ #
    def add_tip(
        self,
        section: str,
        content: str,
        tip_id: Optional[str] = None,
        scenario_tags: Optional[List[str]] = None,
    ) -> None :
        # Valid tip_id, if not provided or unvalid, generate a new one
        tip_id = tip_id if tip_id is not None and tip_id not in self._tips else self._generate_id(section)

        # apply metadata and save tip
        scenario_tags = scenario_tags or []
        tip = Tip(id=tip_id, section=section, content=content, scenario_tags=scenario_tags)
        self._tips[tip_id] = tip
        self._sections.setdefault(section, []).append(tip_id)

    def update_tip(
        self,
        tip_id: str,
        *,
        content: Optional[str] = None,
        scenario_tags: Optional[List[str]] = None,
    ) -> None:
        # if tip not found, return None
        tip = self._tips.get(tip_id)
        if tip is None:
            return

        # update content if provided
        if content is not None:
            tip.content = content

        # update tags if provided
        if scenario_tags is not None:
            tip.apply_tags(scenario_tags)

        # update timestamp
        tip.updated_at = datetime.now(timezone.utc).isoformat()

    def tag_tip(self, tip_id: str, tags: List[str]) -> None:
        # if tip not found, return None
        tip = self._tips.get(tip_id)
        if tip is None:
            return

        # apply tags
        tip.apply_tags(tags)

    def remove_tip(self, tip_id: str) -> None:
        # if tip not found, return None, else remove tip
        tip = self._tips.pop(tip_id, None)
        if tip is None:
            return
        
        # remove tip from section
        section_list = self._sections.get(tip.section)
        if section_list:
            self._sections[tip.section] = [
                id for id in section_list if id != tip_id
            ]
            # if section is empty, remove it
            if not self._sections[tip.section]:
                del self._sections[tip.section]

    def get_tip(self, tip_id: str) -> Optional[Tip]:
        return self._tips.get(tip_id)

    def tips(self) -> List[Tip]:
        return list(self._tips.values())

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, object]:
        return {
            "tips": {tip_id: asdict(tip) for tip_id, tip in self._tips.items()},
            "sections": self._sections,
            "next_id": self._next_id,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "Playbook":
        instance = cls()
        tips_payload = payload.get("tips", {})
        if isinstance(tips_payload, dict):
            for tip_id, tip_value in tips_payload.items():
                if isinstance(tip_value, dict):
                    instance._tips[tip_id] = Tip(**tip_value)
        sections_payload = payload.get("sections", {})
        if isinstance(sections_payload, dict):
            instance._sections = {
                section: list(ids) if isinstance(ids, Iterable) else []
                for section, ids in sections_payload.items()
            }
        instance._next_id = int(payload.get("next_id", 0))
        return instance

    def dumps(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def loads(cls, data: str) -> "Playbook":
        payload = json.loads(data)
        if not isinstance(payload, dict):
            raise ValueError("Playbook serialization must be a JSON object.")
        return cls.from_dict(payload)

    # ------------------------------------------------------------------ #
    # Delta application
    # ------------------------------------------------------------------ #
    def apply_delta(self, delta: DeltaBatch) -> None:
        for operation in delta.operations:
            self._apply_operation(operation)
        # TODO: Thinking harmful tag necessity
        # # drop out harmful tips after applying delta
        # self.drop_out_harmful()

    def _apply_operation(self, operation: DeltaOperation) -> None:
        op_type = operation.type.upper()
        if op_type == "ADD":
            self.add_tip(
                section=operation.section,
                content=operation.content or "",
                tip_id=operation.tip_id,
                scenario_tags=operation.scenario_tags,
            )
        elif op_type == "UPDATE":
            if operation.tip_id is None:
                return
            self.update_tip(
                operation.tip_id,
                content=operation.content,
                scenario_tags=operation.scenario_tags,
            )
        elif op_type == "TAG":
            if operation.tip_id is None:
                return
            self.tag_tip(operation.tip_id, operation.scenario_tags)
        elif op_type == "REMOVE":
            if operation.tip_id is None:
                return
            self.remove_tip(operation.tip_id)

    # TODO: if harmful tag is not necessary, remove it
    # def drop_out_harmful(self, threshold: int = 3) -> None:
    #     """
    #     Removes bullets tagged as harmful above a certain threshold.

    #     Args:
    #         threshold: The harmful tag count threshold.
    #     Returns:
    #         None
    #     """
    #     removed_ids = [
    #         bullet_id
    #         for bullet_id, bullet in self._tips.items()
    #         if bullet.harmful >= threshold
    #     ]
    #     for bullet_id in removed_ids:
    #         self.remove_tip(bullet_id)

    def deduplicate(self, deduplicator: OllamaDeduplicator, tip_ids: List[str]) -> List[str]:
        """
        Finds and removes duplicate tips from the playbook.

        Args:
            deduplicator: The Deduplicator instance.
            tip_ids: A list of new tip IDs to check for duplicates.

        Returns:
            A list of tip IDs that were removed.
        """
        new_tips = {
            tip_id: self._tips[tip_id].content
            for tip_id in tip_ids
            if tip_id in self._tips
        }
        existing_tips = {
            tip_id: tip.content
            for tip_id, tip in self._tips.items()
            if tip_id not in new_tips
        }

        duplicate_ids = deduplicator.find_duplicates(new_tips, existing_tips)

        for tip_id in duplicate_ids:
            self.remove_tip(tip_id)

        return duplicate_ids

    # ------------------------------------------------------------------ #
    # Presentation helpers
    # ------------------------------------------------------------------ #
    def as_prompt(self) -> str:
        """Return a human-readable playbook string for prompting LLMs."""
        parts: List[str] = []
        for section, tip_ids in sorted(self._sections.items()):
            for tip_id in tip_ids:
                if tip_id not in self._tips:
                    continue

                tip = self._tips[tip_id]
                scenario_tags = ", ".join(tip.scenario_tags)
                parts.append(f"- [{tip.id}] {tip.content} [{scenario_tags}]")
        return "\n".join(parts)

    def stats(self) -> Dict[str, object]:
        """Return statistics about the playbook."""
        return {
            "sections": len(self._sections),
            "tips": len(self._tips),
            "scenario_tags": len(set(tag for tip in self._tips.values() for tag in tip.scenario_tags))
        }
    
    def __len__(self) -> int:
        """Return the number of tips in the playbook."""
        return len(self._tips)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _generate_id(self, section: str) -> str:
        """Generate a unique ID for a new tip."""
        self._next_id += 1
        section_prefix = section.split()[0].lower()
        return f"{section_prefix}-{self._next_id:05d}"
