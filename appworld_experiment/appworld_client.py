#!/usr/bin/env python3
"""
AppWorld HTTP Client 測試腳本
直接透過 HTTP 與 AppWorld environment 服務通訊
"""

import httpx
import json

# 配置
BASE_URL = "http://localhost:8777"

def main():
    client = httpx.Client(base_url=BASE_URL, timeout=60)
    
    # ========================================
    # Step 1: 測試基本連線
    # ========================================
    print("=" * 50)
    print("Step 1: 測試基本連線")
    print("=" * 50)
    
    try:
        r = client.get("/")
        print(f"狀態碼: {r.status_code}")
        print(f"回應: {r.text[:300]}")
    except Exception as e:
        print(f"❌ 連線失敗: {e}")
        return
    
    # ========================================
    # 查看API文件
    # ========================================
    print("\n" + "=" * 50)
    print("查看 OpenAPI 文件")
    print("=" * 50)

    try:
        r = client.get("/api_docs")
        print(f"Redoc 狀態碼: {r.status_code}")
        print(f"Redoc 回應預覽: {r.text[:300]}")
    except Exception as e:
        print(f"❌ Redoc 連線失敗: {e}")

    # ========================================
    # Step 2: 查看 API 參數格式
    # ========================================
    print("\n" + "=" * 50)
    print("Step 2: 查看 /initialize 參數格式")
    print("=" * 50)
    
    r = client.get("/openapi.json")
    schema = r.json()
    
    # 顯示 initialize 端點的詳細資訊
    if "/initialize" in schema.get("paths", {}):
        init_schema = schema["paths"]["/initialize"]
        print(json.dumps(init_schema, indent=2, ensure_ascii=False)[:1000])
    
    # ========================================
    # Step 3: 初始化任務
    # ========================================
    print("\n" + "=" * 50)
    print("Step 3: 初始化任務")
    print("=" * 50)
    
    # close all tasks before starting new ones
    # 先嘗試一個簡單的 task_id（train 集的第一個）
    # 你可能需要從 appworld-server/data/datasets/train.txt 獲取真實的 task_id
    
    # 嘗試不同的請求格式
    test_payloads = [
        # 格式 1: 直接 JSON body
        {"task_id": "0a9d82a_1", "load_ground_truth": "true","ground_truth_mode": "fullminimal"},
    ]
    
    for i, payload in enumerate(test_payloads):
        print(f"\n嘗試格式 {i+1}: {payload}")
        try:
            r = client.post("/initialize", json=payload)
            print(f"  狀態碼: {r.status_code}")
            print(f"  回應: {r.text}")
            
            if r.status_code == 200:
                print("  ✅ 成功!")
        except Exception as e:
            print(f"  ❌ 失敗: {e}")
    
    # ========================================
    # Step 4: Execute 任務代碼
    # ========================================
    print("\n" + "=" * 50)
    print("Step 4: Execute 任務代碼")
    print("=" * 50)

    test_code ="print(answer=4)"
    
    
    for i, payload in enumerate(test_payloads):
        print(f"\n嘗試格式 {i+1}: {payload}")
        json_payload = {
            "task_id": payload["task_id"],
            "code": test_code
        }
        print(json_payload)
        try:
            r = client.post("/execute", json=json_payload)
            print(f"  狀態碼: {r.status_code}")
            print(f"  回應: {r.text}")
            
            if r.status_code == 200:
                print("  ✅ 成功!")
            
            print("\n" + "=" * 50)
            print("Step 5: task_completed")
            print("=" * 50)
            r = client.post("/task_completed", json={"task_id": payload["task_id"]})
            print(f"  狀態碼: {r.status_code}")
            print(f"  回應: {r.text}")

            print("\n" + "=" * 50)
            print("Step 5: 評估任務完成")
            print("=" * 50)
            r = client.post("/evaluate", json={"task_id": payload["task_id"], "report": "true"})
            print(f"  狀態碼: {r.status_code}")
            print(f"  回應: {r.text}")
            
            if r.status_code == 200:
                print("  ✅ 成功!")

            response = client.post("/close_all", json={"task_id": payload["task_id"]},)
            print(f"關閉任務狀態碼: {response.status_code}")
            print(f"關閉任務回應: {response.text}")
        except Exception as e:
            print(f"  ❌ 失敗: {e}")
            
    
    client.close()
    print("\n✅ 測試完成!")

if __name__ == "__main__":
    main()