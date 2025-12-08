#!/usr/bin/env python3
"""Run offline training followed by online evaluation to compare w/ and w/o offline training.

This script helps answer the research question:
"Does offline training on the training set improve online evaluation performance on dev/test sets?"

Workflow:
1. Run offline adaptation on train split (multiple epochs)
2. Save the trained playbook
3. Run online evaluation on dev/test split with trained playbook
4. Compare with baseline (online evaluation without offline training)

The experiment generates two sets of results:
- With offline training: offline (train) → online (dev/test)
- Without offline training: online (dev/test) from scratch

This allows comparison of TGC/SGC metrics to evaluate the benefit of offline training.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List
from datetime import datetime

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
from src.opence.methods.ace.deduplication import Deduplicator
from appworld_experiment.run_offline_experiment import (
    AppWorldDataset,
    AppWorldEnvironment,
)
from appworld_experiment.appworld_adaptation import (
    AppWorldOfflineAdapter,
    AppWorldOnlineAdapter
)
from appworld_experiment.appworld_roles import (
    AppWorldGenerator,
    AppWorldReflector,
    AppWorldCurator,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline-epochs",
        type=int,
        default=3,
        help="Number of offline training epochs (default: 3)",
    )
    parser.add_argument(
        "--offline-samples",
        type=int,
        default=None,
        help="Limit offline training samples (for testing). Default: use all train samples",
    )
    parser.add_argument(
        "--online-split",
        type=str,
        default="dev",
        choices=["dev", "test_normal", "test_challenge"],
        help="Split to use for online evaluation (default: dev)",
    )
    parser.add_argument(
        "--online-samples",
        type=int,
        default=None,
        help="Limit online evaluation samples (for testing). Default: use all",
    )
    parser.add_argument(
        "--skip-baseline",
        action="store_true",
        help="Skip baseline (w/o offline) evaluation",
    )
    parser.add_argument(
        "--save-playbook",
        type=str,
        default=None,
        help="Save trained playbook to specified path (default: auto-generated in logs)",
    )
    parser.add_argument(
        "--load-playbook",
        type=str,
        default=None,
        help="Load pre-trained playbook from specified path (skips offline training)",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default="gpt-oss:20b",
        help="Your model name (default: gpt-oss:20b)",
    )
    return parser.parse_args()


def save_playbook(playbook: Playbook, filepath: Path, logger) -> None:
    """Save playbook to JSON file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(playbook.dumps())
    logger.info(f"Playbook saved to: {filepath}")
    print(f"✓ Playbook saved to: {filepath}")


def load_playbook(filepath: Path, logger) -> Playbook:
    """Load playbook from JSON file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = f.read()
    playbook = Playbook.loads(data)
    logger.info(f"Playbook loaded from: {filepath}")
    print(f"✓ Playbook loaded from: {filepath}")
    return playbook


def run_offline_training(
    args,
    client,
    environment,
    dataset,
    logger
) -> Playbook:
    """Run offline adaptation on train split."""
    from appworld_experiment.experiment_logger import ExperimentConfig

    print(f"\n{'='*80}")
    print(f"PHASE 1: Offline Training (train split)")
    print(f"{'='*80}\n")

    # Load training samples
    all_train_samples = dataset.load_samples(split="train")
    train_samples = all_train_samples[:args.offline_samples] if args.offline_samples else all_train_samples

    logger.info(f"Offline training: {len(train_samples)} samples, {args.offline_epochs} epochs")
    print(f"Training samples: {len(train_samples)}")
    print(f"Epochs: {args.offline_epochs}\n")

    # Create offline adapter
    generator = AppWorldGenerator(client)
    reflector = AppWorldReflector(client)
    curator = AppWorldCurator(client)

    offline_adapter = AppWorldOfflineAdapter(
        playbook=Playbook(),
        generator=generator,
        reflector=reflector,
        curator=curator,
        deduplicator=Deduplicator("all-MiniLM-L6-v2"),
        max_refinement_rounds=1,
        max_interaction_steps=5,
        logger=logger,
    )

    # Run offline training
    logger.info("Starting offline training...")
    offline_results = offline_adapter.run(train_samples, environment, epochs=args.offline_epochs)

    logger.info(f"Offline training complete: {len(offline_results)} results")
    print(f"\n✓ Offline training complete")
    print(f"  Processed: {len(offline_results)} task instances")
    print(f"  Final playbook size: {len(offline_adapter.playbook.as_prompt().split(chr(10)) if offline_adapter.playbook.as_prompt() else [])} lines\n")

    return offline_adapter.playbook


def run_online_evaluation(
    args,
    client,
    environment,
    dataset,
    logger,
    playbook: Playbook,
    experiment_name_suffix: str
) -> List:
    """Run online evaluation on specified split."""
    print(f"\n{'='*80}")
    print(f"Online Evaluation ({experiment_name_suffix})")
    print(f"{'='*80}\n")

    # Load evaluation samples
    all_eval_samples = dataset.load_samples(split=args.online_split)
    eval_samples = all_eval_samples[:args.online_samples] if args.online_samples else all_eval_samples

    logger.info(f"Online evaluation: {len(eval_samples)} samples from {args.online_split} split")
    print(f"Evaluation samples: {len(eval_samples)} ({args.online_split} split)")
    print(f"Playbook size: {len(playbook.as_prompt().split(chr(10)) if playbook.as_prompt() else [])} lines\n")

    # Create online adapter
    generator = AppWorldGenerator(client)
    reflector = AppWorldReflector(client)
    curator = AppWorldCurator(client)

    online_adapter = AppWorldOnlineAdapter(
        playbook=playbook,
        generator=generator,
        reflector=reflector,
        curator=curator,
        max_refinement_rounds=1,
        max_interaction_steps=5,
        logger=logger,
    )

    # Run online evaluation
    logger.info(f"Starting online evaluation ({experiment_name_suffix})...")
    online_results = online_adapter.run(eval_samples, environment)

    logger.info(f"Online evaluation complete: {len(online_results)} results")
    print(f"\n✓ Online evaluation complete ({experiment_name_suffix})")
    print(f"  Processed: {len(online_results)} samples\n")

    return online_results


def main() -> None:
    from appworld_experiment.experiment_logger import ExperimentLogger, ExperimentConfig

    args = parse_args()

    # Setup base experiment name
    base_experiment_name = f"offline_then_online_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # Model configuration
    model_name = args.model_name

    # Initialize dataset and environment
    dataset = AppWorldDataset("/home/yanhong/appworld-server/data")

    # Phase 1: Offline Training (or load pre-trained playbook)
    if args.load_playbook:
        # Load pre-trained playbook
        print(f"\n{'='*80}")
        print(f"Loading pre-trained playbook")
        print(f"{'='*80}\n")

        offline_logger = ExperimentLogger(experiment_name=f"{base_experiment_name}_offline_loaded")
        trained_playbook = load_playbook(Path(args.load_playbook), offline_logger)
        playbook_path = Path(args.load_playbook)
    else:
        # Run offline training
        offline_logger = ExperimentLogger(experiment_name=f"{base_experiment_name}_offline")

        # Log offline config
        train_samples_count = len(dataset.load_samples(split="train")[:args.offline_samples] if args.offline_samples else dataset.load_samples(split="train"))
        offline_config = ExperimentConfig(
            experiment_name=f"{base_experiment_name}_offline",
            model=model_name,
            max_interaction_steps=5,
            max_refinement_rounds=1,
            reflection_window=3,
            epochs=args.offline_epochs,
            num_samples=train_samples_count,
            timestamp=datetime.now().isoformat()
        )
        offline_logger.log_config(offline_config)

        # Initialize client
        client = OpenAIClient(
            model=model_name,
            api_key="ollama",
            base_url="http://hc5.isl.lab.nycu.edu.tw:11434/v1"
        )

        # Create environment
        environment = AppWorldEnvironment(logger=offline_logger)

        # Run offline training
        trained_playbook = run_offline_training(args, client, environment, dataset, offline_logger)

        # Save trained playbook
        if args.save_playbook:
            playbook_path = Path(args.save_playbook)
        else:
            playbook_path = offline_logger.log_dir / "trained_playbook.json"
        save_playbook(trained_playbook, playbook_path, offline_logger)

        # Log offline experiment summary
        offline_logger.log_experiment_summary()

    # Phase 2: Online Evaluation with Trained Playbook
    online_with_offline_logger = ExperimentLogger(experiment_name=f"{base_experiment_name}_online_with_offline")

    # Log online config
    eval_samples_count = len(dataset.load_samples(split=args.online_split)[:args.online_samples] if args.online_samples else dataset.load_samples(split=args.online_split))
    online_config = ExperimentConfig(
        experiment_name=f"{base_experiment_name}_online_with_offline",
        model=model_name,
        max_interaction_steps=5,
        max_refinement_rounds=1,
        reflection_window=3,
        epochs=1,
        num_samples=eval_samples_count,
        timestamp=datetime.now().isoformat()
    )
    online_with_offline_logger.log_config(online_config)

    # Initialize client and environment for online evaluation
    client = OpenAIClient(
        model=model_name,
        api_key="ollama",
        base_url="http://hc5.isl.lab.nycu.edu.tw:11434/v1"
    )
    environment = AppWorldEnvironment(logger=online_with_offline_logger)

    # Run online evaluation with trained playbook
    online_with_offline_results = run_online_evaluation(
        args, client, environment, dataset,
        online_with_offline_logger,
        trained_playbook,
        "with offline training"
    )

    # Log online with offline experiment summary
    online_with_offline_logger.log_experiment_summary()

    # Phase 3: Baseline - Online Evaluation without Offline Training
    if not args.skip_baseline:
        online_without_offline_logger = ExperimentLogger(experiment_name=f"{base_experiment_name}_online_without_offline")

        # Log baseline config
        baseline_config = ExperimentConfig(
            experiment_name=f"{base_experiment_name}_online_without_offline",
            model=model_name,
            max_interaction_steps=5,
            max_refinement_rounds=1,
            reflection_window=3,
            epochs=1,
            num_samples=eval_samples_count,
            timestamp=datetime.now().isoformat()
        )
        online_without_offline_logger.log_config(baseline_config)

        # Create new environment for baseline
        baseline_environment = AppWorldEnvironment(logger=online_without_offline_logger)

        # Run online evaluation with empty playbook (baseline)
        online_without_offline_results = run_online_evaluation(
            args, client, baseline_environment, dataset,
            online_without_offline_logger,
            Playbook(),  # Empty playbook
            "without offline training (baseline)"
        )

        # Log baseline experiment summary
        online_without_offline_logger.log_experiment_summary()

    # Print final summary
    print(f"\n{'='*80}")
    print(f"EXPERIMENT COMPLETE")
    print(f"{'='*80}\n")
    print(f"Results saved in: logs/appworld_experiments/")
    print(f"  - Offline training: {offline_logger.log_dir if not args.load_playbook else 'N/A (loaded)'}")
    print(f"  - Online w/ offline: {online_with_offline_logger.log_dir}")
    if not args.skip_baseline:
        print(f"  - Online w/o offline: {online_without_offline_logger.log_dir}")
    print(f"\nTrained playbook: {playbook_path}")
    print(f"\nCompare statistics_report.json files to see the impact of offline training!")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
