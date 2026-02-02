import os
import json
from pathlib import Path
from dotenv import load_dotenv
from sklearn import metrics
load_dotenv()

ROOT = Path(__file__).resolve().parents[1]
GT = ROOT / "ground_truth"
LOGS_PATH = os.getenv("LOG_FILE_PATH", "undefined_path")

full_data = {}
scenario_summary = {}

def compute_sgc_summary(scenario: dict) -> dict:
    total_scenarios = len(scenario)
    passed_scenarios = 0

    scenario_keys = sorted(scenario.keys())
    for scenario_id in scenario_keys:
        passed_scenario = 0
        for subtask_id in scenario[scenario_id]:
            if scenario[scenario_id][subtask_id] == 1.0:
                passed_scenario += 1
        print(f"Scenario {scenario_id}: Passed {passed_scenario}/{len(scenario[scenario_id])} subtasks.")
        if passed_scenario == len(scenario[scenario_id]):
            passed_scenarios += 1
            print(f"Scenario {scenario_id} passed all subtasks.")
    return {
        "total_scenarios": total_scenarios,
        "passed_scenarios": passed_scenarios,
        "sgc_score": passed_scenarios / total_scenarios if total_scenarios > 0 else 0.0
    }
        

def load_tgc():
    with open(LOGS_PATH, "r") as f:
        logs = json.load(f) 
    for phase in logs["phases"]:
        for task in logs["phases"][phase]["per_task_results"]:
            scenario_id = task["task_id"].split("_")[0]
            if scenario_id not in scenario_summary:
                scenario_summary[scenario_id] = {}

            scenario_summary[scenario_id][task["task_id"]] = task["tgc"]

def evaluate():
    load_tgc()

    result = compute_sgc_summary(scenario_summary)
    
    return result

if __name__ == "__main__":
    res = evaluate()
    print("SGC Evaluation Results:")
    print(f"Total Scenarios: {res['total_scenarios']}")
    print(f"Passed Scenarios: {res['passed_scenarios']}")
    print(f"SGC Score: {res['sgc_score']:.4f}")






    