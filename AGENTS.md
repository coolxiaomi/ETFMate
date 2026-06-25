# 仓库指南

## 项目结构与模块组织

ETFMate 是一个 Python 3.10+ CLI 项目，源码位于 `src/etfmate`。核心模块按职责拆分：`browser/` 负责采集已登录的同花顺投资账本和 Touker 网格数据，`market/` 负责构建 ETF 行情快照，`analysis/` 包含规则引擎、网格建议、AI 复核输入和交易复盘，`report/` 负责用 `report/templates/` 渲染 HTML 报告，`storage/` 维护数据模型和 JSON 读写。测试位于 `tests/`。产品规则、评分和报告契约位于 `docs/`。仓库内的 agent skill 契约位于 `.agents/skills/etfmate-skill/`。运行采集结果和生成报告写入 `data/`，该目录不进入 Git。

## 构建、测试与本地开发命令

- `python -m pip install -e .`：以可编辑模式安装本地 CLI，安装后可使用 `etfmate` 命令。
- `python -m etfmate.cli --help`：查看当前 CLI 子命令。
- `python -m etfmate.cli --root . run`：执行采集 -> 分析 -> 生成报告，依赖当前浏览器登录态。
- `python -m etfmate.cli --root . report --run-id 20260623-103000`：复用已有快照重新渲染报告。
- `python -m compileall src\etfmate`：做基础语法和导入检查。
- `python -m pytest -q`：运行全部回归测试。

## 代码风格与命名约定

使用带类型提示的 Python，函数保持小而明确。模块名使用 snake_case，领域字段保持稳定，例如 `position_pct`、`holding_pct`、`risk_level`、`target_position_ratio`。报告和文档中的中文内容必须保持 UTF-8；在 Windows 上读写中文文件时显式指定 UTF-8。不要把投资决策逻辑藏到模板里：决策放在 `analysis/`，展示放在 `report/`。

## 知识读取与沉淀

每次修改前，必须先读取 `docs/` 中与本次任务对应的文件，理解项目已有规则、评分、报告、设计或流程知识后再动代码。每次修改后，必须把新增认知、规则变化、设计决策或踩坑经验提炼到 `docs/` 中对应文件；如果没有合适文件，就创建一个语义相关的新文档，避免知识只停留在代码或对话里。

## 测试规范

测试框架使用 pytest。新增测试放在 `tests/test_*.py`。修改规则、网格、报告或 CLI 契约时，应增加聚焦回归测试。决策相关修改至少关注高风险目标仓位为 0、组合仓位上限、证据置信度降级、网格买入反弹和卖出回落联动，以及报告文案是否一致。决策逻辑可用 `python -m pytest -q tests\test_decision_consistency.py` 快速验证。

## 提交与 Pull Request 规范

当前提交历史偏向短中文祈使句，例如 `优化网格建议`、`优化报告的 严谨性`。提交应保持范围集中，不混入无关改动。PR 需要说明变更的业务规则或报告契约，列出验证命令；如果改动 HTML 报告，应说明检查过的报告 run-id，并附上关键截图。

## 安全与配置提示

正式分析必须使用同花顺和 Touker 的真实登录态数据，并通过 `web-access` 采集；不要用样例数据、手工替代数据或只采首屏的滚动列表生成最终建议。不要提交 `data/`、`.env`、浏览器 profile、含账户隐私的截图或 ShareOne 发布产物。
