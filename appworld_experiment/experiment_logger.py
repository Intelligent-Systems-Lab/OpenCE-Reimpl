"""Logging utilities for AppWorld experiments.

This module provides structured logging for tracking experiment progress,
metrics, and debugging information.
"""

import logging
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict


@dataclass
class ExperimentConfig:
    """Configuration for an experiment run."""
    experiment_name: str
    model: str
    max_interaction_steps: int
    max_refinement_rounds: int
    reflection_window: int
    epochs: int
    num_samples: int
    timestamp: str


@dataclass
class TaskMetrics:
    """Metrics for a single task execution."""
    task_id: str
    sample_index: int
    epoch: int
    completed: bool
    num_steps: int
    success: bool
    execution_time: float
    trajectory_length: int
    num_bullet_tags: int
    playbook_size: int
    # AppWorld-specific metrics
    tgc: float  # Task Goal Completion: unit test pass rate (0.0-1.0)
    unit_tests_passed: int  # Number of unit tests passed
    unit_tests_total: int  # Total number of unit tests


@dataclass
class EpochSummary:
    """Summary statistics for an epoch."""
    epoch: int
    total_samples: int
    completed_tasks: int
    successful_tasks: int
    avg_steps: float
    avg_execution_time: float
    playbook_size: int
    playbook_changes: int
    # AppWorld-specific metrics
    avg_tgc: float  # Average Task Goal Completion across all tasks
    sgc: float  # Scenario Goal Completion: percentage of tasks with TGC >= threshold (e.g., 0.8)


def parse_unit_test_results(unit_test_output: str) -> tuple[int, int]:
    """Parse AppWorld unit test output to extract passed/total counts.

    AppWorld returns formatted output like:
    ─────────────────────────────────────────── Overall Stats ─────────────────────────
    Num Passed Tests : 1
    Num Failed Tests : 1
    Num Total  Tests : 2

    Args:
        unit_test_output: String output from AppWorld /evaluate endpoint

    Returns:
        Tuple of (passed_count, total_count)

    Examples:
        "Num Passed Tests : 5\\nNum Total Tests : 10" -> (5, 10)
    """
    import re

    if not unit_test_output:
        return (0, 0)

    passed = 0
    total = 0

    # Parse "Num Passed Tests : X"
    passed_match = re.search(r'Num Passed Tests\s*:\s*(\d+)', unit_test_output)
    if passed_match:
        passed = int(passed_match.group(1))

    # Parse "Num Total Tests : X"
    total_match = re.search(r'Num Total\s+Tests\s*:\s*(\d+)', unit_test_output)
    if total_match:
        total = int(total_match.group(1))

    return (passed, total)


class ExperimentLogger:
    """Logger for AppWorld experiments with structured output.

    This logger creates multiple log files:
    - experiment.log: Detailed text logs
    - metrics.jsonl: Per-task metrics in JSON Lines format
    - summary.json: Experiment-level summary
    """

    def __init__(
        self,
        log_dir: str = "logs/appworld_experiments",
        experiment_name: Optional[str] = None
    ):
        """Initialize experiment logger.

        Args:
            log_dir: Base directory for log files
            experiment_name: Name of the experiment (defaults to timestamp)
        """
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.experiment_name = experiment_name or f"exp_{self.timestamp}"

        # Create log directory
        self.log_dir = Path(log_dir) / self.experiment_name
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Setup file paths
        self.log_file = self.log_dir / "experiment.log"
        self.metrics_file = self.log_dir / "metrics.jsonl"
        self.summary_file = self.log_dir / "summary.json"
        self.stats_report_file = self.log_dir / "statistics_report.json"
        self.trajectory_dir = self.log_dir / "trajectories"
        self.trajectory_dir.mkdir(exist_ok=True)

        # Setup Python logger
        self.logger = logging.getLogger(f"appworld_experiment.{self.experiment_name}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()

        # File handler (detailed logs)
        file_handler = logging.FileHandler(self.log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)

        # Console handler (important logs only)
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_formatter = logging.Formatter(
            '%(levelname)s - %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)

        # Experiment state
        self.config: Optional[ExperimentConfig] = None
        self.task_metrics: List[TaskMetrics] = []
        self.epoch_summaries: List[EpochSummary] = []

        self.logger.info(f"Experiment logger initialized: {self.experiment_name}")
        self.logger.info(f"Log directory: {self.log_dir}")

    def log_config(self, config: ExperimentConfig):
        """Log experiment configuration.

        Args:
            config: Experiment configuration to log
        """
        self.config = config
        self.logger.info("=" * 80)
        self.logger.info("EXPERIMENT CONFIGURATION")
        self.logger.info("=" * 80)
        for key, value in asdict(config).items():
            self.logger.info(f"  {key}: {value}")
        self.logger.info("=" * 80)

        # Write config to JSON
        config_file = self.log_dir / "config.json"
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(config), f, indent=2, ensure_ascii=False)

    def log_task_start(self, task_id: str, sample_index: int, epoch: int):
        """Log the start of a task execution.

        Args:
            task_id: Task identifier
            sample_index: Index of the sample in the dataset
            epoch: Current epoch number
        """
        self.logger.info(f"\n{'='*60}")
        self.logger.info(f"Starting Task: {task_id}")
        self.logger.info(f"Sample: {sample_index}, Epoch: {epoch}")
        self.logger.info(f"{'='*60}")

    def log_task_metrics(self, metrics: TaskMetrics):
        """Log metrics for a completed task.

        Args:
            metrics: Task metrics to log
        """
        self.task_metrics.append(metrics)

        # Log to console
        status = "✓ SUCCESS" if metrics.success else "✗ FAILED"
        self.logger.info(f"{status} - Task {metrics.task_id}")
        self.logger.info(f"  Completed: {metrics.completed}")
        self.logger.info(f"  Steps: {metrics.num_steps}")
        self.logger.info(f"  Time: {metrics.execution_time:.2f}s")
        self.logger.info(f"  TGC: {metrics.tgc:.2%} ({metrics.unit_tests_passed}/{metrics.unit_tests_total} tests passed)")
        self.logger.info(f"  Playbook size: {metrics.playbook_size}")

        # Write to JSONL file
        with open(self.metrics_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(metrics), ensure_ascii=False) + '\n')

    def log_trajectory(self, task_id: str, trajectory: str):
        """Save trajectory to a separate file.

        Args:
            task_id: Task identifier
            trajectory: Formatted trajectory string
        """
        trajectory_file = self.trajectory_dir / f"{task_id}.txt"
        with open(trajectory_file, 'w', encoding='utf-8') as f:
            f.write(trajectory)
        self.logger.debug(f"Saved trajectory for {task_id}")

    def log_epoch_summary(self, summary: EpochSummary):
        """Log summary for an epoch.

        Args:
            summary: Epoch summary statistics
        """
        self.epoch_summaries.append(summary)

        self.logger.info("\n" + "=" * 80)
        self.logger.info(f"EPOCH {summary.epoch} SUMMARY")
        self.logger.info("=" * 80)
        self.logger.info(f"  Total samples: {summary.total_samples}")
        self.logger.info(f"  Completed: {summary.completed_tasks} ({summary.completed_tasks/summary.total_samples*100:.1f}%)")
        self.logger.info(f"  Successful: {summary.successful_tasks} ({summary.successful_tasks/summary.total_samples*100:.1f}%)")
        self.logger.info(f"  Average TGC: {summary.avg_tgc:.2%}")
        self.logger.info(f"  SGC (tasks with TGC≥80%): {summary.sgc:.2%}")
        self.logger.info(f"  Avg steps: {summary.avg_steps:.1f}")
        self.logger.info(f"  Avg time: {summary.avg_execution_time:.2f}s")
        self.logger.info(f"  Playbook size: {summary.playbook_size} bullets")
        self.logger.info(f"  Playbook changes: {summary.playbook_changes}")
        self.logger.info("=" * 80)

    def log_experiment_summary(self):
        """Log final experiment summary."""
        if not self.task_metrics:
            self.logger.warning("No task metrics to summarize")
            return

        total_tasks = len(self.task_metrics)
        completed = sum(1 for m in self.task_metrics if m.completed)
        successful = sum(1 for m in self.task_metrics if m.success)
        avg_steps = sum(m.num_steps for m in self.task_metrics) / total_tasks
        avg_time = sum(m.execution_time for m in self.task_metrics) / total_tasks
        total_time = sum(m.execution_time for m in self.task_metrics)

        # Calculate TGC and SGC
        avg_tgc = sum(m.tgc for m in self.task_metrics) / total_tasks
        sgc_threshold = 0.8  # Tasks with TGC >= 80% are considered successful
        sgc = sum(1 for m in self.task_metrics if m.tgc >= sgc_threshold) / total_tasks

        summary = {
            "experiment_name": self.experiment_name,
            "timestamp": self.timestamp,
            "config": asdict(self.config) if self.config else None,
            "overall_stats": {
                "total_tasks": total_tasks,
                "completed_tasks": completed,
                "successful_tasks": successful,
                "completion_rate": completed / total_tasks * 100,
                "success_rate": successful / total_tasks * 100,
                "avg_tgc": avg_tgc,
                "sgc": sgc,
                "avg_steps_per_task": avg_steps,
                "avg_time_per_task": avg_time,
                "total_execution_time": total_time,
            },
            "epoch_summaries": [asdict(s) for s in self.epoch_summaries],
            "per_task_metrics": [asdict(m) for m in self.task_metrics],
        }

        # Write summary to JSON
        with open(self.summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)

        # Generate statistics report
        self._generate_statistics_report()

        # Log to console
        self.logger.info("\n" + "=" * 80)
        self.logger.info("EXPERIMENT COMPLETE")
        self.logger.info("=" * 80)
        self.logger.info(f"  Total tasks: {total_tasks}")
        self.logger.info(f"  Completion rate: {completed/total_tasks*100:.1f}%")
        self.logger.info(f"  Success rate: {successful/total_tasks*100:.1f}%")
        self.logger.info(f"  Average TGC: {avg_tgc:.2%}")
        self.logger.info(f"  SGC (tasks with TGC≥80%): {sgc:.2%}")
        self.logger.info(f"  Average steps: {avg_steps:.1f}")
        self.logger.info(f"  Average time: {avg_time:.2f}s")
        self.logger.info(f"  Total time: {total_time:.2f}s ({total_time/60:.1f} min)")
        self.logger.info("=" * 80)
        self.logger.info(f"Results saved to: {self.log_dir}")

    def _generate_statistics_report(self):
        """Generate a comprehensive statistics report for experimental analysis.

        This report includes:
        - Model information
        - Overall TGC and SGC metrics
        - Per-task breakdown
        - Statistical analysis (min, max, std, quartiles)
        """
        if not self.task_metrics:
            return

        import statistics

        # Basic statistics
        total_tasks = len(self.task_metrics)
        completed = sum(1 for m in self.task_metrics if m.completed)
        successful = sum(1 for m in self.task_metrics if m.success)

        # TGC statistics
        tgc_values = [m.tgc for m in self.task_metrics]
        avg_tgc = sum(tgc_values) / total_tasks
        min_tgc = min(tgc_values)
        max_tgc = max(tgc_values)
        std_tgc = statistics.stdev(tgc_values) if total_tasks > 1 else 0.0
        median_tgc = statistics.median(tgc_values)

        # SGC calculation
        sgc_threshold = 0.8
        sgc_count = sum(1 for m in self.task_metrics if m.tgc >= sgc_threshold)
        sgc_percentage = sgc_count / total_tasks

        # Per-task TGC breakdown
        task_breakdown = []
        for m in self.task_metrics:
            task_breakdown.append({
                "task_id": m.task_id,
                "tgc": round(m.tgc, 4),
                "tgc_percentage": f"{m.tgc*100:.2f}%",
                "unit_tests_passed": m.unit_tests_passed,
                "unit_tests_total": m.unit_tests_total,
                "completed": m.completed,
                "num_steps": m.num_steps,
                "execution_time": round(m.execution_time, 2)
            })

        # TGC distribution
        tgc_bins = {
            "0-20%": sum(1 for t in tgc_values if 0 <= t < 0.2),
            "20-40%": sum(1 for t in tgc_values if 0.2 <= t < 0.4),
            "40-60%": sum(1 for t in tgc_values if 0.4 <= t < 0.6),
            "60-80%": sum(1 for t in tgc_values if 0.6 <= t < 0.8),
            "80-100%": sum(1 for t in tgc_values if 0.8 <= t <= 1.0),
        }

        # Build statistics report
        stats_report = {
            "experiment_info": {
                "experiment_name": self.experiment_name,
                "timestamp": self.timestamp,
                "model": self.config.model if self.config else "unknown",
                "total_tasks": total_tasks,
                "total_execution_time": f"{sum(m.execution_time for m in self.task_metrics):.2f}s"
            },

            "overall_metrics": {
                "completion_rate": f"{completed/total_tasks*100:.2f}%",
                "success_rate": f"{successful/total_tasks*100:.2f}%",

                "tgc_overall": {
                    "average": f"{avg_tgc*100:.2f}%",
                    "median": f"{median_tgc*100:.2f}%",
                    "min": f"{min_tgc*100:.2f}%",
                    "max": f"{max_tgc*100:.2f}%",
                    "std": f"{std_tgc*100:.2f}%",
                    "raw_average": round(avg_tgc, 4)
                },

                "sgc_overall": {
                    "percentage": f"{sgc_percentage*100:.2f}%",
                    "count": f"{sgc_count}/{total_tasks}",
                    "threshold": f"{sgc_threshold*100:.0f}%",
                    "raw_percentage": round(sgc_percentage, 4)
                }
            },

            "tgc_distribution": {
                bin_name: f"{count} tasks ({count/total_tasks*100:.1f}%)"
                for bin_name, count in tgc_bins.items()
            },

            "per_task_results": task_breakdown,

            "summary_statistics": {
                "avg_steps_per_task": round(sum(m.num_steps for m in self.task_metrics) / total_tasks, 2),
                "avg_execution_time": f"{sum(m.execution_time for m in self.task_metrics) / total_tasks:.2f}s",
                "total_unit_tests_passed": sum(m.unit_tests_passed for m in self.task_metrics),
                "total_unit_tests": sum(m.unit_tests_total for m in self.task_metrics),
            }
        }

        # Write statistics report
        with open(self.stats_report_file, 'w', encoding='utf-8') as f:
            json.dump(stats_report, f, indent=2, ensure_ascii=False)

        self.logger.info(f"Statistics report saved to: {self.stats_report_file}")

    def debug(self, message: str):
        """Log debug message."""
        self.logger.debug(message)

    def info(self, message: str):
        """Log info message."""
        self.logger.info(message)

    def warning(self, message: str):
        """Log warning message."""
        self.logger.warning(message)

    def error(self, message: str, exc_info: bool = False):
        """Log error message.

        Args:
            message: Error message
            exc_info: Whether to include exception traceback
        """
        self.logger.error(message, exc_info=exc_info)
