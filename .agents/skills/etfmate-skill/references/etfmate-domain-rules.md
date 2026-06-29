# ETFMate Skill 运行检查清单

本文档是 `etfmate-skill` 的运行期检查清单，只保留正式运行必须确认的采集、阻断、文件产物和验收项。业务规则、评分、仓位动作、网格参数和报告展示契约以仓库 `docs/` 为准，不在本文件重复维护。

## 必读文档

按任务读取对应文档：

- `docs/skill-contract.md`：skill 入口契约、文档权威顺序和维护边界。
- `docs/score.md`：`ShortTrendScore` 趋势评分算法。
- `docs/action.md`：趋势评分到仓位动作、目标仓位和禁用交易指令文案。
- `docs/rule.md`：ETF 池过滤、交易硬过滤、规则引擎数据流和 AI 复核边界。
- `docs/grid.md`：Touker 网格建议、基准价、买入反弹/卖出回落、风险联动和回归测试。
- `docs/t-grid.md`：震荡网格（T网格）候选筛选、参数、生命周期、回测估算和报告隔离契约。
- `docs/report.md`：HTML 报告展示排序、风险页聚合和展示契约。
- `docs/data-quality.md`：采集完整性、字段完整性、universe 对账和报告前硬阻断。

如果修改 Python 规则、网格、AI 输入或报告模板，必须同步更新对应 `docs/*.md` 和聚焦回归测试。

## 数据源与阻断

正式分析只接受真实登录态采集结果。

同花顺投资账本：

- 持仓/清仓/交易 URL：`https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO`
- 自选 ETF 池 URL：`https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/ISUeEwK`
- 必须采集持仓列表、已清仓、交易记录、持仓备注/看法列和自选 ETF 池。
- 持仓、已清仓、交易记录和自选 ETF 池都是滚动加载列表，必须滚动到底并累积每屏 DOM/table/text 证据。
- 交易记录必须覆盖“本月”“近三月”“近半年”“今年”“自定义”5 个子 tab。
- 自选 ETF 池必须保存纳入列表、过滤列表和过滤原因；自选未持仓标的也进入行情、规则评分、AI 复核和报告。
- T网格是自选池上的独立分析类型，只分析 clean watchlist ETF；不得用持仓、Touker 网格、交易记录、样例代码或手工代码扩展 T网格 universe。
- 投资账本页面没有“可卖数量/可用数量”列；不要生成 T+1 可卖数量护栏。

Touker：

- URL：`https://m.touker.com/fd/conditions/monitoring`
- 必须采集 ETF 代码/名称、启用/休眠状态、基准价、现价、上下边界、买入下跌触发、买入反弹、卖出上升触发、卖出回落、买入/卖出委托数量、最小底仓、最大持仓和最近触发记录。
- 移动端页面可能存在内部滚动容器或虚拟列表，必须按页面 `监控中(N)` 校验去重后的 ETF 数量。

立即停止的情况：

- 页面未登录、验证码、风控、协议确认、短信/人脸/设备验证。
- 关键表格、卡片或滚动列表未加载完成。
- 同花顺持仓/交易/自选 ETF 池或 Touker 网格任一核心源未采齐。
- 只能拿到样例数据、首屏数据、搜索结果、WebFetch/curl 结果或手工指定代码。
- `data/raw/market/RUN_ID/data_quality.json` 的 `status=FAIL`。

停止时不得生成最终建议，不得发布 ShareOne。

质量闸门必须在三处执行：

- `collect` 后：校验同花顺和 Touker 原始采集结果。
- `analyze` 前和分析结果落盘前：防止复用坏快照或生成 AI 复核输入。
- `report` 前：防止旧的或手工拼接的 `analysis.json` 绕过采集完整性。

## web-access 要求

- 所有联网、登录态页面读取、网页交互和动态渲染页面采集必须通过 `$web-access` skill。
- 对已知登录态 URL，直接使用 web-access 的浏览器 CDP 模式，不用 WebFetch、curl 或搜索引擎替代。
- CDP Proxy 默认地址为 `http://localhost:3456`；当前 CLI 可用 `ETFMATE_WEB_ACCESS_PROXY_URL` 覆盖。
- 采集时优先用 `/eval` 读取 DOM、表格、页面文本、localStorage/sessionStorage 和页面内已加载数据结构；必要时用 `/screenshot` 留存证据。
- 程序化 `/eval` 受阻时，切换为 web-access 的 GUI 交互点击、滚动、刷新，再重新读取 DOM；不要在同一个失败选择器上反复重试。
- 任务结束关闭自己创建的后台 tab，不主动改动用户已有 tab。

## AI 复核与报告

- `analyze` 生成 `data/raw/market/RUN_ID/ai_review_input.json`。
- `analyze` 同时生成 `analysis.json` 中的 `t_grid_advices`；它复用同一份自选池采集结果，不新增独立登录态采集项目。
- 宿主 AI 使用当前会话模型读取 `ai_review_input.json`，写回 `data/raw/market/RUN_ID/ai_judgements.json`。
- ETFMate 本地 CLI 不要求用户额外配置 API Key 或模型。
- AI 只做规则引擎后的证据复核；硬过滤、流动性约束、仓位约束、Touker 采集完整性和数据缺失降级优先。
- 报告标题使用“实时 ETF 持仓与网格分析”，不要写“每日报告/日度报告”。
- HTML 报告内不写 ShareOne 发布提示；快捷触发和默认运行视为要求发布，报告完整生成后由 skill 调用 `$shareone` 发布。

## 文件产物

默认路径使用实时 `run_id`，格式示例 `20260618-153000`：

```text
data/raw/ths/RUN_ID/account.json
data/raw/touker/RUN_ID/grids.json
data/raw/market/RUN_ID/snapshots.json
data/raw/market/RUN_ID/analysis.json
data/raw/market/RUN_ID/data_quality.json
data/raw/market/RUN_ID/ai_review_input.json
data/raw/market/RUN_ID/ai_judgements.json
data/reports/RUN_ID-etf-realtime.html
runtime/
```

`runtime/`、`data/raw/`、`data/reports/*.html`、`.env` 不应提交 Git。

## P0 验收项

修改 ETFMate Python 代码或报告模板后，至少验证：

- 趋势交易账户契约：规则输出必须包含 `account_mode=TREND_TRADING`、`trend_overheat_level`、`trend_trade_mode` 和 `execution_mode`；报告和 AI 输入不得只围绕配置型目标仓位解释。
- 高风险或短线转弱：`ShortTrendScore < 45` 或退出短线仓位时，动作必须进入卖出/清仓候选语义；网格 `grid_mode` 必须是 `ONLY_SELL_OR_CLEAR`，买入侧用 `buy_execution_status=DISABLED` 表示停用，不得输出 `0股` 条件单。
- 执行层数量校验：卖出数量不得超过当前持仓，买卖数量必须为 100 股整数倍；停用侧用状态字段表达，不得渲染为 `0股`；历史样例 515880、159781、562950、159516 不得再出现卖出数量超过持仓。
- 组合仓位超限：组合总仓位超过 80% 时，禁止新增 `ADD/OPEN/LIGHT_OPEN`；
- AI 未启用：`ai_enabled=false` 或 `ai_confidence=0` 时，只展示“AI复核未启用，本次采用规则引擎”。
- 证据置信度不足：七层证据未完整接入只作复核提示；只有多层证据方向偏弱、风险未确认、仓位偏高或量能确认不足时才降速。
- 强趋势盈利网格：趋势评分高、风险低且已有盈利时，不得因 ATR 公式把现有 Touker 卖出上升触发收紧成更早止盈。
- 网格风险联动：趋势弱或过热时必须切换到 `WEAK_REDUCE`、`ONLY_SELL_OR_CLEAR` 或 `PROFIT_PROTECTION`，不得维持正常买入侧。
- 买入反弹和卖出回落必须按 `docs/grid.md` 的基准价分档，且同一 ETF 两者相等。
- T网格结果必须展示在独立 `T网格` tab，不计入现有 `网格` 或 `执行策略` tab；收益估算必须标记为历史估算，不得输出“可用数量为0”“今日不可卖”或 `0股` 条件单。

推荐验证命令：

```bash
python -m pytest -q tests/test_decision_consistency.py
```
