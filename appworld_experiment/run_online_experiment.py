#!/usr/bin/env python3
"""Run ACE online adaptation loop with AppWorld environment.

Online adaptation processes samples in a streaming fashion, updating the
playbook after each sample. This is suitable for continuous learning scenarios
where samples arrive sequentially.

Key differences from offline adaptation:
- No epochs: processes samples once in order
- Immediate playbook updates after each sample
- No deduplication (can be added if needed)
- Suitable for production deployment and continuous learning
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List

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
        default=0.0,
        help="Sampling temperature for generation.",
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
    model_name = "gpt-oss:20b"
    max_interaction_steps = 5
    max_refinement_rounds = 1

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
        api_key="ollama",
        base_url="http://hc5.isl.lab.nycu.edu.tw:11434/v1"
    )

    # Use AppWorld-specific roles
    generator = AppWorldGenerator(client)
    reflector = AppWorldReflector(client)
    curator = AppWorldCurator(client)

    # Use AppWorld online adapter with logger
    adapter = AppWorldOnlineAdapter(
        playbook=Playbook(),
        generator=generator,
        reflector=reflector,
        curator=curator,
        max_refinement_rounds=max_refinement_rounds,
        max_interaction_steps=max_interaction_steps,
        logger=logger,
    )

    # Create environment with logger
    environment = AppWorldEnvironment(logger=logger)

    logger.info("Starting online adaptation with AppWorld...")
    logger.info(f"Processing {len(samples)} samples from {args.split} split")
    print(f"\n{'='*80}")
    print(f"Starting online adaptation with AppWorld...")
    print(f"Processing {len(samples)} samples from {args.split} split")
    print(f"{'='*80}\n")

    try:
        # Run online adaptation (processes samples sequentially)
        results = adapter.run(samples, environment)

        # Log experiment summary
        logger.log_experiment_summary()

        # Print summary
        print(f"\n{'='*80}")
        print(f"Online Adaptation Complete")
        print(f"{'='*80}")
        print(f"Processed {len(results)} samples")
        print(f"\nFinal playbook ({len(adapter.playbook.as_prompt().split(chr(10)) if adapter.playbook.as_prompt() else [])} lines):")
        print(adapter.playbook.as_prompt() or "(playbook is empty)")
        print(f"\n{'='*80}")

    except Exception as e:
        logger.error(f"Experiment failed with error: {str(e)}", exc_info=True)
        raise
    finally:
        logger.info("Online adaptation finished")
        logger.info(f"Logs saved to: {logger.log_dir}")


if __name__ == "__main__":
    main()
