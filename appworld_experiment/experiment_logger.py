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
        self.phase_metrics: dict[str, List[TaskMetrics]] = {}  # Phase-separated metrics (e.g., "train", "test", "default")

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

    def log_task_metrics(self, metrics: TaskMetrics, phase: str = "default"):
        """Log metrics for a completed task.

        Args:
            metrics: Task metrics to log
            phase: Phase identifier (e.g., "train", "test", "online", "default")
        """
        if phase not in self.phase_metrics:
            self.phase_metrics[phase] = []
        self.phase_metrics[phase].append(metrics)

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

    def _compute_phase_stats(self, metrics: List[TaskMetrics]) -> dict:
        """Compute comprehensive statistics for a list of task metrics.

        Args:
            metrics: List of TaskMetrics to compute statistics for

        Returns:
            Dictionary containing computed statistics (used for both logging and reports)
        """
        import statistics as stats_lib

        if not metrics:
            return {
                "total_tasks": 0,
                "execution_status_breakdown": {
                    "completed_rate": 0.0,
                    "max_steps_reached_rate": 0.0,
                    "crashed_rate": 0.0,
                },
                "tgc": {"avg": 0.0, "min": 0.0, "max": 0.0, "std": 0.0, "median": 0.0},
                "sgc": {"avg": 0.0, "count": 0},
                "avg_steps": 0.0,
                "avg_time": 0.0,
                "total_time": 0.0,
                "tgc_distribution": {},
                "per_task_results": [],
                "unit_tests": {"passed": 0, "total": 0},
            }

        total_tasks = len(metrics)

        # Execution status breakdown
        completed_count = sum(1 for m in metrics if m.execution_status == "completed")
        max_steps_count = sum(1 for m in metrics if m.execution_status == "max_steps_reached")
        crashed_count = sum(1 for m in metrics if m.execution_status == "crashed")

        # TGC statistics
        tgc_values = [m.tgc for m in metrics]
        avg_tgc = sum(tgc_values) / total_tasks
        min_tgc = min(tgc_values)
        max_tgc = max(tgc_values)
        std_tgc = stats_lib.stdev(tgc_values) if total_tasks > 1 else 0.0
        median_tgc = stats_lib.median(tgc_values)

        # SGC statistics
        avg_sgc = sum(m.sgc for m in metrics) / total_tasks
        sgc_count = sum(1 for m in metrics if m.sgc == 1.0)

        # TGC distribution
        tgc_bins = {
            "0-20%": sum(1 for t in tgc_values if 0 <= t < 0.2),
            "20-40%": sum(1 for t in tgc_values if 0.2 <= t < 0.4),
            "40-60%": sum(1 for t in tgc_values if 0.4 <= t < 0.6),
            "60-80%": sum(1 for t in tgc_values if 0.6 <= t < 0.8),
            "80-100%": sum(1 for t in tgc_values if 0.8 <= t < 1.0),
            "100%": sum(1 for t in tgc_values if t == 1.0),
        }

        # Per-task breakdown
        per_task_results = [
            {
                "task_id": m.task_id,
                "execution_status": m.execution_status,
                "tgc": round(m.tgc, 4),
                "sgc": m.sgc,
                "unit_tests_passed": m.unit_tests_passed,
                "unit_tests_total": m.unit_tests_total,
                "num_steps": m.num_steps,
                "execution_time": round(m.execution_time, 2)
            }
            for m in metrics
        ]

        return {
            "total_tasks": total_tasks,
            "execution_status_breakdown": {
                "completed_rate": completed_count / total_tasks,
                "max_steps_reached_rate": max_steps_count / total_tasks,
                "crashed_rate": crashed_count / total_tasks,
            },
            "tgc": {"avg": avg_tgc, "min": min_tgc, "max": max_tgc, "std": std_tgc, "median": median_tgc},
            "sgc": {"avg": avg_sgc, "count": sgc_count},
            "avg_steps": sum(m.num_steps for m in metrics) / total_tasks,
            "avg_time": sum(m.execution_time for m in metrics) / total_tasks,
            "total_time": sum(m.execution_time for m in metrics),
            "tgc_distribution": tgc_bins,
            "per_task_results": per_task_results,
            "unit_tests": {
                "passed": sum(m.unit_tests_passed for m in metrics),
                "total": sum(m.unit_tests_total for m in metrics),
            },
        }

    def _log_phase_stats(self, phase_name: str, stats: dict):
        """Log statistics for a single phase to console.

        Args:
            phase_name: Name of the phase (e.g., "train", "test")
            stats: Statistics dictionary from _compute_phase_stats
        """
        self.logger.info(f"\n  [{phase_name.upper()}] ({stats['total_tasks']} tasks)")
        self.logger.info(f"    Execution status:")
        self.logger.info(f"      - Completed: {stats['execution_status_breakdown']['completed_rate']:.1%}")
        self.logger.info(f"      - Max steps reached: {stats['execution_status_breakdown']['max_steps_reached_rate']:.1%}")
        self.logger.info(f"      - Crashed: {stats['execution_status_breakdown']['crashed_rate']:.1%}")
        self.logger.info(f"    TGC: avg={stats['tgc']['avg']:.2%}, median={stats['tgc']['median']:.2%}, std={stats['tgc']['std']:.2%}")
        self.logger.info(f"    SGC: {stats['sgc']['avg']:.2%} ({stats['sgc']['count']}/{stats['total_tasks']} tasks)")
        self.logger.info(f"    Average steps: {stats['avg_steps']:.1f}")
        self.logger.info(f"    Total time: {stats['total_time']:.2f}s ({stats['total_time']/60:.1f} min)")

    def log_experiment_summary(self):
        """Log final experiment summary with per-phase statistics."""
        if not self.phase_metrics:
            self.logger.warning("No task metrics to summarize")
            return

        # Compute per-phase statistics
        phase_stats = {
            phase_name: self._compute_phase_stats(metrics_list)
            for phase_name, metrics_list in self.phase_metrics.items()
        }

        # Build summary JSON (per-phase only, no overall)
        summary = {
            "experiment_name": self.experiment_name,
            "timestamp": self.timestamp,
            "config": asdict(self.config) if self.config else None,
            "phases": phase_stats,
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

        # Log per-phase statistics
        for phase_name, stats in phase_stats.items():
            self._log_phase_stats(phase_name, stats)

        self.logger.info("=" * 80)
        self.logger.info(f"Results saved to: {self.log_dir}")

    def _generate_statistics_report(self):
        """Generate a comprehensive statistics report for experimental analysis.

        This report includes per-phase:
        - Model information
        - TGC and SGC metrics with distribution
        - Execution status breakdown
        - Per-task breakdown
        - Statistical analysis (min, max, std, median)
        """
        if not self.phase_metrics:
            return

        # Compute per-phase statistics (reuses _compute_phase_stats)
        phase_stats = {
            phase_name: self._compute_phase_stats(metrics_list)
            for phase_name, metrics_list in self.phase_metrics.items()
        }

        # Build statistics report
        stats_report = {
            "experiment_info": {
                "experiment_name": self.experiment_name,
                "timestamp": self.timestamp,
                "model": self.config.model if self.config else "unknown",
                "phases": list(self.phase_metrics.keys()),
            },
            "per_phase_statistics": phase_stats,
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
