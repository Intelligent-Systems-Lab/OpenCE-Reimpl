#!/usr/bin/env python3
"""Run comparison experiment: Offline vs Online adaptation.

This script compares two adaptation strategies:

1. **Offline Adaptation**:
   - Training Phase: Learn playbook from training data (Generator → Reflector → Curator)
   - Evaluation Phase: Test with frozen playbook (Generator only, no learning)

2. **Online Adaptation**:
   - Continuous learning on each sample (Generator → Reflector → Curator)
   - Playbook evolves throughout evaluation

Research Question:
"Does pre-training a playbook offline improve performance compared to online learning from scratch?"

Workflow:
1. Run offline adaptation: train on train split → evaluate on test split with frozen playbook
2. Run online adaptation: learn continuously on the same test split
3. Compare TGC/SGC metrics between the two approaches
"""

from __future__ import annotations

import argparse
import sys
import os
from pathlib import Path
from typing import List
from datetime import datetime
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
    OpenAIClient
)
from appworld_experiment.appworld_deduplication import OllamaDeduplicator
from appworld_experiment.appworld_dataset import AppWorldDataset, AppWorldSample
from appworld_experiment.appworld_environment import AppWorldEnvironment
from appworld_experiment.appworld_adaptation import (
    AppWorldOfflineAdapter,
    AppWorldOnlineAdapter,
    AdapterStepResult,
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
        default=int(os.getenv("EPOCHS", "3")),
        help="Number of offline training epochs (default: from .env or 3)",
    )
    parser.add_argument(
        "--train-samples",
        type=int,
        default=None,
        help="Limit training samples (for testing). Default: use all train samples",
    )
    parser.add_argument(
        "--test-split",
        type=str,
        default="dev",
        choices=["dev", "test_normal", "test_challenge"],
        help="Split to use for evaluation (default: dev)",
    )
    parser.add_argument(
        "--test-samples",
        type=int,
        default=None,
        help="Limit test samples (for testing). Default: use all",
    )
    parser.add_argument(
        "--save-playbook",
        type=str,
        default=None,
        help="Save trained playbook to specified path (default: auto-generated in logs)",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=os.getenv("MODEL_NAME", "gpt-oss:20b"),
        help="Your model name (default from .env or gpt-oss:20b)",
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
    return parser.parse_args()


def save_playbook(playbook: Playbook, filepath: Path, logger) -> None:
    """Save playbook to JSON file."""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(playbook.dumps())
    logger.info(f"Playbook saved to: {filepath}")


def calculate_metrics(results: List[AdapterStepResult]) -> dict:
    """Calculate aggregate metrics from results."""
    if not results:
        return {
            "count": 0,
            "completed_rate": 0.0,
            "max_steps_reached_rate": 0.0,
            "crashed_rate": 0.0,
            "avg_tgc": 0.0,
            "avg_sgc": 0.0,
        }

    count = len(results)
    completed_count = sum(1 for r in results if r.environment_result.metrics.get("execution_status") == "completed")
    max_steps_count = sum(1 for r in results if r.environment_result.metrics.get("execution_status") == "max_steps_reached")
    crashed_count = sum(1 for r in results if r.environment_result.metrics.get("execution_status") == "crashed")
    tgc_sum = sum(r.environment_result.metrics.get("tgc", 0) for r in results)
    sgc_sum = sum(r.environment_result.metrics.get("sgc", 0) for r in results)

    return {
        "count": count,
        "completed_rate": completed_count / count,
        "max_steps_reached_rate": max_steps_count / count,
        "crashed_rate": crashed_count / count,
        "avg_tgc": tgc_sum / count,
        "avg_sgc": sgc_sum / count,
    }


def main() -> None:
    from appworld_experiment.experiment_logger import ExperimentLogger, ExperimentConfig

    args = parse_args()

    # Setup base experiment name
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    base_experiment_name = f"comparison_{timestamp}"

    # Model configuration
    model_name = args.model_name
    base_url = args.base_url
    api_key = args.api_key
    appworld_url = args.appworld_url

    # Dataset path from environment variable
    dataset_path = os.getenv("APPWORLD_DATA_PATH", "/home/yanhong/appworld-server/data")

    # Initialize dataset
    dataset = AppWorldDataset(dataset_path)

    # Load samples
    all_train_samples = dataset.load_samples(split="train")
    all_test_samples = dataset.load_samples(split=args.test_split)

    train_samples = all_train_samples[:args.train_samples] if args.train_samples else all_train_samples
    test_samples = all_test_samples[:args.test_samples] if args.test_samples else all_test_samples

    print("=" * 70)
    print("COMPARISON EXPERIMENT: Offline vs Online Adaptation")
    print("=" * 70)
    print(f"Training samples: {len(train_samples)}")
    print(f"Test samples: {len(test_samples)} ({args.test_split})")
    print(f"Offline epochs: {args.offline_epochs}")
    print("=" * 70)

    # Initialize LLM clients
    client = OpenAIClient(
        model=model_name,
        api_key=api_key,
        base_url=base_url
    )
    openai_client = OpenAIClient(
        model="gpt-4o-mini",
        api_key=api_key
    )

    # ==================== OFFLINE ADAPTATION ====================
    print("\n" + "=" * 70)
    print("PHASE 1: OFFLINE ADAPTATION")
    print("  - Training: Learn playbook from training data")
    print("  - Evaluation: Test with frozen playbook (Generator only)")
    print("=" * 70)

    offline_logger = ExperimentLogger(experiment_name=f"{base_experiment_name}_offline")

    offline_config = ExperimentConfig(
        experiment_name=f"{base_experiment_name}_offline",
        model=model_name,
        max_interaction_steps=args.max_interaction_steps,
        max_refinement_rounds=1,
        reflection_window=3,
        epochs=args.offline_epochs,
        num_samples=len(train_samples) + len(test_samples),
        timestamp=datetime.now().isoformat()
    )
    offline_logger.log_config(offline_config)

    # Create offline adapter
    offline_generator = AppWorldGenerator(client, logger=offline_logger)
    offline_reflector = AppWorldReflector(openai_client, logger=offline_logger)
    offline_curator = AppWorldCurator(openai_client, logger=offline_logger)

    offline_adapter = AppWorldOfflineAdapter(
        playbook=Playbook(),
        generator=offline_generator,
        reflector=offline_reflector,
        curator=offline_curator,
        deduplicator=OllamaDeduplicator(logger=offline_logger, model_name=args.deduplication_model) if args.dedup_frequency > 0 else None,
        dedup_frequency=args.dedup_frequency,
        max_refinement_rounds=1,
        max_interaction_steps=args.max_interaction_steps,
        logger=offline_logger,
    )

    offline_environment = AppWorldEnvironment(base_url=appworld_url, logger=offline_logger)

    # Run offline adaptation (train + evaluate with frozen playbook)
    offline_train_results, offline_test_results = offline_adapter.run(
        train_samples=train_samples,
        test_samples=test_samples,
        environment=offline_environment,
        epochs=args.offline_epochs
    )

    # Save playbook
    if args.save_playbook:
        playbook_path = Path(args.save_playbook)
    else:
        playbook_path = offline_logger.log_dir / "trained_playbook.json"
    save_playbook(offline_adapter.playbook, playbook_path, offline_logger)

    offline_logger.log_experiment_summary()

    # ==================== ONLINE ADAPTATION ====================
    print("\n" + "=" * 70)
    print("PHASE 2: ONLINE ADAPTATION")
    print("  - Continuous learning on test data")
    print("  - Playbook updated after each sample")
    print("=" * 70)

    online_logger = ExperimentLogger(experiment_name=f"{base_experiment_name}_online")

    online_config = ExperimentConfig(
        experiment_name=f"{base_experiment_name}_online",
        model=model_name,
        max_interaction_steps=args.max_interaction_steps,
        max_refinement_rounds=1,
        reflection_window=3,
        epochs=1,
        num_samples=len(test_samples),
        timestamp=datetime.now().isoformat()
    )
    online_logger.log_config(online_config)

    # Create online adapter
    online_generator = AppWorldGenerator(client, logger=online_logger)
    online_reflector = AppWorldReflector(openai_client, logger=online_logger)
    online_curator = AppWorldCurator(openai_client, logger=online_logger)

    online_adapter = AppWorldOnlineAdapter(
        playbook=Playbook(),  # Start with empty playbook
        generator=online_generator,
        reflector=online_reflector,
        curator=online_curator,
        deduplicator=OllamaDeduplicator(logger=online_logger, model_name=args.deduplication_model) if args.dedup_frequency > 0 else None,
        dedup_frequency=args.dedup_frequency,
        max_refinement_rounds=1,
        max_interaction_steps=args.max_interaction_steps,
        logger=online_logger,
    )

    online_environment = AppWorldEnvironment(base_url=appworld_url, logger=online_logger)

    # Run online adaptation (continuous learning on test data)
    online_results = online_adapter.run(test_samples, online_environment)

    online_logger.log_experiment_summary()

    # ==================== COMPARISON SUMMARY ====================
    offline_metrics = calculate_metrics(offline_test_results)
    online_metrics = calculate_metrics(online_results)

    print("\n" + "=" * 70)
    print("COMPARISON RESULTS")
    print("=" * 70)

    print(f"\nOFFLINE ADAPTATION (frozen playbook evaluation):")
    print(f"  Training samples: {len(offline_train_results)}")
    print(f"  Test samples: {offline_metrics['count']}")
    print(f"  Execution status breakdown:")
    print(f"    - Completed: {offline_metrics['completed_rate']:.1%}")
    print(f"    - Max steps reached: {offline_metrics['max_steps_reached_rate']:.1%}")
    print(f"    - Crashed: {offline_metrics['crashed_rate']:.1%}")
    print(f"  Average TGC: {offline_metrics['avg_tgc']:.2%}")
    print(f"  Average SGC: {offline_metrics['avg_sgc']:.2%}")
    print(f"  Final playbook: {offline_adapter.playbook.__len__()} bullets")

    print(f"\nONLINE ADAPTATION (continuous learning):")
    print(f"  Test samples: {online_metrics['count']}")
    print(f"  Execution status breakdown:")
    print(f"    - Completed: {online_metrics['completed_rate']:.1%}")
    print(f"    - Max steps reached: {online_metrics['max_steps_reached_rate']:.1%}")
    print(f"    - Crashed: {online_metrics['crashed_rate']:.1%}")
    print(f"  Average TGC: {online_metrics['avg_tgc']:.2%}")
    print(f"  Average SGC: {online_metrics['avg_sgc']:.2%}")
    print(f"  Final playbook: {online_adapter.playbook.__len__()} bullets")

    print(f"\nDIFFERENCE (Offline - Online):")
    print(f"  Completed rate: {(offline_metrics['completed_rate'] - online_metrics['completed_rate']):+.1%}")
    print(f"  Average TGC: {(offline_metrics['avg_tgc'] - online_metrics['avg_tgc']):+.2%}")
    print(f"  Average SGC: {(offline_metrics['avg_sgc'] - online_metrics['avg_sgc']):+.2%}")

    print("\n" + "=" * 70)
    print("EXPERIMENT COMPLETE")
    print("=" * 70)
    print(f"Offline logs: {offline_logger.log_dir}")
    print(f"Online logs: {online_logger.log_dir}")
    print(f"Trained playbook: {playbook_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
