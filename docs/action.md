# ETFMate 短线趋势评分到仓位动作的决策算法（趋势纯净版）

## 1. 目标

本文档定义一套基于 `ShortTrendScore` 的仓位动作算法，用于将 ETF 短线趋势评分转换为：

```text
观察
轻仓建仓
建仓
持有
加仓
持有或小幅减仓
减仓
趋势复核
退出短线仓位
```

本算法适用于 ETFMate 中的：

```text
持仓诊断
短线趋势状态判断
ETF候选池过滤
AI分析解释
仓位动作建议
```

注意：

```text
本算法不直接输出“必须买入”“必须清仓”“满仓”“梭哈”等交易指令。
系统输出应为趋势分析、仓位建议和风险提示。
```

---

## 2. 前置条件

本算法依赖上游已经计算完成的短线趋势评分结果。

输入字段包括：

```text
symbol
tradeDate
shortTrendScore
trendLevel
trendName
currentPositionRatio
scores
indicators
tags
```

其中：

```text
shortTrendScore: 0 ~ 100
currentPositionRatio: 当前该 ETF 在组合中的仓位比例，范围 0 ~ 1
tags: 趋势解释标签数组
```

示例：

```json
{
  "symbol": "510300",
  "tradeDate": "2026-06-25",
  "shortTrendScore": 82.0,
  "trendLevel": "UPTREND",
  "trendName": "短线上升趋势",
  "currentPositionRatio": 0.20,
  "tags": [
    "短线均线多头"
  ],
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
  }
}
```

说明：

```text
ATR_RISK_DEDUCT、ATR_EXPANSION_RATIO 不属于本文档的必要输入。
ATR 后续只用于网格建议或独立波动模块，不参与趋势评分到仓位动作的核心决策。
```

---

## 3. 核心原则

不要直接根据评分输出买卖动作。

正确流程是：

```text
ShortTrendScore
    -> 判断是否存在短线追高提示 trendCaution
    -> 计算基础目标仓位 baseTargetPositionRatio
    -> 根据 trendCaution 调整目标仓位 targetPositionRatio
    -> 比较当前仓位 currentPositionRatio
    -> 得出仓位动作 positionAction
    -> 计算加仓/减仓比例 adjustRatio
```

核心公式：

```text
positionGap = targetPositionRatio - currentPositionRatio
```

含义：

```text
positionGap > 0：目标仓位高于当前仓位，可考虑加仓
positionGap < 0：目标仓位低于当前仓位，可考虑减仓
positionGap 接近 0：当前仓位基本合理，继续持有或不操作
```

---

## 4. 动作枚举

建议使用枚举，不要只使用中文字符串。

```java
public enum PositionAction {
    NO_ACTION,             // 不操作
    WATCH,                 // 观察
    LIGHT_OPEN,            // 轻仓建仓
    OPEN,                  // 建仓
    HOLD,                  // 持有
    ADD,                   // 加仓
    HOLD_OR_REDUCE,        // 持有或小幅减仓
    REDUCE,                // 减仓
    TREND_REVIEW,          // 趋势复核
    EXIT_TREND_POSITION    // 退出短线仓位
}
```

中文名称建议：

| 枚举 | 中文名称 |
|---|---|
| NO_ACTION | 不操作 |
| WATCH | 观察 |
| LIGHT_OPEN | 轻仓建仓 |
| OPEN | 建仓 |
| HOLD | 持有 |
| ADD | 加仓 |
| HOLD_OR_REDUCE | 持有或小幅减仓 |
| REDUCE | 减仓 |
| TREND_REVIEW | 趋势复核 |
| EXIT_TREND_POSITION | 退出短线仓位 |

---

## 5. 短线追高提示判断

### 5.1 追高提示标签

如果 `tags` 中包含以下任意标签，则认为存在短线追高提示：

```text
RSI短线过热
RSI短线偏热
BIAS严重偏离MA5
BIAS12明显正乖离
BIAS24严重正乖离
接近或突破布林上轨
放量急涨
```

说明：

```text
这些标签不改变 ShortTrendScore。
它们只用于限制继续追高、降低目标仓位或触发人工复核。
```

### 5.2 追高提示判断函数

```java
boolean hasTrendCaution(ShortTrendScoreResult result) {
    return result.getTags().contains("RSI短线过热")
        || result.getTags().contains("RSI短线偏热")
        || result.getTags().contains("BIAS严重偏离MA5")
        || result.getTags().contains("BIAS12明显正乖离")
        || result.getTags().contains("BIAS24严重正乖离")
        || result.getTags().contains("接近或突破布林上轨")
        || result.getTags().contains("放量急涨");
}
```

### 5.3 无追高提示定义

```text
noTrendCaution =
RSI6 < 70
and BIAS5 <= 0.06
and BIAS12 < +6%
and BIAS24 < +10%
and BOLL_POSITION < 0.90
and tags 不包含 "RSI短线过热"
and tags 不包含 "RSI短线偏热"
and tags 不包含 "BIAS严重偏离MA5"
and tags 不包含 "BIAS12明显正乖离"
and tags 不包含 "BIAS24严重正乖离"
and tags 不包含 "接近或突破布林上轨"
and tags 不包含 "放量急涨"
```

Java 伪代码：

```java
boolean noTrendCaution(ShortTrendScoreResult result) {
    return result.getIndicators().getRsi6() < 70
        && result.getIndicators().getBias5() <= 0.06
        // BIAS12/BIAS24 使用百分数值，例如 6 表示 +6%。
        && result.getIndicators().getBias12() < 6
        && result.getIndicators().getBias24() < 10
        && result.getIndicators().getBollPosition() < 0.90
        && !result.getTags().contains("RSI短线过热")
        && !result.getTags().contains("RSI短线偏热")
        && !result.getTags().contains("BIAS严重偏离MA5")
        && !result.getTags().contains("BIAS12明显正乖离")
        && !result.getTags().contains("BIAS24严重正乖离")
        && !result.getTags().contains("接近或突破布林上轨")
        && !result.getTags().contains("放量急涨");
}
```

---

## 6. 基础目标仓位规则

根据 `ShortTrendScore` 先计算基础目标仓位。

```text
if ShortTrendScore >= 85:
    baseTargetPositionRatio = 0.30
else if ShortTrendScore >= 75:
    baseTargetPositionRatio = 0.20
else if ShortTrendScore >= 60:
    baseTargetPositionRatio = 0.10
else if ShortTrendScore >= 45:
    baseTargetPositionRatio = 0.05
else:
    baseTargetPositionRatio = 0.00
```

解释：

| ShortTrendScore | 趋势状态 | 基础目标仓位 |
|---:|---|---:|
| >= 85 | 短线强趋势 | 30% |
| 75 ~ 85 | 短线上升趋势 | 20% |
| 60 ~ 75 | 震荡偏强 | 10% |
| 45 ~ 60 | 震荡观察 | 5% |
| < 45 | 短线转弱 | 0% |

说明：

```text
这里的目标仓位是单只 ETF 的规则目标仓位，不是组合总仓位。
```

---

## 7. 追高降档规则

如果存在短线追高提示，则目标仓位降低一档。

降档规则：

```text
30% -> 20%
20% -> 10%
10% -> 5%
5%  -> 0%
0%  -> 0%
```

Java 伪代码：

```java
double downgradeTargetPosition(double baseTargetPositionRatio) {
    if (baseTargetPositionRatio >= 0.30) {
        return 0.20;
    }
    if (baseTargetPositionRatio >= 0.20) {
        return 0.10;
    }
    if (baseTargetPositionRatio >= 0.10) {
        return 0.05;
    }
    if (baseTargetPositionRatio >= 0.05) {
        return 0.00;
    }
    return 0.00;
}
```

最终目标仓位：

```java
double targetPositionRatio = baseTargetPositionRatio;

if (hasTrendCaution(result)) {
    targetPositionRatio = downgradeTargetPosition(baseTargetPositionRatio);
}
```

---

## 8. 未持仓场景决策

当：

```text
currentPositionRatio <= 0
```

认为当前未持仓。

### 8.1 未持仓动作规则

```text
if ShortTrendScore >= 85 and noTrendCaution:
    action = OPEN
    targetPositionRatio = 0.10 ~ 0.15
else if ShortTrendScore >= 75 and noTrendCaution:
    action = LIGHT_OPEN
    targetPositionRatio = 0.05 ~ 0.10
else:
    action = WATCH
    targetPositionRatio = 0.00
```

说明：

```text
未持仓时，即使评分很高，也不建议一次建到目标满仓。
第一次建仓属于试错仓；后续是否加仓，需要等趋势继续确认。
```

### 8.2 未持仓解释文案

如果 `ShortTrendScore >= 85` 且无追高提示：

```text
短线趋势较强，且未出现明显追高提示，可进入建仓观察区。建议以初始仓位参与，不建议一次性重仓。
```

如果 `ShortTrendScore >= 75` 且无追高提示：

```text
短线趋势偏强，可轻仓建仓观察。后续需要继续观察 MA5、量能和短线动能是否保持稳定。
```

如果存在追高提示：

```text
趋势评分较高，但存在短线过热或偏离过大，不适合直接追高，建议等待回踩 MA5 或 MA10 后重新评估。
```

如果评分低于 75：

```text
短线趋势强度不足，暂不进入建仓区，建议继续观察。
```

---

## 9. 已持仓场景决策

当：

```text
currentPositionRatio > 0
```

认为当前已经持仓。

### 9.1 已持仓基础动作规则

先计算：

```text
positionGap = targetPositionRatio - currentPositionRatio
```

建议设置一个最小调整阈值，避免频繁微调。

```text
minAdjustRatio = 0.05
```

也就是仓位差小于 5% 时，不做实际调整。

```text
if abs(positionGap) < minAdjustRatio:
    action = HOLD
    adjustRatio = 0
```

### 9.2 已持仓动作判断

```text
if targetPositionRatio > currentPositionRatio + minAdjustRatio:
    action = ADD
else if targetPositionRatio < currentPositionRatio - minAdjustRatio:
    action = REDUCE
else:
    action = HOLD
```

### 9.3 趋势明显转弱场景

如果出现明显转弱：

```text
ShortTrendScore < 45
and close < MA5
and MA5 < MA10
```

则：

```text
action = EXIT_TREND_POSITION
```

说明：

```text
EXIT_TREND_POSITION 表示退出短线仓位或降至观察仓位，不等于系统强制清仓。
```

---

## 10. 加仓规则

### 10.1 加仓条件

只有同时满足以下条件，才允许加仓：

```text
ShortTrendScore >= 75
close > MA5
MA5 > MA10
VOL_RATIO_1_5 >= 1.1
不存在 BIAS严重偏离MA5
不存在 放量急涨
不存在 短线量能不足
```

更强加仓条件：

```text
ShortTrendScore >= 85
MA5 > MA10 > MA20
VOL_RATIO_1_5 >= 1.1
RSI6 <= 85
BIAS5 <= 0.06
```

### 10.2 单次最大加仓比例

建议：

```text
maxAddStepRatio = 0.10
```

也就是：

```text
单次最多加 10% 仓位
```

说明：

```text
代码实现必须保持该上限，不能把单次最大加仓扩大到 20%。
```

加仓公式：

```text
addRatio = min(positionGap, maxAddStepRatio)
```

加仓后仓位：

```text
newPositionRatio = currentPositionRatio + addRatio
newPositionRatio = min(newPositionRatio, targetPositionRatio)
```

### 10.3 阶梯加仓模型

假设单只 ETF 最大目标仓位为：

```text
maxPositionRatio = 0.30
```

分层如下：

| 仓位层级 | 仓位比例 | 含义 |
|---|---:|---|
| 观察仓 | 5% | 试错和跟踪 |
| 初始仓 | 10% | 趋势初步确认 |
| 标准仓 | 20% | 趋势较强 |
| 强趋势仓 | 30% | 短线强趋势 |

加仓路径建议：

```text
当前仓位 = 0%
score >= 75:
    建立 5% ~ 10% 初始仓

当前仓位 = 10%
score >= 85 且无追高提示:
    加到 20%

当前仓位 = 20%
score >= 85 且连续 2 天保持强势:
    加到 30%

当前仓位 >= 30%:
    不再加仓
```

注意：

```text
不是每次评分高都加仓。
加到目标仓位后停止。
强趋势但短线量能不足时，先持有等待加仓确认，不因为同类 ETF 占比高而强制转成减仓或止盈。
```

---

## 11. 减仓规则

减仓分为三种类型：

```text
趋势减仓
过热减仓
趋势转弱减仓
```

### 11.1 趋势减仓

当：

```text
ShortTrendScore < 60
```

说明短线趋势已经不强。

建议：

```text
降低到 10% 或更低目标仓位
```

示例：

```text
当前仓位 30%
ShortTrendScore = 55
targetPositionRatio = 5%
本次最多减 30%
newPositionRatio 不低于系统目标仓位
```

### 11.2 过热减仓

如果评分仍高，但出现以下标签：

```text
RSI短线过热
BIAS严重偏离MA5
接近或突破布林上轨
放量急涨
```

说明：

```text
趋势没有完全走坏，但短线追高和回撤压力上升。
```

处理规则：

```text
停止加仓
目标仓位降低一档
已有高仓位时，可减掉部分强趋势仓
```

示例：

```text
当前仓位 30%
ShortTrendScore = 88
但存在 RSI短线过热 + BIAS严重偏离MA5
baseTargetPositionRatio = 30%
targetPositionRatio 降档为 20%
本次减仓到 20% 或分步接近 20%
```

### 11.3 趋势转弱减仓

如果出现明显转弱：

```text
ShortTrendScore < 45
close < MA5
MA5 < MA10
```

建议：

```text
退出短线仓位或降至观察仓位
```

输出文案：

```text
短线趋势明显转弱，建议退出短线仓位或降至观察仓位，并等待趋势重新确认。
```

---

## 12. 单次最大减仓比例

普通减仓：

```text
maxReduceStepRatio = 0.30
```

趋势明显转弱减仓：

```text
maxReduceStepRatio = 0.50
```

判断：

```text
if ShortTrendScore < 45 and close < MA5 and MA5 < MA10:
    maxReduceStepRatio = 0.50
else:
    maxReduceStepRatio = 0.30
```

减仓公式：

```text
reduceRatio = min(abs(positionGap), maxReduceStepRatio)
```

减仓后仓位：

```text
newPositionRatio = currentPositionRatio - reduceRatio
newPositionRatio = max(newPositionRatio, targetPositionRatio)
newPositionRatio = max(newPositionRatio, 0)
```

---

## 13. 趋势提示等级

建议输出一个趋势提示等级 `trendAlertLevel`。

```java
public enum TrendAlertLevel {
    LOW,
    MEDIUM,
    HIGH
}
```

判断规则：

```text
if ShortTrendScore < 45
   or tags 包含 "BIAS严重偏离MA5":
    trendAlertLevel = HIGH
else if ShortTrendScore < 60
   or tags 包含 "RSI短线过热"
   or tags 包含 "接近或突破布林上轨"
   or tags 包含 "放量急涨":
    trendAlertLevel = MEDIUM
else:
    trendAlertLevel = LOW
```

---

## 14. 完整决策流程

```text
1. 接收 ShortTrendScoreResult 和 currentPositionRatio
2. 判断是否持仓
3. 判断 noTrendCaution / hasTrendCaution
4. 根据评分计算 baseTargetPositionRatio
5. 如果存在追高提示，则目标仓位降档
6. 如果未持仓：
   6.1 根据评分和追高状态生成 WATCH / LIGHT_OPEN / OPEN
   6.2 设置初始 targetPositionRatio
7. 如果已持仓：
   7.1 计算 positionGap
   7.2 根据 positionGap 判断 ADD / HOLD / REDUCE
   7.3 如果趋势明显转弱，则覆盖为 EXIT_TREND_POSITION
8. 计算 adjustRatio
9. 计算 newPositionRatio
10. 生成 reasons
11. 生成 warnings
12. 返回 PositionDecisionResult
``` 

---

## 15. 输出结构建议

```json
{
  "symbol": "510300",
  "tradeDate": "2026-06-25",
  "shortTrendScore": 82.0,
  "trendLevel": "UPTREND",
  "trendName": "短线上升趋势",

  "currentPositionRatio": 0.20,
  "targetPositionRatio": 0.20,
  "newPositionRatio": 0.20,
  "adjustRatio": 0.00,

  "positionAction": "HOLD",
  "actionName": "持有",
  "trendAlertLevel": "LOW",

  "reasons": [
    "短线趋势评分高于75，趋势处于上升状态",
    "当前仓位与目标仓位基本匹配",
    "未出现严重短线追高提示"
  ],
  "warnings": [
    "该建议仅为趋势评分结果，不构成交易指令",
    "后续仍需观察MA5、量能和RSI变化"
  ],
  "tags": [
    "短线均线多头"
  ]
}
```

---

## 16. 禁止输出文案

系统不得输出以下绝对化交易指令：

```text
必须买入
必须清仓
满仓
梭哈
无脑买入
马上卖出
稳赚
必涨
必跌
```

应替换为：

```text
可进入观察
可轻仓参与
可分步加仓
建议降低仓位
触发趋势复核
不适合追高
等待趋势重新确认
```

---

## 17. 关键结论

1. `ShortTrendScore` 不直接等于买卖信号，应先转换为目标仓位。
2. 加仓和减仓的核心依据是 `targetPositionRatio - currentPositionRatio`。
3. 未持仓时，即使评分很高，也建议先建立初始仓，不建议直接重仓。
4. 已持仓时，评分高且无追高提示，可以逐步加仓；评分下降或出现追高提示，应降低目标仓位。
5. RSI 过热、BIAS 偏离、接近布林上轨、放量急涨时，不应继续加仓，目标仓位应降低一档。
6. ATR 不参与本文档决策；ATR 后续只进入网格建议或独立波动模块。
7. 当 `targetPositionRatio == 0` 且已有持仓时，主动作必须明确为 `REDUCE` / `EXIT_TREND_POSITION` 这类可执行降风险语义；`TREND_REVIEW` 只能作为辅助标签，不能替代主动作。
8. 系统输出应是“建议”和“风险提示”，不应输出绝对化交易指令。

---

## 18. 趋势交易账户模式

当前 ETFMate 默认账户模式为：

```text
account_mode = TREND_TRADING
```

在该模式下，旧的 `targetPositionRatio` / `newPositionRatio` / `adjustRatio` 字段继续输出，主要用于兼容报告、AI 输入和旧 JSON 回放；它们不再作为单只 ETF 固定仓位上限，也不因 ETF 类型、黄金属性或同类集中度自动触发减仓。

主决策链调整为：

```text
ShortTrendScore
  -> trend_overheat_level
  -> trend_trade_mode
  -> execution_mode
  -> 网格执行参数校验
```

`trend_trade_mode` 取值：

```text
TREND_ADD            强趋势加仓
TREND_HOLD_GRID      趋势持有
PROFIT_PROTECTION    高位保护
BALANCED_GRID        震荡滚动
WEAK_REDUCE          弱势减仓
ONLY_SELL_OR_CLEAR   只卖清仓
PAUSE                暂停
```

关键规则：

1. `ShortTrendScore < 45` 时，进入 `ONLY_SELL_OR_CLEAR`，买入侧必须归零，允许按条件单卖出或清仓候选处理。
2. 强趋势且不过热时，不因浮盈或单只仓位参考值过早减仓；是否加仓由 MA5/MA10、量能和过热状态确认。
3. 强趋势但过热时，进入 `PROFIT_PROTECTION`，停止追买或只保留小额买入，同时分批兑现。
4. `45 <= ShortTrendScore < 60` 时，进入 `WEAK_REDUCE`，不继续扩大仓位。
5. 商品/黄金/QDII 与其他 ETF 一样按趋势模式处理，不再有配置型特殊动作。
