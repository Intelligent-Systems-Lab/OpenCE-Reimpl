#!/usr/bin/env python3
"""Test script to verify AppWorld prompt formatting is correct."""

from appworld_prompts import APPWORLD_GENERATOR_PROMPT

# Test parameters
test_params = {
    "playbook": "[Example playbook content]",
    "task": "Book a flight to San Francisco",
    "main_user_first_name": "John",
    "main_user_last_name": "Doe",
    "main_user_email": "john.doe@example.com",
    "main_user_phone_number": "+1234567890",
}

# Format the prompt
try:
    formatted_prompt = APPWORLD_GENERATOR_PROMPT.format(**test_params)
    print("✅ Prompt formatting successful!")
    print("\n" + "="*80)
    print("FORMATTED PROMPT PREVIEW:")
    print("="*80)
    print(formatted_prompt[:500])
    print("\n...")
    print("\n" + "="*80)
    print("LAST 500 CHARACTERS:")
    print("="*80)
    print(formatted_prompt[-500:])

    # Check that JSON examples are properly formatted (should contain single braces)
    if '"reasoning":' in formatted_prompt and '{{' not in formatted_prompt:
        print("\n✅ JSON examples are properly formatted (single braces)")
    else:
        print("\n⚠️  Warning: Check JSON formatting in examples")

    # Check that user info is properly inserted
    if "John Doe" in formatted_prompt and "john.doe@example.com" in formatted_prompt:
        print("✅ User parameters correctly inserted")
    else:
        print("❌ User parameters not found")

except KeyError as e:
    print(f"❌ Missing placeholder: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
