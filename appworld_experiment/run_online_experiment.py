#!/usr/bin/env python3
"""Run ACE online adaptation loop with AppWorld environment.

Online adaptation processes samples in a streaming fashion, updating the
playbook after each sample. This is suitable for continuous learning scenarios
where samples arrive sequentially.

Key differences from offline adaptation:
- No epochs: processes samples once in order
- Immediate playbook updates after each sample
- Suitable for production deployment and continuous learning
"""

from __future__ import annotations

import argparse
import json
import sys
import os
from pathlib import Path
from typing import List
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
from appworld_experiment.run_offline_experiment import (
    AppWorldDataset,
    AppWorldEnvironment,
    AppWorldSample
)
from appworld_experiment.appworld_adaptation import AppWorldOnlineAdapter
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
        default=float(os.getenv("TEMPERATURE", "0.0")),
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
        default=os.getenv("BASE_URL", "http://hc5.isl.lab.nycu.edu.tw:11434/v1"),
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
        "--max-samples",
        type=int,
        default=None,
        help="Maximum number of samples to process (for testing). Default: process all samples.",
    )
    parser.add_argument(
        "--split",
        type=str,
        default="dev",
        choices=["train", "dev", "test_normal", "test_challenge"],
        help="Dataset split to use. Default: dev (for online evaluation).",
    )
    return parser.parse_args()


def main() -> None:
    from appworld_experiment.experiment_logger import ExperimentLogger, ExperimentConfig
    from datetime import datetime

    args = parse_args()

    # Setup experiment logging
    experiment_name = f"appworld_ace_online_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    logger = ExperimentLogger(experiment_name=experiment_name)

    # Configuration
    model_name = args.model_name
    base_url = args.base_url
    api_key = args.api_key
    appworld_url = args.appworld_url
    max_interaction_steps = int(os.getenv("MAX_INTERACTION_STEPS", "5"))
    max_refinement_rounds = int(os.getenv("MAX_REFINEMENT_ROUNDS", "1"))

    # Load dataset
    dataset = AppWorldDataset("/home/yanhong/appworld-server/data")
    all_samples: List[Sample] = dataset.load_samples(split=args.split)

    # Limit samples if specified
    if args.max_samples:
        samples = all_samples[:args.max_samples]
        logger.info(f"Limited to {args.max_samples} samples (out of {len(all_samples)})")
    else:
        samples = all_samples

    # Log configuration
    config = ExperimentConfig(
        experiment_name=experiment_name,
        model=model_name,
        max_interaction_steps=max_interaction_steps,
        max_refinement_rounds=max_refinement_rounds,
        reflection_window=3,
        epochs=1,  # Online adaptation is single-pass
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

    # Use AppWorld-specific roles with logger
    generator = AppWorldGenerator(client, logger=logger)
    reflector = AppWorldReflector(client, logger=logger)
    curator = AppWorldCurator(client, logger=logger)

    # Use AppWorld online adapter with logger
    from src.opence.methods.ace.deduplication import Deduplicator

    adapter = AppWorldOnlineAdapter(
        playbook=Playbook(),
        generator=generator,
        reflector=reflector,
        curator=curator,
        max_refinement_rounds=max_refinement_rounds,
        max_interaction_steps=max_interaction_steps,
        deduplicator=Deduplicator(model_name=args.deduplication_model) if args.dedup_frequency > 0 else None,
        dedup_frequency=args.dedup_frequency,
        logger=logger,
    )

    # Create environment with logger
    environment = AppWorldEnvironment(base_url=appworld_url, logger=logger)

    logger.info("Starting online adaptation with AppWorld...")
    logger.info(f"Processing {len(samples)} samples from {args.split} split")
    
    logger.info(f"Starting online adaptation with AppWorld...")
    logger.info(f"Processing {len(samples)} samples from {args.split} split")
    

    try:
        # Run online adaptation (processes samples sequentially)
        results = adapter.run(samples, environment)

        # Log experiment summary
        logger.log_experiment_summary()

        # Print summary
        
        logger.info(f"Online Adaptation Complete")
        
        logger.info(f"Processed {len(results)} samples")
        logger.info(f"\nFinal playbook ({len(adapter.playbook.as_prompt().split(chr(10)) if adapter.playbook.as_prompt() else [])} lines):")
        logger.info(adapter.playbook.as_prompt() or "(playbook is empty)")
        

    except Exception as e:
        logger.error(f"Experiment failed with error: {str(e)}", exc_info=True)
        raise
    finally:
        logger.info("Online adaptation finished")
        logger.info(f"Logs saved to: {logger.log_dir}")


if __name__ == "__main__":
    main()
