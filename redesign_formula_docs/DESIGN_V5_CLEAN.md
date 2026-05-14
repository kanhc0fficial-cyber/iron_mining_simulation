# 选矿仿真系统 v5 clean 规格

本文档只保留不可结构化的设计原则、执行顺序和审查口径。公式、变量、DCS 点位、因果边和迁移台账存放在同目录 CSV 中，作为实现与 pytest 自动审查的唯一结构化来源。

## 结构化文件

- `v5_formulas.csv`: 唯一公式表。一个 `lhs` 只能有一个 canonical 公式。
- `v5_executable_formulas.csv`: 实现和 pytest 默认读取的执行公式表，不包含概念模板。
- `v5_variables.csv`: 变量注册表。记录变量所属工序、状态类型、可观测性和定义公式。
- `v5_dcs_outputs.csv`: DCS 点位表。每个 DCS 应有物理父节点和 `meas(...)` 来源。
- `v5_causal_edges.csv`: 由公式右侧父变量抽取的候选因果边，供 DAG/pytest 初筛。
- `v5_execution_steps.csv`: 每分钟仿真的执行顺序。
- `v5_migration_from_v4.csv`: V4 公式迁移台账。每条 V4 公式必须有迁移状态。
- `v5_manual_formulas.csv`: V5 为闭合关键因果链而新增的人工公式，主要用于实际药剂剂量和浮选 CSTR 缺口。
- `v5_external_inputs.csv`: 未由公式生成但被公式引用的父节点注册表。每个父节点必须被分类为参数、上游流状态、设备状态、控制器内部量、实验室输入或模板索引。
- `v5_implementation_constraints.csv`: 不作为每分钟公式执行、但必须进入 pytest/实现红线的设计约束。

## 执行原则

1. Markdown 不再重复可执行公式；实现以 `v5_executable_formulas.csv` 为准。
2. 概念章节只描述因果意图，不再作为代码来源。
3. 所有 Stream 属性必须随物流、库存或一阶/CSTR 状态传递，禁止入口边界矿质瞬时穿越到下游。
4. DCS 必须由物理父节点经测量方程得到，禁止 `y` 或当前最终精矿化验直接进入 DCS。
5. K6 药箱液位默认是库存/DCS sink，不作为实际加药量父节点，除非显式启用断药场景。
6. 一个变量只允许一个 canonical 公式；跨章节重复的概念公式只能保留为 prose 或迁移台账，不能进入执行表。
7. 非公式父节点必须出现在 `v5_external_inputs.csv`，不能在实现中临时发明名称或默认常数。

## 迁移状态口径

- `migrated`: 作为 V5 canonical 公式保留。
- `merged`: 与 canonical 公式重复，已合并。
- `superseded`: 与 canonical 冲突或低优先级，被执行段公式替代。
- `dropped`: 非执行公式、示例禁用公式或多行块头，不进入公式 CSV。
- `needs_review`: DCS 或变量无法由脚本确认完整迁移，需要人工裁决。

## 当前完整性口径

生成与校验脚本共同维护以下硬约束：无重复 `lhs`、无重复公式 ID、变量表与公式表一一对应、DCS 点位均有物理父节点、V4 公式均有迁移状态、所有非公式父节点均已注册且无 `needs_review`。若后续新增公式，必须先更新 CSV，再运行 `validate_v5_clean_spec.py`。
