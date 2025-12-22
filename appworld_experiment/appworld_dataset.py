"""AppWorld Dataset and Sample classes.

This module provides classes for loading and representing AppWorld task data:
- AppWorldSample: Dataclass representing a single task sample
- AppWorldDataset: Dataset loader for AppWorld task files
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

from src.opence.methods.ace.adaptation import Sample

# Fallback logger
_fallback_logger = logging.getLogger(__name__)


@dataclass
class AppWorldSample(Sample):
    """AppWorld task sample.

    Extends the base Sample class with AppWorld-specific fields.

    Attributes:
        question: Task instruction
        context: Additional context (used for trajectory storage)
        ground_truth: Ground truth solution (only for train split)
        metadata: Supervisor information (first_name, last_name, email, phone_number)
        task_id: Unique task identifier
        datetime: Task datetime context
    """
    task_id: str = ""
    datetime: str = ""


class AppWorldDataset:
    """Dataset loader for AppWorld tasks.

    Loads task samples from AppWorld dataset files. The dataset is organized as:
    - datasets/: Contains split files (train.txt, dev.txt, test_normal.txt, test_challenge.txt)
    - tasks/: Contains task JSON files with specs and ground truth

    Example:
        ```python
        dataset = AppWorldDataset("/path/to/appworld-server/data")
        train_samples = dataset.load_samples(split="train")
        test_samples = dataset.load_samples(split="test_normal")
        ```
    """

    def __init__(self, data_path: str):
        """Initialize dataset with path to AppWorld data directory.

        Args:
            data_path: Path to AppWorld data directory containing datasets/ and tasks/
        """
        self.data_path = data_path

    def load_and_clean_ground_truth(self, file_path: str) -> str:
        """Load and format ground truth Python code from file.

        Args:
            file_path: Path to the ground truth Python file

        Returns:
            Formatted code string wrapped in markdown code block,
            or "No ground truth code available." if file doesn't exist
        """
        if not os.path.exists(file_path):
            return "No ground truth code available."

        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # Combine into string
        code_content = "".join(lines).strip()

        # Add Markdown format
        formatted_code = f"```python\n{code_content}\n```"

        return formatted_code

    def load_samples(self, split: str = "train") -> List[AppWorldSample]:
        """Load samples from a specific dataset split.

        Args:
            split: Dataset split to load. One of:
                - "train": Training data with ground truth
                - "dev": Development/validation data
                - "test_normal": Normal difficulty test data
                - "test_challenge": Challenge difficulty test data

        Returns:
            List of AppWorldSample instances

        Raises:
            FileNotFoundError: If split file or task files don't exist
        """
        file_path = Path(self.data_path, "datasets", split + ".txt")
        tasks_id = []

        # Load sample IDs from txt file
        with open(file_path, 'r', encoding='utf-8') as f:
            id_lines = f.readlines()
            tasks_id.extend([i.strip() for i in id_lines])

        samples = []

        # Load task data from JSON files
        for task_id in tasks_id:
            # Task data path
            task_data_path = Path(self.data_path, "tasks", task_id)

            # Spec file
            task_file = Path(task_data_path, "specs.json")
            with open(task_file, 'r', encoding='utf-8') as f:
                task_data = json.load(f)

            # Ground truth file (only for train split)
            gt_data = None
            if split == "train":
                task_gt_path = Path(task_data_path, "ground_truth", "compiled_solution.py")
                gt_data = self.load_and_clean_ground_truth(str(task_gt_path))

            sample = AppWorldSample(
                task_id=task_id,
                question=task_data.get('instruction', ''),
                metadata=task_data.get('supervisor', {}),
                datetime=task_data.get('datetime', ''),
                ground_truth=gt_data
            )
            samples.append(sample)
            _fallback_logger.debug(f"Successfully loaded task: {task_id}")

        _fallback_logger.info(f"Loaded {len(samples)} samples for split: {split}")
        return samples[:1]
