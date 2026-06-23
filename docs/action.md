# ETFMate 短线趋势评分到仓位动作的决策算法

## 1. 目标

本文档定义一套基于 `ShortTrendScore` 的仓位决策算法，用于将 ETF 短线趋势评分转换为：

```text
观察
建仓
轻仓建仓
持有
加仓
持有或减仓
减仓
风控复核
退出短线仓位
```

本算法适用于 ETFMate 中的：

```text
持仓诊断
短线趋势状态判断
ETF候选池过滤
AI分析解释
风险提示生成
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
tags: 风险标签数组
```

示例：

```json
{
  "symbol": "510300",
  "tradeDate": "2026-06-23",
  "shortTrendScore": 82.5,
  "trendLevel": "UPTREND",
  "trendName": "短线上升趋势",
  "currentPositionRatio": 0.20,
  "tags": [
    "短线均线多头"
  ],
  "scores": {
    "atrRiskDeduct": 0
  },
  "indicators": {
    "close": 4.125,
    "ma5": 4.06,
    "ma10": 4.01,
    "ma20": 3.92,
    "bias5": 0.016,
    "rsi6": 76.3,
    "atrExpansionRatio": 1.1
  }
}
```

---

## 3. 核心原则

不要直接根据评分输出买卖动作。

正确流程是：

```text
ShortTrendScore
    -> 计算基础目标仓位 baseTargetPositionRatio
    -> 根据风险标签调整目标仓位 targetPositionRatio
    -> 比较当前仓位 currentPositionRatio
    -> 得出仓位动作 positionAction
    -> 计算加仓/减仓比例 adjustRatio
```

核心公式：

```text
positionGap = targetPositionRatio - currentPositionRatio
```

如果：

```text
positionGap > 0
```

说明目标仓位高于当前仓位，可以加仓。

如果：

```text
positionGap < 0
```

说明目标仓位低于当前仓位，需要减仓。

如果：

```text
positionGap 接近 0
```

说明当前仓位基本合理，继续持有或不操作。

---

## 4. 动作枚举

建议使用枚举，不要只使用中文字符串。

```java
public enum PositionAction {
    NO_ACTION,        // 不操作
    WATCH,            // 观察
    OPEN,             // 建仓
    LIGHT_OPEN,       // 轻仓建仓
    HOLD,             // 持有
    ADD,              // 加仓
    HOLD_OR_ADD,      // 持有或加仓
    HOLD_OR_REDUCE,   // 持有或小幅减仓
    REDUCE,           // 减仓
    RISK_REVIEW,      // 风控复核
    EXIT_SHORT_TERM   // 退出短线仓位
}
```

中文名称建议：

| 枚举              | 中文名称    |
| --------------- | ------- |
| NO_ACTION       | 不操作     |
| WATCH           | 观察      |
| OPEN            | 建仓      |
| LIGHT_OPEN      | 轻仓建仓    |
| HOLD            | 持有      |
| ADD             | 加仓      |
| HOLD_OR_ADD     | 持有或加仓   |
| HOLD_OR_REDUCE  | 持有或小幅减仓 |
| REDUCE          | 减仓      |
| RISK_REVIEW     | 风控复核    |
| EXIT_SHORT_TERM | 退出短线仓位  |

---

## 5. 风险状态判断

### 5.1 高风险标签

如果 `tags` 中包含以下任意标签，则认为存在短线高风险：

```text
RSI短线过热
BIAS严重偏离MA5
ATR波动放大
放量急涨
接近或突破布林上轨
```

### 5.2 高风险判断函数

```java
boolean hasHighRisk(TrendScoreResult result) {
    return result.getTags().contains("RSI短线过热")
        || result.getTags().contains("BIAS严重偏离MA5")
        || result.getTags().contains("ATR波动放大")
        || result.getTags().contains("放量急涨")
        || result.getTags().contains("接近或突破布林上轨");
}
```

### 5.3 无高风险定义

```text
noHighRisk =
ATR_RISK_DEDUCT == 0
and RSI6 <= 85
and BIAS5 <= 0.06
and tags 不包含 "放量急涨"
and tags 不包含 "ATR波动放大"
```

Java 伪代码：

```java
boolean noHighRisk(TrendScoreResult result) {
    return result.getScores().getAtrRiskDeduct() == 0
        && result.getIndicators().getRsi6() <= 85
        && result.getIndicators().getBias5() <= 0.06
        && !result.getTags().contains("放量急涨")
        && !result.getTags().contains("ATR波动放大");
}
```

---

## 6. 基础目标仓位规则

根据 `ShortTrendScore` 先计算基础目标仓位。

```text
if ShortTrendScore >= 85 and noHighRisk:
    baseTargetPositionRatio = 0.60
else if ShortTrendScore >= 75 and noHighRisk:
    baseTargetPositionRatio = 0.40
else if ShortTrendScore >= 60:
    baseTargetPositionRatio = 0.25
else if ShortTrendScore >= 45:
    baseTargetPositionRatio = 0.10
else:
    baseTargetPositionRatio = 0.00
```

解释：

| ShortTrendScore | 风险状态  | 基础目标仓位 |
| --------------: | ----- | -----: |
|           >= 85 | 无明显风险 |    60% |
|         75 ~ 85 | 无明显风险 |    40% |
|         60 ~ 75 | 一般趋势  |    25% |
|         45 ~ 60 | 震荡观察  |    10% |
|            < 45 | 短线转弱  |     0% |

---

## 7. 风险降档规则

如果存在高风险标签，则目标仓位降低一档。

降档规则：

```text
60% -> 40%
40% -> 25%
25% -> 10%
10% -> 0%
0%  -> 0%
```

Java 伪代码：

```java
double downgradeTargetPosition(double baseTargetPositionRatio) {
    if (baseTargetPositionRatio >= 0.60) {
        return 0.40;
    }
    if (baseTargetPositionRatio >= 0.40) {
        return 0.25;
    }
    if (baseTargetPositionRatio >= 0.25) {
        return 0.10;
    }
    if (baseTargetPositionRatio >= 0.10) {
        return 0.00;
    }
    return 0.00;
}
```

最终目标仓位：

```java
double targetPositionRatio = baseTargetPositionRatio;

if (hasHighRisk(result)) {
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
if ShortTrendScore >= 85 and noHighRisk:
    action = OPEN
    targetPositionRatio = 0.30
else if ShortTrendScore >= 75 and noHighRisk:
    action = LIGHT_OPEN
    targetPositionRatio = 0.20
else:
    action = WATCH
    targetPositionRatio = 0.00
```

说明：

未持仓时，即使评分很高，也不建议一次建到 60%。

原因：

```text
第一次建仓属于试错仓；
后续是否加仓，需要等趋势继续确认。
```

### 8.2 未持仓解释文案

如果 `ShortTrendScore >= 85` 且无高风险：

```text
短线趋势较强，且未出现明显过热或波动放大，可进入建仓观察区。建议以初始仓位参与，不建议一次性重仓。
```

如果 `ShortTrendScore >= 75` 且无高风险：

```text
短线趋势偏强，可轻仓建仓观察。后续需要继续观察 MA5、量能和 ATR 是否保持稳定。
```

如果存在高风险标签：

```text
趋势评分较高，但存在短线过热或波动放大，不适合直接追高，建议等待回踩 MA5 或 MA10 后重新评估。
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

### 9.3 特殊风控场景

如果出现明显转弱：

```text
ShortTrendScore < 45
and close < MA5
and MA5 < MA10
```

则：

```text
action = RISK_REVIEW
```

如果同时 ATR 明显放大：

```text
ATR_EXPANSION_RATIO >= 1.5
```

则：

```text
action = EXIT_SHORT_TERM
```

说明：

```text
EXIT_SHORT_TERM 表示退出短线仓位或降至观察仓位，不等于系统强制清仓。
```

---

## 10. 加仓规则

### 10.1 加仓条件

只有同时满足以下条件，才允许加仓：

```text
ShortTrendScore >= 75
close > MA5
MA5 > MA10
没有 ATR 波动放大
没有 BIAS 严重偏离
```

更强加仓条件：

```text
ShortTrendScore >= 85
MA5 > MA10 > MA20
VOL_RATIO_1_5 >= 1.1
RSI6 <= 85
ATR_RISK_DEDUCT == 0
```

### 10.2 单次最大加仓比例

建议：

```text
maxAddStepRatio = 0.20
```

也就是：

```text
单次最多加 20% 仓位
```

加仓公式：

```text
addRatio = min(positionGap, maxAddStepRatio)
```

加仓后仓位：

```text
newPositionRatio = currentPositionRatio + addRatio
```

需要限制：

```text
newPositionRatio = min(newPositionRatio, targetPositionRatio)
```

### 10.3 阶梯加仓模型

假设单只 ETF 短线最大目标仓位为：

```text
maxPositionRatio = 0.60
```

分层如下：

| 仓位层级 | 仓位比例 | 含义       |
| ---- | ---: | -------- |
| 观察仓  |  10% | 试错和跟踪    |
| 初始仓  |  20% | 趋势初步确认   |
| 标准仓  |  40% | 趋势较强     |
| 进攻仓  |  60% | 强趋势且风险可控 |

加仓路径建议：

```text
当前仓位 = 0%
score >= 75:
    建立 10% ~ 20% 初始仓

当前仓位 = 20%
score >= 85 且无高风险:
    加到 40%

当前仓位 = 40%
score >= 85 且连续 2 天保持强势:
    加到 60%

当前仓位 >= 60%:
    不再加仓
```

注意：

```text
不是每次评分高都加仓。
加到目标仓位后停止。
```

---

## 11. 减仓规则

减仓分为三种类型：

```text
趋势减仓
风险减仓
风控减仓
```

---

### 11.1 趋势减仓

当：

```text
ShortTrendScore < 60
```

说明短线趋势已经不强。

建议：

```text
降低到 25% 或更低目标仓位
```

示例：

```text
当前仓位 60%
ShortTrendScore = 55
targetPositionRatio = 25%
本次最多减 30%
newPositionRatio = 30%
```

---

### 11.2 风险减仓

如果评分仍高，但出现以下风险标签：

```text
RSI短线过热
BIAS严重偏离MA5
ATR波动放大
放量急涨
```

说明：

```text
趋势没有完全走坏，但短线回撤风险上升。
```

处理规则：

```text
停止加仓
目标仓位降低一档
已有高仓位时，可减掉部分进攻仓
```

示例：

```text
当前仓位 60%
ShortTrendScore = 88
但存在 RSI短线过热 + BIAS严重偏离MA5
baseTargetPositionRatio = 60%
targetPositionRatio 降档为 40%
本次减仓到 40%
```

输出文案：

```text
强趋势仍在，但短线过热，建议停止加仓。已有较高仓位时，可考虑降低部分进攻仓，等待回踩后再评估。
```

---

### 11.3 风控减仓

如果出现明显转弱：

```text
ShortTrendScore < 45
close < MA5
MA5 < MA10
```

建议：

```text
触发风控复核
降低到观察仓或退出短线仓位
```

如果同时：

```text
ATR_EXPANSION_RATIO >= 1.5
```

则风险进一步提高：

```text
action = EXIT_SHORT_TERM
```

输出文案：

```text
短线趋势明显转弱，且波动放大，建议退出短线进攻仓位或降至观察仓位，并等待趋势重新确认。
```

---

## 12. 单次最大减仓比例

普通减仓：

```text
maxReduceStepRatio = 0.30
```

严重风控减仓：

```text
maxReduceStepRatio = 0.50
```

判断：

```text
if ShortTrendScore < 45 and close < MA5 and MA5 < MA10 and ATR_EXPANSION_RATIO >= 1.5:
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
```

需要限制：

```text
newPositionRatio = max(newPositionRatio, targetPositionRatio)
newPositionRatio = max(newPositionRatio, 0)
```

---

## 13. 操作建议等级

建议输出一个风险等级 `riskLevel`。

```java
public enum RiskLevel {
    LOW,
    MEDIUM,
    HIGH
}
```

判断规则：

```text
if tags 包含 "ATR波动放大"
   or tags 包含 "BIAS严重偏离MA5"
   or ShortTrendScore < 45:
    riskLevel = HIGH
else if tags 包含 "RSI短线过热"
   or tags 包含 "接近或突破布林上轨"
   or ShortTrendScore < 60:
    riskLevel = MEDIUM
else:
    riskLevel = LOW
```

---

## 14. 完整决策流程

```text
1. 接收 ShortTrendScoreResult 和 currentPositionRatio
2. 判断是否持仓
3. 判断 noHighRisk / hasHighRisk
4. 如果未持仓：
   4.1 根据评分和风险状态生成 WATCH / LIGHT_OPEN / OPEN
   4.2 设置初始 targetPositionRatio
5. 如果已持仓：
   5.1 根据评分计算 baseTargetPositionRatio
   5.2 如果存在高风险标签，则目标仓位降档
   5.3 计算 positionGap
   5.4 根据 positionGap 判断 ADD / HOLD / REDUCE
   5.5 如果触发严重风控，则覆盖为 RISK_REVIEW 或 EXIT_SHORT_TERM
6. 计算 adjustRatio
7. 计算 newPositionRatio
8. 生成 reasons
9. 生成 warnings
10. 返回 PositionDecisionResult
```

---

## 15. Java 伪代码

```java
public PositionDecisionResult decidePositionAction(
        ShortTrendScoreResult trendResult,
        double currentPositionRatio
) {
    double score = trendResult.getShortTrendScore();

    boolean holding = currentPositionRatio > 0;
    boolean noHighRisk = noHighRisk(trendResult);
    boolean highRisk = hasHighRisk(trendResult);

    double targetPositionRatio;
    PositionAction action;
    double adjustRatio = 0.0;
    double newPositionRatio = currentPositionRatio;

    // 未持仓场景
    if (!holding) {
        if (score >= 85 && noHighRisk) {
            action = PositionAction.OPEN;
            targetPositionRatio = 0.30;
        } else if (score >= 75 && noHighRisk) {
            action = PositionAction.LIGHT_OPEN;
            targetPositionRatio = 0.20;
        } else {
            action = PositionAction.WATCH;
            targetPositionRatio = 0.00;
        }

        adjustRatio = targetPositionRatio;
        newPositionRatio = targetPositionRatio;

        return buildResult(trendResult, currentPositionRatio, targetPositionRatio,
                newPositionRatio, action, adjustRatio);
    }

    // 已持仓场景
    double baseTargetPositionRatio = calculateBaseTargetPosition(score, noHighRisk);

    if (highRisk) {
        targetPositionRatio = downgradeTargetPosition(baseTargetPositionRatio);
    } else {
        targetPositionRatio = baseTargetPositionRatio;
    }

    double positionGap = targetPositionRatio - currentPositionRatio;
    double minAdjustRatio = 0.05;

    boolean seriousRisk = isSeriousRisk(trendResult);

    if (seriousRisk) {
        if (trendResult.getIndicators().getAtrExpansionRatio() >= 1.5) {
            action = PositionAction.EXIT_SHORT_TERM;
        } else {
            action = PositionAction.RISK_REVIEW;
        }
    } else if (Math.abs(positionGap) < minAdjustRatio) {
        action = PositionAction.HOLD;
    } else if (positionGap > 0) {
        action = PositionAction.ADD;
    } else {
        action = PositionAction.REDUCE;
    }

    if (action == PositionAction.ADD) {
        double maxAddStepRatio = 0.20;
        adjustRatio = Math.min(positionGap, maxAddStepRatio);
        newPositionRatio = currentPositionRatio + adjustRatio;
        newPositionRatio = Math.min(newPositionRatio, targetPositionRatio);
    } else if (action == PositionAction.REDUCE
            || action == PositionAction.RISK_REVIEW
            || action == PositionAction.EXIT_SHORT_TERM) {

        double maxReduceStepRatio = seriousRisk ? 0.50 : 0.30;
        double reduceGap = Math.max(0, currentPositionRatio - targetPositionRatio);
        adjustRatio = Math.min(reduceGap, maxReduceStepRatio);
        newPositionRatio = currentPositionRatio - adjustRatio;
        newPositionRatio = Math.max(newPositionRatio, targetPositionRatio);
        newPositionRatio = Math.max(newPositionRatio, 0.0);
    }

    return buildResult(trendResult, currentPositionRatio, targetPositionRatio,
            newPositionRatio, action, adjustRatio);
}
```

---

## 16. 辅助函数伪代码

### 16.1 基础目标仓位

```java
double calculateBaseTargetPosition(double score, boolean noHighRisk) {
    if (score >= 85 && noHighRisk) {
        return 0.60;
    }
    if (score >= 75 && noHighRisk) {
        return 0.40;
    }
    if (score >= 60) {
        return 0.25;
    }
    if (score >= 45) {
        return 0.10;
    }
    return 0.00;
}
```

### 16.2 风险降档

```java
double downgradeTargetPosition(double baseTargetPositionRatio) {
    if (baseTargetPositionRatio >= 0.60) {
        return 0.40;
    }
    if (baseTargetPositionRatio >= 0.40) {
        return 0.25;
    }
    if (baseTargetPositionRatio >= 0.25) {
        return 0.10;
    }
    if (baseTargetPositionRatio >= 0.10) {
        return 0.00;
    }
    return 0.00;
}
```

### 16.3 严重风险判断

```java
boolean isSeriousRisk(ShortTrendScoreResult result) {
    double score = result.getShortTrendScore();
    double close = result.getIndicators().getClose();
    double ma5 = result.getIndicators().getMa5();
    double ma10 = result.getIndicators().getMa10();

    return score < 45
        && close < ma5
        && ma5 < ma10;
}
```

---

## 17. 输出结构建议

```json
{
  "symbol": "510300",
  "tradeDate": "2026-06-23",
  "shortTrendScore": 82.5,
  "trendLevel": "UPTREND",
  "trendName": "短线上升趋势",

  "currentPositionRatio": 0.20,
  "targetPositionRatio": 0.40,
  "newPositionRatio": 0.40,
  "adjustRatio": 0.20,

  "positionAction": "ADD",
  "actionName": "加仓",
  "riskLevel": "LOW",

  "reasons": [
    "短线趋势评分高于75，趋势处于上升状态",
    "价格位于MA5上方，且MA5高于MA10",
    "未出现ATR波动放大",
    "目标仓位高于当前仓位，允许分步加仓"
  ],
  "warnings": [
    "该建议仅为趋势评分结果，不构成交易指令",
    "加仓后仍需观察成交量、MA5和ATR变化"
  ],
  "tags": [
    "短线均线多头"
  ]
}
```

---

## 18. 文案生成规则

### 18.1 OPEN

```text
短线趋势较强，且未出现明显过热或波动放大，可进入建仓观察区。建议以初始仓位参与，不建议一次性重仓。
```

### 18.2 LIGHT_OPEN

```text
短线趋势偏强，可轻仓建仓观察。后续需要继续观察 MA5、量能和 ATR 是否保持稳定。
```

### 18.3 WATCH

```text
短线趋势强度不足，暂不进入建仓区，建议继续观察。
```

### 18.4 HOLD

```text
当前仓位与目标仓位基本匹配，短线趋势尚未明显破坏，建议继续观察持有。
```

### 18.5 ADD

```text
短线趋势评分较高，且目标仓位高于当前仓位，可按阶梯方式加仓。单次加仓比例不应超过系统设定上限。
```

### 18.6 REDUCE

```text
当前目标仓位低于实际仓位，说明短线趋势或风险状态发生变化，建议降低部分仓位。
```

### 18.7 RISK_REVIEW

```text
短线趋势明显转弱，建议触发持仓复核，降低短线进攻仓位。
```

### 18.8 EXIT_SHORT_TERM

```text
短线趋势转弱且波动风险放大，建议退出短线进攻仓位或降至观察仓位，等待趋势重新确认。
```

---

## 19. 禁止输出文案

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
触发风控复核
不适合追涨
等待趋势重新确认
```

---

## 20. 最终建议规则摘要

### 20.1 未持仓

```text
ShortTrendScore >= 85 且无高风险:
    可建 20% ~ 30%

ShortTrendScore >= 75 且无高风险:
    可建 10% ~ 20%

ShortTrendScore < 75:
    观察
```

### 20.2 已持仓

```text
ShortTrendScore >= 85 且无高风险:
    目标仓位 60%

ShortTrendScore >= 75 且无高风险:
    目标仓位 40%

ShortTrendScore >= 60:
    目标仓位 25%

ShortTrendScore >= 45:
    目标仓位 10%

ShortTrendScore < 45:
    目标仓位 0%
```

### 20.3 风险降档

```text
存在 RSI短线过热 / BIAS严重偏离MA5 / ATR波动放大 / 放量急涨:
    目标仓位降低一档
```

### 20.4 加减仓

```text
targetPositionRatio > currentPositionRatio:
    加仓

targetPositionRatio ≈ currentPositionRatio:
    持有

targetPositionRatio < currentPositionRatio:
    减仓
```

### 20.5 单次调整上限

```text
单次最大加仓比例: 20%
普通单次最大减仓比例: 30%
严重风控单次最大减仓比例: 50%
```

---

## 21. 关键结论

1. `ShortTrendScore` 不直接等于买卖信号，应先转换为目标仓位。
2. 加仓和减仓的核心依据是 `targetPositionRatio - currentPositionRatio`。
3. 未持仓时，即使评分很高，也建议先建立初始仓，不建议直接重仓。
4. 已持仓时，评分高且无风险，可以逐步加仓；评分下降或风险升高，应降低目标仓位。
5. RSI 过热、BIAS 偏离、ATR 放大、放量急涨时，不应继续加仓，目标仓位应降低一档。
6. 单次加仓和减仓都需要设置上限，避免系统因单日波动频繁大幅调整。
7. 系统输出应是“建议”和“风险提示”，不应输出绝对化交易指令。
