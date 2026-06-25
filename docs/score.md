# ETFMate 短线趋势评分算法设计文档（修正版）

## 1. 目标

本算法用于根据 ETF 的短线技术指标，计算统一的 `ShortTrendScore`，用于判断 ETF 当前是否处于短线趋势强弱状态。

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
网格条件单辅助判断
```

注意：

```text
ShortTrendScore 不直接等于买入或卖出信号。
系统不得输出“必须买入”“必须清仓”“满仓”“梭哈”等绝对交易指令。
```

推荐输出：

```text
趋势较强
趋势转弱
短线过热
波动放大
不适合追涨
触发风控复核
适合继续观察
```

---

## 2. 适用范围

当前版本面向以下场内 ETF/LOF/基金类标的：

```text
宽基 ETF
行业 ETF
主题 ETF
跨境 / QDII ETF
商品 / 黄金 ETF
债券 ETF
货币 ETF
```

示例：

```text
宽基 ETF：沪深300ETF、中证500ETF、创业板ETF、科创50ETF、上证50ETF等
行业/主题 ETF：证券ETF、半导体ETF、芯片ETF、军工ETF、新能源ETF、医药ETF、消费ETF等
跨境/QDII ETF：纳指ETF、标普ETF、恒生科技ETF、中概互联ETF等
商品/黄金 ETF：黄金ETF、豆粕ETF、能源化工ETF等
债券/货币 ETF：国债ETF、政金债ETF、货币ETF、现金类ETF等
```

当前版本仍不覆盖：

```text
杠杆/反向 ETF
```

说明：

```text
商品/黄金、跨境/QDII、债券、货币 ETF 不应在自选池或分析 universe 中被过滤掉。
它们也可以计算 ShortTrendScore，但解释和仓位动作必须结合 ETF 类型分层处理。
例如跨境/QDII 需要额外注意海外市场时差、汇率、溢价和额度因素；商品/黄金需要额外注意商品价格、避险属性和宏观因子；债券/货币 ETF 的波动和流动性阈值不能照搬权益 ETF。
```

---

## 3. 算法定位

本算法是：

```text
ETF短线趋势评分 / ETF短线进攻评分
```

不是：

```text
ETF估值评分
ETF长期配置评分
ETF中期轮动主排序因子
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

这些指标对日级波动比较敏感，更适合判断短线状态，而不适合单独决定 ETF 中期轮动排名。

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

## 4. 使用指标

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

| 指标 | 作用 |
|---|---|
| MA | 判断短线趋势方向，是核心趋势因子 |
| VOL | 判断成交量是否确认趋势，是辅助确认因子 |
| BOLL | 判断价格所处强弱区间 |
| BIAS | 判断价格是否短线偏离过大 |
| RSI | 判断短线动能强弱 |
| ATR | 判断波动风险是否突然放大 |

---

## 5. 总分结构

最终总分为 `0 ~ 100`。

正向评分项如下：

| 模块 | 最高分 | 说明 |
|---|---:|---|
| MA_SCORE | 30 | 看 close / MA5 / MA10 / MA20 / MA5斜率 |
| VOL_SCORE | 15 | 看 vol_ratio_1_5 和 vol_ratio_5_20 |
| BOLL_SCORE | 20 | 看 boll_position |
| BIAS_SCORE | 10 | 看 bias5_ratio |
| RSI_SCORE | 15 | 看 rsi6 |
| 正向合计 | 90 | 正向指标最高只有 90 分 |

风险扣分项如下：

| 模块 | 最大扣分 | 说明 |
|---|---:|---|
| ATR_RISK_DEDUCT | 10 | 看 atr_expansion_ratio |

重要说明：

```text
MA_SCORE + VOL_SCORE + BOLL_SCORE + BIAS_SCORE + RSI_SCORE 的最高分是 90 分，不是 100 分。
因此必须先将正向得分归一化到 100 分制，再扣除 ATR 风险分。
```

---

## 6. 最终评分公式

### 6.1 正向原始分

```text
positiveRawScore =
MA_SCORE
+ VOL_SCORE
+ BOLL_SCORE
+ BIAS_SCORE
+ RSI_SCORE
```

取值范围：

```text
0 ~ 90
```

### 6.2 正向归一化分

```text
positiveNormalizedScore = positiveRawScore / 90 * 100
```

取值范围：

```text
0 ~ 100
```

### 6.3 扣除 ATR 风险分

```text
rawScore = positiveNormalizedScore - ATR_RISK_DEDUCT
```

### 6.4 最终得分

```text
ShortTrendScore = clamp(rawScore, 0, 100)
```

完整公式：

```text
ShortTrendScore = clamp(
  (MA_SCORE + VOL_SCORE + BOLL_SCORE + BIAS_SCORE + RSI_SCORE) / 90 * 100
  - ATR_RISK_DEDUCT,
  0,
  100
)
```

---

## 7. 输入数据要求

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

## 8. 指标计算

### 8.1 MA

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
MA10、MA20 用于防止单日反抽误判；
MA5_SLOPE_3 用于判断短线趋势是否正在增强。
```

---

### 8.2 VOL

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

说明：

```text
VOL_RATIO_1_5 用于判断今日是否明显放量；
VOL_RATIO_5_20 用于判断短期成交量中枢是否抬升。
```

---

### 8.3 BOLL

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
BOLL_POSITION 越接近 0，说明越靠近下轨；
对于宽基和行业 ETF，处于 0.60 ~ 0.90 通常代表短线偏强但尚未极端过热。
```

---

### 8.4 BIAS

计算：

```text
BIAS5 = (close - MA5) / MA5
```

说明：

```text
BIAS5 > 0 表示价格在 MA5 上方；
BIAS5 < 0 表示价格在 MA5 下方；
BIAS5 过高说明短线追高风险上升。
```

---

### 8.5 RSI

计算：

```text
RSI6
```

说明：

```text
RSI6 用于判断短线动能。
RSI6 不单独作为买卖依据，只用于趋势强弱和过热风险识别。
```

---

### 8.6 ATR

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
行业/主题 ETF 的 ATR 放大更常见，因此 ATR 只作为风险扣分项，不作为趋势加分项。
```

---

## 9. 分项评分规则

---

### 9.1 MA_SCORE，满分 30

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

### 9.2 VOL_SCORE，满分 15

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
但成交量容易受到套利交易、申赎、大资金调仓、市场整体活跃度等因素影响；
因此 VOL 更适合作为确认因子，不适合作为核心趋势因子。
```

---

### 9.3 BOLL_SCORE，满分 20

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

### 9.4 BIAS_SCORE，满分 10

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

### 9.5 RSI_SCORE，满分 15

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

### 9.6 ATR_RISK_DEDUCT，最多扣 10 分

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

## 10. 趋势等级

等级划分：

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

等级含义：

| 分数区间 | 等级 | 含义 |
|---:|---|---|
| `>= 85 且 ATR_RISK_DEDUCT = 0` | 强势进攻区 | 趋势、位置、动能、量能均较强，且波动未明显放大 |
| `>= 75` | 短线上升趋势 | 多头结构较明显，但可能存在局部过热、量能不足或波动放大 |
| `>= 60` | 震荡偏强 | 有一定强势特征，但趋势确认不足 |
| `>= 45` | 震荡观察 | 趋势不清晰，适合观察和复核 |
| `< 45` | 短线转弱 | 均线、动能或位置明显走弱，短线风险上升 |

重要说明：

```text
只有 ShortTrendScore >= 85 且 ATR_RISK_DEDUCT == 0 时，才允许标记为“强势进攻区”。
如果 ShortTrendScore >= 85 但 ATR_RISK_DEDUCT > 0，应降级为“短线上升趋势”，并输出 ATR 风险标签。
```

---

## 11. 趋势标签

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

宽基 ETF 和行业/主题 ETF 可共用上述标签。

行业/主题 ETF 的标签解释需要更谨慎：

```text
行业/主题 ETF 波动更大，出现“ATR波动放大”“放量急涨”“RSI短线过热”时，不应直接输出追涨结论。
```

---

## 12. 输出结构建议

```json
{
  "symbol": "510300",
  "name": "沪深300ETF",
  "etfType": "BROAD_BASED",
  "tradeDate": "2026-06-23",
  "shortTrendScore": 78.11,
  "trendLevel": "UPTREND",
  "trendName": "短线上升趋势",
  "dataSufficient": true,
  "scores": {
    "maScore": 25,
    "volScore": 12,
    "bollScore": 20,
    "biasScore": 8,
    "rsiScore": 10,
    "positiveRawScore": 75,
    "positiveNormalizedScore": 83.33,
    "atrRiskDeduct": 5.22,
    "shortTrendScore": 78.11
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

`etfType` 建议使用枚举：

```text
BROAD_BASED      宽基 ETF
INDUSTRY_THEME   行业/主题 ETF
CROSS_BORDER     跨境 / QDII ETF
COMMODITY_GOLD   商品 / 黄金 ETF
BOND             债券 ETF
MONEY            货币 / 现金类 ETF
```

---

## 13. 实现注意事项

### 13.1 数据排序

输入 K 线必须按交易日期升序排序。

```text
oldest -> newest
```

最后一条数据作为当前交易日。

---

### 13.2 缺失数据处理

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

### 13.3 除零保护

以下情况必须做保护：

```text
MA5 == 0
MA5_3_days_ago == 0
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

### 13.4 分数精度

建议：

```text
内部计算使用 double；
中间分数保留足够精度；
最终 ShortTrendScore 输出保留 2 位小数。
```

---

### 13.5 ATR 扣分必须在归一化之后执行

正确顺序：

```text
先计算 positiveRawScore
再计算 positiveNormalizedScore = positiveRawScore / 90 * 100
最后执行 ShortTrendScore = positiveNormalizedScore - ATR_RISK_DEDUCT
```

错误顺序：

```text
ShortTrendScore = MA_SCORE + VOL_SCORE + BOLL_SCORE + BIAS_SCORE + RSI_SCORE - ATR_RISK_DEDUCT
```

原因：

```text
正向指标合计最高只有 90 分，如果不归一化，会导致最高分只有 90 分，强势进攻区会过窄。
```

---

## 14. Java 伪代码

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
    // 11. 计算 positiveRawScore
    // 12. 计算 positiveNormalizedScore = positiveRawScore / 90.0 * 100.0
    // 13. 计算 shortTrendScore = clamp(positiveNormalizedScore - atrRiskDeduct, 0, 100)
    // 14. 生成 TrendLevel、TrendName、tags
    // 15. 返回 ShortTrendScoreResult
}
```

核心计算示例：

```java
double positiveRawScore = maScore + volScore + bollScore + biasScore + rsiScore;
double positiveNormalizedScore = positiveRawScore / 90.0 * 100.0;
double rawScore = positiveNormalizedScore - atrRiskDeduct;
double shortTrendScore = clamp(rawScore, 0.0, 100.0);
```

---

## 15. 使用建议

```text
ShortTrendScore >= 75:
    可进入短线趋势候选池

ShortTrendScore >= 85 and ATR_RISK_DEDUCT == 0:
    标记为强势进攻状态

ShortTrendScore >= 85 and ATR_RISK_DEDUCT > 0:
    不标记为强势进攻区，标记为短线上升趋势，并输出波动风险标签

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
适合继续观察
```

---

## 16. 与 ETF 轮动主模型的关系

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

说明：

```text
对于宽基 ETF，MomentumScore 更适合判断市场主线和指数强弱；
对于行业/主题 ETF，MomentumScore 更适合判断风格轮动和行业景气交易强弱；
对于商品/黄金 ETF，MomentumScore 需要结合商品价格和宏观因子解释；
对于跨境/QDII ETF，MomentumScore 需要结合海外市场、汇率和溢价解释；
ShortTrendScore 主要负责判断当前短线状态是否健康，不能作为过滤商品、黄金或 QDII 标的的理由。
```

---

## 17. 关键结论

1. 当前模型适合所有纳入 ETFMate universe 的场内 ETF/LOF/基金类标的做短线趋势评分，包括商品、黄金、跨境/QDII、债券和货币 ETF。
2. 商品、黄金、跨境/QDII、债券和货币 ETF 不得因类型被过滤；只是在解释、流动性阈值、仓位动作和风险提示上需要分层。
3. 正向指标 MA、VOL、BOLL、BIAS、RSI 合计最高只有 90 分，必须归一化到 100 分制。
4. 正确公式为：`ShortTrendScore = clamp(positiveRawScore / 90 * 100 - ATR_RISK_DEDUCT, 0, 100)`。
5. ATR 是风险扣分项，不是趋势加分项，且必须在正向分归一化之后扣除。
6. VOL 不建议给 25 分，建议控制在 15 分，作为趋势确认因子。
7. MA5 需要结合 MA10、MA20，否则容易把单日反抽误判为趋势转强。
8. BOLL 接近上轨不应直接视为卖点，应结合 RSI、BIAS、ATR 判断是否过热。
9. RSI6 超过 85 不建议直接归零，可降低分数并输出“RSI短线过热”标签。
10. 最终系统输出应是分析与风险提示，不应输出绝对买卖指令。
