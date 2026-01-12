"""AppWorld-specific Generator, Reflector, and Curator components.

This module provides AppWorld-customized versions of ACE roles that allow you to override
prompt templates while inheriting all the core functionality from the base classes.

Example usage:
    ```python
    from appworld_experiment.appworld_roles import AppWorldGenerator
    from appworld_experiment.appworld_prompts import APPWORLD_GENERATOR_PROMPT
    from opence.models.clients import OpenAIClient

    # Use with custom prompt
    custom_prompt = "Your custom prompt here with {playbook}, {task}, etc."
    llm = OpenAIClient(model="gpt-4")
    generator = AppWorldGenerator(llm, prompt_template=custom_prompt)

    # Or use the default AppWorld prompt
    generator = AppWorldGenerator(llm)

    # Generate with AppWorld-specific parameters
    output = generator.generate(
        task="Book a ticket to NYC",
        playbook=playbook,
        main_user_first_name="John",
        main_user_last_name="Doe",
        main_user_email="john@example.com",
        main_user_phone_number="+1234567890"
    )
    ```
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Dict, List, Sequence, TYPE_CHECKING
import re
import ast

from src.opence.models.clients import LLMClient
from src.opence.methods.ace.roles import (
    Generator,
    Reflector,
    Curator,
    GeneratorOutput,
    ReflectorOutput,
    CuratorOutput,
    BulletTag,
    _format_optional,
    _safe_json_loads,
)
from src.opence.methods.ace.playbook import Playbook
from .appworld_prompts import (
    APPWORLD_GENERATOR_PROMPT,
    APPWORLD_REFLECTOR_PROMPT,
    APPWORLD_CURATOR_PROMPT,
)
import openai

if TYPE_CHECKING:
    from appworld_experiment.experiment_logger import ExperimentLogger

# Fallback logger for when ExperimentLogger is not provided
_fallback_logger = logging.getLogger(__name__)


def _markdown_parser(md_text: str, schema: dict) -> dict:
    """
    Parses Markdown text into a JSON object based on a strict schema.

    This function extracts sections from a Markdown string (denoted by headers like `### Key`)
    and maps them to a dictionary. It enforces strict validation for existence of keys
    but allows for flexibility regarding extra content.

    Args:
        md_text (str): The raw Markdown output string from the LLM.
        schema (dict): A dictionary defining the required keys and type inference hints.
                       Format: {"required_key": "any_value_for_type_inference"}
                       The values in the schema are NOT used as defaults; they are only used
                       to infer if the parser should attempt to parse the content as a list.

    Returns:
        str: A JSON string representing the parsed data.

    Raises:
        ValueError: If any key defined in the `schema` is missing from the `md_text`.

    Behavior:
        1. Missing Keys -> Raise ValueError (Strict enforcement).
        2. Extra Keys   -> Ignore (Do not include in the final result).
    """

    # ==========================================
    # 1. Pre-processing: Parse raw Markdown structure
    # ==========================================
    lines = md_text.strip().split('\n')
    raw_data = {}
    current_key = None
    current_content = []
    in_code_block = False

    for line in lines:
        stripped = line.strip()

        # Handle code block markers to avoid parsing headers inside code
        if stripped.startswith("```"):
            in_code_block = not in_code_block

        # Detect headers (must be outside code blocks)
        # Regex matches lines starting with one or more '#' followed by whitespace
        if not in_code_block and re.match(r'^#+\s+', stripped):
            # Save the previous section if it exists
            if current_key:
                raw_data[current_key] = "\n".join(current_content).strip()
    
            # Normalize header: remove '#', strip whitespace, convert to lowercase, spaces to underscores
            # Example: "### Python Code" -> "python_code"
            header_text = re.sub(r'^#+\s+', '', stripped).strip()
            normalized_key = header_text.lower().replace(" ", "_")

            current_key = normalized_key
            current_content = []
        else:
            current_content.append(line)

    # Save the last section after the loop finishes
    if current_key:
        raw_data[current_key] = "\n".join(current_content).strip()

    # ==========================================
    # 2. Validate Missing Keys
    # ==========================================

    required_keys = set(schema.keys())
    found_keys = set(raw_data.keys())

    # Calculate keys that are present in schema but missing in raw_data
    missing_keys = required_keys - found_keys

    if missing_keys:
        error_msg = f"Parsing Error: Missing required keys in output: {list(missing_keys)}"
        print(error_msg)
        raise ValueError(error_msg)

    # ==========================================
    # 3. Assemble Result (Filter by Schema, ignore extras)
    # ==========================================
    final_result = {}

    # Iterate only through keys defined in the schema.
    # This automatically ignores any extra keys found in raw_data.
    for key in schema.keys():
        content = raw_data[key]

        # --- Smart Content Cleaning ---

        # 1. Attempt to remove ```python ... ``` code block wrappers
        code_match = re.search(r'^```\w*\n(.*?)\n```$', content, re.DOTALL)
        if code_match:
            final_result[key] = code_match.group(1).strip()
            continue

        # 2. Attempt to parse List
        # We use the value provided in the schema to infer if we expect a List.
        # Or if the content string strictly looks like a list structure.
        expected_val = schema[key]
        if isinstance(expected_val, list) or (content.startswith("[") and content.endswith("]")):
            try:
                # Handle "None" text specifically
                if content.lower() == "none" or content.lower() == "null":
                    final_result[key] = []
                else:
                    import json
                    parsed = json.loads(content)
                    if isinstance(parsed, list):
                        final_result[key] = parsed
                continue
            except Exception as e:
                # If parsing fails, fall through to default text handling
                _fallback_logger.debug(f"List parsing failed for key '{key}': {e}. Falling back to raw text.")

        # 3. Default: keep as raw text
        final_result[key] = content

    return final_result

class AppWorldGenerator(Generator):
    """AppWorld-specific Generator that handles AppWorld task format.

    This generator extends the base Generator to work with AppWorld's specific
    requirements including user information and few-shot examples. Unlike the
    base Generator which uses 'question' and 'context', this uses 'task' and
    AppWorld-specific parameters.

    Args:
        llm: LLM client for text generation
        prompt_template: Custom prompt template string. Must include placeholders:
            {playbook}, {task}, {main_user_first_name}, {main_user_last_name},
            {main_user_email}, {main_user_phone_number}, {few_shot_examples}
        max_retries: Maximum number of retry attempts for JSON parsing
        schema: Schema dict defining required output keys and type hints

    Example:
        ```python
        # Use default AppWorld prompt
        generator = AppWorldGenerator(llm)

        # Generate with AppWorld parameters
        output = generator.generate(
            task="Book a flight to San Francisco",
            playbook=my_playbook,
            main_user_first_name="Jane",
            main_user_last_name="Smith",
            main_user_email="jane@example.com",
            main_user_phone_number="+1987654321"
        )
        ```
    """

    def __init__(
        self,
        llm: LLMClient,
        prompt_template: str = APPWORLD_GENERATOR_PROMPT,
        *,
        max_retries: int = 3,
        logger: Optional["ExperimentLogger"] = None,
        schema: Optional[Dict[str, Any]] = {
            "reasoning": "",
            "bullet_ids": [],
            "final_answer": ""
        }
    ) -> None:
        """Initialize AppWorldGenerator with custom prompt template.

        Args:
            llm: LLM client for generation
            prompt_template: Custom prompt template (defaults to APPWORLD_GENERATOR_PROMPT)
            max_retries: Maximum retry attempts for JSON parsing
            logger: ExperimentLogger instance for token usage logging
        """
        super().__init__(
            llm=llm,
            prompt_template=prompt_template,
            max_retries=max_retries,
        )
        self.logger = logger
        self._current_task_id: Optional[str] = None
        self._current_step: Optional[int] = None
        self.schema = schema

    def _log_info(self, message: str) -> None:
        """Log info message using ExperimentLogger or fallback to standard logging."""
        if self.logger:
            self.logger.info(message)
        else:
            _fallback_logger.info(message)

    def _log_debug(self, message: str) -> None:
        """Log debug message using ExperimentLogger or fallback to standard logging."""
        if self.logger:
            self.logger.debug(message)
        else:
            _fallback_logger.debug(message)

    def generate(
        self,
        *,
        task: str,
        playbook: Playbook,
        main_user_first_name: str = "",
        main_user_last_name: str = "",
        main_user_email: str = "",
        main_user_phone_number: str = "",
        trajectory_history: str = "",
        **kwargs: Any,
    ) -> Optional[GeneratorOutput]:
        """Generate AppWorld task solution using playbook and user context.

        Args:
            task: The AppWorld task description
            playbook: Playbook containing strategies and knowledge
            main_user_first_name: User's first name
            main_user_last_name: User's last name
            main_user_email: User's email address
            main_user_phone_number: User's phone number
            trajectory_history: Formatted history of previous steps (for multi-step interaction)
            **kwargs: Additional arguments passed to LLM client

        Returns:
            GeneratorOutput containing reasoning, final_answer, bullet_ids, and raw data

        Raises:
            RuntimeError: If generator fails to produce valid JSON after max_retries
        """
        base_prompt = self.prompt_template.format(
            task=task,
            playbook=playbook.as_prompt() or "(empty playbook)",
            main_user_first_name=main_user_first_name or "(not provided)",
            main_user_last_name=main_user_last_name or "(not provided)",
            main_user_email=main_user_email or "(not provided)",
            main_user_phone_number=main_user_phone_number or "(not provided)",
            trajectory_history=trajectory_history,
        )

        prompt = base_prompt
        # self.logger.debug(f"Generator Prompt: {prompt}")

        for attempt in range(self.max_retries):
            try:
                response = self.llm.complete(prompt, **kwargs)

                # Log token usage if logger is available
                if self.logger and hasattr(response, 'prompt_tokens'):
                    self.logger.log_llm_call(
                        task_id=self._current_task_id or "unknown",
                        role="generator",
                        model=self.llm.model or "unknown",
                        prompt_tokens=response.prompt_tokens,
                        completion_tokens=response.completion_tokens,
                        total_tokens=response.total_tokens,
                        step=self._current_step,
                        estimated_prompt_tokens=response.estimated_prompt_tokens,
                    )

                self._log_info(f"\nAppWorldGenerator's LLM response: {response.text}\n")

                if response.text.strip().startswith('{') or response.text.strip().startswith('```json'):
                    data = _safe_json_loads(response.text)
                else:
                    data = _markdown_parser(response.text, self.schema)

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
                if attempt + 1 >= self.max_retries:
                    break
                prompt = (
                    base_prompt
                    + "\n\nIMPORTANT: You must output a single Text object only."
                    " Obey the Markdown format strictly."
                    " Do not include any explanations or text outside the required format."
                )
            except openai.InternalServerError as err:
                if attempt + 1 >= self.max_retries:
                    break
                self._log_info(f"InternalServerError encountered: {err}. Retrying...")
                prompt = (
                    base_prompt
                    + "\n\nIMPORTANT: You must respond with a SINGLE Text object only."
                    " Obey the Markdown format strictly."
                    " Do not include any explanations or text outside the required format."
                )

        return None


class AppWorldReflector(Reflector):
    """AppWorld-specific Reflector that allows easy prompt template override.

    Inherits all functionality from the base Reflector class but defaults
    to APPWORLD_REFLECTOR_PROMPT. You can also pass your own template.

    Args:
        llm: LLM client for reflection generation
        prompt_template: Custom prompt template string. Must include placeholders:
            {question}, {reasoning}, {prediction}, {ground_truth}, {feedback}, {playbook_excerpt}
        max_retries: Maximum number of retry attempts for JSON parsing
        schema: Schema dict defining required output keys and type hints

    Example:
        ```python
        # Use default AppWorld prompt
        reflector = AppWorldReflector(llm)

        # Use your own prompt template
        my_prompt = '''
        Analyze this AppWorld attempt:
        Question: {question}
        Reasoning: {reasoning}
        Prediction: {prediction}
        Truth: {ground_truth}
        Feedback: {feedback}
        Playbook used: {playbook_excerpt}

        Return JSON with: reasoning, error_identification, root_cause_analysis,
        correct_approach, key_insight, bullet_tags
        '''
        reflector = AppWorldReflector(llm, prompt_template=my_prompt)
        ```
    """

    def __init__(
        self,
        llm: LLMClient,
        prompt_template: str = APPWORLD_REFLECTOR_PROMPT,
        *,
        max_retries: int = 3,
        logger: Optional["ExperimentLogger"] = None,
        schema: Optional[Dict[str, Any]] = {
            "reasoning": "",
            "error_identification": "",
            "root_cause_analysis": "",
            "correct_approach": "", 
            "key_insight": "",
            "bullet_tags": []
        }
    ) -> None:
        """Initialize AppWorldReflector with custom prompt template.

        Args:
            llm: LLM client for reflection
            prompt_template: Custom prompt template (defaults to APPWORLD_REFLECTOR_PROMPT)
            max_retries: Maximum retry attempts for JSON parsing
            logger: ExperimentLogger instance for token usage logging
        """
        super().__init__(
            llm=llm,
            prompt_template=prompt_template,
            max_retries=max_retries,
        )
        self.logger = logger
        self._current_task_id: Optional[str] = None
        self.schema = schema

    def _log_info(self, message: str) -> None:
        """Log info message using ExperimentLogger or fallback to standard logging."""
        if self.logger:
            self.logger.info(message)
        else:
            _fallback_logger.info(message)

    def _log_debug(self, message: str) -> None:
        """Log debug message using ExperimentLogger or fallback to standard logging."""
        if self.logger:
            self.logger.debug(message)
        else:
            _fallback_logger.debug(message)

    def reflect(
        self,
        *,
        playbook: Playbook,
        ground_truth: Optional[str],
        feedback: Optional[str],
        unit_test_results: Optional[str] = None,
        max_refinement_rounds: int = 1,
        **kwargs: Any,
    ) -> ReflectorOutput:
        """Reflect on AppWorld trajectory and provide diagnostic feedback.

        Args:
            question: The task instruction (not used in AppWorld prompt)
            generator_output: Final generator output (not used in AppWorld prompt)
            playbook: Current playbook state
            ground_truth: Ground truth code (reference solution)
            feedback: Full trajectory string from Trajectory.format_for_reflector()
            unit_test_results: Test results from environment.evaluate_unit_tests()
            max_refinement_rounds: Number of refinement rounds
            **kwargs: Additional arguments passed to LLM client

        Returns:
            ReflectorOutput containing analysis and bullet tags
        """
        # Format prompt with AppWorld-specific parameters
        base_prompt = self.prompt_template.format(
            ground_truth_code=_format_optional(ground_truth),
            unit_test_results=_format_optional(unit_test_results),
            playbook=playbook.as_prompt() or "(empty playbook)",
            full_trajectory=_format_optional(feedback),
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

                # Log token usage if logger is available
                if self.logger and hasattr(response, 'prompt_tokens'):
                    self.logger.log_llm_call(
                        task_id=self._current_task_id or "unknown",
                        role="reflector",
                        model=self.llm.model or "unknown",
                        prompt_tokens=response.prompt_tokens,
                        completion_tokens=response.completion_tokens,
                        total_tokens=response.total_tokens,
                        estimated_prompt_tokens=response.estimated_prompt_tokens,
                    )

                self._log_info(f"\nAppWorldReflector's LLM response: {response.text}\n")
                try:
                    # Auto-detect format: check if response starts with '{' for JSON, otherwise use Markdown
                    if response.text.strip().startswith('{'):
                        data = _safe_json_loads(response.text)
                    else:
                        data = _markdown_parser(response.text, self.schema)

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
                        + "\n\nIMPORTANT: You must output a single Text object only."
                        " Obey the Markdown format strictly."
                        " Do not include any explanations or text outside the required format."
                    )
        if result is None:
            raise RuntimeError(
                f"AppWorldReflector failed to produce valid Markdown after {self.max_retries} attempts."
            ) from last_error
        return result


class AppWorldCurator(Curator):
    """AppWorld-specific Curator that allows easy prompt template override.

    Inherits all functionality from the base Curator class but defaults
    to APPWORLD_CURATOR_PROMPT. You can also pass your own template.

    Args:
        llm: LLM client for curation
        prompt_template: Custom prompt template string. Must include placeholders:
            {progress}, {stats}, {reflection}, {playbook}, {question_context}
        max_retries: Maximum number of retry attempts for JSON parsing

    Example:
        ```python
        # Use default AppWorld prompt
        curator = AppWorldCurator(llm)

        # Use your own prompt template
        my_prompt = '''
        Update the playbook based on AppWorld feedback:
        Progress: {progress}
        Stats: {stats}
        Reflection: {reflection}
        Current playbook: {playbook}
        Question context: {question_context}

        Return JSON with: reasoning, operations (list of ADD/UPDATE/TAG/REMOVE ops)
        '''
        curator = AppWorldCurator(llm, prompt_template=my_prompt)
        ```
    """

    def __init__(
        self,
        llm: LLMClient,
        prompt_template: str = APPWORLD_CURATOR_PROMPT,
        *,
        max_retries: int = 3,
        logger: Optional["ExperimentLogger"] = None,
        schema: Optional[Dict[str, Any]] = {
            "reasoning": "",
            "operations": []
        }
    ) -> None:
        """Initialize AppWorldCurator with custom prompt template.

        Args:
            llm: LLM client for curation
            prompt_template: Custom prompt template (defaults to APPWORLD_CURATOR_PROMPT)
            max_retries: Maximum retry attempts for JSON parsing
            logger: ExperimentLogger instance for token usage logging
            schema: Schema dict defining required output keys and type hints
        """
        super().__init__(
            llm=llm,
            prompt_template=prompt_template,
            max_retries=max_retries,
        )
        self.logger = logger
        self._current_task_id: Optional[str] = None
        self.schema = schema

    def _log_info(self, message: str) -> None:
        """Log info message using ExperimentLogger or fallback to standard logging."""
        if self.logger:
            self.logger.info(message)
        else:
            _fallback_logger.info(message)

    def _log_debug(self, message: str) -> None:
        """Log debug message using ExperimentLogger or fallback to standard logging."""
        if self.logger:
            self.logger.debug(message)
        else:
            _fallback_logger.debug(message)

    def curate(
        self,
        *,
        playbook: Playbook,
        question_context: str,
        guidebook: Optional[str] = None,
        **kwargs: Any,
    ) -> CuratorOutput:
        """Curate playbook updates based on reflection and trajectory.

        Args:
            playbook: Current playbook state
            question_context: Task context information
            guidebook: Recent reflections summary
            **kwargs: Additional arguments passed to LLM client

        Returns:
            CuratorOutput containing delta operations
        """
        from src.opence.methods.ace.delta import DeltaBatch

        # Format prompt with AppWorld-specific parameters
        base_prompt = self.prompt_template.format(
            question_context=question_context,
            current_playbook=playbook.as_prompt() or "(empty playbook)",
            guidebook=guidebook
        )

        prompt = base_prompt
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            response = self.llm.complete(prompt, **kwargs)

            # Log token usage if logger is available
            if self.logger and hasattr(response, 'prompt_tokens'):
                self.logger.log_llm_call(
                    task_id=self._current_task_id or "unknown",
                    role="curator",
                    model=self.llm.model or "unknown",
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    total_tokens=response.total_tokens,
                    estimated_prompt_tokens=response.estimated_prompt_tokens,
                )

            self._log_info(f"\nAppWorldCurator's LLM response: {response.text}\n")
            try:
                # Auto-detect format: check if response starts with '{' for JSON, otherwise use Markdown
                if response.text.strip().startswith('{'):
                    data = _safe_json_loads(response.text)
                else:
                    data = _markdown_parser(response.text, self.schema)
                
                delta = DeltaBatch.from_json(data)
                return CuratorOutput(delta=delta, raw=data)
            
            except ValueError as err:
                last_error = err
                if attempt + 1 >= self.max_retries:
                    break
                prompt = (
                    base_prompt
                    + "\n\nIMPORTANT: You must output a single Text object only."
                    " Obey the Markdown format strictly."
                    " Do not include any explanations or text outside the required format."
                )

        raise RuntimeError(
            f"AppWorldCurator failed to produce valid Markdown after {self.max_retries} attempts."
        ) from last_error
