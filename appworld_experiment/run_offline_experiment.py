#!/usr/bin/env python3
"""Run a minimal ACE offline adaptation loop with a local transformers model."""

from __future__ import annotations

import argparse
import json
import httpx
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List
import os

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for candidate in (SRC, ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from src.opence.methods.ace import (
    EnvironmentResult,
    Playbook,
    Sample,
    TaskEnvironment,
    OpenAIClient
)
from src.opence.methods.ace.deduplication import Deduplicator
from appworld_experiment.appworld_adaptation import AppWorldOfflineAdapter
from appworld_experiment.appworld_roles import (
    AppWorldGenerator,
    AppWorldReflector,
    AppWorldCurator,
)

# Appworld dataset, environment, and sample definitions 
class AppWorldDataset:
    def __init__(self, data_path: str):
        self.data_path = data_path

    def load_and_clean_ground_truth(self, file_path):
        """
        讀取 Ground Truth Python 檔案，移除雜訊，並格式化為 Prompt 可用的字串。
        """
        if not os.path.exists(file_path):
            return "No ground truth code available."

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 重新組合成字串
        code_content = "".join(lines).strip()
        
        # 3. 加上 Markdown 格式
        formatted_code = f"```python\n{code_content}\n```"
        
        return formatted_code

    def load_samples(self, split: str = "train") -> List[AppWorldSample]:
        """Dataset have train/dev/test_normal/test_challenge splits."""
        
        file_path = Path(self.data_path,"datasets", split + ".txt")
        tasks_id = []
        # loading samples id from txt file
        with open(file_path, 'r', encoding='utf-8') as f:
            id = f.readlines()
            tasks_id.extend([i.strip() for i in id])

        samples = []
        # loading task data from json file
        for task_id in tasks_id:
            # task data path
            task_data_path =Path(self.data_path, "tasks", task_id)

            # spec file
            task_file = Path(task_data_path,"specs.json")
            with open(task_file, 'r', encoding='utf-8') as f:
                task_data = json.load(f)

            # ground truth file (only for train split)
            gt_data = None
            if(split=="train"):
                task_gt_path = Path(task_data_path, "ground_truth", "compiled_solution.py")
                gt_data = self.load_and_clean_ground_truth(task_gt_path)

            sample = AppWorldSample(
                task_id=task_id,
                question=task_data.get('instruction', ''),
                metadata=task_data.get('supervisor', {}),
                datetime=task_data.get('datetime', ''),
                ground_truth=gt_data
            )
            samples.append(sample)

            print(f"Successfully loaded task: {task_id}")
        
        print(f"Loaded {len(samples)} samples for split: {split}")
        return samples

@dataclass
class AppWorldSample(Sample):
    """
        AppWorld task sample.
        Base on the Sample class, extend with AppWorld-specific fields.
        question: instruction
        metadata: supervisor
    """
    task_id: str = ""
    datetime: str = ""

class AppWorldEnvironment(TaskEnvironment):
    """AppWorld Environment providing HTTP API interface for agent-environment interaction.

    This class provides methods for:
    - Session management (initialize_task, close_task)
    - Code execution (execute_code)
    - Status checking (check_task_completion, is_task_completed)
    - Evaluation (evaluate_task, evaluate)
    """

    def __init__(self, base_url: str = "http://localhost:8777", logger=None):
        """Initialize AppWorld environment client.

        Args:
            base_url: Base URL of the AppWorld server
            logger: Optional ExperimentLogger instance for logging
        """
        self.client = httpx.Client(base_url=base_url, timeout=120)
        self.logger = logger

    # ==================== Session Management ====================

    def initialize_task(self, sample: AppWorldSample) -> dict:
        """Initialize a task session in AppWorld.

        Args:
            sample: AppWorldSample containing task_id

        Returns:
            Response dictionary from the server
        """
        response = self.client.post("/initialize", json={
            "task_id": sample.task_id,
            "experiment_name": "ace_experiment_1"
        })
        result = response.json()
        print(f"\nInitialized task {sample.task_id}\n")
        return result

    def close_task(self, task_id: str) -> dict:
        """Close a task session and clean up resources.

        Args:
            task_id: Task ID to close

        Returns:
            Response dictionary from the server
        """
        response = self.client.post("/close_all", json={"task_id": task_id})
        result = response.json()
        print(f"Closed task {task_id}")
        return result

    # ==================== Code Execution ====================

    def execute_code(self, task_id: str, code: str) -> dict:
        """Execute Python code in the AppWorld environment.

        This is the core execution method used by both single-step and multi-step workflows.

        Args:
            task_id: Task ID for the current task
            code: Python code to execute

        Returns:
            Dictionary with execution result:
                - output: stdout/stderr from execution
                - status: execution status
                - ... other fields from AppWorld API
        """
        if self.logger:
            self.logger.debug(f"Executing code for task {task_id}")
            self.logger.debug(f"Code:\n{code}")
        print(f"\nExecuting code for task {task_id}...")
        print(f"Code:\n{code}\n")

        payload = {
            "task_id": task_id,
            "code": code
        }

        response = self.client.post("/execute", json=payload)
        result = response.json()

        if self.logger:
            self.logger.debug(f"Execution result: {result.get('status', 'unknown')}")
        print(f"Execution response: {response.text}")
        return result

    # ==================== Status Checking ====================

    def check_task_completion(self, task_id: str) -> dict:
        """Check if apis.supervisor.complete_task() has been called.

        This is the primary method to query task completion status.

        Args:
            task_id: Task ID for the current task

        Returns:
            Dictionary with completion status:
                - output: True/False indicating if complete_task() was called
                - ... other fields from AppWorld API
        """
        response = self.client.post("/task_completed", json={"task_id": task_id})
        result = response.json()
        return result

    def is_task_completed(self, task_id: str) -> bool:
        """Convenience method to check if task is completed (returns boolean).

        Args:
            task_id: Task ID for the current task

        Returns:
            True if complete_task() was called, False otherwise
        """
        result = self.check_task_completion(task_id)
        return bool(result.get("output", False))

    # ==================== Evaluation ====================

    def evaluate_task(self, task_id: str, suppress_errors: bool = True, report: bool = True) -> dict:
        """Evaluate the task with unit tests and get detailed results.

        This calls the AppWorld /evaluate endpoint to run unit tests.

        Args:
            task_id: Task ID for the current task
            suppress_errors: Whether to suppress errors in the report
            report: Whether to include detailed test report

        Returns:
            Dictionary with unit test results:
                - output: detailed test report string
                - ... other fields from AppWorld API
        """
        payload = {
            "task_id": task_id,
            "suppress_errors": suppress_errors,
            "report": report
        }
        response = self.client.post("/evaluate", json=payload)
        result = response.json()
        print(f"Unit test evaluation: {response.text}")
        return result

    def evaluate(self, sample: AppWorldSample, generator_output) -> EnvironmentResult:
        """TaskEnvironment interface method for single-step evaluation.

        This method implements the TaskEnvironment.evaluate() interface for
        compatibility with base ACE adaptation. For multi-step interaction,
        use the granular methods instead (initialize_task, execute_code, etc.).

        Args:
            sample: AppWorldSample with task information
            generator_output: GeneratorOutput containing generated code

        Returns:
            EnvironmentResult with feedback and metrics
        """
        # 1. Initialize task session
        self.initialize_task(sample)

        # 2. Execute generated code
        code = generator_output.final_answer
        exec_result = self.execute_code(sample.task_id, code)

        # 3. Check completion status
        completion_status = self.check_task_completion(sample.task_id)

        # 4. Evaluate with unit tests
        unit_test_result = self.evaluate_task(sample.task_id)
        unit_test_output = unit_test_result.get("output", "")

        # Parse unit test results for TGC
        from appworld_experiment.experiment_logger import parse_unit_test_results
        unit_tests_passed, unit_tests_total = parse_unit_test_results(unit_test_output)
        tgc = unit_tests_passed / unit_tests_total if unit_tests_total > 0 else 0.0

        # 5. Close task session
        self.close_task(sample.task_id)

        # 6. Return consolidated result
        return EnvironmentResult(
            feedback=f"Execution: {exec_result}\nUnit Tests: {unit_test_output}",
            ground_truth=sample.ground_truth,
            metrics={
                "completed": 1.0 if completion_status.get("output") else 0.0,
                "execution_status": exec_result.get("status", "unknown"),
                "tgc": tgc,
                "unit_tests_passed": unit_tests_passed,
                "unit_tests_total": unit_tests_total
            }
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature for generation.",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default="gpt-oss:20b",
        help="Your model name (default: gpt-oss:20b)",
    )
    return parser.parse_args()


def main() -> None:
    from appworld_experiment.experiment_logger import ExperimentLogger, ExperimentConfig
    from datetime import datetime

    # Setup experiment logging
    experiment_name = f"appworld_ace_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logger = ExperimentLogger(experiment_name=experiment_name)

    # Parse command-line arguments
    args = parse_args()
    
    # Configuration
    model_name = args.model_name
    max_interaction_steps = 5
    max_refinement_rounds = 1
    epochs = 3

    # Log configuration
    dataset = AppWorldDataset("/home/yanhong/appworld-server/data")
    samples: List[Sample] = dataset.load_samples(split="train")

    config = ExperimentConfig(
        experiment_name=experiment_name,
        model=model_name,
        max_interaction_steps=max_interaction_steps,
        max_refinement_rounds=max_refinement_rounds,
        reflection_window=3,
        epochs=epochs,
        num_samples=len(samples),
        timestamp=datetime.now().isoformat()
    )
    logger.log_config(config)

    # Initialize LLM client
    client = OpenAIClient(
        model=model_name,
        api_key="ollama",
        base_url="http://hc5.isl.lab.nycu.edu.tw:11434/v1"
    )

    # Use AppWorld-specific roles
    generator = AppWorldGenerator(client)
    reflector = AppWorldReflector(client)
    curator = AppWorldCurator(client)

    # Use AppWorld-specific adapter with logger
    adapter = AppWorldOfflineAdapter(
        playbook=Playbook(),
        generator=generator,
        reflector=reflector,
        curator=curator,
        max_refinement_rounds=max_refinement_rounds,
        max_interaction_steps=max_interaction_steps,
        deduplicator=Deduplicator("all-MiniLM-L6-v2"),
        logger=logger,
    )

    # Create environment with logger
    environment = AppWorldEnvironment(logger=logger)

    logger.info("Starting offline adaptation with AppWorld-specific adapter...")
    print("Starting offline adaptation with AppWorld-specific adapter...")

    try:
        results = adapter.run(samples, environment, epochs=epochs)

        # Log experiment summary
        logger.log_experiment_summary()

        # Print results
        for step, result in enumerate(results, start=1):
            print(f"\nStep {step}:")
            print(f"  Question: {result.sample.question}")
            print(f"  Model final answer: {result.generator_output.final_answer}")
            print(f"  Feedback: {result.environment_result.feedback}")
            print("  Reflection:")
            print(json.dumps(result.reflection.raw, ensure_ascii=False, indent=2))
            print("  Curator operations:")
            print(json.dumps(result.curator_output.raw, ensure_ascii=False, indent=2))

        print("\nFinal playbook:\n")
        print(adapter.playbook.as_prompt() or "(playbook is empty)")

    except Exception as e:
        logger.error(f"Experiment failed with error: {str(e)}", exc_info=True)
        raise
    finally:
        logger.info("Experiment finished")
        logger.info(f"Logs saved to: {logger.log_dir}")


if __name__ == "__main__":
    main()
