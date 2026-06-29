# ETFMate T网格开发计划

状态：已按用户确认进入开发实现。

本文档基于 `C:\Users\coolx\Downloads\震荡网格_Codex开发计划.md` 和当前 ETFMate 代码/文档契约整理。它只定义后续开发计划，不代表当前运行代码已经支持 T网格。

## 1. 目标与命名

新增一个独立分析类型：

```text
类型：震荡网格
报告统一展示名：T网格
用途：在震荡市场中反复做 T，评估低买高卖的网格候选、参数、运行状态、历史闭环概率和风险
```

命名约束：

1. 用户可见文案统一写作 `T网格`。
2. Skill 入口类型写作 `震荡网格（T网格）`。
3. 新增代码统一使用 `t_grid` / `TGrid` 命名，避免和现有 Touker 网格、趋势网格混用。
4. 外部计划中的 `SwingGrid` 可作为算法来源说明，但不进入报告主文案。
5. 第一版默认每格数量为 `1000份`。

### 用户确认结论

2026-06-29 用户确认：

1. 代码命名使用 `t_grid`。
2. 第一版默认每格 `1000份`。
3. T网格 tab 展示自选池全部 ETF 的通过/拒绝原因，不只展示候选项。
4. 开发完成后的真实分析复用最近一次通过质量闸门的 run-id。
5. T网格是现有 ETFMate skill 的新业务扩展，不是新项目；采集阶段仍统一执行同花顺投资账本和 Touker 网格采集，T网格只在分析阶段读取同一份自选池数据。

## 2. 策略边界

T网格只回答这些问题：

1. 自选池里的 ETF 是否适合开启 T网格。
2. 建议网格间距、上沿、下沿、向上卖出格数、向下买入格数。
3. 当前状态是开启、观察、暂停买入、暂停卖出、暂停全部还是关闭。
4. 最近历史窗口里的触发概率、闭环命中率、平均闭环天数、收益估算和资金占用。
5. 为什么适合或不适合，以及主要风险是什么。

T网格不做这些事：

1. 不替代 `ShortTrendScore`。
2. 不生成趋势加仓、趋势持有、趋势减仓或清仓决策。
3. 不修改现有 Touker 网格建议。
4. 不自动下单，不承诺收益。
5. 不把历史年化收益当成未来收益预测。

## 3. 与现有网格的隔离关系

当前 `docs/grid.md` 和 `src/etfmate/analysis/grid_advisor.py` 管的是 Touker 条件单网格，它消费持仓动作、Touker 参数、行情指标和七层证据，输出 `grid_advices`。

T网格必须独立：

```text
现有网格：grid_advices，服务 Touker 条件单和趋势交易执行层
T网格：t_grid_advices，只服务震荡做 T 候选筛选和参数评估
```

隔离要求：

1. 不改 `advise_grid()` 的输出含义。
2. 不把 T网格候选计入现有顶部“网格”数量。
3. 不把现有 `grid_mode=BALANCED_GRID / 震荡滚动` 解释成 T网格。
4. 不让 T网格结果反向影响 `recommendations`、`rule_decision`、`grid_advices`。
5. 报告可以在同一个 HTML 中展示 T网格，但必须使用独立 tab、独立字段和独立说明。

## 4. 分析 universe

用户要求：只分析自选池 ETF。

后续实现时，T网格 universe 必须来自同花顺投资账本自选 ETF 池：

```text
account.json -> watchlist -> clean watchlist ETF codes
```

规则：

1. 当前持仓不自动进入 T网格分析，除非它也在自选池里。
2. Touker 网格不自动进入 T网格分析，除非它也在自选池里。
3. 自选池里的已持仓 ETF 可以分析，因为来源仍是自选池。
4. 自选池过滤规则沿用 `docs/rule.md`：保留宽基、行业、主题、商品/黄金、跨境/QDII 场内 ETF；过滤股票、可转债、债券 ETF、货币 ETF、杠杆/反向、REITs 和非场内基金。
5. 不能用手工代码列表、样例数据、Touker 列表或搜索结果扩展 T网格 universe。

## 5. 数据要求与当前差距

外部计划要求每只 ETF 至少最近 60 个交易日 OHLCV，并需要成交额：

```text
trade_date, open, high, low, close, volume, amount
```

当前仓库事实：

1. `build_market_snapshot()` 只返回最新 `MarketSnapshot`，没有保留完整 K 线 DataFrame。
2. `tencent_daily_kline()` 当前把 `amount` 填为 `0.0`，不能直接用于 20 日成交额均值过滤。
3. `baidu_daily_kline()` 可能提供 `amount`，但需要保留数据源和失败原因。
4. 当前 `Position` 没有 `available_quantity`，投资账本也没有可靠“可卖数量”列；不能恢复旧的“今日可卖/不可卖”伪护栏。

开发要求：

1. 新增一个可返回完整日线数据的数据入口，例如 `fetch_daily_ohlcv(code, count=260)`。
2. 优先使用能提供真实 `amount` 的来源；如果只拿到成交量没有成交额，T网格应降级为数据不足或流动性无法确认。
3. `MarketSnapshot` 可继续服务趋势报告，T网格使用完整日线数据独立计算。
4. T+1 和可卖份额只作为可选执行校验；当前没有可靠字段时，报告写“需人工核对可卖份额”，不能把它当作硬阻断或输出“可用数量为0”。

## 6. 指标与评分计划

新增指标优先放在 T网格模块内，必要时再提取到 `market/indicators.py`：

1. 日内振幅：`(high - low) / close * 100`，计算 10/20/60 日均值。
2. ATR14 百分比：用于网格间距和风险，不进入趋势评分。
3. BOLL 带宽与位置：`boll_width_pct`、`boll_position`。
4. MA20/MA60 斜率：MA20 用 5 日前对比，MA60 用 10 日前对比。
5. 20/30/60 日箱体上下沿、箱体宽度和当前位置。
6. ADX14：优先实现；如果第一版时间不足，使用外部计划里的趋势风险替代逻辑，但要在结果中标记 `adx_available=false`。

硬过滤沿用外部计划的方向：

```text
K线不足 60 日 -> 不适合
20日平均成交额 < 3000万 -> 不适合
20日日均振幅 < 网格间距 * 1.5 -> 不适合
ADX14 >= 25 或 MA20 斜率过大 -> 不适合
跌破 20 日箱体、MA60 或 BOLL 下轨 -> 不适合新开
BOLL 带宽过大 -> 不适合
```

评分按 100 分实现：

```text
流动性 20
波动性 25
震荡结构 25
趋势风险 20
当前价格位置 10
```

候选标准：

```text
t_grid_score >= 70 且 reject_reason 为空 -> T网格候选
t_grid_score >= 60 -> 可观察
低于 60 或硬过滤失败 -> 不适合
```

## 7. 参数与资金占用计划

第一版以固定份额模式为默认：

```text
fixed_qty：每格固定份额，默认 1000 份
fixed_cash：每格固定金额，金额向下换算为 100 份整数倍
```

默认网格间距：

```text
suggest_grid_step_pct = max(avg_amplitude_20 / 2, atr_pct * 0.8)
限制在 0.8% 到 3.0%
```

默认上下沿：

```text
grid_upper = range_high_20 * 0.995
grid_lower = range_low_20 * 1.005
```

网格数量：

```text
grid_count_up = 当前价到上沿可卖格数
grid_count_down = 当前价到下沿可买格数
任一方向少于 2 格 -> 不建议新开
```

资金占用：

```text
one_grid_cash
buy_cash_required
base_position_cash_required
basic_required_cash
reserve_cash
suggest_total_cash
```

如果当前缺少可用现金字段，报告只给资金占用估算，不声称账户一定可执行。

## 8. 生命周期动作

新增 T网格动作枚举：

```text
OPEN：开启T网格
KEEP：继续运行T网格
PAUSE_BUY：暂停T网格买入
PAUSE_SELL：暂停T网格卖出
PAUSE_ALL：暂停全部T网格
CLOSE：关闭T网格
WATCH：观察，不开启T网格
```

说明：

1. `CLOSE` 表示关闭 T网格条件，不等于清仓。
2. `PAUSE_BUY` 表示防止越跌越买，可以保留反弹卖出逻辑。
3. `PAUSE_SELL` 表示防止强趋势卖飞，可以保留低位买回逻辑。
4. 这些动作只属于 T网格，不覆盖现有趋势动作和 Touker 网格动作。

## 9. 历史概率与收益估算

新增保守回测估算：

1. 默认回看 60 个交易日。
2. 默认闭环观察期 `max_holding_days=5`。
3. 默认 OHLC 路径使用 `conservative`，同一天不假设买卖都能闭环。
4. 估算触发概率、闭环命中率、平均闭环天数、平均每日触发格数、平均每日闭环格数。
5. 收益输出包含预期日收益、预期年化、保守年化、风险调整后年化。
6. 所有收益文案必须标记为“历史估算，不代表未来收益”。

## 10. 代码落点计划

建议新增和修改：

```text
src/etfmate/analysis/t_grid.py
  TGridConfig
  TGridResult
  TGridBacktestResult
  analyze_t_grid_candidates()
  analyze_single_etf_for_t_grid()
  calc_t_grid_indicators()
  calc_t_grid_score()
  advise_t_grid_params()
  decide_t_grid_lifecycle()
  estimate_t_grid_backtest_metrics()

src/etfmate/market/providers.py
  fetch_daily_ohlcv()
  或 build_market_data_bundle()

src/etfmate/market/indicators.py
  视实现复用程度补充 ADX、BOLL 带宽、箱体指标

src/etfmate/cli.py
  run_analyze() 中只对 watchlist codes 生成 t_grid_advices
  analysis.json 新增 t_grid_advices

src/etfmate/analysis/ai_advisor.py
  ai_review_input.json 新增独立 t_grid 字段

src/etfmate/report/daily_report.py
src/etfmate/report/templates/daily_report.html
  新增 T网格 tab 和每只 ETF 的 T网格独立展示块

.agents/skills/etfmate-skill/SKILL.md
.agents/skills/etfmate-skill/references/etfmate-domain-rules.md
  增加“震荡网格（T网格）”入口与 docs/t-grid.md 索引
```

## 11. 报告展示计划

报告中新增独立 `T网格` tab，展示自选池 ETF 的 T网格分析结果。

展示规则：

1. T网格 tab 只统计 `t_grid_advices`。
2. 现有 `网格` tab 继续只统计可执行双边 Touker 网格。
3. 现有 `执行策略` tab 不接收 T网格暂停/关闭动作。
4. 每只 ETF 明细卡中可新增一行 `T网格`，但不能替换原 `网格` 行。
5. T网格候选排序：候选优先、评分、风险调整后收益、闭环命中率、成交额、振幅。
6. 报告文案要短，优先展示结论、建议间距、上下沿、上下格数、资金占用、命中率、历史收益估算和风险。
7. 不显示“0股”作为停用侧，缺少可卖份额时写“需人工核对可卖份额”。

## 12. Skill 契约计划

Skill 已作为现有 ETFMate skill 的能力扩展处理。

入口建议：

```text
用户说“分析T网格”“T网格分析”“震荡网格”“找适合做T的ETF”时，使用 ETFMate skill。
默认仍走真实登录态采集 -> 分析 -> AI复核 -> HTML报告 -> ShareOne 发布。
T网格只分析同花顺自选 ETF 池，不因持仓或 Touker 网格扩大范围。
采集阶段仍执行统一 ETFMate 采集流程，不新增独立采集项目。
```

Skill 文档只增加入口和索引，不复制 T网格评分细节。评分、参数、回测和报告契约以本文件为准。

## 13. 测试计划

新增聚焦测试：

```text
tests/test_t_grid.py
```

至少覆盖：

1. 只分析自选池 ETF，不因持仓或 Touker 网格扩大 universe。
2. K线不足 60 日直接不适合。
3. 20 日成交额不足直接不适合。
4. 波动不足直接不适合。
5. 趋势过强直接不适合或降级观察。
6. 箱体边缘导致上下某一方向不足 2 格时，不建议新开。
7. 候选评分达到 70 且无硬过滤时输出 `OPEN` 或 `READY`。
8. 暂停买入、暂停卖出、关闭三类生命周期动作互斥且有原因。
9. 回测默认保守路径，不夸大同日闭环。
10. 缺少可卖份额字段时不输出“可用数量为0”或“今日不可卖”。
11. `t_grid_advices` 不改变现有 `grid_advices` 和报告网格数量。

回归验证命令：

```bash
python -m compileall src\etfmate
python -m pytest -q tests\test_decision_consistency.py tests\test_t_grid.py
python -m etfmate.cli --root . report --run-id <已通过质量闸门的run-id>
```

如果报告 UI 改动明显，需要用一个真实通过质量闸门的 run-id 重渲染并检查 HTML 中：

```text
T网格 tab 存在
网格 tab 数量未被 T网格污染
执行策略 tab 未混入 T网格暂停/关闭
T网格收益估算带“历史估算”提示
没有“0股”“可用数量为0”“今日不可卖”等旧式误导文案
```

## 14. 开发里程碑

### 阶段一：文档确认

已完成。用户确认代码命名、默认份额、报告范围和 run-id 复用策略。

### 阶段二：数据入口和指标

完成完整日线数据入口、T网格指标、ADX 或替代趋势风险逻辑。

### 阶段三：评分、过滤和参数

完成硬过滤、100 分评分、候选判断、网格间距、上下沿、上下格数和资金占用。

### 阶段四：生命周期和回测估算

完成开启、观察、暂停买入、暂停卖出、关闭，以及保守历史闭环估算。

### 阶段五：CLI 和产物

`run_analyze()` 生成 `t_grid_advices`，并写入 `analysis.json` 和 `ai_review_input.json`。

### 阶段六：报告和 skill

报告新增独立 T网格展示；skill 增加震荡网格入口和文档索引。

### 阶段七：真实 run 验证

使用真实登录态采集结果重跑分析和报告，只发布通过质量闸门的报告。

## 15. 待确认点

开发前需要用户确认：

1. 是否接受代码命名统一为 `TGrid/t_grid`，而不是外部计划里的 `SwingGrid`。
2. 第一版默认每格是否使用 `1000份`；如果希望按金额，默认金额是多少。
3. T网格 tab 是否只展示候选和观察项，还是展示自选池全部 ETF 的通过/拒绝原因。
4. 开发完成后的真实分析，是复用最近一次通过质量闸门的 run-id，还是重新采集一轮实时数据。
