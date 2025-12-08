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
        main_user_phone_number="+1234567890",
        few_shot_examples="[Example 1]...",
    )
    ```
"""

from __future__ import annotations

from typing import Any, Optional, List, Sequence

from src.opence.models.clients import LLMClient
from src.opence.methods.ace.roles import (
    Generator,
    Reflector,
    Curator,
    GeneratorOutput,
    ReflectorOutput,
    CuratorOutput,
    BulletTag,
    _safe_json_loads,
    _format_optional
)
from src.opence.methods.ace.playbook import Playbook
from .appworld_prompts import (
    APPWORLD_GENERATOR_PROMPT,
    APPWORLD_REFLECTOR_PROMPT,
    APPWORLD_CURATOR_PROMPT,
)
import openai


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
            main_user_phone_number="+1987654321",
            few_shot_examples="[Example demonstrations]",
        )
        ```
    """

    def __init__(
        self,
        llm: LLMClient,
        prompt_template: str = APPWORLD_GENERATOR_PROMPT,
        *,
        max_retries: int = 3,
    ) -> None:
        """Initialize AppWorldGenerator with custom prompt template.

        Args:
            llm: LLM client for generation
            prompt_template: Custom prompt template (defaults to APPWORLD_GENERATOR_PROMPT)
            max_retries: Maximum retry attempts for JSON parsing
        """
        super().__init__(
            llm=llm,
            prompt_template=prompt_template,
            max_retries=max_retries,
        )

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
    ) -> GeneratorOutput:
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
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                response = self.llm.complete(prompt, **kwargs)
                print(f"\nAppWorldGenerator's LLM response: {response.text}\n")
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
                    + "\n\nIMPORTANT: You must output a single valid JSON object only. "
                    "Escape all quotes properly and avoid any extra text outside the JSON."
                )
            except openai.InternalServerError as err:
                last_error = err
                if attempt + 1 >= self.max_retries:
                    break
                print(f"InternalServerError encountered: {err}. Retrying...")
                prompt = (
                    base_prompt
                    + "\n\nIMPORTANT: You must respond with a SINGLE valid JSON object. Do not output raw Python code."
                )

        raise RuntimeError(
            f"AppWorldGenerator failed to produce valid JSON after {self.max_retries} attempts."
        ) from last_error


class AppWorldReflector(Reflector):
    """AppWorld-specific Reflector that allows easy prompt template override.

    Inherits all functionality from the base Reflector class but defaults
    to APPWORLD_REFLECTOR_PROMPT. You can also pass your own template.

    Args:
        llm: LLM client for reflection generation
        prompt_template: Custom prompt template string. Must include placeholders:
            {question}, {reasoning}, {prediction}, {ground_truth}, {feedback}, {playbook_excerpt}
        max_retries: Maximum number of retry attempts for JSON parsing

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
    ) -> None:
        """Initialize AppWorldReflector with custom prompt template.

        Args:
            llm: LLM client for reflection
            prompt_template: Custom prompt template (defaults to APPWORLD_REFLECTOR_PROMPT)
            max_retries: Maximum retry attempts for JSON parsing
        """
        super().__init__(
            llm=llm,
            prompt_template=prompt_template,
            max_retries=max_retries,
        )

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
                print(f"\nAppWorldReflector's LLM response: {response.text}\n")
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
                        + "\n\nIMPORTANT: Output only valid JSON. "
                        "Escape all quotes properly and avoid extra text."
                    )
        if result is None:
            raise RuntimeError(
                f"AppWorldReflector failed to produce valid JSON after {self.max_retries} attempts."
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
    ) -> None:
        """Initialize AppWorldCurator with custom prompt template.

        Args:
            llm: LLM client for curation
            prompt_template: Custom prompt template (defaults to APPWORLD_CURATOR_PROMPT)
            max_retries: Maximum retry attempts for JSON parsing
        """
        super().__init__(
            llm=llm,
            prompt_template=prompt_template,
            max_retries=max_retries,
        )

    def curate(
        self,
        *,
        reflection: ReflectorOutput,
        playbook: Playbook,
        question_context: str,
        progress: str,
        final_generated_code: Optional[str] = None,
        guidebook: Optional[str] = None,
        **kwargs: Any,
    ) -> CuratorOutput:
        """Curate playbook updates based on reflection and trajectory.

        Args:
            reflection: ReflectorOutput from reflection phase
            playbook: Current playbook state
            question_context: Task context information
            progress: Training progress string (for compatibility, not used in AppWorld prompt)
            final_generated_code: Final code generated by agent (last step)
            guidebook: Recent reflections summary
            **kwargs: Additional arguments passed to LLM client

        Returns:
            CuratorOutput containing delta operations
        """
        from src.opence.methods.ace.delta import DeltaBatch
        import json

        # Format prompt with AppWorld-specific parameters
        base_prompt = self.prompt_template.format(
            question_context=question_context,
            current_playbook=playbook.as_prompt() or "(empty playbook)",
            final_generated_code=final_generated_code or "(no code provided)",
            guidebook=guidebook or json.dumps(reflection.raw, ensure_ascii=False, indent=2),
        )

        prompt = base_prompt
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries):
            response = self.llm.complete(prompt, **kwargs)
            print(f"\nAppWorldCurator's LLM response: {response.text}\n")
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
                    + "\n\nIMPORTANT: Output only valid JSON. "
                    "Escape all quotes properly and avoid extra text."
                )

        raise RuntimeError(
            f"AppWorldCurator failed to produce valid JSON after {self.max_retries} attempts."
        ) from last_error
