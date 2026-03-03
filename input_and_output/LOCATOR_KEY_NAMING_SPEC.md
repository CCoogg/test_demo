# LOCATOR_KEY_NAMING_SPEC.md
## Locator Key 命名规范（工业级指导版）

---

# 一、文档目标

本规范用于统一 locator_key（元素语义标识）命名规则，确保：

✅ DSL / YAML 稳定  
✅ Locator Registry 可维护  
✅ Agent 输出一致  
✅ 防止命名爆炸 / 漂移  
✅ 支持 Trace / Debug / 自愈（未来）  

---

# 二、Locator Key 的角色定位 ⭐⭐⭐⭐⭐

locator_key 是：

🎯 测试系统中的元素语义主键（Semantic Element ID）

作用：

✔ DSL 引用对象  
✔ Driver 查找入口  
✔ Registry 映射键  
✔ Agent 输出 target  
✔ Assertion 验证对象  

---

# 三、核心设计原则 ⭐⭐⭐⭐⭐

## ✅ 原则 1：locator_key 是逻辑语义名，不是 UI 属性

✔ LOGIN_BUTTON  
❌ login_btn  
❌ btn_123  
❌ text_login  

---

## ✅ 原则 2：命名必须稳定、可长期维护

❌ 禁止临时语义  
❌ 禁止版本相关命名  

---

## ✅ 原则 3：全局唯一 ⭐⭐⭐⭐⭐

✔ 一个逻辑元素 = 一个 locator_key  

---

## ✅ 原则 4：面向业务语义，而非视觉语义

✔ SUBMIT_ORDER_BUTTON  
❌ GREEN_BUTTON  

---

## ✅ 原则 5：命名不描述行为

✔ LOGIN_BUTTON  
❌ CLICK_LOGIN_BUTTON  

---

# 四、命名格式规范 ⭐⭐⭐⭐⭐

✔ 全大写  
✔ 下划线分隔  

示例：

LOGIN_BUTTON ✅  
PAGE_NUMBER ✅  
USERNAME_INPUT ✅  

---

# 五、命名语义规则 ⭐⭐⭐⭐⭐

推荐结构：

[业务域]_[元素语义]_[类型]

示例：

LOGIN_BUTTON  
ORDER_SUBMIT_BUTTON  
READING_PAGE_NUMBER  

---

# 六、禁止命名策略 ❌

❌ BTN_LOGIN（缩写）  
❌ BUTTON1（无语义）  
❌ LOGIN_BUTTON_NEW（版本污染）  

---

# 七、Agent 输出约束 ⭐⭐⭐⭐⭐

✔ target 必须来自 Registry Vocabulary  
或输出 locator_candidate  

---

# 八、Locator Candidate 规范 ⭐⭐⭐⭐

```json
{
  "locator_candidate": {
      "suggested_key": "LOGIN_BUTTON",
      "confidence": 0.72
  }
}
```

✔ 必须带 confidence  
✔ 不直接进入 DSL  

---

# 九、Registry 治理规则 ⭐⭐⭐⭐⭐

✔ 审核 candidate  
✔ 防止语义重复  

---

# 十、DSL 使用规则 ⭐⭐⭐⭐⭐

✔ DSL 永远引用 locator_key  
❌ 不写 resourceId  

---

# 十一、Trace 协作 ⭐⭐⭐⭐

✔ Trace 记录 locator_key + resolved_locator  

---

# 十二、设计收益 ⭐⭐⭐⭐⭐

✔ 防命名爆炸  
✔ 防 Registry 漂移  
✔ 提升稳定性  

---

# 十三、Acceptance Criteria ⭐⭐⭐⭐⭐

✔ 命名统一  
✔ locator_key 全局唯一  
✔ 禁止缩写 / 版本污染  
✔ candidate 带 confidence  

---

End of Document
