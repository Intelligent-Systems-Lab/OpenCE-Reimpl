"""Logging utilities for AppWorld experiments.

This module provides structured logging for tracking experiment progress,
metrics, and debugging information.
"""

import logging
import colorlog
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass, asdict


# ANSI color codes for terminal output
class Colors:
    """ANSI color codes for terminal output."""
    RESET = '\033[0m'
    BOLD = '\033[1m'

    # Role colors
    GENERATOR = '\033[94m'  # Blue
    REFLECTOR = '\033[95m'  # Magenta
    CURATOR = '\033[96m'    # Cyan

    # Token count colors
    GREEN = '\033[92m'      # Low usage
    YELLOW = '\033[93m'     # Medium usage
    RED = '\033[91m'        # High usage

    # Label color
    GRAY = '\033[90m'       # For labels like "Model:", "Tokens:"


@dataclass
class LLMCallRecord:
    """Record of a single LLM API call."""
    timestamp: str
    task_id: str
    role: str  # "generator", "reflector", "curator"
    step: Optional[int]  # Interaction step (for generator)
    prompt_tokens: Optional[int]  # Actual tokens from API response
    completion_tokens: Optional[int]  # Actual tokens from API response
    total_tokens: Optional[int]  # Actual tokens from API response
    model: str
    estimated_prompt_tokens: Optional[int] = None  # Pre-call estimation (tiktoken)


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
    execution_status: str  # "completed", "max_steps_reached", "crashed"
    num_steps: int
    sgc: float  # Scenario Goal Completion: 1.0 if TGC == 100%, else 0.0
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
    # Execution status breakdown (ratios)
    completed_rate: float  # Proportion of tasks with execution_status == "completed"
    max_steps_reached_rate: float  # Proportion of tasks with execution_status == "max_steps_reached"
    crashed_rate: float  # Proportion of tasks with execution_status == "crashed"
    avg_steps: float
    avg_execution_time: float
    playbook_size: int
    playbook_changes: int
    # AppWorld-specific metrics
    avg_tgc: float  # Average Task Goal Completion across all tasks
    avg_sgc: float  # Average SGC (proportion of tasks with TGC == 100%)


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
        self.llm_calls_file = self.log_dir / "llm_calls.jsonl"  # Token usage log
        self.trajectory_dir = self.log_dir / "trajectories"
        self.trajectory_dir.mkdir(exist_ok=True)

        # Setup Python logger
        self.logger = logging.getLogger(f"appworld_experiment.{self.experiment_name}")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()
        self.logger.propagate = False

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
        console_formatter = colorlog.ColoredFormatter(
            "%(log_color)s%(asctime)s - %(levelname)s - %(message)s",
            datefmt='%Y-%m-%d %H:%M:%S',
            log_colors={
                'DEBUG':    'cyan',
                'INFO':     'green',
                'WARNING':  'yellow',
                'ERROR':    'red',
                'CRITICAL': 'red,bg_white',
            }
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
        self.logger.info(f"Task {metrics.task_id} - {metrics.execution_status}")
        self.logger.info(f"  Steps: {metrics.num_steps}")
        self.logger.info(f"  Time: {metrics.execution_time:.2f}s")
        self.logger.info(f"  TGC: {metrics.tgc:.2%} ({metrics.unit_tests_passed}/{metrics.unit_tests_total} tests passed)")
        self.logger.info(f"  SGC: {metrics.sgc:.0f}")
        self.logger.info(f"  Playbook size: {metrics.playbook_size}")

        # Write to JSONL file
        with open(self.metrics_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(metrics), ensure_ascii=False) + '\n')

    def log_llm_call(
        self,
        task_id: str,
        role: str,
        model: str,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        total_tokens: Optional[int] = None,
        step: Optional[int] = None,
        estimated_prompt_tokens: Optional[int] = None,
    ):
        """Log a single LLM API call with token usage.

        Args:
            task_id: Task identifier
            role: Role making the call ("generator", "reflector", "curator")
            model: Model name
            prompt_tokens: Actual number of input tokens from API
            completion_tokens: Actual number of output tokens from API
            total_tokens: Actual total tokens from API
            step: Interaction step number (for generator)
            estimated_prompt_tokens: Pre-call token estimation (tiktoken)
        """
        record = LLMCallRecord(
            timestamp=datetime.now().isoformat(),
            task_id=task_id,
            role=role,
            step=step,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            model=model,
            estimated_prompt_tokens=estimated_prompt_tokens,
        )

        # Log to console with colors
        tokens_str = f"{total_tokens:,}" if total_tokens else "N/A"
        step_str = f" (step {step})" if step is not None else ""

        # Choose role color
        role_colors = {
            "generator": Colors.GENERATOR,
            "reflector": Colors.REFLECTOR,
            "curator": Colors.CURATOR,
        }
        role_color = role_colors.get(role.lower(), Colors.RESET)

        # Choose token count color based on usage
        # Thresholds: <4000 = green, 4000-6000 = yellow, >6000 = red
        if total_tokens:
            if total_tokens < 4000:
                token_color = Colors.GREEN
            elif total_tokens < 6000:
                token_color = Colors.YELLOW
            else:
                token_color = Colors.RED
        else:
            token_color = Colors.GRAY

        # Format estimation string
        if estimated_prompt_tokens:
            est_str = f" {Colors.GRAY}(est: {estimated_prompt_tokens:,}){Colors.RESET}"
        else:
            est_str = ""

        # Build colored log message
        colored_msg = (
            f"{Colors.BOLD}[LLM Call]{Colors.RESET} "
            f"{role_color}{role}{Colors.RESET}{Colors.GRAY}{step_str}{Colors.RESET} "
            f"{Colors.GRAY}|{Colors.RESET} Model: {model} {Colors.GRAY}|{Colors.RESET} "
            f"Tokens: {token_color}{prompt_tokens:,} + {completion_tokens:,} = {tokens_str}{Colors.RESET}{est_str}"
        )

        self.logger.info(colored_msg)

        # Write to JSONL file
        with open(self.llm_calls_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + '\n')

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
        self.logger.info(f"  Execution status breakdown:")
        self.logger.info(f"    - Completed: {summary.completed_rate:.1%}")
        self.logger.info(f"    - Max steps reached: {summary.max_steps_reached_rate:.1%}")
        self.logger.info(f"    - Crashed: {summary.crashed_rate:.1%}")
        self.logger.info(f"  Average TGC: {summary.avg_tgc:.2%}")
        self.logger.info(f"  Average SGC: {summary.avg_sgc:.2%}")
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

        # Execution status breakdown
        completed_count = sum(1 for m in self.task_metrics if m.execution_status == "completed")
        max_steps_count = sum(1 for m in self.task_metrics if m.execution_status == "max_steps_reached")
        crashed_count = sum(1 for m in self.task_metrics if m.execution_status == "crashed")

        completed_rate = completed_count / total_tasks
        max_steps_rate = max_steps_count / total_tasks
        crashed_rate = crashed_count / total_tasks

        avg_steps = sum(m.num_steps for m in self.task_metrics) / total_tasks
        avg_time = sum(m.execution_time for m in self.task_metrics) / total_tasks
        total_time = sum(m.execution_time for m in self.task_metrics)

        # Calculate TGC and SGC
        avg_tgc = sum(m.tgc for m in self.task_metrics) / total_tasks
        avg_sgc = sum(m.sgc for m in self.task_metrics) / total_tasks

        summary = {
            "experiment_name": self.experiment_name,
            "timestamp": self.timestamp,
            "config": asdict(self.config) if self.config else None,
            "overall_stats": {
                "total_tasks": total_tasks,
                "execution_status_breakdown": {
                    "completed_rate": completed_rate,
                    "max_steps_reached_rate": max_steps_rate,
                    "crashed_rate": crashed_rate,
                },
                "avg_tgc": avg_tgc,
                "avg_sgc": avg_sgc,
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
        self.logger.info(f"  Execution status breakdown:")
        self.logger.info(f"    - Completed: {completed_rate:.1%}")
        self.logger.info(f"    - Max steps reached: {max_steps_rate:.1%}")
        self.logger.info(f"    - Crashed: {crashed_rate:.1%}")
        self.logger.info(f"  Average TGC: {avg_tgc:.2%}")
        self.logger.info(f"  Average SGC: {avg_sgc:.2%}")
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
        - Execution status breakdown
        - Per-task breakdown
        - Statistical analysis (min, max, std, quartiles)
        """
        if not self.task_metrics:
            return

        import statistics

        # Basic statistics
        total_tasks = len(self.task_metrics)

        # Execution status breakdown
        completed_count = sum(1 for m in self.task_metrics if m.execution_status == "completed")
        max_steps_count = sum(1 for m in self.task_metrics if m.execution_status == "max_steps_reached")
        crashed_count = sum(1 for m in self.task_metrics if m.execution_status == "crashed")

        # TGC statistics
        tgc_values = [m.tgc for m in self.task_metrics]
        avg_tgc = sum(tgc_values) / total_tasks
        min_tgc = min(tgc_values)
        max_tgc = max(tgc_values)
        std_tgc = statistics.stdev(tgc_values) if total_tasks > 1 else 0.0
        median_tgc = statistics.median(tgc_values)

        # SGC calculation (average of all sgc values)
        avg_sgc = sum(m.sgc for m in self.task_metrics) / total_tasks
        sgc_count = sum(1 for m in self.task_metrics if m.sgc == 1.0)

        # Per-task breakdown
        task_breakdown = []
        for m in self.task_metrics:
            task_breakdown.append({
                "task_id": m.task_id,
                "execution_status": m.execution_status,
                "tgc": round(m.tgc, 4),
                "tgc_percentage": f"{m.tgc*100:.2f}%",
                "sgc": m.sgc,
                "unit_tests_passed": m.unit_tests_passed,
                "unit_tests_total": m.unit_tests_total,
                "num_steps": m.num_steps,
                "execution_time": round(m.execution_time, 2)
            })

        # TGC distribution
        tgc_bins = {
            "0-20%": sum(1 for t in tgc_values if 0 <= t < 0.2),
            "20-40%": sum(1 for t in tgc_values if 0.2 <= t < 0.4),
            "40-60%": sum(1 for t in tgc_values if 0.4 <= t < 0.6),
            "60-80%": sum(1 for t in tgc_values if 0.6 <= t < 0.8),
            "80-100%": sum(1 for t in tgc_values if 0.8 <= t < 1.0),
            "100%": sum(1 for t in tgc_values if t == 1.0),
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
                "execution_status_breakdown": {
                    "completed_rate": f"{completed_count/total_tasks*100:.2f}%",
                    "max_steps_reached_rate": f"{max_steps_count/total_tasks*100:.2f}%",
                    "crashed_rate": f"{crashed_count/total_tasks*100:.2f}%",
                },

                "tgc_overall": {
                    "average": f"{avg_tgc*100:.2f}%",
                    "median": f"{median_tgc*100:.2f}%",
                    "min": f"{min_tgc*100:.2f}%",
                    "max": f"{max_tgc*100:.2f}%",
                    "std": f"{std_tgc*100:.2f}%",
                    "raw_average": round(avg_tgc, 4)
                },

                "sgc_overall": {
                    "average": f"{avg_sgc*100:.2f}%",
                    "count": f"{sgc_count}/{total_tasks}",
                    "raw_average": round(avg_sgc, 4)
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
