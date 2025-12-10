"""Simple test to verify 4k+ token sample handling."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.opence.models.clients import OpenAIClient


def main():
    # 建立一個超過 4k token 的 sample
    # 使用重複的文字確保超過目標 token 數
    base_text = (
        "In the field of artificial intelligence and machine learning, "
        "researchers are constantly exploring new methods to improve model "
        "performance and efficiency. Context engineering is an emerging area "
        "that focuses on optimizing how information is presented to language models. "
    )

    # 估計需要約 20,000 個字元才能達到 4500+ tokens (1 token ≈ 4 chars)
    sample = (base_text * 150)  # 重複 100 次，約 20,000+ 字元

    print(f"Sample 字元數: {len(sample):,}")
    print(f"估計 token 數: {len(sample) // 4:,}")
    print(f"\nSample 預覽 (前 100 字元):\n{sample[:100]}...\n")

    # 初始化 OpenAI client
    print("初始化 OpenAIClient...")
    client = OpenAIClient(
            model="32k-deepseek-r1:32b",
            api_key="ollama",
            base_url="http://localhost:11434/v1"
        )

    # 發送請求
    print("\n發送請求到 API...\n")
    prompt = f"Please count how many times the word 'artificial' appears in the following text:\n\n{sample}"

    response = client.complete(prompt)

    # 顯示結果
    print("=" * 70)
    print("TOKEN 使用統計")
    print("=" * 70)
    print(f"估計的 Prompt Tokens:     {response.estimated_prompt_tokens:>10,}")
    print(f"實際的 Prompt Tokens:     {response.prompt_tokens:>10,}")
    print(f"Completion Tokens:        {response.completion_tokens:>10,}")
    print(f"Total Tokens:             {response.total_tokens:>10,}")
    print("=" * 70)

    # 計算誤差
    if response.prompt_tokens and response.estimated_prompt_tokens:
        diff = response.prompt_tokens - response.estimated_prompt_tokens
        error_pct = (diff / response.estimated_prompt_tokens) * 100
        print(f"\n估計誤差: {diff:+,} tokens ({error_pct:+.2f}%)")

    # 判斷是否超過 4k
    if response.prompt_tokens > 4000:
        print(f"\n✅ 確認: Sample 超過 4k tokens! ({response.prompt_tokens:,} tokens)")
    else:
        print(f"\n⚠️  Sample 未超過 4k tokens ({response.prompt_tokens:,} tokens)")

    print(f"\n模型回應:\n{response.text}\n")


if __name__ == "__main__":
    main()
