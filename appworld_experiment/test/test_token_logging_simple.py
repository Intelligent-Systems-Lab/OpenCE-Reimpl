#!/usr/bin/env python3
"""Simple test to verify token logging works without needing AppWorld data.

This test creates mock components and verifies that:
1. Token usage is extracted from API responses
2. Logger receives and writes LLM call records
3. llm_calls.jsonl is created with correct format
"""

import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.opence.models.clients import OpenAIClient
from appworld_experiment.experiment_logger import ExperimentLogger, LLMCallRecord


def test_token_extraction():
    """Test that OpenAIClient extracts token usage from API."""
    print("=" * 80)
    print("Test 1: Token Extraction from API")
    print("=" * 80 + "\n")

    client = OpenAIClient(
        model="gpt-oss:20b",
        api_key="ollama",
        base_url="http://hc5.isl.lab.nycu.edu.tw:11434/v1"
    )

    prompt = "Return a JSON object with one key 'test' and value 'success'."

    print("📡 Sending test prompt to Ollama...")
    response = client.complete(prompt)

    print(f"✓ Response received: {response.text[:50]}...\n")

    print("Token usage:")
    print(f"  Estimated (pre-call):  {response.estimated_prompt_tokens:,}" if response.estimated_prompt_tokens else "  Estimated: Not available")
    print(f"  Actual prompt tokens:  {response.prompt_tokens:,}" if response.prompt_tokens else "  Actual prompt:     Not available")
    print(f"  Completion tokens:     {response.completion_tokens:,}" if response.completion_tokens else "  Completion:        Not available")
    print(f"  Total tokens:          {response.total_tokens:,}" if response.total_tokens else "  Total:             Not available")

    # Check estimation accuracy
    if response.estimated_prompt_tokens and response.prompt_tokens:
        diff = abs(response.estimated_prompt_tokens - response.prompt_tokens)
        pct_diff = (diff / response.prompt_tokens * 100) if response.prompt_tokens > 0 else 0
        print(f"\n  Estimation accuracy:   {100 - pct_diff:.1f}% (diff: {diff} tokens)")

    if response.total_tokens and response.estimated_prompt_tokens:
        print("\n✅ PASSED: Token estimation and extraction working\n")
        return True
    elif response.total_tokens:
        print("\n⚠️  WARNING: API returned tokens but estimation failed\n")
        return True
    else:
        print("\n❌ FAILED: No token information available\n")
        return False


def test_logger_functionality():
    """Test that ExperimentLogger can log LLM calls."""
    print("=" * 80)
    print("Test 2: ExperimentLogger LLM Call Logging")
    print("=" * 80 + "\n")

    # Clean up old log files first
    import shutil
    test_log_dir = Path("logs/appworld_experiments/token_test_simple")
    if test_log_dir.exists():
        shutil.rmtree(test_log_dir)

    logger = ExperimentLogger(experiment_name="token_test_simple")

    print(f"📁 Created logger at: {logger.log_dir}\n")

    # Log some mock LLM calls
    print("Logging 3 mock LLM calls...")

    logger.log_llm_call(
        task_id="test_task_1",
        role="generator",
        model="gpt-oss:20b",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        step=1,
        estimated_prompt_tokens=98,  # Slightly different to show estimation
    )

    logger.log_llm_call(
        task_id="test_task_1",
        role="reflector",
        model="gpt-oss:20b",
        prompt_tokens=200,
        completion_tokens=100,
        total_tokens=300,
    )

    logger.log_llm_call(
        task_id="test_task_1",
        role="curator",
        model="gpt-oss:20b",
        prompt_tokens=150,
        completion_tokens=75,
        total_tokens=225,
    )

    print("✓ 3 calls logged\n")

    # Verify file was created
    if not logger.llm_calls_file.exists():
        print(f"❌ FAILED: {logger.llm_calls_file} was not created!\n")
        return False

    print(f"✓ Log file created: {logger.llm_calls_file.name}\n")

    # Read and verify content
    with open(logger.llm_calls_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    print(f"File contains {len(lines)} lines\n")

    if len(lines) != 3:
        print(f"❌ FAILED: Expected 3 lines, got {len(lines)}\n")
        return False

    # Parse and verify JSON
    print("Verifying JSON records...")
    records = []
    for i, line in enumerate(lines):
        try:
            record = json.loads(line)
            records.append(record)
        except json.JSONDecodeError as e:
            print(f"❌ FAILED: Line {i+1} is not valid JSON: {e}\n")
            return False

    print(f"✓ All {len(records)} records are valid JSON\n")

    # Verify record structure
    required_fields = ['timestamp', 'task_id', 'role', 'model', 'prompt_tokens', 'completion_tokens', 'total_tokens']

    for i, record in enumerate(records):
        for field in required_fields:
            if field not in record:
                print(f"❌ FAILED: Record {i+1} missing field '{field}'\n")
                return False

    print("✓ All records have required fields\n")

    # Display sample record
    print("Sample record:")
    print(f"  {json.dumps(records[0], indent=2)}\n")

    print("✅ PASSED: Logger successfully creates and writes LLM call records\n")
    return True


def test_end_to_end():
    """Test end-to-end: API call → token extraction → logging."""
    print("=" * 80)
    print("Test 3: End-to-End Integration")
    print("=" * 80 + "\n")

    # Clean up old log files first
    import shutil
    test_log_dir = Path("logs/appworld_experiments/token_test_e2e")
    if test_log_dir.exists():
        shutil.rmtree(test_log_dir)

    # Create client and logger
    client = OpenAIClient(
        model="gpt-oss:20b",
        api_key="ollama",
        base_url="http://hc5.isl.lab.nycu.edu.tw:11434/v1"
    )

    logger = ExperimentLogger(experiment_name="token_test_e2e")

    print(f"📁 Logger directory: {logger.log_dir}\n")

    # Make real API call
    prompt = "Return JSON: {\"status\": \"ok\", \"number\": 42}"

    print("📡 Making API call...")
    response = client.complete(prompt)

    print(f"✓ Response: {response.text[:50]}...\n")

    # Log the call
    print("📝 Logging the call...")
    logger.log_llm_call(
        task_id="e2e_test",
        role="generator",
        model=client.model,
        prompt_tokens=response.prompt_tokens,
        completion_tokens=response.completion_tokens,
        total_tokens=response.total_tokens,
        step=1,
    )

    print("✓ Call logged\n")

    # Verify it was written
    if not logger.llm_calls_file.exists():
        print("❌ FAILED: Log file not created\n")
        return False

    with open(logger.llm_calls_file, 'r', encoding='utf-8') as f:
        line = f.read().strip()

    record = json.loads(line)

    print("Logged record:")
    print(f"  Task ID: {record['task_id']}")
    print(f"  Role: {record['role']}")
    print(f"  Model: {record['model']}")
    print(f"  Tokens: {record['prompt_tokens']} + {record['completion_tokens']} = {record['total_tokens']}")
    print()

    if record['total_tokens'] and record['total_tokens'] > 0:
        print("✅ PASSED: End-to-end integration works correctly\n")
        return True
    else:
        print("⚠️  WARNING: Token count is 0 or None\n")
        return False


def main():
    print("\n" + "="*80)
    print("Token Logging System Test Suite")
    print("="*80 + "\n")

    results = []

    # Run tests
    results.append(("Token Extraction", test_token_extraction()))
    results.append(("Logger Functionality", test_logger_functionality()))
    results.append(("End-to-End Integration", test_end_to_end()))

    # Summary
    print("=" * 80)
    print("Test Results Summary")
    print("=" * 80 + "\n")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}  {name}")

    print()
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests PASSED! Token logging system is working correctly.\n")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Please review the output above.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
