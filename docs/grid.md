# ETFMate 网格建议知识库

本文档沉淀当前 ETFMate 网格建议的实现知识和维护约束。运行逻辑以 `src/etfmate/analysis/grid_advisor.py` 为准，采集字段以 `src/etfmate/storage/models.py` 的 `GridConfig` 为准，报告和 AI 复核字段分别由 `src/etfmate/report/daily_report.py`、`src/etfmate/analysis/ai_advisor.py` 消费。

## 1. 定位

ETFMate 的网格建议不是独立交易系统，而是“持仓动作 + Touker 条件单参数 + 行情指标 + 七层证据”的执行层辅助。它只对本次运行的当前数据负责，每只 ETF 只输出一套当前适合的参数，不输出进取/稳健/保守多方案。

全局策略画像：

```text
条件单代替盯盘；胜率优先；不追求吃完整段行情；盈利看趋势管理；不深研标的时默认保守
```

该画像必须进入网格建议结构和 AI 复核输入。报告中不重复展示完整全局文案，只展示本 ETF 实际触发的护栏、参数和依据。

核心原则：

1. 网格动作必须服从持仓动作、目标仓位、风险等级和组合约束。
2. 浮盈不是卖出充分条件，趋势健康时保留继续盈利空间。
3. 浮亏、趋势转弱或目标仓位为 0 时，不通过调低基准价或提高买入侧鼓励补仓。
4. 胜率优先护栏必须实际改变参数，不能只停留在解释文案。

## 2. 输入数据

网格建议由 `advise_grid(grid, market, position, layered_context, rule_decision)` 生成。

### 2.1 Touker 网格

`GridConfig` 必须尽量保留 Touker 原始参数：

```text
code, name, enabled, status
base_price, last_price, distance_from_base_pct
lower_price, upper_price
grid_step_pct, grid_step_amount
order_amount, order_quantity
buy_quantity, sell_quantity
buy_fall_pct, buy_rebound_pct
sell_rise_pct, sell_pullback_pct
min_base_quantity, max_position_quantity
last_trigger_time
```

Touker 未采齐时，不应生成最终建议。已有 Touker 网格时，`base_price` 是待评估输入，不得默认改成当前价。

### 2.2 行情快照

`MarketSnapshot` 至少影响以下判断：

```text
last_price, pct_chg, amount
ma20, ma60
boll_upper, boll_mid, boll_lower, boll_position
atr14_pct
bias6, bias5_ratio
rsi6, rsi14
amount_ratio20
```

当前实现主要使用 MA20/MA60、BOLL 上下轨、ATR14 百分比、BIAS6 和当前价生成网格间距、基准价和买卖侧强弱。

### 2.3 持仓与规则决策

`Position` 提供当前数量、成本、浮盈亏、资金仓位等约束。`rule_decision` 提供持仓动作和风控结论，关键字段包括：

```text
action
position_action
trend_score
risk_score
risk_level
target_position_ratio
blocked_actions
```

网格动作必须与这些字段一致。尤其是 `risk_level=HIGH` 且目标仓位为 0 时，不允许继续输出普通“维持”或正常买入数量。

### 2.4 七层证据

`layered_context` 通过 `normalize_context` 进入网格建议，当前使用：

```text
confidence
total_score
missing_layers
summary
```

证据置信度不足时，先作为复核提示处理，不把“数据层未完整接入”直接等同于市场风险。当前实现中置信度低于 45 时，不做过细调宽/调窄；只有多层证据方向偏弱、风险未确认或仓位偏高时，买入侧才继续降档。

## 3. 生成流程

当前流程可概括为：

```text
1. 判断是否适合生成可执行网格
2. 计算基础买卖间距和基础委托数量
3. 判断弱势、强势、低位和盈利延续状态
4. 评估现有基准价或生成新建基准价
5. 在仍适合运行网格时，根据 ATR 判断调宽/调窄
6. 用持仓动作、风险等级、目标仓位和交易过滤覆盖主动作
7. 用七层证据方向和胜率护栏再次降低买入侧或强化卖出侧
8. 计算买入反弹/卖出回落确认参数、底仓和最大持仓
9. 输出完整结构给报告和 AI 复核输入
```

## 4. 适用性规则

只有满足以下任一条件时，才生成可执行网格参数：

1. 已有 Touker 网格。
2. 已有当前持仓。
3. 未持仓自选 ETF 的规则动作允许建仓或轻仓建仓。

未持仓且规则动作为观察/等待时，输出：

```text
action = 暂不设网格
grid_applicable = false
grid_purpose = 暂不设网格
suggested_base_price = null
```

此时报告不展示买触发、买量等可执行参数，避免把观察标的误读成可下单计划。

## 5. 输出契约

网格建议必须包含以下字段：

```text
code, name
action
grid_mode
grid_mode_label
execution_checks
cash_constraint_status
grid_applicable
grid_purpose
strategy_profile
strategy_guardrails
has_existing_grid
base_price_status
base_price_reason
current_base_price
suggested_base_price
current_buy_fall_pct
suggested_buy_fall_pct
current_buy_rebound_pct
suggested_buy_rebound_pct
current_sell_rise_pct
suggested_sell_rise_pct
current_sell_pullback_pct
suggested_sell_pullback_pct
current_quantity
current_buy_quantity
current_sell_quantity
suggested_buy_quantity
suggested_sell_quantity
buy_execution_status
sell_execution_status
current_min_base_quantity
suggested_min_base_quantity
current_max_position_quantity
suggested_max_position_quantity
reasons
layered_confidence
layered_score
rule_decision
```

报告将网格建议嵌入每只 ETF 的主表，“规则”行下方展示完整 Touker 网格建议表，并在“动作”合并行展示用途、胜率护栏、基准判断和依据。AI 复核输入会读取同一套字段，不允许报告和 AI 使用不同的网格契约。

## 6. 主动作与用途

当前网格主动作包括：

```text
趋势加仓
趋势持有
高位保护
震荡滚动
弱势减仓
只卖清仓
维持
新建网格
调宽网格
调窄网格
降低买入侧
暂停买入侧
只保留卖出
暂不设网格
```

主动作必须互斥。严重风险优先于调宽/调窄；触发暂停买入侧或只保留卖出时，不再同时把网格间距调参作为主建议。

内部 `grid_mode` 是报告、AI 和执行校验的主契约：

| grid_mode | 中文展示 | 执行含义 |
|---|---|---|
| TREND_ADD | 趋势加仓 | 强趋势且不过热，买入积极，卖出放慢 |
| TREND_HOLD_GRID | 趋势持有 | 趋势仍好，保留趋势仓，买卖均衡 |
| PROFIT_PROTECTION | 高位保护 | 趋势好但过热，降买并分批兑现 |
| BALANCED_GRID | 震荡滚动 | 震荡偏强，小额滚动 |
| WEAK_REDUCE | 弱势减仓 | 趋势不强，买入侧停用，反弹卖出 |
| ONLY_SELL_OR_CLEAR | 只卖清仓 | 趋势失效，买入侧停用，卖出不超过持仓 |
| PAUSE | 暂停 | 禁止交易或数据不可用 |

`grid_purpose` 必须归一为唯一目的：

```text
建仓网格
加仓网格
持仓网格
止盈网格
防守网格
止盈/退出网格
暂不设网格
```

用途判断要区分盈利延续和风险保护。盈利且趋势评分高、风险等级低、MA 未转弱时，维持为持仓网格并保留盈利空间；趋势转弱、风控复核、目标仓位为 0 或只保留卖出时，升级为止盈/退出网格。

## 7. 基准价规则

### 7.1 已有 Touker 网格

已有网格时先评估 `base_price` 是否仍合理。

偏离计算：

```text
deviation_pct = abs(base_price / last_price - 1) * 100
threshold = max(2 * atr14_pct, 6.0)
```

当基准价偏离超过阈值，或当前价已经越过 Touker 上下边界时，输出“建议调整基准”。否则输出“维持现有基准”。

盈利持仓接近上轨时，不能机械把基准价上移到当前价：

1. 若趋势评分不低于 75、风险等级 LOW，且价格未低于 MA60/MA20，维持现有基准，保留继续盈利空间。
2. 若趋势或风险未确认，仍不轻易上移基准价，优先保留分批止盈纪律。

弱势浮亏时，基准价调整只用于修正失真的条件单，不用于鼓励继续补仓。

### 7.2 无现有网格

无 Touker 基准价时，输出“新建建议基准”。

已有持仓时：

```text
参考价 = MA20 / BOLL中轨 / 当前价的技术中枢
若持仓浮亏，建议基准不低于当前价
```

未持仓建仓网格时：

```text
优先使用当前价、MA20、BOLL中轨
若当前价高于 MA20，基准不追得过高
```

## 8. 买卖间距规则

基础建议：

```text
suggested_buy_fall_pct = clamp(atr14_pct * 0.9, 2.0, 8.0)
suggested_sell_rise_pct = clamp(atr14_pct * 0.8, 2.0, 8.0)
```

当有现有网格间距时：

```text
current_step = grid_step_pct 或 buy_fall_pct/sell_rise_pct 均值
```

只有仍适合正常运行网格时，才判断调宽/调窄：

```text
current_step < 0.6 * atr14_pct  -> 调宽网格
current_step > 1.8 * atr14_pct  -> 调窄网格
否则                           -> 当前间距与 ATR 基本匹配
```

弱势、风控复核、目标仓位为 0、风险等级 HIGH 时，优先降低买入侧、暂停买入侧或只保留卖出，不把调宽/调窄作为主动作。

## 9. 确认参数规则

买入反弹和卖出回落是防止过快买/过早卖的确认参数，不随 ATR 放大，按本次建议基准价分档设置。同一 ETF 的买入反弹和卖出回落必须保持一致。

| 建议基准价 | 买入反弹 | 卖出回落 |
|---:|---:|---:|
| `<= 1` | 0.20% | 0.20% |
| `1 ~ 2` | 0.15% | 0.15% |
| `2 ~ 3` | 0.10% | 0.10% |
| `3 ~ 5` | 0.07% | 0.07% |
| `5 ~ 8` | 0.05% | 0.05% |
| `> 8` | 0.03% | 0.03% |

该规则由一致性测试覆盖，不能拆成买入和卖出两套独立参数。

## 10. 数量与仓位边界

基础委托数量：

```text
优先使用 order_quantity
其次使用 buy_quantity / sell_quantity / grid_step_amount
没有现有网格时使用当前持仓数量的 20%，但不低于 100 且不超过当前持仓
未持仓建仓默认 100
```

A 股一手规则：

```text
所有常规买卖数量最小 100 股，并取 100 的整数倍。
```

数量约束：

1. 当前持仓很小时，买入数量不得明显超过现有持仓。
2. 卖出数量不得超过当前持仓数量。
3. 趋势交易模式下，`WEAK_REDUCE` / `ONLY_SELL_OR_CLEAR` / `PAUSE` 必须用 `buy_execution_status=DISABLED` 和 `suggested_buy_quantity=null` 表示停用买入侧，不得把停用侧渲染成 `0股` 条件单。
4. 买入侧降速时，通常将买入数量降为基础数量的 50%，卖出侧保持基础数量。
5. 盈利保护且趋势/风险确认不足时，卖出侧可提高到基础数量的 1.5 倍。
6. 盈利且趋势健康时，不因 ATR 公式把现有卖出上升幅度收紧；已有 Touker 卖出触发更宽时沿用现有触发，以保留趋势利润空间。

底仓与最大持仓：

```text
suggested_min_base_quantity:
  仓位 >= 2% 时，保留当前持仓约 50% 作为底仓
  低仓位或无持仓时，可为 0

suggested_max_position_quantity:
  优先沿用 Touker max_position_quantity
  否则已有持仓按 max(当前持仓 + 3格买入量, 当前持仓 * 1.5)
  无持仓按 3格买入量
```

## 11. 风险联动

### 11.1 弱势与浮亏

价格同时低于 MA20 和 MA60，且仓位偏高或浮亏较深时：

```text
action = 降低买入侧
buy_quantity = 基础数量 * 50%
sell_quantity = 基础数量
买卖间距沿用现有网格
```

仅低于 MA60 但尚未触发更严重条件时，也先降低买入侧，不直接关闭整个网格。

### 11.2 目标仓位为 0

当 `target_position_ratio <= 0` 且当前有持仓，并且仓位动作是 `REDUCE` / `TREND_REVIEW` / `EXIT_TREND_POSITION` / `RISK_REVIEW` / `EXIT_SHORT_TERM`，或规则动作为“减仓/趋势复核/风控复核/退出短线仓位”时：

```text
trend_score >= 30 -> 只保留卖出
trend_score < 30  -> 暂停买入侧
buy_execution_status = DISABLED
suggested_buy_quantity = null
suggested_sell_quantity = 基础数量
```

此场景不得输出普通“维持”，也不得输出正常买入数量。风险等级 HIGH 只是该规则的强触发条件之一，不是唯一触发条件。

### 11.3 风控复核与退出短线仓

当持仓动作是 `RISK_REVIEW`、`EXIT_SHORT_TERM`，或规则动作是“风控复核 / 退出短线仓位”，或趋势评分低于 45：

```text
action = 降低买入侧
买入侧降速
卖出侧纪律保留
```

### 11.4 交易过滤与禁止交易

当规则动作是“禁止交易”：

```text
action = 降低买入侧
沿用现有买卖触发比例
买入侧只给一手倍数的保守降速建议
```

## 12. 技术位置联动

价格接近 BOLL 上轨且 BIAS 正偏：

1. 若趋势评分高、风险等级 LOW、价格未转弱，不因浮盈提前减仓，买入侧不追高，卖出侧保留盈利空间。
2. 若趋势或风险确认不足，降低买入侧，并提高卖出侧数量或让卖出侧更积极保护利润。

价格接近 BOLL 下轨且 BIAS 负偏：

1. 可保留小额买入侧。
2. 必须同时检查总仓位、单 ETF 上限、最大持仓和证据置信度。
3. 不能把低位技术信号单独解释为加仓理由。

## 13. 胜率优先护栏

当前护栏包括：

```text
条件单用于替代盯盘，只给当前时点一套可执行参数
七层证据未完整接入，仅作复核提示
趋势或风险未确认，宁可少赚，不用网格扩大不确定仓位
已有盈利但趋势健康，浮盈不是卖出充分条件，网格保留继续盈利空间
已有盈利且趋势/风险未完全确认时，优先保留分批兑现纪律
仓位偏高时不提高买入侧，优先控制回撤和重复暴露
未持仓建仓只做小额试探，不假设现金充足
```

如果护栏包含风险未确认或仓位偏高，买入侧需要再降一档；证据层未完整接入本身不触发降档。若持仓已有不低浮盈且趋势/风险确认不足，卖出侧保持更积极；若盈利且趋势健康，卖出侧不因 ATR 公式提前收紧。

报告会过滤掉“条件单用于替代盯盘”这类全局护栏，只展示本 ETF 实际触发的约束。

## 14. AI 与报告集成

`build_ai_review_input` 会把网格建议压缩进 `ai_review_input.json`：

```text
action
grid_mode
grid_mode_label
execution_checks
cash_constraint_status
grid_applicable
grid_purpose
strategy_profile
strategy_guardrails
base_price_status
current_base_price
suggested_base_price
current/suggested 买入下跌、买入反弹、卖出上升、卖出回落
suggested_buy_quantity
suggested_sell_quantity
buy_execution_status
sell_execution_status
suggested_min_base_quantity
suggested_max_position_quantity
```

AI 只能基于这些结构化证据复核，不得编造未采集到的行情、新闻、研报或公告。AI 与规则冲突时，硬过滤、流动性约束、仓位约束、Touker 采集完整性和数据缺失降级优先。

HTML 报告中：

1. 有网格建议时，嵌入完整网格表。
2. `grid_applicable=false` 时，只显示暂不设网格原因。
3. 报告展示优先使用 `grid_mode_label`，弱趋势不得再把“只卖清仓/弱势减仓”压缩成“降低买”。
4. 报告展示的买卖数量必须来自执行校验后的结果；卖出不得超过当前持仓；弱趋势、暂停或只卖模式下买入侧显示“停买”，不得显示 `0股`。

## 15. 回归测试

修改网格建议时至少关注 `tests/test_decision_consistency.py` 中这些场景：

1. 高风险目标仓位为 0 时，网格不能保留正常买入侧。
2. 买入反弹和卖出回落必须按基准价分档，且同一 ETF 两者相等。
3. 合理现有基准价应维持，不默认改成当前价。
4. 明显失真的基准价应输出“建议调整基准”。
5. 盈利且趋势健康时，不把基准价机械上移到当前价，不因浮盈提前减仓。
6. 盈利且趋势健康时，已有 Touker 卖出上升触发不得被 ATR 公式收紧成更早止盈。
7. 弱势浮亏且仓位不低时，买入侧必须降速。
8. 未持仓自选 ETF 只有在规则允许建仓/轻仓建仓时才生成建仓网格。
9. 未持仓且规则为观察时，必须输出“暂不设网格”。

推荐验证命令：

```bash
python -m pytest -q tests/test_decision_consistency.py
```

## 16. 维护边界

1. 决策逻辑放在 `analysis/`，展示逻辑放在 `report/`，不要把投资判断藏进 HTML 模板。
2. 如果调整网格字段契约，必须同步 `grid_advisor.py`、`ai_advisor.py`、`daily_report.py`、skill 参考文档和测试。
3. 如果调整反弹/回落确认参数，必须保持买入反弹和卖出回落联动，不能拆成两套独立规则。
4. 如果新增网格动作，必须确认报告导航、动作颜色、AI 输入和测试都能识别。
5. 正式分析必须使用真实同花顺和 Touker 登录态数据；不得用样例或首屏数据生成最终网格建议。
