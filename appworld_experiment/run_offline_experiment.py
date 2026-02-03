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
from appworld_experiment.appworld_adaptation import AppWorldOfflineAdapter
from appworld_experiment.appworld_dataset import AppWorldDataset, AppWorldSample
from appworld_experiment.appworld_environment import AppWorldEnvironment
from appworld_experiment.appworld_roles import (
    AppWorldGenerator,
    AppWorldReflector,
    AppWorldCurator,
)


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
        "--dedup-base-url",
        type=str,
        default=os.getenv("DEDUP_BASE_URL", "http://localhost:11434"),
        help="Base URL for deduplication model (default from .env)",
    )
    parser.add_argument(
        "--deduplication-model",
        type=str,
        default=os.getenv("DEDUPLICATION_MODEL", "all-MiniLM-L6-v2"),
        help="Model name for deduplication (default from .env)",
    )
    parser.add_argument(
        "--dedup-frequency",
        type=int,
        default=int(os.getenv("DEDUP_FREQUENCY", "0")),
        help="Perform deduplication every N samples (0=disabled, >0=every N samples)",
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
        "--max-refinement-rounds",
        type=int,
        default=int(os.getenv("MAX_REFINEMENT_ROUNDS", "1")),
        help="Maximum refinement rounds per interaction (default from .env)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=int(os.getenv("EPOCHS", "3")),
        help="Number of epochs to run the offline adaptation (default from .env)",
    )
    parser.add_argument(
        "--split",
        type=str,
        default="dev",
        choices=["train", "dev", "test_normal", "test_challenge", "difficulty_1", "difficulty_2", "difficulty_3"],
        help="Dataset split to use for evaluation (dev, test_normal, test_challenge, difficulty_1, difficulty_2, difficulty_3), default: dev",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Maximum number of samples to process (for testing). Default: process all samples.",
    )
    return parser.parse_args()


def main() -> None:
    from appworld_experiment.experiment_logger import ExperimentLogger, ExperimentConfig
    from datetime import datetime

    # Setup experiment logging
    experiment_name = f"appworld_ace_offline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logger = ExperimentLogger(experiment_name=experiment_name)

    # Parse command-line arguments
    args = parse_args()

    # Configuration
    model_name = args.model_name
    base_url = args.base_url
    api_key = args.api_key
    appworld_url = args.appworld_url
    max_interaction_steps = args.max_interaction_steps
    max_refinement_rounds = args.max_refinement_rounds
    epochs = args.epochs
    max_samples = args.max_samples

    # Create environment with logger
    environment = AppWorldEnvironment(base_url=appworld_url, logger=logger)

    # Load dataset - train split for training, test split for evaluation
    dataset = AppWorldDataset(os.getenv("APPWORLD_DATA_PATH", "None"), env=environment)
    train_samples: List[Sample] = dataset.load_samples(split=args.split)
    test_samples: List[Sample] = dataset.load_samples(split=args.split)

    if max_samples is not None:
        train_samples = train_samples[:max_samples]
        test_samples = test_samples[:max_samples]

    logger.info(f"Loaded {len(train_samples)} training samples")
    logger.info(f"Loaded {len(test_samples)} test samples")

    config = ExperimentConfig(
        experiment_name=experiment_name,
        model=model_name,
        max_interaction_steps=max_interaction_steps,
        max_refinement_rounds=max_refinement_rounds,
        epochs=epochs,
        num_samples=len(train_samples) + len(test_samples),
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
        model="gpt-4o-mini-2024-07-18",
        api_key=api_key
    )

    # Use AppWorld-specific roles with logger
    generator = AppWorldGenerator(openai_client, logger=logger)
    reflector = AppWorldReflector(openai_client, logger=logger)
    curator = AppWorldCurator(openai_client, logger=logger)

    # Use AppWorld-specific adapter with logger
    adapter = AppWorldOfflineAdapter(
        playbook=Playbook(),
        generator=generator,
        reflector=reflector,
        curator=curator,
        max_refinement_rounds=max_refinement_rounds,
        max_interaction_steps=max_interaction_steps,
        deduplicator=OllamaDeduplicator(logger=logger, base_url=args.dedup_base_url, model_name=args.deduplication_model) if args.dedup_frequency > 0 else None,
        dedup_frequency=args.dedup_frequency,
        logger=logger,
    )

    logger.info("=" * 60)
    logger.info("OFFLINE ADAPTATION EXPERIMENT")
    logger.info("=" * 60)
    logger.info("Phase 1: Training - Learn playbook from training data")
    logger.info("  - Generator → Environment → Reflector → Curator loop")
    logger.info("  - Playbook is updated after each sample")
    logger.info("Phase 2: Evaluation - Test with frozen playbook")
    logger.info("  - Generator only (no Reflector/Curator)")
    logger.info("  - Playbook remains unchanged")
    logger.info("=" * 60)

    try:
        # Run offline adaptation: train then evaluate
        train_results, test_results = adapter.run(
            train_samples=train_samples,
            test_samples=test_samples,
            environment=environment,
            epochs=epochs
        )

        # Log experiment summary
        logger.log_experiment_summary()

        # Log training results summary
        logger.info("=" * 60)
        logger.info("TRAINING RESULTS SUMMARY")
        logger.info("=" * 60)
        for step, result in enumerate(train_results, start=1):
            logger.info(f"[Train] Step {step} completed")
            logger.debug(f"  Question: {result.sample.question}")
            logger.debug(f"  Model final answer: {result.generator_output.final_answer if result.generator_output else 'N/A'}")
            logger.debug(f"  Feedback: {result.environment_result.feedback}")
            logger.debug(f"  Reflection: {json.dumps(result.reflection.raw, ensure_ascii=False, indent=2)}")
            logger.debug(f"  Curator operations: {json.dumps(result.curator_output.raw, ensure_ascii=False, indent=2)}")

        # Log test results summary
        logger.info("=" * 60)
        logger.info("EVALUATION RESULTS SUMMARY")
        logger.info("=" * 60)

        if test_results:
            test_count = len(test_results)
            test_completed_count = sum(1 for r in test_results if r.environment_result.metrics.get("execution_status") == "completed")
            test_max_steps_count = sum(1 for r in test_results if r.environment_result.metrics.get("execution_status") == "max_steps_reached")
            test_crashed_count = sum(1 for r in test_results if r.environment_result.metrics.get("execution_status") == "crashed")
            test_tgc_sum = sum(r.environment_result.metrics.get("tgc", 0) for r in test_results)
            test_sgc_sum = sum(r.environment_result.metrics.get("sgc", 0) for r in test_results)
            test_avg_tgc = test_tgc_sum / test_count
            test_avg_sgc = test_sgc_sum / test_count
        else:
            test_count = 0
            test_completed_count = test_max_steps_count = test_crashed_count = 0
            test_avg_tgc = test_avg_sgc = 0

        for step, result in enumerate(test_results, start=1):
            status = result.environment_result.metrics.get("execution_status", "unknown")
            logger.info(f"[Test] Step {step} - {status}")
            logger.debug(f"  Question: {result.sample.question}")
            logger.debug(f"  Model final answer: {result.generator_output.final_answer if result.generator_output else 'N/A'}")
            logger.debug(f"  Feedback: {result.environment_result.feedback}")
            logger.debug(f"  TGC: {result.environment_result.metrics.get('tgc', 0):.2%}")

        # Final summary
        logger.info("=" * 60)
        logger.info("FINAL EXPERIMENT SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Training samples: {len(train_results)}")
        logger.info(f"Test samples: {test_count}")
        if test_count > 0:
            logger.info(f"Test execution status breakdown:")
            logger.info(f"  - Completed: {test_completed_count}/{test_count} ({test_completed_count/test_count*100:.1f}%)")
            logger.info(f"  - Max steps reached: {test_max_steps_count}/{test_count} ({test_max_steps_count/test_count*100:.1f}%)")
            logger.info(f"  - Crashed: {test_crashed_count}/{test_count} ({test_crashed_count/test_count*100:.1f}%)")
            logger.info(f"Test average TGC: {test_avg_tgc:.2%}")
            logger.info(f"Test average SGC: {test_avg_sgc:.2%}")
        logger.info(f"Final playbook size: {adapter.playbook.__len__()} bullets")
        logger.debug(f"Playbook content:\n{adapter.playbook.as_prompt() or '(playbook is empty)'}")

    except Exception as e:
        logger.error(f"Experiment failed with error: {str(e)}", exc_info=True)
        raise
    finally:
        logger.info("Experiment finished")
        logger.info(f"Logs saved to: {logger.log_dir}")


if __name__ == "__main__":
    main()
