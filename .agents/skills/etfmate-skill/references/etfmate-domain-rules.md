# ETFMate Domain Rules

## 数据源与阻塞规则

同花顺投资账本：

- URL：`https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO`
- 采集当前持仓、可用数量、成本价、现价、市值、浮盈亏、仓位占比、交易记录、清仓数据，以及持仓表“备注/看法”列。
- 备注列是用户本人观点，不是噪音字段。报告必须展示或融合该观点，并判断它与市场指标是否一致。
- 页面未登录、验证码、风控、协议确认、表格未加载或持仓为空且页面不是明确空仓时，立即停止。

Touker：

- URL：`https://m.touker.com/fd/conditions/monitoring`
- 采集 ETF 代码/名称、启用/休眠状态、基准价、现价、距基准比例、上下边界、买入下跌触发、买入反弹、卖出上升触发、卖出回落、买入/卖出委托数量、最小底仓、最大持仓、最近触发记录。
- 移动端页面可能有内部滚动容器和虚拟列表。必须按页面显示的 `监控中(N)` 校验去重后的 ETF 数量，数量不一致时继续滚动内部容器，不要只读首屏。
- Touker 没采齐时，不生成最终建议。

行情与指标：

- 行情/K线来源由 `$a-stock-data` 或当前行情适配器自行选择，本 skill 不指定优先级。
- 指标至少包含 MA5/10/20/60/200、BOLL、成交量/VOL、VOL MA5/20、量比、换手、振幅、ATR7/14/30/60、BIAS6/12/24。
- 可按需要增加 ETF 成分股重合度、行业/主题暴露、规模、费率、跟踪误差、资金流和相对强弱。

## 数据模型

`Position`：

- `code`、`name`、`quantity`、`available_quantity`、`cost_price`、`last_price`、`market_value`、`pnl`、`pnl_pct`、`position_pct`、`note`、`source`

`Trade`：

- `trade_date`、`trade_time`、`code`、`name`、`side`、`price`、`quantity`、`amount`、`fee`、`source`

`GridConfig`：

- `code`、`name`、`enabled`、`status`、`base_price`、`last_price`、`distance_from_base_pct`、`lower_price`、`upper_price`
- `sell_rise_pct`、`sell_pullback_pct`、`buy_fall_pct`、`buy_rebound_pct`
- `buy_quantity`、`sell_quantity`、`order_quantity`、`min_base_quantity`、`max_position_quantity`、`last_trigger_time`

`MarketSnapshot`：

- `code`、`name`、`last_price`、`pct_chg`、`volume`、`amount`、`amplitude_pct`、`turnover_pct`、`vol_ratio`
- `ma5`、`ma10`、`ma20`、`ma60`、`ma200`
- `boll_upper`、`boll_mid`、`boll_lower`
- `atr7`、`atr7_pct`、`atr14`、`atr14_pct`、`atr30`、`atr30_pct`、`atr60`、`atr60_pct`
- `bias6`、`bias12`、`bias24`
- `vol_ma5`、`vol_ma20`

## 持仓建议规则

- `买入`：无持仓或很低仓位，价格靠近 BOLL 下轨，BIAS 明显负偏离，量能没有放大破位，且组合仓位允许。
- `分批买入`：已有小仓位且进入低位区，只能给不超过当前持仓规模或单格预算的小份额建议。
- `持有`：趋势、波动、量能和仓位处于中性，网格参数合理。
- `减仓`：价格接近 BOLL 上轨、BIAS 正偏离、量能冲高或已有较高浮盈。
- `卖出`：跌破关键均线且放量，或趋势明显走坏并触发风控。
- `暂停网格`：单边下跌、低于 MA60、跌破网格下沿或浮亏较深时，暂停买入侧，保留必要卖出/减仓纪律。
- `恢复网格`：价格回到 BOLL 中轨附近，ATR 回落，量能恢复正常，且趋势不再破位。

必须考虑：

- 当前持仓数量和可用数量。建议数量不得明显超过当前持仓规模；100 份持仓不应给 1000 份建仓/加仓建议。
- 仓位占比和单只市值。仓位偏高时，即便低位，也优先“持有/暂停买入/小额试探”。
- 用户备注。备注看好且指标确认，可增强持有或小额加仓理由；备注看好但趋势/量能不确认，要指出冲突；备注谨慎且指标偏弱，可增强减仓或暂停网格理由。
- ETF 重合度。同主题、同赛道或成分股高度重合的 ETF，要提示压缩重复标的，给出保留/替换方法：优先保留流动性、规模、费率、跟踪误差、策略暴露、历史执行效果更合适的一只。

## 网格建议规则

- 网格主动作必须互斥。`暂停网格` 优先级高于 `调宽网格`、`调窄网格`；一旦建议暂停，不要同时把调宽/调窄作为主动作。
- 只有仍适合运行网格时，才判断间距过密或过宽：
  - `grid_step_pct < 0.6 * ATR14_pct`：网格过密，建议调宽。
  - `grid_step_pct > 1.8 * ATR14_pct`：网格过宽，建议调窄。
- 价格低于 MA60、跌破下边界、浮亏较深或放量破位：建议暂停买入侧，买入数量为 0 或显著降低，卖出侧保留或提高。
- 价格接近 BOLL 上轨且 BIAS 正偏：降低买入侧强度，提高卖出侧数量或更积极止盈。
- 价格接近 BOLL 下轨且 BIAS 负偏：可保留小额买入侧，但必须检查总仓位和最大持仓上限。
- Touker 支持买入/卖出间距不对称、买入/卖出数量不对等，建议必须给具体数值。

## 交易复盘

- ETFMate 是实时分析，不是日度报告。交易复盘可按“本次日内、近3日、近7日、近30日”展示。
- 每个周期包含评分、交易笔数、买入金额、卖出金额、手续费、主要问题、改进动作、下一步计划。
- 评分必须结合网格触发价格和指标位置，识别追涨、杀跌、逆势补仓、同类 ETF 过度集中、交易过频。

## HTML 报告格式

- 报告标题为“实时 ETF 持仓与网格分析”，顶部显示具体分析时间。
- 分析结果按 ETF 聚合：同一只 ETF 的持仓建议、技术指标、备注判断、网格建议放在同一个小节。
- 页面必须提供 ETF 快速导航。
- 每个 ETF 标题行带现价、涨跌、持仓、浮盈亏和网格状态；基础信息小字号。
- 持仓表至少包含：持仓、BOLL、MA、量能(VOL)、真实波幅(ATR)、乖离率(BIAS)、动作、总述。
- 网格表至少包含：买入触发、卖出触发、委托股数、卖出股数、动作。
- 动作行和总述行使用合并单元格，避免表格过宽。
- 盈利用红色、亏损用绿色；买入/加仓用红色，减仓/卖出用绿色，暂停/调参/风险提醒用橙色或深红色。
- HTML 不写 ShareOne 发布提示。

## 文件保存

默认路径使用实时 `run_id`，格式示例 `20260618-153000`：

```text
data/raw/ths/RUN_ID/account.json
data/raw/touker/RUN_ID/grids.json
data/raw/market/RUN_ID/snapshots.json
data/raw/market/RUN_ID/analysis.json
data/reports/RUN_ID-etf-realtime.html
runtime/chrome-cdp-profile/
```

`runtime/`、`data/raw/`、`data/reports/*.html`、`.env` 不应提交 Git。
