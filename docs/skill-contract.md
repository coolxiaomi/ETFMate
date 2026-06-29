# ETFMate Skill 契约维护说明

## 定位

`.agents/skills/etfmate-skill/SKILL.md` 是 ETFMate 的入口契约，只负责让 agent 在正确场景触发正确流程。它不再复制完整业务规则。

入口契约必须直接保留：

1. 短口令触发范围，例如 `分析ETF`、`跑 ETFMate`、`ETFMate`。
2. 默认完整流程：真实采集、分析、宿主 AI 复核、HTML 报告、ShareOne 发布。
3. 必须使用 `$web-access` 和真实登录态数据。
4. 核心源缺失、登录态失效、验证码、风控、滚动加载未采齐时停止。
5. `ai_review_input.json` / `ai_judgements.json` 的宿主 AI 复核约定。

## 文档权威顺序

产品和规则细节以 `docs/` 为准：

- `docs/score.md`：趋势评分。
- `docs/action.md`：仓位动作。
- `docs/rule.md`：规则引擎、ETF 池和 AI 边界。
- `docs/grid.md`：Touker 网格建议。
- `docs/t-grid.md`：震荡网格（T网格）候选筛选、参数、生命周期、回测估算和报告隔离契约。
- `docs/report.md`：HTML 报告展示契约。
- `docs/data-quality.md`：采集完整性、字段完整性和 analyze/report 前的硬阻断闸门。

Skill 专用 reference 只保留运行检查清单：

- `.agents/skills/etfmate-skill/references/etfmate-domain-rules.md`

## 维护规则

- 改触发词、默认发布策略、web-access 强制流程或硬阻断条件时，同步更新 `SKILL.md` 和 skill reference。
- 改评分、动作、网格、报告或 AI 输入字段时，优先更新对应 `docs/*.md`、运行代码和测试；`SKILL.md` 只需要保持索引准确。
- 不在 `SKILL.md` 中重复粘贴网格参数、趋势评分、HTML 表格布局等细节，避免同一规则多处漂移。
- 正式分析仍必须使用同花顺和 Touker 的真实登录态数据；文档精简不放宽采集完整性或 ShareOne 发布前置条件。
