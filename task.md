# CSV→逐子步骤执行→JSONL 输出（Task 清单）

目标：读取 `input_and_output/ReadingApp_测试用例.csv`，按行执行用例；每条“子步骤”强制模型 `finish` 一次；每条用例输出 1 行 JSON（JSONL），结构符合 `input_and_output/AGENT_OUTPUT_SCHEMA_SPEC.md`（最小实现允许在 observations 中携带 `screenshot_path`，且仅在失败时保存截图）。

---

## 0) Runner 位置与最小命令

- 入口脚本：`tools/csv_runner.py`（支持 `--target-package com.example.readingapp` 绑定目标应用）
- 最小命令（干跑验证，不连设备/模型）：
  - `python tools/csv_runner.py --csv input_and_output/ReadingApp_测试用例.csv --dry-run`
- 实机执行（示例，Android + 本地模型服务）：
  - `python tools/csv_runner.py --csv input_and_output/ReadingApp_测试用例.csv --base-url http://localhost:8000/v1 --model autoglm-phone-9b --device-type adb`

---

## 1) 输入与数据约定

- [x] 固定 CSV 表头映射（至少支持这些列）：
  - `用例编号`、`应用端`、`模块`、`用例标题`、`前置条件`、`页面进入步骤`、`测试步骤`、`预期结果`、`优先级`（`测试结果/测试执行过程`可忽略不回填）
- [x] 定义“子步骤”拆分规则：
  - 将 `页面进入步骤` 和 `测试步骤` 的内容合并后，统一拆分为 `test_steps[]` 数组
  - 拆分依据（保守实现）：按“换行”和“；/;”分割；将来可扩展对 `1./（1）/1）` 等编号前缀的识别
- [x] 定义空值与跳过规则（如：步骤为空、优先级过滤、用例编号白名单）
- [ ] 定义变量替换（可选）：如 `{{xxx}}` 的替换来源与策略（后续补）

---

## 2) 运行器（Runner）总体结构

- [x] 新增 runner 入口：`tools/csv_runner.py`
- [x] 支持 CLI 参数：
  - `--csv path`、`--out outputs/run-YYYYmmdd-HHMMSS.jsonl`（未提供时自动生成）
  - `--device-type adb|hdc|ios`、`--device-id ...`
  - `--base-url ...`、`--model ...`、`--apikey ...`、`--lang cn|en`
  - `--max-steps-per-substep N`（子步骤内允许的 agent 回合上限，默认 6）
  - `--filter-priority ...` / `--filter-module ...` / `--case-ids id1,id2`
  - `--resume`（断点续跑：跳过已输出的用例编号）
  - `--dry-run`（不连模型/设备，仅生成占位输出）
- [x] 产物目录约定：
  - JSONL：`outputs/<run_id>.jsonl`（每行 1 个用例 JSON）
  - 证据：`outputs/<run_id>/artifacts/<case_id>/subXX_stepYY.png`

---

## 3) “子步骤必须 finish” 的执行策略（关键）

为保证 JSONL 里 `steps` 可靠可复盘：每条子步骤都以一次 `finish` 作为边界。

- [x] 子步骤执行模式：A. 子步骤独立会话（每个子步骤 `agent.reset()` 后执行到 `finish` 即停止）
- [x] Prompt 约束（在系统 Prompt 基础上）：仅完成当前子步骤并 `finish`，禁止越界（由 `PhoneAgent` 系统提示词与动作解析保障，Runner 以回合上限兜底）
- [x] 将“模型输出动作序列”落到 `steps[]`：
  - 每个 `do(...)` → 1 条 `steps`（`action/params/status/error`）；`target/zone` 暂时留空（后续由 registry & UI tree 反推）
  - 子步骤收束时的 `finish(...)` 通过 `status` 与最后一条动作体现

---

## 4) Observations（证据采集）能力（最小先行）

- [x] 仅在失败时采集整屏截图，保存到 `artifacts/<case_id>/subXX_stepYY.png`
- [x] 在 `observations[]` 写入：`related_step` + `screenshot_path`（仅失败步骤存在）
- [x] 常规动作可写 `locator_candidate`；同时记录 `coord` 以便与 steps 的坐标回放对应
- [x] UI 文本采集：Android 通过 `uiautomator dump` 提取 text/content-desc，用于基础断言
- [x] UI 树/元素快照：对常规动作 best-effort 生成 `element_snapshot/locator_candidate`

---

## 5) Assertions（从“预期结果”生成并验证）

- [x] 起步：从 `预期结果` 解析关键短语并在 UI 文本中做 contains 校验，输出到 `assertions[]`（`type_suggestion/params/status/confidence`）
- [ ] 验证优先基于 UI 树；必要时再 OCR 或图片比对（后续补）

---

## 6) 可靠性与治理

- [x] 子步骤回合上限：`--max-steps-per-substep`
- [x] 断点续跑：`--resume` 读取既有 JSONL 跳过已完成 `用例编号`
- [x] 错误分级：单用例错误 → 记录失败并继续；致命/环境级错误 → 进程非零退出
- [x] 输出前做最小 schema 校验（软校验，无 `jsonschema` 依赖），可选参考：`input_and_output/agent_output.schema.json`

---

## 7) JSONL 行结构（最小实现要求）

- [x] 每行 JSON 至少包含：
  - `case_meta`：从 CSV 映射 + 运行元信息（run_id、device、model、timestamps）
  - `steps`：动作级记录（含 `step_index/status/error`；`target/zone` 先留空）
  - `assertions`：允许为空数组（后续补）
  - `observations`：失败步骤包含 `related_step` 与 `screenshot_path`
- [x] 输出前做最小结构校验（字段齐全、类型基本正确）

最小示例（节选，失败截屏场景）：
```json
{
  "case_meta": {"case_id": "TC–书架–001", "run_id": "run-20260101-120000"},
  "steps": [
    {"step_index": 1, "action": "Tap", "target": null, "zone": null, "params": {"start": [100,200]}, "status": "failed", "error": "element not found"}
  ],
  "assertions": [],
  "observations": [
    {"related_step": 1, "screenshot_path": "outputs/run-20260101-120000/artifacts/TC–书架–001/sub01_step01.png"}
  ]
}
```

---

## 8) 验收标准（Definition of Done）

- [x] 给定 `input_and_output/ReadingApp_测试用例.csv`（可先选 3–5 条），能稳定输出 `outputs/<run_id>.jsonl`
- [x] 每条用例在 JSONL 中：
  - 子步骤边界清晰（每条子步骤都有 `finish` 收束痕迹）
  - `steps.step_index` 单调递增且可回放
  - 失败步骤具备截图证据（`observations.screenshot_path`）
  - 常规动作可回溯定位（`observations.coord`/`locator_candidate`）
- [x] 失败用例不会阻塞后续用例（除非环境级错误）

---

## 9) 最小落地路径（实施顺序）

1. 离线：CSV→子步骤→JSONL 框架 + 最小 schema 校验（已完成）
2. 上设备：仅实现 steps + 失败截屏 artifacts（已完成，UI 树后置）
3. 再补：UI 树采集与 `element_snapshot`、断言抽取/验证（`assertions.status`）、`locator_candidate` 生成

---

备注：若需 iOS/HarmonyOS，运行时通过 `--device-type ios|hdc`，并按 `README.md` 的平台准备文档配置环境。
