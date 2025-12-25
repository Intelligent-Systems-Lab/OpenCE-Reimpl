"""AppWorld Environment for agent-environment interaction.

This module provides the AppWorldEnvironment class that handles HTTP API
interactions with the AppWorld server for multi-step task execution.
"""

from __future__ import annotations

import logging
import httpx
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from appworld_experiment.experiment_logger import ExperimentLogger
    from appworld_experiment.appworld_dataset import AppWorldSample

# Fallback logger for when ExperimentLogger is not provided
_fallback_logger = logging.getLogger(__name__)


class AppWorldEnvironment:
    """AppWorld Environment providing HTTP API interface for agent-environment interaction.

    This class provides methods for:
    - Session management (initialize_task, close_task)
    - Code execution (execute_code)
    - Status checking (is_task_completed)
    - Evaluation (evaluate_task)
    """

    def __init__(self, base_url: str = "http://localhost:8777", logger: Optional["ExperimentLogger"] = None):
        """Initialize AppWorld environment client.

        Args:
            base_url: Base URL of the AppWorld server
            logger: Optional ExperimentLogger instance for logging
        """
        self.client = httpx.Client(base_url=base_url, timeout=120)
        self.logger = logger

    def _log_info(self, message: str) -> None:
        """Log info message using ExperimentLogger or fallback to standard logging."""
        if self.logger:
            self.logger.info(message)
        else:
            _fallback_logger.info(message)

    # ==================== Session Management ====================

    def initialize_task(self, sample: "AppWorldSample") -> dict:
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
        self._log_info(f"Initialized task {sample.task_id}")
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
        self._log_info(f"Closed task {task_id}")
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
        self._log_info(f"Executing code for task {task_id}")
        self._log_info(f"Code:\n{code}")

        payload = {
            "task_id": task_id,
            "code": code
        }

        response = self.client.post("/execute", json=payload)
        result = response.json()

        self._log_info(f"Execution response: {response.text}")
        return result

    # ==================== Status Checking ====================

    def is_task_completed(self, task_id: str) -> bool:
        """Check if the task status is completed.

        Args:
            task_id: Task ID for the current task

        Returns:
            True if task status is completed, False otherwise
        """
        response = self.client.post("/task_completed", json={"task_id": task_id})
        result = response.json()
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
        for i in range(3):  # Retry up to 3 times
            try:
                response = self.client.post("/evaluate", json=payload)
                result = response.json()
                self._log_info(f"Unit test evaluation: {response.text}")
                return result
            except Exception as e:
                self._log_info(f"Evaluation attempt {i+1} failed with error: {str(e)}")
        return {"output": "Evaluation failed after 3 attempts."}
            