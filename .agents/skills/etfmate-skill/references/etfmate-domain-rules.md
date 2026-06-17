# ETFMate Domain Rules

## 数据源

同花顺账户页：

- URL：`https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO`
- 采集当前持仓、当日/历史交易记录、清仓数据。
- 优先保存网络 JSON；接口不可解析时退化为 DOM 表格。

Touker 网格页：

- URL：`https://m.touker.com/fd/conditions/monitoring`
- 使用移动端 viewport `390 x 844`、device scale factor `2`、移动端 UA。
- 采集 ETF 代码/名称、启用状态、基准价、网格间距、每格金额或份额、上下边界、最近触发记录。

行情与指标：

- K 线、盘口、成交量优先使用 mootdx。
- ETF 实时价格、涨跌幅、换手、市值等优先使用腾讯财经。
- 东方财富只用于独有数据，必须串行限流。
- 指标至少包含 MA5/10/20/60、BOLL、VOL MA5/20、ATR14、ATR14_pct、BIAS6/12/24。

## 数据模型

`Position`：

- `code`、`name`、`quantity`、`available_quantity`、`cost_price`、`last_price`、`market_value`、`pnl`、`pnl_pct`、`source`

`Trade`：

- `trade_date`、`trade_time`、`code`、`name`、`side`、`price`、`quantity`、`amount`、`fee`、`source`

`GridConfig`：

- `code`、`name`、`enabled`、`base_price`、`lower_price`、`upper_price`、`grid_step_pct`、`grid_step_amount`、`order_amount`、`last_trigger_time`

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

## 网格参数规则

- `grid_step_pct < 0.6 * ATR14_pct`：网格过密，建议调宽。
- `grid_step_pct > 1.8 * ATR14_pct`：网格过宽，建议调窄。
- 价格长期在上半区且 MA20 上行：建议上移网格中心。
- 价格跌破 MA60 且 BOLL 带宽扩大：建议降低单格金额或暂停下沿补仓。
- 成交量显著萎缩：降低触发预期，不主动加大网格密度。
- 浮亏超过阈值且仍处下跌趋势：不机械加仓，先评估仓位上限。

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
runtime/playwright-profile/
```

`runtime/`、`data/raw/`、`data/reports/*.html`、`.env` 不应提交 Git。
