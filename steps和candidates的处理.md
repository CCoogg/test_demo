# steps 和 candidates 的处理总结

## 目标与规范来源
- steps 使用语义层产物，不直接写 UI 物理属性。
- locator_candidate 作为证据输出，放在 observations 中。
- 规范依据：
  - `input_and_output/LOCATOR_KEY_NAMING_SPEC.md`
  - `input_and_output/LOCATOR_CANDIDATE_RESOLUTION_SPEC.md`

## steps 处理规则
- steps.action 仍由模型输出的动作类型决定（Tap/Swipe/Wait/Back/Launch 等）。
- steps.target **不写 UI 物理属性**（resourceId/text/bounds）。
- 若需要语义 target，应来自 Registry 或人工审核后的语义 key。
- steps.params 可以保留动作必要参数（坐标、duration 等）用于回溯与排障。

## 常规步骤定义（需记录 locator_candidate）
- 目标：有助于下游固定测试代码的可定位动作，都尽量记录 locator_candidate。
- 常规步骤（目前认定）：Tap / Double Tap / Long Press / Swipe / Type / Type_Name / Scroll / Drag / Press / Back / Wait。
- 说明：
  - 若动作本身没有可用坐标（例如 Type/Back/Wait），则 locator_candidate 只能按“best-effort”跳过。
  - 若动作包含坐标参数（element/start/end），优先使用 element；否则使用 start；仍无则可使用 end。

## locator_candidate 输出位置
- 输出在 JSONL 每条用例的 `observations` 数组中。
- 结构示例：
  ```json
  {
    "related_step": 1,
    "coord": [400, 154],
    "element_snapshot": {"text":"登录","resourceId":"com.xxx:id/login_btn","class":"android.widget.Button","bounds":"[1,2][3,4]","clickable":"true","contentDesc":null},
    "locator_candidate": {
      "strategies": [
        {"by":"id","value":"com.xxx:id/login_btn"},
        {"by":"text","value":"登录"},
        {"by":"class_chain","value":"..."}
      ],
      "confidence": 0.82
    }
  }
  ```

## locator_candidate 生成规则（按规范实现）
- 点击前获取 UI 树（uiautomator dump）。
- 取 bounds 包含点击点的节点集合；若无则容差 3-5px。
- 候选裁决优先级：
  - `resourceId > content-desc > text > class_chain`
- confidence 计算：
  - 有 resourceId +0.4
  - clickable=true +0.2
  - 有 text +0.2
  - 有 content-desc +0.1
- 容器被点击时：
  - 若节点无 id/text/desc 且不可点击 → 优先找最近 clickable 子节点；否则找最近 clickable 父节点。

## 关键约束
- 坐标不是 locator，仅作为操作证据保留在 steps.params。
- locator_candidate 不等于最终 locator_key，需要后续裁决与审核。

## 实现位置（便于回忆）
- 生成逻辑：`tools/csv_runner.py`
- 输出位置：JSONL 的 `observations`

