"""Generator, Reflector, and Curator components."""

from __future__ import annotations

import logging
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .delta import DeltaBatch
from opence.models.clients import LLMClient
from .playbook import Playbook
from .prompts import CURATOR_PROMPT, GENERATOR_PROMPT, REFLECTOR_PROMPT


def _safe_json_loads(text: str) -> Dict[str, Any]:
    """
    Parse JSON configuration content from agent responses

    Automatically handles multiple common wrapping formats in priority order:
    1. <json_output> XML tag format
    2. Markdown code block format (```json or ```)
    3. Raw JSON object pattern matching

    For non-string inputs, attempts to serialize to JSON format.

    Args:
        response_text: Agent response text that may contain embedded JSON configuration

    Returns:
        dict: Configuration dictionary when parsing succeeds, empty dict {} when parsing fails

    Note:
        This function is designed for fault tolerance - it will not raise exceptions
        even when parsing fails, instead returning an empty dict to ensure system stability.
    """
    # If input is not a string, try to use it directly
    if not isinstance(text, str):
        try:
            # If it's a dictionary, try to serialize to JSON
            return json.dumps(repr(text), ensure_ascii=False, indent=4)
        except:
            raise ValueError("Input is not a string and cannot be serialized to JSON.")

    # First check XML tag format
    xml_pattern = re.compile(r'<json_output>(.*?)</json_output>', re.DOTALL)
    xml_match = xml_pattern.search(text)

    if xml_match:
        extracted_json_text  = xml_match.group(1).strip()
        logging.debug(f"\nJSON found in XML tags: {extracted_json_text}\n")
        try:
            data = json.loads(extracted_json_text)
            return data
        except json.JSONDecodeError as e:
            logging.error(f"\nJSONDecodeError in XML content: {e}\n")
            # If XML tag content is invalid, continue trying other methods

        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object from LLM.")
        return data
    
    # Remove Markdown code block markers (backward compatibility)
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    # Remove extra blank lines
    text = text.strip()

    # Find valid JSON object
    # Find content from first { to matching last }
    json_object_pattern  = re.compile(r'({.*})', re.DOTALL)
    json_match  = json_object_pattern.search(text)

    if not json_match :
        return {}

    extracted_json_text = json_match.group(1)
    logging.debug(f"\nPotential JSON found: {extracted_json_text}\n")
    # Validate if it's valid JSON
    try:
        data = json.loads(extracted_json_text)
    except json.JSONDecodeError as exc:
        logging.error(f"\nJSONDecodeError: {exc}\n")
        debug_path = Path("logs/json_failures.log")
        debug_path.parent.mkdir(parents=True, exist_ok=True)
        with debug_path.open("a", encoding="utf-8") as fh:
            fh.write("----\n")
            fh.write(repr(text))
            fh.write("\n")
        raise ValueError(f"LLM response is not valid JSON: {exc}\n{text}") from exc
    
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object from LLM.")
    return data

def _format_optional(value: Optional[str]) -> str:
    return value or "(none)"


@dataclass
class GeneratorOutput:
    reasoning: str
    final_answer: str
    bullet_ids: List[str]
    raw: Dict[str, Any]


class Generator:
    """Produces trajectories using the current playbook."""

    def __init__(
        self,
        llm: LLMClient,
        prompt_template: str = GENERATOR_PROMPT,
        *,
        max_retries: int = 3,
    ) -> None:
        self.llm = llm
        self.prompt_template = prompt_template
        self.max_retries = max_retries

    def generate(
        self,
        *,
        question: str,
        context: Optional[str],
        playbook: Playbook,
        reflection: Optional[str] = None,
        **kwargs: Any,
    ) -> GeneratorOutput:
        base_prompt = self.prompt_template.format(
            playbook=playbook.as_prompt() or "(empty playbook)",
            reflection=_format_optional(reflection),
            question=question,
            context=_format_optional(context),
        )
        prompt = base_prompt
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            response = self.llm.complete(prompt, **kwargs)
            try:
                data = _safe_json_loads(response.text)
                reasoning = str(data.get("reasoning", ""))
                final_answer = str(data.get("final_answer", ""))
                bullet_ids = [
                    str(item)
                    for item in data.get("bullet_ids", [])
                    if isinstance(item, (str, int))
                ]
                return GeneratorOutput(
                    reasoning=reasoning,
                    final_answer=final_answer,
                    bullet_ids=bullet_ids,
                    raw=data,
                )
            except ValueError as err:
                last_error = err
                if attempt + 1 >= self.max_retries:
                    break
                prompt = (
                    base_prompt
                    + "\n\n务必仅输出单个有效 JSON 对象，"
                    "请转义所有引号或改用单引号，避免输出额外文本。"
                )
        raise RuntimeError("Generator failed to produce valid JSON.") from last_error


@dataclass
class BulletTag:
    id: str
    tag: str


@dataclass
class ReflectorOutput:
    reasoning: str
    error_identification: str
    root_cause_analysis: str
    correct_approach: str
    key_insight: str
    bullet_tags: List[BulletTag]
    raw: Dict[str, Any]


class Reflector:
    """Extracts lessons and bullet feedback from trajectories."""

    def __init__(
        self,
        llm: LLMClient,
        prompt_template: str = REFLECTOR_PROMPT,
        *,
        max_retries: int = 3,
    ) -> None:
        self.llm = llm
        self.prompt_template = prompt_template
        self.max_retries = max_retries

    def reflect(
        self,
        *,
        question: str,
        generator_output: GeneratorOutput,
        playbook: Playbook,
        ground_truth: Optional[str],
        feedback: Optional[str],
        max_refinement_rounds: int = 1,
        **kwargs: Any,
    ) -> ReflectorOutput:
        playbook_excerpt = _make_playbook_excerpt(playbook, generator_output.bullet_ids)
        base_prompt = self.prompt_template.format(
            question=question,
            reasoning=generator_output.reasoning,
            prediction=generator_output.final_answer,
            ground_truth=_format_optional(ground_truth),
            feedback=_format_optional(feedback),
            playbook_excerpt=playbook_excerpt or "(no bullets referenced)",
        )
        result: Optional[ReflectorOutput] = None
        prompt = base_prompt
        last_error: Optional[Exception] = None
        for round_idx in range(max_refinement_rounds):
            prompt = base_prompt
            for attempt in range(self.max_retries):
                response = self.llm.complete(
                    prompt, refinement_round=round_idx, **kwargs
                )
                try:
                    data = _safe_json_loads(response.text)
                    bullet_tags: List[BulletTag] = []
                    tags_payload = data.get("bullet_tags", [])
                    if isinstance(tags_payload, Sequence):
                        for item in tags_payload:
                            if isinstance(item, dict) and "id" in item and "tag" in item:
                                bullet_tags.append(
                                    BulletTag(
                                        id=str(item["id"]), tag=str(item["tag"]).lower()
                                    )
                                )
                    candidate = ReflectorOutput(
                        reasoning=str(data.get("reasoning", "")),
                        error_identification=str(data.get("error_identification", "")),
                        root_cause_analysis=str(data.get("root_cause_analysis", "")),
                        correct_approach=str(data.get("correct_approach", "")),
                        key_insight=str(data.get("key_insight", "")),
                        bullet_tags=bullet_tags,
                        raw=data,
                    )
                    result = candidate
                    # Early exit if we already have actionable output
                    if bullet_tags or candidate.key_insight:
                        return candidate
                    break
                except ValueError as err:
                    last_error = err
                    if attempt + 1 >= self.max_retries:
                        break
                    prompt = (
                        base_prompt
                        + "\n\n请严格输出有效 JSON，对双引号进行转义，"
                        "不要输出额外解释性文本。"
                    )
        if result is None:
            raise RuntimeError("Reflector failed to produce a result.") from last_error
        return result


@dataclass
class CuratorOutput:
    delta: DeltaBatch
    raw: Dict[str, Any]


class Curator:
    """Transforms reflections into delta updates."""

    def __init__(
        self,
        llm: LLMClient,
        prompt_template: str = CURATOR_PROMPT,
        *,
        max_retries: int = 3,
    ) -> None:
        self.llm = llm
        self.prompt_template = prompt_template
        self.max_retries = max_retries

    def curate(
        self,
        *,
        reflection: ReflectorOutput,
        playbook: Playbook,
        question_context: str,
        progress: str,
        **kwargs: Any,
    ) -> CuratorOutput:
        base_prompt = self.prompt_template.format(
            progress=progress,
            stats=json.dumps(playbook.stats()),
            reflection=json.dumps(reflection.raw, ensure_ascii=False, indent=2),
            playbook=playbook.as_prompt() or "(empty playbook)",
            question_context=question_context,
        )
        prompt = base_prompt
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            response = self.llm.complete(prompt, **kwargs)
            try:
                data = _safe_json_loads(response.text)
                delta = DeltaBatch.from_json(data)
                return CuratorOutput(delta=delta, raw=data)
            except ValueError as err:
                last_error = err
                if attempt + 1 >= self.max_retries:
                    break
                prompt = (
                    base_prompt
                    + "\n\n提醒：仅输出有效 JSON，所有字符串请转义双引号或改用单引号，"
                    "不要添加额外文本。"
                )
        raise RuntimeError("Curator failed to produce valid JSON.") from last_error


def _make_playbook_excerpt(playbook: Playbook, bullet_ids: Sequence[str]) -> str:
    lines: List[str] = []
    seen = set()
    for bullet_id in bullet_ids:
        if bullet_id in seen:
            continue
        bullet = playbook.get_bullet(bullet_id)
        if bullet:
            seen.add(bullet_id)
            lines.append(f"[{bullet.id}] {bullet.content}")
    return "\n".join(lines)
