"""AppWorld-specific adaptation loops for offline and online ACE training.

This module extends the base adaptation framework to work with AppWorld's specific
requirements. The key difference is that AppWorldGenerator requires different parameters
(task, user info) instead of (question, context).

User information (first_name, last_name, email, phone) is stored in sample.metadata.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Iterable, List, Optional, Sequence, TYPE_CHECKING
import re
import json

from src.opence.methods.ace.adaptation import (
    AdapterBase,
    AdapterStepResult,
    EnvironmentResult,
    Sample,
    TaskEnvironment,
)
from appworld_experiment.appworld_deduplication import OllamaDeduplicator
from src.opence.methods.ace.playbook import Playbook
from appworld_experiment.appworld_roles import (
    AppWorldGenerator,
    AppWorldReflector,
    AppWorldCurator,
)
from appworld_experiment.trajectory import Trajectory

if TYPE_CHECKING:
    from appworld_experiment.experiment_logger import ExperimentLogger

# Fallback logger for when ExperimentLogger is not provided
_fallback_logger = logging.getLogger(__name__)

class ExecutionStatus(Enum):
    """Execution status for a task."""
    COMPLETED = "completed"  # Task completed successfully
    MAX_STEPS_REACHED = "max_steps_reached"  # Hit max interaction steps without completing
    CRASHED = "crashed"  # Execution failed due to error

class AppWorldAdapterBase(AdapterBase):
    """Shared orchestration logic for AppWorld offline and online adaptation.

    This base class overrides _process_sample to call AppWorldGenerator with
    task-specific parameters instead of question/context.
    """

    def __init__(
        self,
        *,
        playbook: Optional[Playbook] = None,
        generator: AppWorldGenerator,
        reflector: AppWorldReflector,
        curator: AppWorldCurator,
        max_refinement_rounds: int = 1,
        max_interaction_steps: int = 10,
        logger: Optional["ExperimentLogger"] = None,
    ) -> None:
        """Initialize AppWorld adapter with AppWorld-specific roles.

        Args:
            playbook: Initial playbook (creates empty if None)
            generator: AppWorldGenerator instance
            reflector: AppWorldReflector instance
            curator: AppWorldCurator instance
            max_refinement_rounds: Number of reflector refinement rounds
            max_interaction_steps: Maximum number of agent-environment interaction steps
            logger: Optional ExperimentLogger for tracking metrics
        """
        # Pass AppWorld roles to base class (they inherit from base roles)
        super().__init__(
            playbook=playbook,
            generator=generator,
            reflector=reflector,
            curator=curator,
            max_refinement_rounds=max_refinement_rounds
        )
        self.max_interaction_steps = max_interaction_steps
        self.logger = logger
        self.sgc_cnt = {}

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

    def _log_error(self, message: str) -> None:
        """Log error message using ExperimentLogger or fallback to standard logging."""
        if self.logger:
            self.logger.error(message)
        else:
            _fallback_logger.error(message)

    def extract_code(self, text: str) -> str:
        """
        Extracts the Python code snippet from a Markdown-formatted LLM response.

        This method specifically targets code blocks enclosed in ```python ... ``` tags.
        It uses regular expressions to robustly handle variations in whitespace and
        newlines that often occur in LLM outputs.

        Args:
            text (str): The raw text response containing the Markdown code block.

        Returns:
            str: The extracted and cleaned Python code. If no specific ```python
                block is found, it returns the original text stripped of leading/trailing
                whitespace.

        Example:
            >>> raw_text = "Here is the code: ```python\\nprint('Hello')\\n```\\n"
            >>> extract_code(raw_text)
            "print('Hello')"
        """
        # Define the regex pattern to match Python code blocks.
        # Breakdown of r"```python\s+(.*?)```":
        #   ```python : Matches the literal starting tag.
        #   \s+       : Matches one or more whitespace characters (including \n) immediately following the tag.
        #   (.*?)     : Non-greedy capture group to match everything inside the block.
        #   ```       : Matches the literal closing tag.
        pattern = r"```python\s+(.*?)```"

        # Search for the pattern within the input text.
        # re.DOTALL is essential here; it allows the '.' character to match newlines,
        # enabling the extraction of multi-line code blocks.
        match = re.search(pattern, text, re.DOTALL)

        if match:
            # If a match is found, extract the captured content (group 1).
            # .strip() is used to remove any residual whitespace or newlines 
            # that might exist at the start or end of the captured string.
            return match.group(1).strip()

        # Fallback: If no formatted code block is found, return the clean original text.
        return text.strip()
    
    def _extract_user_info(self, sample: Sample) -> dict:
        """Extract user information from sample.metadata.

        Args:
            sample: Sample with metadata containing supervisor info

        Returns:
            Dictionary with user information fields
        """
        metadata = sample.metadata or {}
        return {
            "main_user_first_name": metadata.get("first_name", ""),
            "main_user_last_name": metadata.get("last_name", ""),
            "main_user_email": metadata.get("email", ""),
            "main_user_phone_number": metadata.get("phone_number", ""),
        }

    def _question_context(self, sample: Sample, environment_result: EnvironmentResult) -> str:
        parts = [
            f"question: {sample.question}",
            f"metadata: {json.dumps(sample.metadata)}",
            f"ground_truth: {environment_result.ground_truth}",
        ]
        return "\n".join(parts)
    
    def _process_sample(
        self,
        sample: Sample,
        environment: TaskEnvironment,
        *,
        epoch: int,
        step_index: int,
        phase: str = "default",
    ) -> AdapterStepResult:
        """Process a single AppWorld sample through multi-step interaction.

        This implements a multi-step agent-environment interaction loop where
        the Generator produces code step-by-step, receives observations from
        the Environment, and continues until task completion or max steps.

        Args:
            sample: Sample to process (AppWorldSample with metadata)
            environment: Task environment for evaluation
            epoch: Current epoch number
            step_index: Current step index in epoch

        Returns:
            AdapterStepResult containing all outputs from the pipeline
        """
        import time
        start_time = time.time()

        # Get task_id for logging
        task_id = getattr(sample, 'task_id', f'sample_{step_index}')

        # Set task_id in roles for token logging
        if hasattr(self.generator, '_current_task_id'):
            self.generator._current_task_id = task_id
        if hasattr(self.reflector, '_current_task_id'):
            self.reflector._current_task_id = task_id
        if hasattr(self.curator, '_current_task_id'):
            self.curator._current_task_id = task_id

        # Log task start
        if self.logger:
            self.logger.log_task_start(
                task_id=task_id,
                sample_index=step_index,
                epoch=epoch
            )

        # Extract user info from metadata
        user_info = self._extract_user_info(sample)

        # Initialize trajectory
        trajectory = Trajectory(task=sample.question, steps=[])

        # Initialize task in environment
        environment.initialize_task(sample, self.logger.experiment_name)

        # Multi-step interaction loop
        execution_status = ExecutionStatus.MAX_STEPS_REACHED  # Default status
        final_generator_output = None

        for interaction_step in range(1, self.max_interaction_steps + 1):
            self._log_info(f"Interaction Step {interaction_step}/{self.max_interaction_steps}")

            # Set current step for generator logging
            if hasattr(self.generator, '_current_step'):
                self.generator._current_step = interaction_step

            # Format trajectory history for generator
            trajectory_history = trajectory.format_for_generator() if trajectory.steps else ""

            try:
                # Generate next step
                generator_output = self.generator.generate(
                    task=sample.question,
                    playbook=self.playbook,
                    main_user_first_name=user_info["main_user_first_name"],
                    main_user_last_name=user_info["main_user_last_name"],
                    main_user_email=user_info["main_user_email"],
                    main_user_phone_number=user_info["main_user_phone_number"],
                    trajectory_history=trajectory_history,
                )

                # Handle the case where generation fails when out of retries
                if generator_output is None:
                    self._log_error("Generator failed to produce output after maximum retries.")
                    execution_status = ExecutionStatus.CRASHED
                    break

                # Execute code in environment
                code = generator_output.final_answer
                exec_result = environment.execute_code(sample.task_id, self.extract_code(code))

                # Format observation
                observation = f"Output: {exec_result.get('output', '')}\n"

                # Add step to trajectory
                trajectory.add_step(
                    reasoning=generator_output.reasoning,
                    bullet_ids=generator_output.bullet_ids,
                    code=code,
                    observation=observation,
                )

                # Check if task is completed via environment API
                if environment.is_task_completed(sample.task_id):
                    self._log_info("Task completion detected by environment")
                    execution_status = ExecutionStatus.COMPLETED
                    final_generator_output = generator_output
                    break

                final_generator_output = generator_output

            except Exception as e:
                self._log_error(f"Execution crashed: {str(e)}")
                execution_status = ExecutionStatus.CRASHED
                break

        # Save final task status
        trajectory.execution_status = execution_status.value

        # Get unit test results
        unit_test_result = environment.evaluate_task(sample.task_id)
        unit_test_output = unit_test_result.get("output", "(no unit test output)")

        # Parse unit test results for TGC calculation
        from appworld_experiment.experiment_logger import parse_unit_test_results
        unit_tests_passed, unit_tests_total = parse_unit_test_results(unit_test_output)
        tgc = 1.0 if unit_tests_passed == unit_tests_total else 0.0
        
        scenario_id = sample.task_id.split("_")[0]
        self.sgc_cnt[scenario_id] = self.sgc_cnt.get(scenario_id, 0) + (1 if tgc == 1.0 else 0.0)
        self.logger.scenario_summary = self.sgc_cnt

        # Close task
        environment.close_task(sample.task_id)

        # Store trajectory in sample.context for later use
        sample.context = trajectory.format_for_reflector()

        # Create final environment result
        env_result = EnvironmentResult(
            feedback=f"Task completed in {len(trajectory.steps)} steps. Status: {execution_status.value}",
            ground_truth=sample.ground_truth,
            metrics={
                "execution_status": execution_status.value,
                "num_steps": len(trajectory.steps),
                "tgc": tgc,
                "unit_tests_passed": unit_tests_passed,
                "unit_tests_total": unit_tests_total
            }
        )

        # Reflection - use trajectory for analysis
        reflection = self.reflector.reflect(
            playbook=self.playbook,
            ground_truth=env_result.ground_truth,
            feedback=sample.context,  # Pass full trajectory as feedback
            unit_test_results=unit_test_output,  # Pass unit test results
            max_refinement_rounds=self.max_refinement_rounds,
        )

        # Apply bullet tags and update reflection history
        self._apply_bullet_tags(reflection)
        self._update_recent_reflections(reflection)

        # Curation - update playbook based on reflection
        curator_output = self.curator.curate(
            question_context=self._question_context(sample, env_result),
            playbook=self.playbook,
            guidebook=self._reflection_context(),  # Recent reflections
        )

        # Apply delta to playbook
        self.playbook.apply_delta(curator_output.delta)
        self._log_debug(f"Updated playbook:\n{self.playbook.as_prompt()}")

        # Calculate execution time and log metrics
        execution_time = time.time() - start_time

        if self.logger:
            from appworld_experiment.experiment_logger import TaskMetrics

            # Save trajectory
            task_id = getattr(sample, 'task_id', f'sample_{step_index}')
            self.logger.log_trajectory(task_id, sample.context)

            # Log task metrics with the specified phase
            metrics = TaskMetrics(
                task_id=task_id,
                sample_index=step_index,
                epoch=epoch,
                execution_status=execution_status.value,
                num_steps=len(trajectory.steps),
                execution_time=execution_time,
                trajectory_length=len(sample.context),
                num_bullet_tags=len(reflection.bullet_tags),
                playbook_size=self.playbook.__len__(),
                tgc=tgc,
                unit_tests_passed=unit_tests_passed,
                unit_tests_total=unit_tests_total
            )
            self.logger.log_task_metrics(metrics, phase=phase)

        return AdapterStepResult(
            sample=sample,
            generator_output=final_generator_output,
            environment_result=env_result,
            reflection=reflection,
            curator_output=curator_output,
            playbook_snapshot=self.playbook.as_prompt(),
        )
    
    def _evaluation_sample(
        self,
        sample: Sample,
        environment: TaskEnvironment,
        *,
        step_index: int,
        phase: str = "test",
    ) -> AdapterStepResult:
        """Process a single AppWorld sample for evaluation with frozen playbook.

        In evaluation mode, only the Generator executes. Reflector and Curator
        are NOT called, so the playbook remains unchanged.

        Args:
            sample: Sample to process (AppWorldSample with metadata)
            environment: Task environment for evaluation
            step_index: Current step index in evaluation
            total_steps: Total number of steps in evaluation
        Returns:
            AdapterStepResult containing generator outputs and environment results
        """
        import time
        start_time = time.time()

        # Get task_id for logging
        task_id = getattr(sample, 'task_id', f'sample_{step_index}')

        # Set task_id in generator for token logging
        if hasattr(self.generator, '_current_task_id'):
            self.generator._current_task_id = task_id

        # Log task start
        if self.logger:
            self.logger.log_task_start(
                task_id=task_id,
                sample_index=step_index,
                epoch=0  # Use 0 to indicate evaluation phase
            )

        # Extract user info from metadata
        user_info = self._extract_user_info(sample)

        # Initialize trajectory
        trajectory = Trajectory(task=sample.question, steps=[])

        # Initialize task in environment
        environment.initialize_task(sample, self.logger.experiment_name)

        # Multi-step interaction loop (Generator only, no Reflector/Curator)
        execution_status = ExecutionStatus.MAX_STEPS_REACHED  # Default status
        final_generator_output = None

        for interaction_step in range(1, self.max_interaction_steps + 1):
            self._log_info(f"[Evaluation] Interaction Step {interaction_step}/{self.max_interaction_steps}")

            # Set current step for generator logging
            if hasattr(self.generator, '_current_step'):
                self.generator._current_step = interaction_step

            # Format trajectory history for generator
            trajectory_history = trajectory.format_for_generator() if trajectory.steps else ""

            try:
                # Generate next step
                generator_output = self.generator.generate(
                    task=sample.question,
                    playbook=self.playbook,
                    main_user_first_name=user_info["main_user_first_name"],
                    main_user_last_name=user_info["main_user_last_name"],
                    main_user_email=user_info["main_user_email"],
                    main_user_phone_number=user_info["main_user_phone_number"],
                    trajectory_history=trajectory_history,
                )

                # Handle the case where generation fails
                if generator_output is None:
                    self._log_error("Generator failed to produce output after maximum retries.")
                    execution_status = ExecutionStatus.CRASHED
                    break

                # Execute code in environment
                code = generator_output.final_answer
                exec_result = environment.execute_code(sample.task_id, self.extract_code(code))

                # Format observation
                observation = f"Output: {exec_result.get('output', '')}\n"

                # Add step to trajectory
                trajectory.add_step(
                    reasoning=generator_output.reasoning,
                    bullet_ids=generator_output.bullet_ids,
                    code=code,
                    observation=observation,
                )

                # Check if task is completed via environment API
                if environment.is_task_completed(sample.task_id):
                    self._log_info("Task completion detected by environment")
                    execution_status = ExecutionStatus.COMPLETED
                    final_generator_output = generator_output
                    break

                final_generator_output = generator_output

            except Exception as e:
                self._log_error(f"Execution crashed: {str(e)}")
                execution_status = ExecutionStatus.CRASHED
                break

        # Save final task status
        trajectory.execution_status = execution_status.value

        # Get unit test results
        unit_test_result = environment.evaluate_task(sample.task_id)
        unit_test_output = unit_test_result.get("output", "(no unit test output)")

        # Parse unit test results for TGC calculation
        from appworld_experiment.experiment_logger import parse_unit_test_results
        unit_tests_passed, unit_tests_total = parse_unit_test_results(unit_test_output)
        tgc = 1.0 if unit_tests_passed == unit_tests_total else 0.0
        
        scenario_id = sample.task_id.split("_")[0]
        self.sgc_cnt[scenario_id] = self.sgc_cnt.get(scenario_id, 0) + (1 if tgc == 1.0 else 0.0)
        self.logger.scenario_summary = self.sgc_cnt

        # Close task
        environment.close_task(sample.task_id)

        # Store trajectory in sample.context for logging
        sample.context = trajectory.format_for_reflector()

        # Create environment result (no Reflector/Curator in evaluation mode)
        env_result = EnvironmentResult(
            feedback=f"Task completed in {len(trajectory.steps)} steps. Status: {execution_status.value}",
            ground_truth=sample.ground_truth,
            metrics={
                "execution_status": execution_status.value,
                "num_steps": len(trajectory.steps),
                "tgc": tgc,
                "unit_tests_passed": unit_tests_passed,
                "unit_tests_total": unit_tests_total
            }
        )

        # Calculate execution time and log metrics
        execution_time = time.time() - start_time

        if self.logger:
            from appworld_experiment.experiment_logger import TaskMetrics

            # Save trajectory
            self.logger.log_trajectory(task_id, sample.context)

            # Log task metrics with the specified phase
            metrics = TaskMetrics(
                task_id=task_id,
                sample_index=step_index,
                epoch=0,  # Indicate evaluation phase
                execution_status=execution_status.value,
                num_steps=len(trajectory.steps),
                execution_time=execution_time,
                trajectory_length=len(sample.context),
                num_bullet_tags=0,  # No reflection in evaluation
                playbook_size=self.playbook.__len__(),
                tgc=tgc,
                unit_tests_passed=unit_tests_passed,
                unit_tests_total=unit_tests_total
            )
            self.logger.log_task_metrics(metrics, phase=phase)

        # Return result without reflection/curator outputs
        # Create dummy reflection and curator outputs for compatibility
        from src.opence.methods.ace.roles import ReflectorOutput, CuratorOutput
        from src.opence.methods.ace.playbook import DeltaBatch

        dummy_reflection = ReflectorOutput(
            reasoning="(Evaluation mode - no reflection)",
            error_identification="",
            root_cause_analysis="",
            correct_approach="",
            key_insight="",
            raw={},
            bullet_tags=[]
        )
        dummy_curator_output = CuratorOutput(
            raw={},
            delta=DeltaBatch(reasoning="(Evaluation mode - no curation)", operations=[])
        )

        return AdapterStepResult(
            sample=sample,
            generator_output=final_generator_output,
            environment_result=env_result,
            reflection=dummy_reflection,
            curator_output=dummy_curator_output,
            playbook_snapshot=self.playbook.as_prompt(),
        )


class AppWorldOfflineAdapter(AppWorldAdapterBase):
    """Runs multi-epoch offline adaptation on AppWorld training split, then evaluates on test split.

    Key differences from base OfflineAdapter:
    1. Uses AppWorldGenerator with task-specific parameters
    2. Extracts user info from sample.metadata
    3. After training completes, runs inference on test data with frozen playbook
    
    Example:
        ```python
        from appworld_experiment.appworld_adaptation import AppWorldOfflineAdapter
        from appworld_experiment.appworld_roles import (
            AppWorldGenerator, AppWorldReflector, AppWorldCurator
        )
        from opence.models.clients import OpenAIClient
        from opence.methods.ace import Playbook

        llm = OpenAIClient(model="gpt-4")
        adapter = AppWorldOfflineAdapter(
            playbook=Playbook(),
            generator=AppWorldGenerator(llm),
            reflector=AppWorldReflector(llm),
            curator=AppWorldCurator(llm)
        )

        # Run training then test (playbook frozen after training)
        train_results, test_results = adapter.run(
            train_samples, test_samples, environment, epochs=3
        )
        ```
    """

    def __init__(
        self,
        *,
        playbook: Optional[Playbook] = None,
        generator: AppWorldGenerator,
        reflector: AppWorldReflector,
        curator: AppWorldCurator,
        deduplicator: Optional[OllamaDeduplicator] = None,
        dedup_frequency: int = 0,
        max_refinement_rounds: int = 1,
        max_interaction_steps: int = 10,
        logger=None,
    ) -> None:
        """Initialize AppWorld offline adapter.

        Args:
            playbook: Initial playbook
            generator: AppWorldGenerator instance
            reflector: AppWorldReflector instance
            curator: AppWorldCurator instance
            deduplicator: Optional deduplicator for playbook cleanup
            dedup_frequency: Perform deduplication every N samples.
                             0 = once per epoch (default),
                             N > 0 = every N samples
            max_refinement_rounds: Reflector refinement iterations
            max_interaction_steps: Maximum number of agent-environment interaction steps
            logger: Optional ExperimentLogger for tracking
        """
        super().__init__(
            playbook=playbook,
            generator=generator,
            reflector=reflector,
            curator=curator,
            max_refinement_rounds=max_refinement_rounds,
            max_interaction_steps=max_interaction_steps,
            logger=logger,
        )
        self.deduplicator = deduplicator
        self.dedup_frequency = dedup_frequency
        self.sgc_cnt = {}

    def run(
        self,
        train_samples: Sequence[Sample],
        test_samples: Sequence[Sample],
        environment: TaskEnvironment,
        epochs: int = 1,
    ) -> tuple[List[AdapterStepResult], List[AdapterStepResult]]:
        """Run offline adaptation loop for multiple epochs, then evaluate on test data.

        Offline adaptation has two phases:
        1. Training Phase: Process train samples with full Generator → Environment →
           Reflector → Curator loop. Playbook is updated after each sample.
        2. Evaluation Phase: Process test samples with Generator only. Playbook is
           frozen and not updated.

        Args:
            train_samples: Sequence of train Samples to process (with metadata
                containing user info and ground truth)
            test_samples: Sequence of test Samples to process (with metadata
                containing user info but no ground truth)
            environment: TaskEnvironment for evaluation
            epochs: Number of training epochs

        Returns:
            Tuple of (train_results, test_results) containing AdapterStepResults
        """
        # ==================== Training Phase ====================
        self._log_info("=" * 60)
        self._log_info("Starting TRAINING PHASE (Playbook Learning)")
        self._log_info(f"Training samples: {len(train_samples)}, Epochs: {epochs}")
        self._log_info("=" * 60)

        train_results: List[AdapterStepResult] = []
        total_train_steps = len(train_samples)
        bullet_ids_buffer = []  # Buffer for collecting bullet IDs
        train_sample_counter = 0  # Track total train samples processed

        for epoch_idx in range(1, epochs + 1):
            self._log_info(f"[Training] Epoch {epoch_idx}/{epochs}")
            for step_idx, sample in enumerate(train_samples, start=1):
                self._log_info(f"[Training] Processing sample {step_idx}/{total_train_steps}")
                result = self._process_sample(
                    sample,
                    environment,
                    epoch=epoch_idx,
                    step_index=step_idx,
                    phase="train",
                )
                train_results.append(result)

                # Collect bullet IDs
                new_bullet_ids = [
                    op.bullet_id
                    for op in result.curator_output.delta.operations
                    if op.bullet_id
                ]
                bullet_ids_buffer.extend(new_bullet_ids)
                train_sample_counter += 1

                # Sample-based deduplication (if enabled)
                if self.deduplicator and self.dedup_frequency > 0:
                    if train_sample_counter % self.dedup_frequency == 0:
                        self._log_info(f"[Deduplication] Processing after {train_sample_counter} samples")
                        self.playbook.deduplicate(self.deduplicator, bullet_ids_buffer)
                        bullet_ids_buffer = []  # Clear buffer after dedup

        # Final deduplication for any remaining bullets in buffer
        if self.deduplicator and bullet_ids_buffer:
            self._log_info(f"[Deduplication] Final processing for remaining {len(bullet_ids_buffer)} bullets")
            self.playbook.deduplicate(self.deduplicator, bullet_ids_buffer)

        self._log_info("=" * 60)
        self._log_info("TRAINING PHASE COMPLETE")
        self._log_info(f"Final playbook size: {self.playbook.__len__()} bullets")
        self._log_info("=" * 60)

        # ==================== Evaluation Phase ====================
        self._log_info("=" * 60)
        self._log_info("Starting EVALUATION PHASE (Frozen Playbook)")
        self._log_info(f"Test samples: {len(test_samples)}")
        self._log_info("Note: Only Generator runs. No Reflector/Curator updates.")
        self._log_info("=" * 60)

        test_results: List[AdapterStepResult] = []
        total_test_steps = len(test_samples)

        for step_idx, sample in enumerate(test_samples, start=1):
            self._log_info(f"[Evaluation] Processing sample {step_idx}/{total_test_steps}")
            result = self._evaluation_sample(
                sample,
                environment,
                step_index=step_idx,
            )
            test_results.append(result)

        self._log_info("=" * 60)
        self._log_info("EVALUATION PHASE COMPLETE")
        self._log_info(f"Processed {len(test_results)} test samples")
        self._log_info("=" * 60)

        return train_results, test_results


class AppWorldOnlineAdapter(AppWorldAdapterBase):
    """Processes AppWorld samples with continuous playbook learning.

    Online adaptation processes each sample through the full learning loop:
    Generator → Environment → Reflector → Curator

    The playbook is updated AFTER EACH SAMPLE, enabling continuous learning
    where knowledge gained from one task immediately benefits subsequent tasks.

    Key characteristics:
    1. Uses AppWorldGenerator with task-specific parameters
    2. Extracts user info from sample.metadata
    3. Updates playbook after EVERY sample (continuous learning)
    4. Supports sample-based deduplication
    5. No separate training/evaluation phases - always learning

    Comparison with OfflineAdapter:
    - Offline: Train on dataset → Freeze playbook → Evaluate
    - Online: Learn continuously on each sample (no freeze)

    Example:
        ```python
        from appworld_experiment.appworld_adaptation import AppWorldOnlineAdapter

        adapter = AppWorldOnlineAdapter(
            playbook=Playbook(),  # Can be empty or pre-populated
            generator=AppWorldGenerator(llm),
            reflector=AppWorldReflector(llm),
            curator=AppWorldCurator(llm),
            deduplicator=OllamaDeduplicator("qwen3-embedding"),
            dedup_frequency=5,  # Deduplicate every 5 samples
        )

        # Process samples with continuous learning
        results = adapter.run(sample_stream, environment)
        # Playbook is updated after each sample
        ```
    """

    def __init__(
        self,
        *,
        playbook: Optional[Playbook] = None,
        generator: AppWorldGenerator,
        reflector: AppWorldReflector,
        curator: AppWorldCurator,
        deduplicator: Optional[OllamaDeduplicator] = None,
        dedup_frequency: int = 0,
        max_refinement_rounds: int = 1,
        max_interaction_steps: int = 10,
        logger=None,
    ) -> None:
        """Initialize AppWorld online adapter.

        Args:
            playbook: Initial playbook
            generator: AppWorldGenerator instance
            reflector: AppWorldReflector instance
            curator: AppWorldCurator instance
            deduplicator: Optional deduplicator for playbook cleanup
            dedup_frequency: Perform deduplication every N samples.
                             0 = no deduplication (default),
                             N > 0 = every N samples
            max_refinement_rounds: Reflector refinement iterations
            max_interaction_steps: Maximum number of agent-environment interaction steps
            logger: Optional ExperimentLogger for tracking
        """
        super().__init__(
            playbook=playbook,
            generator=generator,
            reflector=reflector,
            curator=curator,
            max_refinement_rounds=max_refinement_rounds,
            max_interaction_steps=max_interaction_steps,
            logger=logger,
        )
        self.deduplicator = deduplicator
        self.dedup_frequency = dedup_frequency
        self.sgc_cnt = {}

    def run(
        self,
        samples: Iterable[Sample],
        environment: TaskEnvironment,
    ) -> List[AdapterStepResult]:
        """Run online adaptation with continuous playbook learning.

        Each sample goes through the full learning loop:
        1. Generator produces code based on current playbook
        2. Environment executes code and provides feedback
        3. Reflector analyzes execution and tags playbook bullets
        4. Curator updates playbook based on reflection

        The playbook evolves continuously - knowledge from each task
        immediately benefits subsequent tasks.

        Args:
            samples: Iterable of Samples (can be infinite stream, with metadata)
            environment: TaskEnvironment for evaluation

        Returns:
            List of AdapterStepResult for all processed samples
        """
        self._log_info("=" * 60)
        self._log_info("Starting ONLINE ADAPTATION (Continuous Learning)")
        self._log_info("Playbook will be updated after each sample")
        self._log_info("=" * 60)

        results: List[AdapterStepResult] = []
        bullet_ids_buffer = []  # Buffer for collecting bullet IDs
        sample_counter = 0  # Track samples processed

        for step_idx, sample in enumerate(samples, start=1):
            self._log_info(f"[Online] Processing sample {step_idx}")
            result = self._process_sample(
                sample,
                environment,
                epoch=1,
                step_index=step_idx,
            )
            results.append(result)

            # Collect bullet IDs
            new_bullet_ids = [
                op.bullet_id
                for op in result.curator_output.delta.operations
                if op.bullet_id
            ]
            bullet_ids_buffer.extend(new_bullet_ids)
            sample_counter += 1

            # Sample-based deduplication (if enabled)
            if self.deduplicator and self.dedup_frequency > 0:
                if sample_counter % self.dedup_frequency == 0:
                    self._log_info(f"[Deduplication] Processing after {sample_counter} samples")
                    self.playbook.deduplicate(self.deduplicator, bullet_ids_buffer)
                    bullet_ids_buffer = []  # Clear buffer after dedup

        # Final deduplication for any remaining bullets in buffer
        if self.deduplicator and bullet_ids_buffer:
            self._log_info(f"[Deduplication] Final processing for remaining {len(bullet_ids_buffer)} bullets")
            self.playbook.deduplicate(self.deduplicator, bullet_ids_buffer)

        self._log_info("=" * 60)
        self._log_info("ONLINE ADAPTATION COMPLETE")
        self._log_info(f"Processed {len(results)} samples")
        self._log_info(f"Final playbook size: {self.playbook.__len__()} bullets")
        self._log_info("=" * 60)

        return results
        
class AppworldBaselineAdapter(AppWorldAdapterBase):
    """Adapter that runs only the Generator on AppWorld samples without learning.

    This baseline adapter processes each sample by generating code using
    the current playbook and executing it in the environment. No reflection
    or curation is performed, so the playbook remains unchanged.

    Key characteristics:
    1. Uses AppWorldGenerator with task-specific parameters
    2. Extracts user info from sample.metadata
    3. No Reflector or Curator - playbook is static
    4. Suitable for baseline comparisons without adaptation

    Example:
        ```python
        from appworld_experiment.appworld_adaptation import AppworldBaselineAdapter

        adapter = AppworldBaselineAdapter(
            playbook=Playbook(),  # Can be empty or pre-populated
            generator=AppWorldGenerator(llm),
        )

        # Process samples without learning
        results = adapter.run(sample_stream, environment)
        # Playbook remains unchanged
        ```
    """

    def __init__(
        self,
        *,
        playbook: Optional[Playbook] = Playbook(),
        generator: AppWorldGenerator,
        max_interaction_steps: int = 10,
        logger=None,
    ) -> None:
        """Initialize AppWorld baseline adapter.

        Args:
            playbook: Initial playbook
            generator: AppWorldGenerator instance
            max_interaction_steps: Maximum number of agent-environment interaction steps
            logger: Optional ExperimentLogger for tracking
        """
        self.generator = generator
        self.max_interaction_steps = max_interaction_steps
        self.logger = logger
        self.playbook = playbook
        self.sgc_cnt = {}

    def run(
        self,
        samples: Iterable[Sample],
        environment: TaskEnvironment,
    ) -> List[AdapterStepResult]:
        """Run baseline adaptation without learning.

        Each sample is processed through:
        1. Generator produces code based on current playbook
        2. Environment executes code and provides feedback

        No reflection or curation is performed, so the playbook remains static.

        Args:
            samples: Iterable of Samples (can be infinite stream, with metadata)
            environment: TaskEnvironment for evaluation
        Returns:
            List of AdapterStepResult for all processed samples
        """
        self._log_info("=" * 60)
        self._log_info("Starting BASELINE ADAPTATION (No Learning)")
        self._log_info("Playbook will remain unchanged")
        self._log_info("=" * 60)

        results: List[AdapterStepResult] = []

        for step_idx, sample in enumerate(samples, start=1):
            self._log_info(f"[Baseline] Processing sample {step_idx}")
            result = self._evaluation_sample(
                sample,
                environment,
                step_index=step_idx,
                phase="baseline"
            )
            results.append(result)

        self._log_info("=" * 60)
        self._log_info("BASELINE ADAPTATION COMPLETE")
        self._log_info(f"Processed {len(results)} samples")
        self._log_info("=" * 60)

        return results
