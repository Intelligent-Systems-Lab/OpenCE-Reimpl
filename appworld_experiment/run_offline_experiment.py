#!/usr/bin/env python3
"""Run a minimal ACE offline adaptation loop with a local transformers model."""

from __future__ import annotations

import argparse
import json
import httpx
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for candidate in (SRC, ROOT):
    if str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

from opence.methods.ace import (
    Curator,
    EnvironmentResult,
    Generator,
    OfflineAdapter,
    Playbook,
    Reflector,
    Sample,
    TaskEnvironment,
    OpenAIClient
)

# Appworld dataset, environment, and sample definitions 
class AppWorldDataset:
    def __init__(self, data_path: str):
        self.data_path = data_path

    def load_samples(self, split: str = "train") -> List[AppWorldSample]:
        """Dataset have train/dev/test_normal/test_challenge splits."""
        
        file_path = Path(self.data_path,"datasets", split + ".txt")
        tasks_id = []
        # loading samples id from txt file
        with open(file_path, 'r', encoding='utf-8') as f:
            id = f.readlines()
            tasks_id.extend([i.strip() for i in id])

        samples = []
        # loading task data from json file
        for task_id in tasks_id:
            # task data path
            task_data_path =Path(self.data_path, "tasks", task_id)

            # spec file
            task_file = Path(task_data_path,"specs.json")
            with open(task_file, 'r', encoding='utf-8') as f:
                task_data = json.load(f)

            # ground truth file
            task_gt_path = Path(task_data_path, "ground_truth", "answer.json")
            with open(task_gt_path, 'r', encoding='utf-8') as f:
                gt_data = json.load(f)

            sample = AppWorldSample(
                task_id=task_id,
                question=task_data.get('instruction', ''),
                metadata=task_data.get('supervisor', {}),
                datetime=task_data.get('datetime', ''),
                ground_truth=gt_data
            )
            samples.append(sample)

            print(f"Successfully loaded task: {task_id}")
        
        print(f"Loaded {len(samples)} samples for split: {split}")
        return samples

@dataclass
class AppWorldSample(Sample):
    """
        AppWorld task sample.
        Base on the Sample class, extend with AppWorld-specific fields.
        question: instruction
        metadata: supervisor
    """
    task_id: str = ""
    datetime: str = ""
    context : str = """
        I am your supervisor and you are a super intelligent AI Assistant whose job is to achieve my day-to-day tasks completely autonomously.

        To do this, you will need to interact with apps/tools (e.g. spotify, venmo etc) using their associated APIs on my behalf. For this you will undertake a multi-step conversation using a python REPL environment. That is, you will write the python code and the environment will execute it and show you the result, based on which, you will write python code for the next step and so on, until you’ve achieved the goal. This environment will let you interact with apps/tools using their associated APIs on my behalf.

        Here are three key APIs that you need to know to get more information

        To get a list of apps that are available to you. **print(apis.api_docs.show_app_descriptions())**

        To get the list of apis under any app listed above, e.g. **spotify print(apis.api_docs.show_api_descriptions(app_name='spotify'))**

        To get the specification of a particular api, e.g. spotify app’s login api **print(apis.api_docs.show_api_doc(app_name='spotify', api_name='login'))**

        Each code execution will produce an output that you can use in subsequent calls. Using these APIs, you can now generate code, that I will execute, to solve the task.

        You are also provided with a curated cheatsheet of strategies, API-specific information, common mistakes, and proven solutions to help you solve the task effectively.
    """

class AppWorldEnvironment(TaskEnvironment):
    """透過 HTTP 與 AppWorld 服務通訊"""
    
    def __init__(self, base_url: str = "http://localhost:8777"):
        self.client = httpx.Client(base_url=base_url, timeout=120)
    
    def initialize_task(self, sample: AppWorldSample) -> dict:
        response = self.client.post("/initialize", json={
            "task_id": sample.task_id,
            "experiment_name": "ace_experiment"
        })
        print(f"Initialized task {sample.task_id}, response: {response.text}")
        print("Successfully initialized task.")
    
    def execute_code(self, task_id: str, code: str) -> dict:
        print(f"Executing code for task {task_id}...")
        print(f"Code:\n{code}\n")
        payload = {
            "task_id": task_id,
            "code": code
        }
        print(f"Payload for execution: {payload}")

        response = self.client.post("/execute", json=payload)
        print(f"Execution response: {response.text}")
        return response.json()
    
    def close_task(self, task_id: str) -> None:
        response = self.client.post("/close_all", json={"task_id": task_id})
        print(f"Closed task {task_id}, response: {response.text}")

    def evaluate(self, sample: AppWorldSample, generator_output) -> EnvironmentResult:
        # 1. Initialize the task
        self.initialize_task(sample)
        
        # 2. Execute the code generated by the Generator
        code = generator_output.final_answer
        result = self.execute_code(sample.task_id, code)
        
        # 3. Evaluate the result
        complete_result = self.client.post("/task_completed", json={"task_id": sample.task_id,})
        print(f"Task completion response: {complete_result.text}")

        # 4. Return environment result
        # success = eval_result.get("success", False)

        # 5. close the task
        self.close_task(sample.task_id)

        return EnvironmentResult(
            feedback=f"Task completed. Result: {result}",
            ground_truth="task_completed",
            metrics={"accuracy": 1.0 if complete_result else 0.0}
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="Sampling temperature for generation.",
    )
    return parser.parse_args()


def main() -> None:
    # client = TransformersLLMClient(
    #     args.model_path,
    #     max_new_tokens=args.max_new_tokens,
    #     temperature=args.temperature,
    #     torch_dtype="bfloat16",
    #     device_map="auto",
    # )

    client = OpenAIClient(
        model="qwen2.5:7b",
        api_key="ollama",
        base_url="http://hc5.isl.lab.nycu.edu.tw:11434/v1"
    )
    
    generator = Generator(client)
    reflector = Reflector(client)
    curator = Curator(client)
    adapter = OfflineAdapter(
        playbook=Playbook(),
        generator=generator,
        reflector=reflector,
        curator=curator,
        max_refinement_rounds=3,
    )

    dataset = AppWorldDataset("/home/yanhong/appworld-server/data")
    samples: List[Sample] = dataset.load_samples(split="train")
    environment = AppWorldEnvironment()
    print("Starting offline adaptation with 1 sample...")
    results = adapter.run(samples, environment, epochs=1)

    for step, result in enumerate(results, start=1):
        print(f"\nStep {step}:")
        print(f"  Question: {result.sample.question}")
        print(f"  Model final answer: {result.generator_output.final_answer}")
        print(f"  Feedback: {result.environment_result.feedback}")
        print("  Reflection:")
        print(json.dumps(result.reflection.raw, ensure_ascii=False, indent=2))
        print("  Curator operations:")
        print(json.dumps(result.curator_output.raw, ensure_ascii=False, indent=2))

    print("\nFinal playbook:\n")
    print(adapter.playbook.as_prompt() or "(playbook is empty)")


if __name__ == "__main__":
    main()
