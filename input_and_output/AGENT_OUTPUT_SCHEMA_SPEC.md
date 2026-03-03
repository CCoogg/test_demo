# AGENT_OUTPUT_SCHEMA_SPEC.md
## Agent 输出 Schema 规范（工业级完整版）

---

# 一、文档目标

本规范定义 Agent 执行测试用例后的标准化 JSON 输出结构，用于：

CSV（文字版测试用例）  
→ Agent 执行  
→ Agent JSON Output ⭐⭐⭐⭐⭐  
→ Locator Registry 冷启动 / 更新  
→ YAML DSL 固化  

目标：

✅ 输出可控、稳定、可验证  
✅ 避免 DSL / UI 信息污染  
✅ 支持 Registry / YAML / Trace 多场景复用  

---

# 二、核心设计原则 ⭐⭐⭐⭐⭐

## ✅ 原则 1：输出必须结构化 JSON

❌ 禁止自然语言  
❌ 禁止纯文本 log  

---

## ✅ 原则 2：DSL 与 UI 信息严格隔离 ⭐⭐⭐⭐⭐

DSL 字段 → 用于 YAML DSL  
UI 字段 → 用于 Observation / Registry / Debug  

❌ 禁止混写。

---

## ✅ 原则 3：Steps / Assertions = DSL 粒度 ⭐⭐⭐⭐⭐

✔ action = DSL Action  
✔ type = Assertion DSL Type  

❌ 禁止 resourceId / driver API  

---

## ✅ 原则 4：Observations = UI 物理快照 ⭐⭐⭐⭐⭐

✔ 可包含 resourceId / text / bounds  
✔ 不进入 DSL  

---

## ✅ 原则 5：Assertions 使用 Suggestion 模型 ⭐⭐⭐⭐⭐

✔ type_suggestion  
✔ confidence  

❌ 禁止 final_type  

示例：

{
  "type_suggestion": "text_equals",
  "target": "PAGE_NUMBER"
}

---

## ✅ 原则 6：action 字段语义澄清 ⭐⭐⭐⭐⭐

action = DSL 级动作语义（Declarative Test Action）

❌ 禁止 Driver / 引擎动作：
- click
- press
- touchAction
- 坐标操作

✅ 合法 DSL Vocabulary（示例）：
- tap
- input
- swipe
- long_press
- wait

推断优先级：

1️⃣ 明确动词优先  
2️⃣ 手势词次优  
3️⃣ fallback = tap  

---

歧义策略：

“操作按钮” → 若 target=BUTTON → tap（低 confidence）

---

参数提取：

输入 test_user  
→ params.text = test_user

---

# 三、标准输出结构 ⭐⭐⭐⭐⭐

```json
{
  "case_meta": {},
  "steps": [],
  "assertions": [],
  "observations": []
}
```

---

# 四、Steps Schema ⭐⭐⭐⭐⭐

```json
{
  "step_index": 1,
  "action": "tap",
  "target": "LOGIN_BUTTON",
  "zone": null,
  "params": {},
  "status": "passed | failed",
  "error": null
}
```

约束：

✔ action 必须来自 Action Registry  
✔ target XOR zone  
❌ 禁止 resourceId / xpath / 坐标  

---

# 五、Assertions Schema ⭐⭐⭐⭐⭐

```json
{
  "assertion_index": 1,
  "type_suggestion": "text_equals",
  "confidence": 0.82,
  "target": "PAGE_NUMBER",
  "params": {
      "expected": "2"
  },
  "status": "passed | failed"
}
```

约束：

✔ type_suggestion 必填  
✔ confidence 必填  
❌ 禁止 final_type  

---

# 六、Observations Schema ⭐⭐⭐⭐⭐

```json
{
  "related_step": 1,
  "coord": [400, 154],
  "element_snapshot": {
      "text": "登录",
      "resourceId": "com.xxx:id/login_btn",
      "class": "android.widget.Button",
      "bounds": "[123,456][234,567]"
  },
  "locator_candidate": {
      "suggested_key": "LOGIN_BUTTON",
      "confidence": 0.76
  }
}
```

用途：

✔ Registry 建立 / Debug / 自愈分析  

---

# 七、Confidence 规则 ⭐⭐⭐⭐⭐

≥ 0.8 → 可自动接受  
0.5 ~ 0.8 → 人工确认  
< 0.5 → 默认忽略  

---

# 八、禁止行为 ⭐⭐⭐⭐⭐

❌ 输出自然语言  
❌ DSL 中写 UI 物理字段  
❌ Assertions 输出 final_type  
❌ Steps 输出 resourceId  

---

# 九、Acceptance Criteria ⭐⭐⭐⭐⭐

✔ JSON 合法  
✔ Steps DSL 粒度  
✔ Assertions Suggestion 模型  
✔ Observations UI 粒度  
✔ 无 DSL / UI 污染  

---

End of Document
