---
name: etfmate-skill
description: 本地 ETF 实时持仓与网格交易辅助分析 skill。用户说“分析ETF”“分析 ETF”“跑ETF”“跑 ETFMate”“生成 ETFMate 报告”，或只指定 etfmate-skill/ETFMate 后加“分析”“干活”“执行”“跑”“开始”，甚至只指定本 skill 而没有其它动作时，默认运行完整 ETFMate 实时流程：先用 $web-access 连接用户已登录的 Chrome，实时采集同花顺投资账本和 Touker 网格，再结合 $a-stock-data 七层数据、行情指标、持仓备注和网格参数生成中文 HTML 实时分析报告，最后使用 $shareone 发布报告并返回链接。触发场景还包括 ETF 实时分析、同花顺投资账本采集、Touker 网格设置、ETF 持仓建议、网格调参建议、web-access 登录态页面采集、多层证据分析、本地 CLI 工具开发。
---

# ETFMate Skill

## 快捷触发与默认动作

- 用户说“分析ETF”“分析 ETF”“跑ETF”“跑 ETFMate”“生成 ETFMate 报告”“更新 ETF 持仓分析”等短口令时，必须使用本 skill，不要退回通用金融分析。
- 用户明确写出 `etfmate-skill`、`ETFMate`、`$etfmate-skill` 或类似指定方式时，即使只追加“分析”“干活”“执行”“跑”“开始”，或没有追加任何动作，也按“完整实时分析并发布报告”处理。
- 默认完整流程是：用 `$web-access` 采集同花顺投资账本和 Touker 网格 -> 构建行情指标和七层证据 -> 运行本地规则引擎 -> 宿主 AI 复核 `ai_review_input.json` 并写回 `ai_judgements.json` -> 生成中文 HTML 报告 -> 使用 `$shareone` 发布报告 -> 返回本地报告路径和 ShareOne 链接。
- 如果用户明确说“不发布”“只生成本地报告”“不要 ShareOne”，则只生成本地 HTML 报告，不调用 `$shareone`。

## 文档权威顺序

- 本文件只定义 skill 的入口路由、强制运行流程、硬阻断规则和参考文档索引。
- 产品规则、评分、动作、网格和报告契约以仓库 `docs/` 为准：`docs/score.md`、`docs/action.md`、`docs/rule.md`、`docs/grid.md`、`docs/report.md`。
- Skill 运行期检查清单以 `references/etfmate-domain-rules.md` 为准；它不复制完整业务规则，只列出正式运行必须检查的采集、阻断、文件产物和验收项。
- 如果规则或报告行为变化，必须同步更新对应 `docs/*.md`；只有入口行为、默认发布策略、采集硬阻断或 skill 资源路径变化时，才更新本文件。

## 强制运行流程

每次正式运行 ETFMate 必须按以下顺序执行，不能跳步：

1. 加载 `$web-access` skill，并按其前置检查启动或确认 CDP Proxy；必须向用户展示 web-access 的账号风险提示。
2. 使用 web-access 的 CDP Proxy 操作用户 Chrome。优先创建后台 tab，不主动改动用户已有 tab；任务结束关闭自己创建的 tab。
3. 实时采集同花顺投资账本和 Touker 网格，此时仍不要分析。
4. 任一页面出现登录、验证码、风控、协议确认、关键数据未加载或滚动列表未采齐，立即停止并提示用户在 Chrome 中手动处理。
5. 只有同花顺持仓/交易/自选 ETF 池和 Touker 网格都采集成功，才继续行情指标、七层证据和规则建议生成。
6. `analyze` 生成 `data/raw/market/RUN_ID/ai_review_input.json` 后，宿主 AI 必须读取该文件，用当前会话模型生成 `ai_judgements.json`，再生成 HTML 报告。
7. 报告完整生成后，若本次来自快捷触发或用户没有明确禁止发布，必须加载 `$shareone` skill 发布生成的 HTML 报告。

目标页面：

- 同花顺投资账本持仓/清仓/交易：`https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO`
- 同花顺投资账本自选 ETF 池：`https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/ISUeEwK`
- Touker 网格：`https://m.touker.com/fd/conditions/monitoring`

## 硬阻断规则

- 正式分析必须使用真实同花顺和 Touker 登录态数据，不得用样例数据、手工替代数据、搜索结果、WebFetch、curl 或只采首屏的滚动列表生成最终建议。
- 所有联网、登录态页面读取、网页交互和动态渲染页面采集都必须通过 `$web-access` skill 执行，不使用旧的直连浏览器自动化实现。
- 同花顺投资账本必须覆盖当前持仓、清仓、交易记录、持仓备注/看法列和自选 ETF 池；所有滚动加载列表必须滚动到底并累积每屏证据。
- Touker 必须覆盖监控中网格并按页面 `监控中(N)` 校验采集数量；采不齐时停止。
- 任一核心源未登录、未加载、未采齐或证据完整性不足时，必须停止；不得生成最终建议，也不得发布 ShareOne。
- 工具只做分析与辅助决策，不自动下单，不绕过验证码、短信、人脸、设备验证或平台风控。

## 规则与报告索引

运行或修改 ETFMate 前，按任务读取对应文档：

- `references/etfmate-domain-rules.md`：skill 运行检查清单、阻断条件、文件产物和 P0 验收项。
- `docs/skill-contract.md`：skill 入口契约与仓库规则文档的权威边界。
- `docs/score.md`：`ShortTrendScore` 趋势评分算法。
- `docs/action.md`：趋势评分到仓位动作、目标仓位和禁用交易指令文案。
- `docs/rule.md`：ETF 池过滤、交易硬过滤、规则引擎数据流和 AI 复核边界。
- `docs/grid.md`：Touker 网格建议、基准价、买入反弹/卖出回落、风险联动和回归测试。
- `docs/report.md`：HTML 报告展示排序、风险页聚合和展示契约。

## CLI 与产物

快速规则版运行：

```bash
etfmate run
```

带 AI 综合研判的推荐流程：

```bash
etfmate collect --run-id 20260618-153000
etfmate analyze --run-id 20260618-153000
# 宿主 AI 读取 data/raw/market/20260618-153000/ai_review_input.json
# 宿主 AI 生成 data/raw/market/20260618-153000/ai_judgements.json
etfmate report --run-id 20260618-153000
```

回放或调试某次实时快照：

```bash
etfmate collect --run-id 20260618-153000
etfmate analyze --run-id 20260618-153000
etfmate ai-attach --run-id 20260618-153000 --input data/raw/market/20260618-153000/ai_judgements.json
etfmate report --run-id 20260618-153000
```

不要把 `daily`、`--date`、`--codes` 或 `data/manual/*.example.json` 作为正式分析流程。

## 资源说明

- `scripts/health_check.py`：检查 Python 分析依赖、`a-stock-data` skill、`web-access` skill 和 web-access Proxy 可见性。
- `scripts/scaffold_etfmate.py`：生成或补齐 ETFMate Python CLI 项目骨架。维护该脚本时必须保持实时 `run/run_id` 流程，并使用 web-access Proxy 采集，不要回退到旧浏览器自动化、`daily/date` 或样例数据流程。
- `references/etfmate-domain-rules.md`：skill 运行期检查清单，不作为完整产品规则副本。
