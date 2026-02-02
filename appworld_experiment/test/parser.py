import re
import json
import ast

def strict_required_parser(md_text, schema):
    """
    嚴格必要欄位解析器。
    
    參數:
    md_text: LLM 輸出的 Markdown 字串
    schema: 定義需要的 Key 與其資料型態參考 (值的內容不作為 default，僅作類型參考)
            格式: {"required_key": "any_value_for_type_inference"}
            
    行為:
    1. 缺少 Key -> Raise ValueError (報錯)
    2. 多餘 Key -> Ignore (忽略，不寫入結果)
    """
    
    # ==========================================
    # 1. 預處理：解析 Markdown 原始結構
    # ==========================================
    lines = md_text.strip().split('\n')
    raw_data = {}
    current_key = None
    current_content = []
    in_code_block = False
    
    for line in lines:
        stripped = line.strip()
        
        # 處理程式碼區塊標記
        if stripped.startswith("```"):
            in_code_block = not in_code_block
        
        # 偵測標題 (必須在 code block 之外)
        if not in_code_block and re.match(r'^#+\s+', stripped):
            # 儲存上一段
            if current_key:
                raw_data[current_key] = "\n".join(current_content).strip()
            
            # 正規化標題: 去除 #, 去空白, 轉小寫, 空格轉底線
            header_text = re.sub(r'^#+\s+', '', stripped).strip()
            normalized_key = header_text.lower().replace(" ", "_")
            
            current_key = normalized_key
            current_content = []
        else:
            current_content.append(line)
            
    # 儲存最後一段
    if current_key:
        raw_data[current_key] = "\n".join(current_content).strip()

    # ==========================================
    # 2. 驗證缺少 Key (Missing Keys Validation)
    # ==========================================
    
    required_keys = set(schema.keys())
    found_keys = set(raw_data.keys())
    
    # 計算缺少的 Keys
    missing_keys = required_keys - found_keys
    
    if missing_keys:
        error_msg = f"Parsing Error: Missing required keys in output: {list(missing_keys)}"
        raise ValueError(error_msg)

    # ==========================================
    # 3. 組裝結果 (只取 Schema 有的，忽略多餘的)
    # ==========================================
    final_result = {}
    
    # 只遍歷 schema 裡定義的 key，這樣自然就忽略了 raw_data 裡多餘的 key
    for key in schema.keys():
        content = raw_data[key]
        
        # --- 智慧內容清洗 ---
        
        # 1. 嘗試去除 ```python ... ``` 包裝
        code_match = re.search(r'^```\w*\n(.*?)\n```$', content, re.DOTALL)
        if code_match:
            final_result[key] = code_match.group(1).strip()
            continue

        # 2. 嘗試解析 List
        # 這裡我們可以用 schema 傳入的值來判斷「是否期望它是 List」
        # 如果 schema[key] 是一個 list (如 [])，我們就嘗試 parse
        expected_val = schema[key]
        if isinstance(expected_val, list) or (content.startswith("[") and content.endswith("]")):
            try:
                if content.lower() == "none":
                    final_result[key] = []
                else:
                    parsed = ast.literal_eval(content)
                    if isinstance(parsed, list):
                        final_result[key] = parsed
                        continue
            except:
                pass 
        
        # 3. 預設保留純文字
        final_result[key] = content

    return json.dumps(final_result, indent=2, ensure_ascii=False)

# ==========================================
# 測試區
# ==========================================

# 定義 Schema (這裡的值只用於類型參考，不再作為預設值 fallback)
MY_SCHEMA = {
    "reasoning": "",         
    "playbook_ids": [],      
    "python_code": "" 
}

# --- 案例 1: 正常成功 ---
print("--- Test 1: Success ---")
valid_input = """
### Reasoning
All good.
### Playbook IDs
['ID_1']
### Python Code
print(1)
"""
print(strict_required_parser(valid_input, MY_SCHEMA))


# --- 案例 2: 忽略多餘 Key (Extra Keys Ignored) ---
print("\n--- Test 2: Ignore Extra Keys ---")
extra_input = """
### Reasoning
I have extra thoughts.
### Playbook IDs
['ID_1']
### Python Code
print(1)
### Secret Notes
Ignore this please.
"""
# 預期：Secret Notes 不會出現在 JSON 中，也不會報錯
print(strict_required_parser(extra_input, MY_SCHEMA))


# --- 案例 3: 缺少 Key 報錯 (Missing Key Raises Error) ---
print("\n--- Test 3: Missing Key Error ---")
missing_input = """
### Reasoning
I forgot the code...
### Playbook IDs
['ID_1']
"""
try:
    print(strict_required_parser(missing_input, MY_SCHEMA))
except Exception as e:
    print(f"CAUGHT ERROR: {e}")