# 目标对齐（已确认）

## 项目基本功能概述
- 本项目是基于 AutoGLM 的手机端智能助理框架（Phone Agent），通过 ADB/HDC 控制设备，结合多模态感知与规划执行，自动完成手机端任务。
- 支持远程调试与多场景任务执行，包含敏感操作确认与人工接管机制。

## 作为测试工程师的目的
- 将“文字版测试用例”转化为可执行的自动化流程，在真实手机端执行回归/冒烟测试。
- 形成稳定、可复用的结构化输出（JSON），用于生成/更新 Locator Registry、固化为 YAML DSL、形成可追溯的执行证据（Observations）。
- 通过标准化输出，降低 UI 变更导致的脚本脆弱性，提升自动化测试的持续可维护性。

## 首要目标（已确认）
- “结构化 JSON 输出用于 Registry/YAML 固化”作为测试工程首要目标。

## 输出目标（基于 input_and_output 规范）
- 仅输出结构化 JSON，符合 `agent_output.schema.json`。
- Steps/Assertions 与 UI 物理信息严格隔离；Assertions 使用 suggestion 模型。
- Locator 命名遵循全大写下划线语义命名规则，禁止 UI 属性命名。

## 落地改造清单（不改代码，仅用于讨论与对齐）
- 输出校验层。引入 JSON Schema 校验与必填字段完整性校验，阻断自然语言/杂项字段进入输出。
- 输出装配层。统一输出结构与字段默认值，避免缺字段与类型漂移。
- Action 词表层。建立 DSL Action 词表与映射规则，禁止 driver 级动词与坐标类动作进入 Steps。
- Assertion 建模层。坚持 suggestion 模型，禁止 final_type，输出 confidence 与参数规范。
- Observation 证据层。强制 observations 关联 step_index，规范 element_snapshot 字段与截图路径保留策略。
- Locator 命名层。执行全大写下划线语义命名规范，禁止 UI 属性命名与版本污染。
- Locator Registry 治理层。引入 candidate 去重与审核流程，禁止无 confidence 的候选。
- 输入链路层。明确 CSV -> 执行 -> JSON -> Registry -> YAML 的流水线边界与产物定义。
- 追溯与审计层。为每条用例输出最小可复核证据集（步骤、断言、观察）。
- 质量门槛层。定义最小通过门槛与回退策略，避免低质量输出污染 Registry/DSL。

## 讨论目标
- 确认以上清单的优先级排序与先后依赖关系。
- 确认各产物的“最小可用形态”（JSON、Registry、YAML、证据包）。

## 讨论顺序建议
- 先对齐各产物的“最小可用形态”（JSON、Registry、YAML、证据包），否则后续优先级难以判断。
- 再讨论落地改造清单的优先级与依赖关系。

## 最小可用形态（已记录）
- JSON：与 `agent_output.schema.json` 保持一致。
- Registry：审核后落库。
- YAML：仅骨架即可（本项目不执行代码，骨架甚至可为空）。
- 证据包：UI 树为主，可仅截取关键元素（被执行动作的元素）。

## 新问题：执行规则
- 用户提出还有“执行规则”相关问题待解决（待展开）。
