# AppWorld Experiment

This directory contains ACE adaptation code for the AppWorld benchmark.

## File Structure

```
appworld_experiment/
├── ace_appworld.py              # Offline adaptation experiment script
├── ace_appworld_online.py       # Online adaptation experiment script (NEW)
├── appworld_adaptation.py       # AppWorld-specific adaptation classes
├── appworld_client.py           # AppWorld HTTP client test
├── appworld_prompts.py          # AppWorld-specific prompt templates
├── appworld_roles.py            # AppWorld-specific Generator/Reflector/Curator
├── experiment_logger.py         # Experiment logging and statistics reporting
├── trajectory.py                # Multi-step interaction trajectory tracking
├── test_prompt_formatting.py    # Prompt formatting tests
├── PROMPT_FORMATTING_GUIDE.md   # Guide for prompt formatting
├── ONLINE_VS_OFFLINE.md         # Complete comparison of Online vs Offline adaptation
└── README.md                    # This file
```

## Core Components

### 1. AppWorld Roles ([appworld_roles.py](appworld_roles.py))

Inherits from base ACE roles with AppWorld-specific parameters:

- **AppWorldGenerator**: Uses `task` and user info instead of `question`/`context`
- **AppWorldReflector**: Inherits base Reflector (no modifications needed)
- **AppWorldCurator**: Inherits base Curator (no modifications needed)

### 2. AppWorld Prompts ([appworld_prompts.py](appworld_prompts.py))

AppWorld-specific prompt templates containing:

- **APPWORLD_GENERATOR_PROMPT**: Includes AppWorld API usage instructions and 3 few-shot examples
- **APPWORLD_REFLECTOR_PROMPT**: Standard reflection prompt
- **APPWORLD_CURATOR_PROMPT**: Standard curation prompt

### 3. AppWorld Adaptation ([appworld_adaptation.py](appworld_adaptation.py))

Extends base adaptation framework to support AppWorld:

- **AppWorldOfflineAdapter**: Multi-epoch offline training with deduplication support
- **AppWorldOnlineAdapter**: Single-pass streaming training

#### Key Features:

1. **Extract user information from metadata**:
   ```python
   metadata = sample.metadata  # Contains first_name, last_name, email, phone_number
   user_info = self._extract_user_info(sample)
   ```

2. **Call AppWorldGenerator**:
   ```python
   generator_output = self.generator.generate(
       task=sample.question,  # Task instruction
       playbook=self.playbook,
       main_user_first_name=user_info["main_user_first_name"],
       main_user_last_name=user_info["main_user_last_name"],
       main_user_email=user_info["main_user_email"],
       main_user_phone_number=user_info["main_user_phone_number"],
       trajectory_history=trajectory_history,
   )
   ```

3. **Multi-step Interaction**:
   - Agent generates code step-by-step
   - Environment executes and returns observations
   - Agent sees results and continues until task completion
   - Full trajectory tracked and used for reflection

### 4. Experiment Logging ([experiment_logger.py](experiment_logger.py))

Comprehensive logging system with:

- **TaskMetrics**: Per-task metrics including TGC/SGC
- **ExperimentLogger**: Multi-format logging (text, JSONL, JSON)
- **Statistics Report**: Automated generation of experimental statistics

Generated files:
```
logs/appworld_experiments/{experiment_name}/
├── experiment.log           # Detailed text logs
├── metrics.jsonl            # Per-task metrics (streaming format)
├── summary.json             # Experiment summary
├── statistics_report.json   # Statistical analysis (TGC/SGC/model info)
└── trajectories/            # Individual task trajectories
```

## Usage

### Offline Adaptation (Multi-epoch Training)

For benchmark evaluation and model training:

```bash
# Ensure AppWorld server is running
cd /home/yanhong/appworld-server
# ... start server ...

# Run offline ACE experiment
cd /home/yanhong/OpenCE-Reimpl
uv run python appworld_experiment/ace_appworld.py
```

**Features**:
- Multiple epochs over training set
- Deduplication after each epoch
- Suitable for benchmark evaluation

### Online Adaptation (Single-pass Evaluation)

For online evaluation and continuous learning:

```bash
# Evaluate on dev split
uv run python appworld_experiment/ace_appworld_online.py --split dev

# Quick test with limited samples
uv run python appworld_experiment/ace_appworld_online.py --split dev --max-samples 5

# Evaluate on test split
uv run python appworld_experiment/ace_appworld_online.py --split test_normal
```

**Features**:
- Single pass through samples
- Immediate playbook updates
- Suitable for production deployment and streaming data

### Command-line Arguments

**ace_appworld_online.py**:
- `--split {train,dev,test_normal,test_challenge}`: Dataset split (default: dev)
- `--max-samples N`: Limit number of samples for testing
- `--temperature FLOAT`: LLM sampling temperature (default: 0.0)

## Data Flow

```
AppWorldDataset
    ↓
Load samples (question, metadata, task_id, datetime, ground_truth)
    ↓
AppWorldOfflineAdapter / AppWorldOnlineAdapter
    ↓
Extract user info from sample.metadata
    ↓
Multi-step Interaction Loop:
  ┌─────────────────────────────────────────┐
  │ AppWorldGenerator.generate(             │
  │   task=sample.question,                 │
  │   main_user_first_name=...,             │
  │   main_user_last_name=...,              │
  │   main_user_email=...,                  │
  │   main_user_phone_number=...,           │
  │   trajectory_history=...,               │
  │ )                                       │
  └─────────────────────────────────────────┘
    ↓
  AppWorldEnvironment.execute_code()
    ↓
  Update trajectory with (reasoning, code, observation)
    ↓
  Check if task completed via environment.is_task_completed()
    ↓
  If not completed and steps < max: loop back
    ↓
  If completed or max steps reached: continue
    ↓
AppWorldEnvironment.evaluate_task() → Unit test results
    ↓
AppWorldReflector.reflect(
    playbook=...,
    ground_truth=...,
    feedback=full_trajectory,  # Complete interaction history
    unit_test_results=...,
)
    ↓
AppWorldCurator.curate(
    reflection=...,
    playbook=...,
    final_generated_code=...,
    guidebook=...,  # Recent reflections
)
    ↓
Playbook updated
```

## AppWorldSample Structure

```python
@dataclass
class AppWorldSample(Sample):
    task_id: str = ""           # Task ID
    datetime: str = ""          # Task datetime
    context: str = ""           # Additional context (trajectory)
    question: str               # Inherited from Sample, contains task instruction
    metadata: Dict              # Contains user information:
                                # - first_name
                                # - last_name
                                # - email
                                # - phone_number
    ground_truth: Optional[str] # Inherited from Sample
```

## Offline vs Online Adaptation

See [ONLINE_VS_OFFLINE.md](ONLINE_VS_OFFLINE.md) for detailed comparison.

### Quick Summary

| Feature | Offline | Online |
|---------|---------|--------|
| **Data Processing** | Batch (epochs) | Streaming |
| **Deduplication** | ✅ Supported | ❌ Not supported |
| **Use Case** | Benchmark evaluation | Real-time deployment |
| **Training Rounds** | Multiple (epochs ≥ 1) | Single (epoch = 1) |

**Use Offline when**:
- ✅ Fixed benchmark dataset
- ✅ Need multi-epoch training
- ✅ Deduplication improves playbook quality

**Use Online when**:
- ✅ Quick single-pass evaluation
- ✅ Simulating production environment
- ✅ Continuous learning scenarios

## Metrics and Statistics

### TGC (Task Goal Completion)
- **Definition**: Unit test pass rate for individual task
- **Calculation**: `passed_tests / total_tests`
- **Range**: 0.0 - 1.0 (0% - 100%)

### SGC (Scenario Goal Completion)
- **Definition**: Percentage of tasks achieving high TGC (≥80%)
- **Calculation**: `tasks_with_tgc_≥_80% / total_tasks`
- **Range**: 0.0 - 1.0 (0% - 100%)

### Statistics Report

Generated automatically at experiment end:

```json
{
  "experiment_info": {
    "model": "gpt-oss:20b",
    "total_tasks": 10,
    ...
  },
  "overall_metrics": {
    "tgc_overall": {
      "average": "72.50%",
      "median": "75.00%",
      "min": "20.00%",
      "max": "100.00%",
      "std": "25.34%"
    },
    "sgc_overall": {
      "percentage": "60.00%",
      "count": "6/10"
    }
  },
  "tgc_distribution": {...},
  "per_task_results": [...]
}
```

## Common Questions

### Q: Why need AppWorld-specific adapter?

**A**: Parameter mismatch:
- Base `Generator.generate()` expects: `question`, `context`
- `AppWorldGenerator.generate()` expects: `task`, `main_user_*`, `trajectory_history`

### Q: Where does metadata come from?

**A**: Loaded from AppWorld dataset:
```python
sample = AppWorldSample(
    question=task_data.get('instruction', ''),
    metadata=task_data.get('supervisor', {}),  # Contains user info
    ...
)
```

### Q: Can I add more few-shot examples?

**A**: Yes! Modify the examples section in `appworld_prompts.py`, or pass when creating adapter:
```python
adapter = AppWorldOfflineAdapter(
    ...,
    # Custom examples can be added to prompts
)
```

### Q: What's the difference between offline and online?

**A**: See [ONLINE_VS_OFFLINE.md](ONLINE_VS_OFFLINE.md) for detailed comparison. Quick summary:
- **Offline**: Multiple epochs, deduplication, for benchmark
- **Online**: Single pass, immediate updates, for production

## Next Steps

1. **Optimize Prompts**: Adjust in [appworld_prompts.py](appworld_prompts.py)
2. **Add Few-shot Examples**: Increase examples for better performance
3. **Debug Loop**: Test complete flow with small sample set
4. **Full Training**: Run with complete training set over multiple epochs
5. **Evaluate**: Use online mode to evaluate on dev/test splits

## References

- [ACE Original Implementation](../src/opence/methods/ace/)
- [OpenCE Documentation](../CLAUDE.md)
- [AppWorld Benchmark](https://appworld.dev/)
- [Online vs Offline Comparison](ONLINE_VS_OFFLINE.md)
