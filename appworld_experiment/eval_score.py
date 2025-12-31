import os
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "ground_truth"
GT_LIST = os.listdir(GT)
IGNORE_API_CALL = ["/api_docs/app_descriptions",
                   "/api_docs/api_descriptions",
                   "/api_docs/api_doc"]

TASK_PATH = "/home/yanhong/appworld-server/experiments/outputs/appworld_ace_online_20251231_053904/tasks"
TASK_LIST = os.listdir(TASK_PATH)
full_data = {}

def compute_score(gt_calls, pred_calls):
    total_calls = len(gt_calls)
    currect_calls = 0

    for pred, gt in zip(pred_calls, gt_calls):
        if pred["url"] == gt["url"] and pred["data"] == gt["data"]:
            currect_calls += 1
    
    return currect_calls / total_calls if total_calls > 0 else 0.0

def load_ground_truth():
    for folder in GT_LIST:
        api_call_file = GT / folder / "api_calls.jsonl"
        task_id = folder.split("_")[0] + "_" + folder.split("_")[1]
    
        if task_id not in full_data:
            continue
        print(f"Processing task: {task_id}")
        data = full_data[task_id]
        
        with open(api_call_file, "r") as f:
            lines = f.readlines()
        data["gt"] = [json.loads(line) for line in lines]
        full_data[task_id] = data

def load_predictions():
    for task in TASK_LIST:
        data = {"gt": [], "pred": []}
        api_call_file = os.path.join(TASK_PATH, task, "logs", "api_calls.jsonl")
        task_id = task.split("_")[0] + "_" + task.split("_")[1]
        print(f"Processing task: {task_id}")

        with open(api_call_file, "r") as f:
            lines = f.readlines()
        data["pred"] = [json.loads(line) for line in lines if json.loads(line)["url"] not in IGNORE_API_CALL]
        full_data[task_id] = data

def evaluate():
    load_predictions()
    load_ground_truth()

    results = {}
    for task_id, data in full_data.items():
        gt_calls = data["gt"]
        pred_calls = data["pred"]
        score = compute_score(gt_calls, pred_calls)
        results[task_id] = score
        print(f"Task {task_id} - Score: {score}")
    return results

if __name__ == "__main__":
    res = evaluate()
    print(f"Average Score: {sum(res.values()) / len(res)}")





    