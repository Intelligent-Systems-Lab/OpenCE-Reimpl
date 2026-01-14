#!/usr/bin/env python3
"""Run ACE offline adaptation loop with AppWorld environment.

Offline adaptation has two phases:
1. Training Phase: Learn playbook from training data (Generator → Reflector → Curator)
2. Evaluation Phase: Test with frozen playbook (Generator only, no learning)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for candidate in (SRC, ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from src.opence.methods.ace import (
    Playbook,
    Sample,
    OpenAIClient
)
from appworld_experiment.appworld_deduplication import OllamaDeduplicator
from appworld_experiment.appworld_adaptation import AppworldBaselineAdapter
from appworld_experiment.appworld_dataset import AppWorldDataset, AppWorldSample
from appworld_experiment.appworld_environment import AppWorldEnvironment
from appworld_experiment.appworld_roles import AppWorldGenerator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--temperature",
        type=float,
        default=float(os.getenv("TEMPERATURE", "0.7")),
        help="Sampling temperature for generation.",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=os.getenv("MODEL_NAME", "gpt-oss:20b"),
        help="Your model name (default from .env or gpt-oss:20b)",
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=os.getenv("BASE_URL", "http://localhost:11434/v1"),
        help="Base URL for LLM API (default from .env)",
    )
    parser.add_argument(
        "--api-key",
        type=str,
        default=os.getenv("OPENAI_API_KEY", "ollama"),
        help="API key for LLM (default from .env)",
    )
    parser.add_argument(
        "--appworld-url",
        type=str,
        default=os.getenv("APPWORLD_API_URL", "http://localhost:8777"),
        help="AppWorld API server URL (default from .env)",
    )
    parser.add_argument(
        "--max-interaction-steps",
        type=int,
        default=int(os.getenv("MAX_INTERACTION_STEPS", "5")),
        help="Maximum interaction steps per task (default from .env)",
    )
    parser.add_argument(
        "--split",
        type=str,
        default="dev",
        choices=["dev", "test_normal", "test_challenge", "difficulty_1", "difficulty_2", "difficulty_3"],
        help="Dataset split to use for baseline (dev, test_normal, test_challenge, difficulty_1, difficulty_2, difficulty_3), default: dev",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Maximum number of samples to process (for testing). Default: process all samples.",
    )
    parser.add_argument(
        "--tasks",
        type=List[str],
        default=None,
        help="Run only on specific task IDs (for testing). e.g  --tasks 07b42fd_1, 07b42fd_2 to run tasks with indices 07b42fd_1 and 07b42fd_2. Default: run all tasks.",
    )
    return parser.parse_args()


def main() -> None:
    from appworld_experiment.experiment_logger import ExperimentLogger, ExperimentConfig
    from datetime import datetime

    # Setup experiment logging
    experiment_name = f"appworld_ace_baseline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logger = ExperimentLogger(experiment_name=experiment_name)

    # Parse command-line arguments
    args = parse_args()

    # Configuration
    model_name = args.model_name
    base_url = args.base_url
    api_key = args.api_key
    appworld_url = args.appworld_url
    max_interaction_steps = args.max_interaction_steps

    # Load dataset - train split for training, test split for evaluation
    dataset = AppWorldDataset(os.getenv("APPWORLD_DATA_PATH", "/home/yanhong/appworld-server/data"))
    samples: List[Sample] = dataset.load_samples(split=args.split)

    if args.max_samples is not None:
        samples = samples[: args.max_samples]
    elif args.tasks is not None:
        task_ids = [task_id.strip() for task_id in args.tasks.split(",")]
        samples = [s for s in samples if isinstance(s, AppWorldSample) and s.task_id in task_ids]
    
    logger.info(f"Loaded {len(samples)} samples")

    config = ExperimentConfig(
        experiment_name=experiment_name,
        model=model_name,
        max_interaction_steps=max_interaction_steps,
        max_refinement_rounds=0,
        epochs=1,
        num_samples=len(samples),
        timestamp=datetime.now().isoformat()
    )
    logger.log_config(config)

    # Initialize LLM client
    client = OpenAIClient(
        model=model_name,
        api_key=api_key,
        base_url=base_url
    )

    openai_client = OpenAIClient(
        model="gpt-4o-mini",
        api_key=api_key
    )

    # Use AppWorld-specific roles with logger
    generator = AppWorldGenerator(openai_client, logger=logger)

    # Use AppWorld-specific adapter with logger
    adapter = AppworldBaselineAdapter(
        generator=generator,
        max_interaction_steps=max_interaction_steps,
        logger=logger,
    )

    # Create environment with logger
    environment = AppWorldEnvironment(base_url=appworld_url, logger=logger)

    logger.info("=" * 60)
    logger.info("BASELINE ADAPTATION EXPERIMENT")
    logger.info("=" * 60)
    logger.info(f"Mode: Baseline (no adaptation)")

    try:
        # Run offline adaptation: train then evaluate
        results = adapter.run(
            samples=samples,
            environment=environment
        )

        # Log experiment summary
        logger.log_experiment_summary()

        # Final summary
        logger.info("=" * 60)
        logger.info("FINAL SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Processed {len(samples)} samples")

    except Exception as e:
        logger.error(f"Experiment failed with error: {str(e)}", exc_info=True)
        raise
    finally:
        logger.info("Baseline adaptation finished")
        logger.info(f"Logs saved to: {logger.log_dir}")

if __name__ == "__main__":
    main()
