#!/usr/bin/env python3
"""Test script to verify context length logging works with Ollama.

This script demonstrates that token usage is now automatically logged
during AppWorld experiments.
"""

import sys
sys.path.insert(0, "/home/yanhong/OpenCE-Reimpl")

from src.opence.models.clients import OpenAIClient

# Example: Using with Ollama
client = OpenAIClient(
    model="deepseek-r1:32b",  # or whatever model you're using
    base_url="http://hc5.isl.lab.nycu.edu.tw:11434/v1",
    api_key="ollama",  # Ollama doesn't need real key
)

# Test with a simple prompt
print("=" * 60)
print("Testing context length logging with Ollama")
print("=" * 60)

test_prompt = """
You are a helpful assistant. Please respond with a JSON object.

Task: List 3 colors.

Respond in this format:
{
  "colors": ["color1", "color2", "color3"]
}
"""

print("\nSending prompt to LLM...")
response = client.complete(test_prompt)

print(f"\n{'-'*60}")
print("Response:")
print(response.text)
print(f"{'-'*60}")

# Access token counts from response object
print("\nToken Usage (from LLMResponse object):")
print(f"  Prompt tokens:     {response.prompt_tokens:,}" if response.prompt_tokens else "  Prompt tokens:     Not available")
print(f"  Completion tokens: {response.completion_tokens:,}" if response.completion_tokens else "  Completion tokens: Not available")
print(f"  Total tokens:      {response.total_tokens:,}" if response.total_tokens else "  Total tokens:      Not available")

print("\n" + "=" * 60)
print("Note: Ollama may not return token counts in the API response.")
print("If you see 'Not available', it means the Ollama API didn't provide")
print("usage statistics. Consider using tiktoken for estimation instead.")
print("=" * 60)
