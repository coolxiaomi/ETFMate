# ETFMate 短线趋势评分算法设计文档

## 1. 目标

本算法用于根据 ETF 的短线技术指标，计算一个统一的 `ShortTrendScore`，用于判断 ETF 当前是否处于短线强势进攻状态。

该评分适用于：

```text
1 ~ 5 个交易日级别的短线趋势判断
```

主要用途：

```text
短线趋势识别
持仓状态诊断
ETF候选池过滤
风险标签生成
AI分析解释
```

注意：

```text
ShortTrendScore 不直接等于买入或卖出信号。
系统不得输出“必须买入”“必须清仓”“满仓”“梭哈”等交易指令。
```

推荐输出：

```text
趋势较强
趋势转弱
短线过热
波动放大
不适合追涨
触发风控复核
```

---

## 2. 算法定位

本算法是：

```text
ETF短线趋势评分 / ETF短线进攻评分
```

不是：

```text
ETF中期趋势评分
ETF长期趋势评分
ETF轮动主排序因子
```

原因：

本算法使用了短周期指标：

```text
MA5
RSI6
BIAS5
今日成交量
短周期ATR变化
```

这些指标对日级波动比较敏感，更适合判断短线状态，而不适合直接决定 ETF 轮动排名。

ETF 轮动主模型建议另设：

```text
MomentumScore
```

用于计算中期动量强弱。

最终可组合为：

```text
FinalScore = 0.7 * MomentumScore + 0.3 * ShortTrendScore
```

其中：

```text
MomentumScore 使用 20日、60日、120日、250日收益率排名计算；
ShortTrendScore 使用本算法计算。
```

---

## 3. 使用指标

本算法使用以下指标：

```text
MA
VOL
BOLL
BIAS
RSI
ATR
```

各指标作用：

| 指标   | 作用           |
| ---- | ------------ |
| MA   | 判断短线趋势方向     |
| VOL  | 判断成交量是否确认趋势  |
| BOLL | 判断价格所处强弱区间   |
| BIAS | 判断是否短线偏离过大   |
| RSI  | 判断短线动能强弱     |
| ATR  | 判断波动风险是否突然放大 |

---

## 4. 总分结构

总分为 `0 ~ 100`。

```text
ShortTrendScore =
MA_SCORE
+ VOL_SCORE
+ BOLL_SCORE
+ BIAS_SCORE
+ RSI_SCORE
- ATR_RISK_DEDUCT
```

最终需要限制范围：

```text
ShortTrendScore = clamp(ShortTrendScore, 0, 100)
```

权重设计：

| 模块        |  分值 |
| --------- | --: |
| MA 短线趋势   |  30 |
| BOLL 价格位置 |  20 |
| VOL 量能确认  |  15 |
| RSI 短线动能  |  15 |
| BIAS 偏离修正 |  10 |
| ATR 风险扣分  | -10 |
| 合计        | 100 |

说明：

相比原始方案，VOL 不建议设置为 25 分。
成交量对 ETF 有参考价值，但容易受到套利交易、申赎、大资金调仓、市场整体活跃度等因素影响。
因此 VOL 更适合作为确认因子，不适合作为和 MA 同权重的核心趋势因子。

---

## 5. 输入数据要求

至少需要最近 60 个交易日的日线数据。

建议字段：

```text
tradeDate
open
high
low
close
volume
amount 可选
```

如果数据不足，允许计算已有指标，但需要返回：

```text
dataSufficient = false
```

如果核心指标无法计算，需要增加标签：

```text
数据不足
```

---

## 6. 指标计算

### 6.1 MA

计算：

```text
MA5
MA10
MA20
```

计算 MA5 斜率：

```text
MA5_SLOPE_3 =
(MA5_today - MA5_3_days_ago) / MA5_3_days_ago
```

说明：

```text
MA5 用于短线灵敏度；
MA10、MA20 用于防止单日反抽误判。
```

---

### 6.2 VOL

计算：

```text
VOL5 = 最近5日平均成交量
VOL20 = 最近20日平均成交量
```

成交量比率：

```text
VOL_RATIO_1_5 = todayVolume / VOL5
VOL_RATIO_5_20 = VOL5 / VOL20
```

---

### 6.3 BOLL

默认参数：

```text
N = 20
K = 2
```

计算：

```text
BOLL_MID = MA20
BOLL_UPPER = MA20 + 2 * STD20
BOLL_LOWER = MA20 - 2 * STD20
```

布林带位置：

```text
BOLL_POSITION =
(close - BOLL_LOWER) / (BOLL_UPPER - BOLL_LOWER)
```

需要限制：

```text
BOLL_POSITION = clamp(BOLL_POSITION, 0, 1)
```

说明：

```text
BOLL_POSITION 越接近 1，说明越靠近上轨；
BOLL_POSITION 越接近 0，说明越靠近下轨。
```

---

### 6.4 BIAS

计算：

```text
BIAS5 = (close - MA5) / MA5
```

说明：

```text
BIAS5 > 0 表示价格在 MA5 上方；
BIAS5 < 0 表示价格在 MA5 下方。
```

---

### 6.5 RSI

计算：

```text
RSI6
```

说明：

```text
RSI6 用于判断短线动能。
```

---

### 6.6 ATR

计算：

```text
ATR14
ATR20_AVG = 最近20日 ATR14 的平均值
```

ATR 放大倍数：

```text
ATR_EXPANSION_RATIO = ATR14 / ATR20_AVG
```

说明：

```text
ATR_EXPANSION_RATIO 越大，说明当前波动相对过去一段时间明显放大。
```

---

## 7. 分项评分规则

---

## 7.1 MA_SCORE，满分 30

评分规则：

```text
if close > MA5 and MA5 > MA10 and MA10 > MA20 and MA5_SLOPE_3 > 0:
    MA_SCORE = 30
else if close > MA5 and MA5 > MA10 and MA5_SLOPE_3 > 0:
    MA_SCORE = 25
else if close > MA5 and MA5_SLOPE_3 > 0:
    MA_SCORE = 18
else if close > MA5:
    MA_SCORE = 12
else if close < MA5 and MA5 < MA10:
    MA_SCORE = 0
else:
    MA_SCORE = 5
```

解释：

```text
价格站上 MA5 代表短线转强；
MA5 > MA10 > MA20 代表短线均线多头；
MA5 斜率向上代表趋势正在增强；
仅价格站上 MA5 但均线未确认时，不给高分。
```

---

## 7.2 VOL_SCORE，满分 15

评分规则：

```text
if VOL_RATIO_1_5 >= 1.3 and VOL_RATIO_5_20 >= 1.0:
    VOL_SCORE = 15
else if VOL_RATIO_1_5 >= 1.1:
    VOL_SCORE = 12
else if VOL_RATIO_1_5 >= 0.9:
    VOL_SCORE = 8
else:
    VOL_SCORE = 4
```

解释：

```text
放量上涨是短线趋势确认；
短期成交量明显高于5日均量，说明资金参与度提升；
但成交量不应和价格趋势同等重要，所以权重控制在15分。
```

---

## 7.3 BOLL_SCORE，满分 20

评分规则：

```text
if BOLL_POSITION >= 0.60 and BOLL_POSITION <= 0.90:
    BOLL_SCORE = 20
else if BOLL_POSITION > 0.90 and BOLL_POSITION <= 1.00:
    BOLL_SCORE = 15
else if BOLL_POSITION >= 0.50 and BOLL_POSITION < 0.60:
    BOLL_SCORE = 12
else if BOLL_POSITION >= 0.35 and BOLL_POSITION < 0.50:
    BOLL_SCORE = 6
else:
    BOLL_SCORE = 2
```

解释：

```text
价格处于中轨上方，说明短线偏强；
价格处于中轨与上轨之间，属于强势区；
接近上轨不直接视为卖点，因为强趋势 ETF 可能沿上轨运行；
是否过热需要结合 RSI、BIAS 和 ATR 判断。
```

---

## 7.4 BIAS_SCORE，满分 10

评分规则：

```text
if BIAS5 > 0 and BIAS5 <= 0.025:
    BIAS_SCORE = 10
else if BIAS5 > 0.025 and BIAS5 <= 0.04:
    BIAS_SCORE = 8
else if BIAS5 > 0.04 and BIAS5 <= 0.06:
    BIAS_SCORE = 5
else if BIAS5 > 0.06:
    BIAS_SCORE = 2
else if BIAS5 <= 0 and BIAS5 >= -0.02:
    BIAS_SCORE = 5
else:
    BIAS_SCORE = 2
```

解释：

```text
略高于 MA5 代表短线强势；
距离 MA5 太远，说明短线追高风险上升；
跌破 MA5 说明短线趋势开始转弱。
```

---

## 7.5 RSI_SCORE，满分 15

评分规则：

```text
if RSI6 > 50 and RSI6 <= 75:
    RSI_SCORE = 15
else if RSI6 > 75 and RSI6 <= 85:
    RSI_SCORE = 10
else if RSI6 > 85:
    RSI_SCORE = 5
else if RSI6 >= 40 and RSI6 <= 50:
    RSI_SCORE = 8
else:
    RSI_SCORE = 2
```

解释：

```text
RSI6 在 50~75 之间代表短线多头动能健康；
RSI6 超过 85 代表短线过热，不直接归零，但需要打风险标签；
RSI6 低于 40，说明短线动能较弱。
```

---

## 7.6 ATR_RISK_DEDUCT，最多扣 10 分

评分规则：

```text
if ATR_EXPANSION_RATIO >= 1.8:
    ATR_RISK_DEDUCT = 10
else if ATR_EXPANSION_RATIO >= 1.5:
    ATR_RISK_DEDUCT = 7
else if ATR_EXPANSION_RATIO >= 1.2:
    ATR_RISK_DEDUCT = 3
else:
    ATR_RISK_DEDUCT = 0
```

解释：

```text
ATR 突然放大代表波动风险上升；
尤其是高位放量大波动时，需要降低短线评分；
ATR 是风险扣分项，不是趋势加分项。
```

---

## 8. 最终评分计算

```text
rawScore =
MA_SCORE
+ VOL_SCORE
+ BOLL_SCORE
+ BIAS_SCORE
+ RSI_SCORE
- ATR_RISK_DEDUCT
```

最终：

```text
ShortTrendScore = clamp(rawScore, 0, 100)
```

---

## 9. 趋势等级

```text
if ShortTrendScore >= 85 and ATR_RISK_DEDUCT == 0:
    TrendLevel = "STRONG_ATTACK"
    TrendName = "强势进攻区"
else if ShortTrendScore >= 75:
    TrendLevel = "UPTREND"
    TrendName = "短线上升趋势"
else if ShortTrendScore >= 60:
    TrendLevel = "WEAK_UPTREND"
    TrendName = "震荡偏强"
else if ShortTrendScore >= 45:
    TrendLevel = "SIDEWAYS"
    TrendName = "震荡观察"
else:
    TrendLevel = "WEAK"
    TrendName = "短线转弱"
```

---

## 10. 趋势标签

输出 `tags` 数组，用于解释评分原因。

初始化：

```text
tags = []
```

规则：

```text
if RSI6 > 85:
    add "RSI短线过热"

if BIAS5 > 0.06:
    add "BIAS严重偏离MA5"

if BOLL_POSITION > 0.95:
    add "接近或突破布林上轨"

if ATR_EXPANSION_RATIO >= 1.5:
    add "ATR波动放大"

if VOL_RATIO_1_5 >= 1.5 and BIAS5 > 0.04:
    add "放量急涨"

if close < MA5:
    add "跌破MA5"

if close > MA5 and MA5 > MA10 and MA10 > MA20:
    add "短线均线多头"

if VOL_RATIO_1_5 < 0.9:
    add "短线量能不足"

if BOLL_POSITION < 0.35:
    add "布林弱势区"

if dataSufficient == false:
    add "数据不足"
```

---

## 11. 输出结构建议

```json
{
  "symbol": "510300",
  "tradeDate": "2026-06-23",
  "shortTrendScore": 78.0,
  "trendLevel": "UPTREND",
  "trendName": "短线上升趋势",
  "dataSufficient": true,
  "scores": {
    "maScore": 25,
    "volScore": 12,
    "bollScore": 20,
    "biasScore": 8,
    "rsiScore": 10,
    "atrRiskDeduct": 7
  },
  "indicators": {
    "close": 4.125,
    "ma5": 4.06,
    "ma10": 4.01,
    "ma20": 3.92,
    "ma5Slope3": 0.012,
    "todayVolume": 150000000,
    "vol5": 120000000,
    "vol20": 100000000,
    "volRatio1To5": 1.25,
    "volRatio5To20": 1.2,
    "bollUpper": 4.20,
    "bollMid": 3.92,
    "bollLower": 3.64,
    "bollPosition": 0.87,
    "bias5": 0.016,
    "rsi6": 76.3,
    "atr14": 0.085,
    "atr20Avg": 0.063,
    "atrExpansionRatio": 1.35
  },
  "tags": [
    "短线均线多头"
  ]
}
```

---

## 12. 实现注意事项

### 12.1 数据排序

输入 K 线必须按交易日期升序排序。

```text
oldest -> newest
```

最后一条数据作为当前交易日。

---

### 12.2 缺失数据处理

如果某项指标无法计算：

```text
该指标值 = null
该项得分 = 0
```

并增加标签：

```text
数据不足
```

如果核心指标无法计算：

```text
MA5
MA10
MA20
BOLL
RSI6
ATR14
```

则返回：

```text
dataSufficient = false
```

---

### 12.3 除零保护

以下情况必须做保护：

```text
MA5 == 0
VOL5 == 0
VOL20 == 0
BOLL_UPPER == BOLL_LOWER
ATR20_AVG == 0
close == 0
```

出现除零风险时：

```text
对应指标返回 null
对应分数返回 0
```

---

### 12.4 分数精度

建议：

```text
内部计算使用 double；
最终输出保留 2 位小数。
```

---

## 13. Java 伪代码

```java
public ShortTrendScoreResult calculateShortTrendScore(List<KLine> klines) {
    // 1. 按 tradeDate 升序排序
    // 2. 取最后一条作为当前交易日
    // 3. 计算 MA5、MA10、MA20
    // 4. 计算 MA5_SLOPE_3
    // 5. 计算 VOL5、VOL20、VOL_RATIO_1_5、VOL_RATIO_5_20
    // 6. 计算 BOLL20
    // 7. 计算 BIAS5
    // 8. 计算 RSI6
    // 9. 计算 ATR14、ATR20_AVG、ATR_EXPANSION_RATIO
    // 10. 分别计算 MA_SCORE、VOL_SCORE、BOLL_SCORE、BIAS_SCORE、RSI_SCORE、ATR_RISK_DEDUCT
    // 11. 汇总 ShortTrendScore
    // 12. 生成 TrendLevel、TrendName、tags
    // 13. 返回 ShortTrendScoreResult
}
```

---

## 14. 使用建议

```text
ShortTrendScore >= 75:
    可进入短线趋势候选池

ShortTrendScore >= 85 and ATR_RISK_DEDUCT == 0:
    标记为强势进攻状态

ShortTrendScore < 60:
    不进入短线进攻候选池

ShortTrendScore < 45:
    触发持仓复核或风控提示
```

禁止直接输出：

```text
必须买入
必须清仓
满仓
梭哈
```

建议输出：

```text
趋势较强
趋势转弱
短线过热
波动放大
不适合追涨
触发风控复核
```

---

## 15. 与 ETF 轮动主模型的关系

该算法不是 ETF 轮动主排序因子。

推荐 ETFMate 使用双评分体系：

```text
MomentumScore：决定哪个 ETF 更强
ShortTrendScore：判断当前短线趋势是否健康
```

最终排序建议：

```text
FinalScore = 0.7 * MomentumScore + 0.3 * ShortTrendScore
```

MomentumScore 可使用：

```text
20日收益率排名
60日收益率排名
120日收益率排名
250日收益率排名
```

示例：

```text
MomentumScore =
0.4 * R20_RankScore
+ 0.3 * R60_RankScore
+ 0.2 * R120_RankScore
+ 0.1 * R250_RankScore
```

---

## 16. 关键结论

1. 该算法适合做 ETF 短线趋势评分，不适合单独作为中期轮动主模型。
2. VOL 不建议给 25 分，建议控制在 15 分，作为趋势确认因子。
3. MA5 需要结合 MA10、MA20，否则容易把单日反抽误判为趋势转强。
4. BOLL 接近上轨不应直接视为卖点，应结合 RSI、BIAS、ATR 判断是否过热。
5. RSI6 超过 85 不建议直接归零，可降低分数并输出“RSI短线过热”标签。
6. “低于 50 分必须清仓”不建议写入系统，应改为“触发持仓复核或风控提示”。
7. 最终系统输出应是分析与风险提示，不应输出绝对买卖指令。
