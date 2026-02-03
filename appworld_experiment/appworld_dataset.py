"""AppWorld Dataset and Sample classes.

This module provides classes for loading and representing AppWorld task data:
- AppWorldSample: Dataclass representing a single task sample
- AppWorldDataset: Dataset loader for AppWorld task files
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

from src.opence.methods.ace.adaptation import Sample
from appworld_experiment.appworld_environment import AppWorldEnvironment

# Fallback logger
_fallback_logger = logging.getLogger(__name__)


@dataclass
class AppWorldSample(Sample):
    """AppWorld task sample.

    Extends the base Sample class with AppWorld-specific fields.

    Attributes:
        question: Task instruction
        context: Additional context (used for trajectory storage)
        metadata: Supervisor information (first_name, last_name, email, phone_number)
        task_id: Unique task identifier
        datetime: Task datetime context
    """
    task_id: str = ""
    datetime: str = ""


class AppWorldDataset:
    """
    Dataset loader for AppWorld task files.

    Provides methods to load task identifiers and task data from the AppWorld
    dataset directory structure, supporting various splits like train, dev, and test.
    """
    def __init__(self, data_path: str, env: AppWorldEnvironment):
        """Initialize dataset with path to AppWorld data directory.

        Args:
            data_path: Path to AppWorld data directory containing datasets/
            env: AppWorldEnvironment instance
        """
        
        # Expand ~ to user's home directory
        data_path = os.path.expanduser(data_path)
        
        # check if data path is valid
        # if "~" in data_path, `os.path.exists` won't parse it into user's home directory
        # so we need to expand it first
        if not os.path.exists(data_path):
            raise ValueError(f"Data path not found: {data_path}, please set APPWORLD_DATA_PATH in .env file")
        
        # save the data path
        self.data_path = data_path

        # check if env is valid
        if not isinstance(env, AppWorldEnvironment):
            raise ValueError(f"Invalid environment: {env}")
        
        # save the environment
        self.env = env

    def load_task_ids(self, split: str) -> List[str]:
        """Load task IDs from a specific dataset split.

        Args:
            split: Dataset split to load. One of:
                - "train": Training data
                - "dev": Development/validation data
                - "test_normal": Normal difficulty test data
                - "test_challenge": Challenge difficulty test data

        Returns:
            List of task ID strings

        Raises:
            FileNotFoundError: If split file doesn't exist
        """
        file_path = Path(self.data_path, "datasets", split + ".txt")
        tasks_id = []

        # Load sample IDs from txt file
        with open(file_path, 'r', encoding='utf-8') as f:
            id_lines = f.readlines()
            tasks_id.extend([i.strip() for i in id_lines])

        _fallback_logger.info(f"Loaded {len(tasks_id)} task IDs for split: {split}")
        return tasks_id

    def load_samples(self, split: str = "train") -> List[AppWorldSample]:
        """Load samples from a list of task IDs.

        Args:
            split: Dataset split to load. One of:
                - "train": Training data (default)
                - "dev": Development/validation data
                - "test_normal": Normal difficulty test data
                - "test_challenge": Challenge difficulty test data
                - "difficulty_1": Difficulty 1 test data
                - "difficulty_2": Difficulty 2 test data
                - "difficulty_3": Difficulty 3 test data
        Returns:
            List of AppWorldSample instances
        """
        samples = []

        # Load task data from JSON files
        tasks_ids = self.load_task_ids(split)

        # Get task info from environment
        for task_id in tasks_ids:
            task_info = self.env.show_task_info(task_id)
            sample = AppWorldSample(
                task_id=task_id,
                question=task_info['instruction'],
                metadata=task_info['supervisor'],
                datetime=task_info['datetime']
            )
            samples.append(sample)
            _fallback_logger.debug(f"Successfully loaded task: {task_id}")

        # # shuffle samples for randomness
        # import random
        # random.shuffle(samples)

        _fallback_logger.info(f"Loaded {len(samples)} samples for split: {split}")
        return samples
