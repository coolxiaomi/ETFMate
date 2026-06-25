# ETFMate 规则引擎文档（基于 ShortTrendScore 的趋势版）

## 1. 目标

本文档定义 ETFMate 的规则引擎流程，用于把行情、持仓、自选 ETF 池和 `ShortTrendScore` 结果转换为可解释的仓位动作建议。

核心目标：

```text
不预测涨跌
不输出绝对交易指令
不重复定义趋势评分
只基于 score.md 的 ShortTrendScore 做规则过滤、仓位动作和报告解释
```

本文档适合：

```text
A股场内宽基 ETF
A股场内行业 / 主题 ETF
A股场内商品 / 黄金 ETF
A股场内跨境 / QDII ETF
```

不覆盖：

```text
债券 ETF
货币 ETF
杠杆 / 反向 ETF
REITs
```

---

## 2. 模块边界

### 2.1 score.md

负责计算：

```text
ShortTrendScore
TrendLevel
TrendName
scores
indicators
tags
```

### 2.2 action.md

负责计算：

```text
targetPositionRatio
positionAction
adjustRatio
newPositionRatio
trendAlertLevel
```

### 2.3 rule.md

负责：

```text
ETF池过滤
交易硬过滤
调用 ShortTrendScore
调用仓位动作算法
统一输出规则结果
给网格建议和 AI 复核提供输入
```

### 2.4 grid.md

负责：

```text
Touker 条件单参数
网格间距
买入反弹 / 卖出回落
基准价
ATR 波动联动
```

说明：

```text
ATR 不进入 score.md 或 action.md 的核心趋势评分和仓位动作。
ATR 只进入 grid.md 或独立波动模块。
```

---

## 3. 输出动作枚举

建议统一使用以下动作：

```text
FORBID               禁止交易 / 数据不可用
WATCH                观察，不操作
LIGHT_OPEN           轻仓建仓
OPEN                 建仓
HOLD                 持有
ADD                  加仓
HOLD_OR_REDUCE       持有或小幅减仓
REDUCE               减仓
TREND_REVIEW         趋势复核
EXIT_TREND_POSITION  退出短线仓位
```

不再使用旧版：

```text
BUY
SELL
riskScore
totalScore
```

说明：

```text
OPEN 比 BUY 更中性，表示进入建仓观察区，不代表必须买入。
EXIT_TREND_POSITION 比 SELL 更中性，表示退出短线仓位或降至观察仓位，不代表系统强制清仓。
```

---

## 4. 必要输入字段

### 4.1 行情数据

```json
{
  "code": "510300",
  "name": "沪深300ETF",
  "close": 3.85,
  "preClose": 3.80,
  "volume": 123456789,
  "amount": 560000000,
  "kline": [
    {
      "date": "2026-06-01",
      "open": 3.7,
      "high": 3.9,
      "low": 3.6,
      "close": 3.85,
      "volume": 123456789,
      "amount": 560000000
    }
  ]
}
```

### 4.2 持仓数据

```json
{
  "code": "510300",
  "name": "沪深300ETF",
  "quantity": 10000,
  "availableQuantity": 10000,
  "costPrice": 3.6,
  "marketValue": 38500,
  "profitRate": 0.0694,
  "positionRatio": 0.25
}
```

### 4.3 趋势评分结果

来自 `score.md`：

```json
{
  "shortTrendScore": 82.0,
  "trendLevel": "UPTREND",
  "trendName": "短线上升趋势",
  "scores": {
    "maScore": 30,
    "bollScore": 20,
    "volScore": 12,
    "rsiScore": 14,
    "biasScore": 6
  },
  "indicators": {
    "close": 4.125,
    "ma5": 4.06,
    "ma10": 4.01,
    "ma20": 3.92,
    "bias5": 0.016,
    "rsi6": 76.3,
    "bollPosition": 0.87,
    "volRatio1To5": 1.25
  },
  "tags": [
    "短线均线多头"
  ]
}
```

---

## 5. 自选 ETF 池过滤

同花顺投资账本里的“自选”列表是分析 universe。自选中可能包含已持仓、未持仓、股票、可转债、港股或其他标的，进入分析前必须过滤。

自选 ETF 池主来源：

```text
https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/ISUeEwK
```

持仓 / 交易 / 备注来源：

```text
https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO
```

保留：

```text
宽基 ETF
行业 ETF
主题 ETF
商品 / 黄金 ETF
跨境 / QDII ETF
场内基金中明确属于宽基、行业、主题、商品、黄金、跨境或 QDII 方向的品种
```

过滤：

```text
A股股票
可转债
港股股票
债券 ETF
货币 ETF
杠杆 / 反向 ETF
REITs
其他非宽基、行业、主题、商品、黄金、跨境或 QDII ETF 标的
```

识别优先级：

```text
1. 优先按场内基金代码段识别：15 / 16 / 50 / 51 / 52 / 56 / 58 开头。
2. 名称包含 ETF / LOF / 基金 作为辅助确认。
3. 名称包含 沪深300 / 中证500 / 创业板 / 科创 / 上证50 等宽基特征，归为宽基 ETF。
4. 名称包含 证券 / 半导体 / 芯片 / 军工 / 新能源 / 医药 / 消费 / 人工智能 等行业主题特征，归为行业/主题 ETF。
5. 名称包含 黄金 / 商品 / 豆粕 / 能源化工 / 有色 等特征，且代码属于 A 股场内基金代码段时，归为商品 / 黄金 ETF，纳入分析和建议。
6. 名称包含 QDII / 纳指 / 标普 / 恒生 / 港股 / 中概 / 日经 等特征，且代码属于 A 股场内基金代码段时，归为跨境 / QDII ETF，纳入分析和建议。
7. 名称包含 债 / 货币 / 现金 / REIT 等特征时，默认过滤，除非后续启用独立模型。
8. 11 / 12 / 123 / 127 / 128 等可转债代码段和名称含“转债/可转债”的标的直接过滤。
```

---

## 6. 交易硬过滤

任何 ETF 满足下面条件，直接输出 `FORBID`：

```text
K线不足 60 个交易日
当前价格 <= 0
无最新价
停牌
无成交额
最近20日平均成交额低于对应 ETF 类型阈值
今日涨幅 >= 9.5%    // 接近涨停，不追
今日跌幅 <= -9.5%   // 接近跌停，不接飞刀
```

建议流动性阈值：

```text
宽基 ETF：最近20日平均成交额 >= 2亿
行业 ETF：最近20日平均成交额 >= 8000万
主题 ETF：最近20日平均成交额 >= 5000万
```

说明：

```text
流动性不足时，即使 ShortTrendScore 很高，也应 FORBID 或 WATCH，不应进入建仓/加仓动作。
```

---

## 7. 趋势评分使用规则

本规则引擎不再重新定义 trendScore。

禁止在 rule.md 中重新计算：

```text
close > MA20       +20
MA20 > MA60        +20
MA60 > MA120       +20
MA20 斜率 > 0      +20
close > MA120      +20
```

也不再计算：

```text
momentumScore
riskScore
totalScore
```

唯一趋势评分来源：

```text
score.md 输出的 ShortTrendScore
```

趋势等级解释：

```text
ShortTrendScore >= 85  短线强趋势
ShortTrendScore >= 75  短线上升趋势
ShortTrendScore >= 60  震荡偏强
ShortTrendScore >= 45  震荡观察
ShortTrendScore < 45   短线转弱
```

---

## 8. 仓位动作生成

仓位动作由 `action.md` 生成。

调用输入：

```text
ShortTrendScoreResult
currentPositionRatio
```

核心过程：

```text
1. 根据 ShortTrendScore 计算 baseTargetPositionRatio
2. 根据趋势标签判断 trendCaution
3. 如果有追高提示，则目标仓位降档
4. 比较 targetPositionRatio 和 currentPositionRatio
5. 输出 positionAction、adjustRatio、newPositionRatio
```

rule.md 不再直接写买入、加仓、卖出、清仓规则，避免和 action.md 冲突。

---

## 9. 决策优先级

最终规则结果按以下优先级执行：

```text
1. FORBID
2. EXIT_TREND_POSITION
3. REDUCE
4. TREND_REVIEW
5. ADD
6. OPEN
7. LIGHT_OPEN
8. HOLD
9. WATCH
```

说明：

```text
硬过滤优先于趋势评分。
趋势明显转弱优先于加仓和建仓。
当目标仓位为 0 且当前仍有持仓时，主动作必须优先显示为 REDUCE / EXIT_TREND_POSITION，趋势复核只能作为辅助说明。
未持仓标的即使评分高，也只允许轻仓试错，不输出满仓或重仓建议。
```

---

## 10. 未持仓自选 ETF 输出要求

未持仓但来自自选 ETF 池的标的也要生成：

```text
行情快照
ShortTrendScore
趋势等级
action.md 仓位动作
AI 复核输入
报告建议
```

输出必须包含：

```text
来源：自选ETF池
当前状态：未持仓
建议：轻仓建仓 / 建仓 / 观察 / 禁止交易
参考观察价：MA20、BOLL中轨、BOLL下轨或等待指标补齐
建仓比例：规则目标仓位；首笔不超过目标仓位约 1/3 或单格小仓位
```

缺少现金数据时：

```text
不假设现金充足
不输出满仓建议
不输出必须买入
```

---

## 11. 已持仓 ETF 输出要求

已持仓 ETF 输出必须包含：

```text
当前仓位
目标仓位
建议新仓位
调整比例
仓位动作
趋势评分
趋势等级
趋势标签
```

当前投资账本不提供可卖数量列：

```text
不按 T+1 或可用数量阻断减仓/退出短线仓提示。
不得输出“可用数量为0”“今日不可卖”等伪护栏。
```

---

## 12. 与网格建议的关系

rule.md 输出给 grid.md 的关键字段：

```text
positionAction
targetPositionRatio
currentPositionRatio
newPositionRatio
adjustRatio
shortTrendScore
trendLevel
trendName
tags
```

grid.md 可以额外读取 ATR：

```text
atr14
atr14Pct
atrExpansionRatio
```

但 ATR 只用于：

```text
网格间距
网格调宽/调窄
基准价偏离阈值
买入侧降速
```

不得用于反向修改：

```text
ShortTrendScore
TrendLevel
TrendName
```

---

## 13. AI 复核边界

AI 综合研判只基于已采集证据解释冲突和降级动作，不绕过硬过滤，不编造未接入数据。

AI 综合研判输出应只包含：

```text
AI 动作倾向
置信度
与规则建议的冲突点
必须遵守的护栏
最终倾向：保持规则建议 / 降级为保守 / 需要人工确认
```

AI 不得输出：

```text
必须买入
必须清仓
满仓
梭哈
稳赚
必涨
必跌
```

---

## 14. 核心伪代码

```python
def decide_rule(etf, position, portfolio):
    # 1. ETF universe 过滤
    if not is_supported_exchange_traded_fund(etf):
        return forbid(etf, reason="不属于当前 ETF/LOF/场内基金分析范围")

    # 2. 交易硬过滤
    forbidden_reason = check_hard_filter(etf)
    if forbidden_reason:
        return forbid(etf, reason=forbidden_reason)

    # 3. 计算趋势评分
    trend_result = calculate_short_trend_score(etf.kline)

    if not trend_result.data_sufficient:
        return watch(etf, trend_result, reason="趋势评分数据不足")

    # 4. 计算当前仓位
    current_position_ratio = position.position_ratio if position else 0.0

    # 5. 根据趋势评分生成仓位动作
    action_result = decide_position_action(
        trend_result=trend_result,
        current_position_ratio=current_position_ratio
    )

    # 6. 可用数量约束
    if action_result.position_action in ["REDUCE", "EXIT_TREND_POSITION"]:
        if position is None or position.available_quantity <= 0:
            action_result.add_warning("当前可用数量为0，不能生成可立即执行的减仓数量")

    # 7. 生成最终规则结果
    return build_rule_result(
        etf=etf,
        position=position,
        trend_result=trend_result,
        action_result=action_result
    )
```

---

## 15. 推荐配置参数

```json
{
  "minKlineDays": 60,
  "minAmountAvg20BroadBased": 200000000,
  "minAmountAvg20Industry": 80000000,
  "minAmountAvg20Theme": 50000000,
  "maxSinglePosition": 0.30,
  "maxTotalPosition": 0.80,
  "initialOpenRatioStrong": 0.15,
  "initialOpenRatioUptrend": 0.10,
  "minAdjustRatio": 0.05,
  "maxAddStepRatio": 0.10,
  "maxReduceStepRatio": 0.30,
  "maxWeakTrendReduceStepRatio": 0.50,
  "strongTrendScore": 85,
  "uptrendScore": 75,
  "weakTrendScore": 45
}
```

组合约束说明：

```text
1. ETFMate 面向趋势型 ETF 交易，行业/主题 ETF 是主要持仓方向；
2. 同类 ETF 占比只作为集中度提示，不阻断 ADD / OPEN / LIGHT_OPEN。
3. 同主题重合只作为成分、流动性、费率和跟踪误差的人工筛选提示，不作为负分或自动降仓理由。
4. 只有组合总仓位达到 80% 现金纪律或单只 ETF 达到 30% 上限时，才压缩新增买入目标。
5. 单次加仓最多 10% 组合仓位；若量能确认不足，即使趋势评分很高，也先输出持有待加仓确认。
```

---

## 16. 回归测试建议

修改规则引擎后至少覆盖以下场景：

```text
1. score.md 不输出 ATR_RISK_DEDUCT。
2. rule.md 不再调用 calc_trend_score / momentumScore / riskScore / totalScore。
3. ShortTrendScore >= 85 且无追高提示，未持仓输出 OPEN，但首笔目标仓位不超过 15%。
4. ShortTrendScore >= 75 且无追高提示，未持仓输出 LIGHT_OPEN。
5. ShortTrendScore < 75，未持仓输出 WATCH。
6. 已持仓时，targetPositionRatio > currentPositionRatio + 5%，输出 ADD。
7. 已持仓时，targetPositionRatio < currentPositionRatio - 5%，输出 REDUCE。
8. ShortTrendScore < 45 且 close < MA5 且 MA5 < MA10，输出 EXIT_TREND_POSITION。
9. 出现 RSI短线过热 / BIAS严重偏离MA5 / 接近布林上轨 / 放量急涨时，目标仓位降档。
10. BOLL_POSITION >= 0.90、RSI6 >= 70、BIAS12 >= 6%、BIAS24 >= 10% 时必须生成追高风险标签；未持仓不得输出普通建仓，已有持仓不得继续扩大买入侧。
11. ATR 放大只能影响 grid.md，不能反向修改 ShortTrendScore 或 TrendLevel。
12. 组合总仓位 80% 仍是现金纪律硬约束。
13. 已持仓强趋势但短线量能不足时，不直接加仓，输出持有待加仓确认。
```

---

## 17. 关键结论

1. rule.md 不再定义第二套趋势评分。
2. rule.md 不再计算 momentumScore、riskScore、totalScore。
3. rule.md 只消费 score.md 的 ShortTrendScore 和 action.md 的仓位动作结果。
4. 当前模型覆盖宽基 ETF、行业 ETF、主题 ETF、商品 / 黄金 ETF、跨境 / QDII ETF；不同类型在流动性阈值、仓位动作和解释文案上应保持区分。
5. ATR 不进入趋势评分和核心仓位动作，只进入网格建议或独立波动模块。
6. 所有输出必须是建议和风险提示，不得输出绝对交易指令。
