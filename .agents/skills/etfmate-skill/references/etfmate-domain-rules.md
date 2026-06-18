# ETFMate Domain Rules

## 数据源

同花顺账户页：

- URL：`https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO`
- 采集当前持仓、当日/历史交易记录、清仓数据。
- 优先保存网络 JSON；接口不可解析时退化为 DOM 表格。

Touker 网格页：

- URL：`https://m.touker.com/fd/conditions/monitoring`
- 使用移动端 viewport `390 x 844`、device scale factor `2`、移动端 UA。
- 采集 ETF 代码/名称、启用状态/休眠状态、基准价、现价、距基准比例、上下边界、买入下跌触发比例、买入反弹比例、卖出上升触发比例、卖出回落比例、买入/卖出委托数量、最小底仓、最大持仓、最近触发记录。
- 移动端页面可能有内部滚动容器和虚拟列表。采集时要按页面显示的 `监控中(N)` 校验去重后的 ETF 数量，数量不一致时继续滚动内部容器，不要只读首屏。

行情与指标：

- K 线、盘口、成交量优先使用 mootdx。
- ETF 实时价格、涨跌幅、换手、市值等优先使用腾讯财经；mootdx 不通或百度 K 线 403 时，K 线允许降级到腾讯 `fqkline` 日线接口。
- 东方财富只用于独有数据，必须串行限流。
- 指标至少包含 MA5/10/20/60、BOLL、VOL MA5/20、ATR14、ATR14_pct、BIAS6/12/24。

## 数据模型

`Position`：

- `code`、`name`、`quantity`、`available_quantity`、`cost_price`、`last_price`、`market_value`、`pnl`、`pnl_pct`、`source`

`Trade`：

- `trade_date`、`trade_time`、`code`、`name`、`side`、`price`、`quantity`、`amount`、`fee`、`source`

`GridConfig`：

- `code`、`name`、`enabled`、`base_price`、`lower_price`、`upper_price`、`grid_step_pct`、`grid_step_amount`、`order_amount`、`last_trigger_time`
- 扩展字段：`status`、`last_price`、`distance_from_base_pct`、`sell_rise_pct`、`sell_pullback_pct`、`buy_fall_pct`、`buy_rebound_pct`、`buy_quantity`、`sell_quantity`、`order_quantity`、`min_base_quantity`、`max_position_quantity`

`MarketSnapshot`：

- `code`、`name`、`last_price`、`pct_chg`、`volume`、`amount`
- `ma5`、`ma10`、`ma20`、`ma60`
- `boll_upper`、`boll_mid`、`boll_lower`
- `atr14`、`atr14_pct`
- `bias6`、`bias12`、`bias24`
- `vol_ma5`、`vol_ma20`

## 单只 ETF 建议规则

- `买入`：价格靠近 BOLL 下轨，BIAS 明显负偏离，成交量没有异常放大破位，且仓位不足。
- `分批买入`：短线偏弱但进入低位区，适合用网格或小仓位试探。
- `持有`：趋势和波动处于中性，现有网格参数合理。
- `减仓`：价格远离 MA20/MA60，BIAS 明显正偏离，接近 BOLL 上轨且放量滞涨。
- `卖出`：跌破关键均线且放量，或趋势明显走坏并触发风控。
- `暂停网格`：单边下跌趋势明显，价格跌破下边界且均线空头。
- `恢复网格`：价格回到 BOLL 中轨附近，ATR 回落，成交量恢复正常。
- 建议必须结合持仓数量、市值、仓位占比、成本价、浮盈亏率。高仓位或单只市值较高时，即便价格进入低位，也优先给“持有/暂停加仓/降低买入股数”，不要机械给“买入”。
- 浮亏超过 10% 且价格低于 MA60：不建议扩大买入数量，先降低买入网格或暂停下沿补仓。
- 浮盈超过 20% 且 BOLL 分位高于 85% 或 BIAS6 明显正偏：优先给“减仓/提高卖出股数/恢复卖出网格”，而不是继续持有不动。

## 网格参数规则

- `grid_step_pct < 0.6 * ATR14_pct`：网格过密，建议调宽。
- `grid_step_pct > 1.8 * ATR14_pct`：网格过宽，建议调窄。
- 价格长期在上半区且 MA20 上行：建议上移网格中心。
- 价格跌破 MA60 且 BOLL 带宽扩大：建议降低单格金额或暂停下沿补仓。
- 成交量显著萎缩：降低触发预期，不主动加大网格密度。
- 浮亏超过阈值且仍处下跌趋势：不机械加仓，先评估仓位上限。
- Touker 支持买入和卖出间距不对称，也支持买入数量和卖出数量不对等。建议必须给具体数值或范围：
  - 建议买入下跌触发：`clamp(0.9 * ATR14_pct, 2.0%, 8.0%)`
  - 建议卖出上升触发：`clamp(0.8 * ATR14_pct, 2.0%, 8.0%)`
  - 价格低于 MA60 或持仓浮亏大：买入股数建议为当前 `0-50%`，卖出股数为当前 `100-150%`
  - 价格接近 BOLL 上轨/BIAS6 正偏：买入触发放宽或暂停，卖出触发可设为 `max(2.0%, 0.6 * ATR14_pct)`，卖出股数提高到当前 `120-150%`
  - 价格接近 BOLL 下轨/BIAS6 负偏且仓位低：买入触发可设为 `max(2.0%, 0.7 * ATR14_pct)`，买入股数不超过组合现金/仓位预算
- 输出不要只写“调宽/调窄”，必须写：当前买入/卖出触发、建议买入/卖出触发范围、当前委托股数、建议买入/卖出股数、是否暂停买入侧或卖出侧。

## 交易复盘评分

基础分 6 分：

- `+1` 顺应网格纪律。
- `+1` 买卖点与技术指标匹配。
- `+1` 仓位控制合理。
- `+1` 有明确止盈/止损或下一步计划。
- `-1` 追涨或杀跌。
- `-1` 逆趋势加仓且无仓位保护。
- `-1` 同类 ETF 过度集中。
- `-1` 交易过频或手续费不划算。
- `-1` 情绪化手动偏离策略。

分数限制在 0 到 10。

复盘周期：

- 当日复盘：只统计分析日交易。
- 三日复盘：统计最近 3 个交易日或最近 3 个有交易日期。
- 7日复盘：统计最近 7 日交易。
- 30日复盘：统计最近 30 日交易。
- 每个周期输出评分、交易笔数、买入金额、卖出金额、手续费、主要问题、改进动作。周期复盘必须与网格触发价格和指标位置关联，识别追涨、杀跌、逆势补仓、同类 ETF 过度集中、交易过频。

## 报告格式

- 不强制所有内容使用 Markdown 表格。表格只用于稳定数值和横向比较；长理由、风险点、复盘问题、下一步计划优先使用短段落或项目符号。
- 持仓建议可以按单只 ETF 小节输出，先给关键指标短行，再给“建议动作 / 理由 / 风险 / 观察价位”。ETF 数量很多时，可先用紧凑表格汇总代码、仓位、盈亏、指标、动作，再在表后补充重点标的。
- 网格建议必须保留可执行数值：当前买入/卖出触发、建议买入/卖出触发范围、当前委托股数、建议买入/卖出股数、是否暂停买入侧或卖出侧。可用表格，也可按 ETF 小节列出。
- 周期复盘可以用表格汇总评分、笔数、买入金额、卖出金额、手续费；优点、问题、改进动作和计划不要硬塞进宽表。
- 报告末尾列出数据完整性：同花顺持仓数量、交易记录数量、Touker 网格数量、行情/K 线来源、缺失或降级接口。
- 报告生成后询问是否使用 `$shareone` 发布。用户同意后再执行 shareone skill 的安全确认和发布流程，标题格式为 `ETFMate-report-YYYY年MM月DD日`。

## 文件保存

默认路径：

```text
data/raw/ths/YYYY-MM-DD/account.json
data/raw/ths/YYYY-MM-DD/trades.json
data/raw/ths/YYYY-MM-DD/closed_positions.json
data/raw/touker/YYYY-MM-DD/grids.json
data/raw/market/YYYY-MM-DD/snapshots.json
data/reports/YYYY-MM-DD-etf-review.md
data/reports/YYYY-MM-DD-etf-review.html
runtime/chrome-cdp-profile/
```

`runtime/`、`data/raw/`、`data/reports/*.html`、`.env` 不应提交 Git。
