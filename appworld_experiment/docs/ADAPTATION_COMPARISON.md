Here is the translation formatted as a professional technical documentation page.

-----

# Online vs. Offline Adaptation

This document outlines the architectural and functional differences between **Offline Adaptation** and **Online Adaptation** within the ACE framework. It provides guidance on selecting the appropriate mode for different use cases, specifically within the context of the `OpenCE` codebase.

## Core Differences Summary

| Feature | Offline Adaptation | Online Adaptation |
| :--- | :--- | :--- |
| **Data Processing** | Batch processing (Epoch-based) | Streaming processing |
| **Playbook Updates** | Updates per sample; Deduplication per epoch | Updates immediately per sample |
| **Training Loop** | Multiple passes over a fixed dataset | Single pass over a data stream |
| **Target Scenario** | Fixed training sets (Benchmarks/Research) | Real-time deployment, Continuous Learning |
| **Deduplication** | Supported (executed at end of epoch) | Not supported |
| **Progress Tracking** | `epoch` / `total_epochs` | Incremental step counter |

-----

## Detailed Comparison

### 1\. Offline Adaptation

**Source Location:** [`adaptation.py:150-201`](https://www.google.com/search?q=../src/opence/methods/ace/adaptation.py%23L150-L201)

The `OfflineAdapter` is designed for scenarios where the entire dataset is available beforehand and iterative optimization is required.

#### Key Characteristics

```python
class OfflineAdapter(AdapterBase):
    def run(self, samples: Sequence[Sample], environment, epochs=1):
        # Key Features:
        # 1. Multi-round training (Epochs)
        # 2. Requires a fixed Sequence of samples
        # 3. Supports Playbook deduplication after each epoch
        # 4. Collects bullet_ids for batch processing
```

#### Execution Flow

1.  Iterate through `1..N` epochs.
2.  For each `sample` in `samples`:
      * **Generator** produces a response.
      * **Environment** evaluates the response.
      * **Reflector** analyzes the result.
      * **Curator** updates the Playbook.
      * System collects `bullet_ids` generated during this step.
3.  **End of Epoch:** Trigger the `Deduplicator` (if configured) to refine the Playbook.

#### Pros & Cons

  * ✅ **High Quality:** Allows multi-epoch training to refine strategies.
  * ✅ **Concise Knowledge:** Supports deduplication to remove redundant insights.
  * ✅ **Stability:** Ideal for fixed datasets where reproducibility matters.
  * ❌ **Resource Intensive:** Higher memory usage (tracks results for batch ops).
  * ❌ **Latency:** Not suitable for streaming or real-time applications.

-----

### 2\. Online Adaptation

**Source Location:** [`adaptation.py:204-224`](https://www.google.com/search?q=../src/opence/methods/ace/adaptation.py%23L204-L224)

The `OnlineAdapter` is designed for real-time environments where data arrives sequentially and the model must adapt on the fly.

#### Key Characteristics

```python
class OnlineAdapter(AdapterBase):
    def run(self, samples: Iterable[Sample], environment):
        # Key Features:
        # 1. Single pass (No Epoch concept)
        # 2. Accepts Iterable inputs (supports Python generators)
        # 3. No deduplication mechanism
        # 4. Immediate, real-time updates
```

#### Execution Flow

1.  Iterate through `sample` in `streaming_samples`:
      * **Generator** produces a response.
      * **Environment** evaluates the response.
      * **Reflector** analyzes the result.
      * **Curator** immediately updates the Playbook.
2.  Process continues indefinitely or until the stream ends.

#### Pros & Cons

  * ✅ **Scalable:** Supports infinite data streams.
  * ✅ **Responsive:** Real-time learning and adaptation.
  * ✅ **Efficient:** Lower memory footprint (processes one sample at a time).
  * ✅ **Production Ready:** Suitable for live deployment.
  * ❌ **Redundancy:** Lack of deduplication may lead to a bloated Playbook.
  * ❌ **Shallow Learning:** Only sees each sample once (Single pass).

-----

## Shared Architecture

Both adapters inherit from `AdapterBase` and share the core logic pipeline:

1.  **Unified Processing Flow** (`_process_sample`):

    ```mermaid
    graph LR
    A[Generator] --> B[Environment]
    B --> C[Reflector]
    C --> D[Curator]
    D --> E[Playbook Update]
    ```

2.  **Shared Components:**

      * **Generator:** Creates the solution/action.
      * **Reflector:** Analyzes errors and successes.
      * **Curator:** Manages the addition of new insights.
      * **Playbook:** The evolving knowledge base.

3.  **Reflection Window:** Both maintain a sliding window of the most recent $N$ reflections to provide context.

-----

## Decision Guide: Which one to choose?

### Choose **Offline Adaptation** when:

  * You are working with a **fixed training dataset**.
  * You need **multi-epoch optimization** to maximize performance.
  * **Playbook quality** (conciseness) is more important than speed.
  * You have sufficient memory and time for batch processing.
  * **Typical Use Case:** Training on the **AppWorld benchmark**.

### Choose **Online Adaptation** when:

  * Data is arriving via a **stream** (e.g., live user requests).
  * You need the system to **respond and learn in real-time**.
  * Memory resources are constrained.
  * You are deploying the agent in a **production environment**.
  * **Typical Use Case:** A live chat-bot or autonomous agent in the wild.

-----

## Implementation Details & Configuration

### Why AppWorld uses Offline Adaptation

For the AppWorld benchmark reproduction, **Offline Adaptation** is the correct choice because:

1.  AppWorld provides a static dataset for evaluation.
2.  Reproducing the paper's results requires **multi-epoch training** (typically 3 epochs).
3.  **Deduplication** is critical to prevent the Playbook from growing too large during training.

### Key Code Differences

#### Offline Implementation

```python
# 1. Deduplicator Support
self.deduplicator = deduplicator

# 2. Epoch Loop
for epoch_idx in range(1, epochs + 1):
    bullet_ids_this_epoch = []
    # ... process samples ...

    # 3. Post-Epoch Deduplication
    if self.deduplicator:
        self.playbook.deduplicate(self.deduplicator, bullet_ids_this_epoch)
```

#### Online Implementation

```python
# 1. No Epoch Parameter
def run(self, samples: Iterable[Sample], environment):

# 2. Incremental Step Counting
total_steps = step_idx  # Real-time counter

# 3. No Deduplication Logic
# (The deduplicator is never invoked in the online loop)
```

-----

## Conclusion

  * **Offline Mode:** Optimized for **Batch, Multi-Round, High-Quality** training (Research/Benchmarks).
  * **Online Mode:** Optimized for **Streaming, Single-Pass, Real-Time** adaptation (Production/Deployment).

**Recommendation for AppWorld:** Stick to the **Offline Adapter** configuration.