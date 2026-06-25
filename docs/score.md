# ETFMate 短线趋势评分算法设计文档（趋势纯净版）

## 1. 目标

本算法用于根据 ETF 的短线技术指标，计算统一的 `ShortTrendScore`，用于判断 ETF 当前的短线趋势强弱。

该评分适用于：

```text
1 ~ 5 个交易日级别的短线趋势判断
```

主要用途：

```text
短线趋势识别
持仓状态诊断
ETF候选池过滤
仓位动作输入
AI分析解释
```

注意：

```text
ShortTrendScore 不直接等于买入或卖出信号。
系统不得输出“必须买入”“必须清仓”“满仓”“梭哈”等绝对化交易指令。
```

推荐输出：

```text
趋势较强
趋势转弱
短线偏热
短线量能不足
不适合追高
适合继续观察
```

---

## 2. 适用范围

当前版本只面向：

```text
宽基 ETF
行业 ETF
主题 ETF
```

示例：

```text
宽基 ETF：沪深300ETF、中证500ETF、创业板ETF、科创50ETF、上证50ETF等
行业/主题 ETF：证券ETF、半导体ETF、芯片ETF、军工ETF、新能源ETF、医药ETF、消费ETF等
```

当前版本不覆盖：

```text
债券 ETF
货币 ETF
商品 / 黄金 ETF
跨境 / QDII ETF
杠杆 / 反向 ETF
REITs
```

说明：

```text
上述不覆盖品种并非不能分析，而是不应直接复用本趋势评分模型。
如果后续纳入跨境、商品、债券或货币类 ETF，应单独设计评分解释、流动性阈值和仓位动作规则。
```

---

## 3. 算法定位

本算法是：

```text
ETF短线趋势评分
```

不是：

```text
ETF估值评分
ETF长期配置评分
ETF中期轮动主排序因子
ETF网格间距模型
```

原因：

本算法使用短周期指标：

```text
MA5
MA10
MA20
RSI6
BIAS5
BOLL20
今日成交量
```

这些指标对日级波动比较敏感，适合判断当前短线趋势是否健康，但不适合单独判断中长期配置价值。

---

## 4. 重要边界：ATR 不进入趋势评分

本版 `ShortTrendScore` 不使用 ATR。

原因：

```text
ATR 衡量的是波动幅度，不衡量趋势方向。
ATR 放大可能来自强势突破，也可能来自高位剧烈波动或下跌加速。
因此 ATR 不应直接扣减趋势评分。
```

ATR 应进入独立模块：

```text
网格间距建议
网格调宽/调窄
波动风险提示
条件单参数调整
```

本文件中不再出现：

```text
ATR_RISK_DEDUCT
ATR_EXPANSION_RATIO
positiveRawScore / 90 * 100
ShortTrendScore - ATR_RISK_DEDUCT
```

---

## 5. 使用指标

本算法只使用以下指标：

```text
MA
VOL
BOLL
BIAS
RSI
```

各指标作用：

| 指标 | 作用 |
|---|---|
| MA | 判断短线趋势方向，是核心趋势因子 |
| BOLL | 判断价格所处强弱区间 |
| VOL | 判断成交量是否确认趋势 |
| RSI | 判断短线动能强弱 |
| BIAS | 判断价格是否短线偏离过大 |

---

## 6. 总分结构

最终总分为 `0 ~ 100`。

权重如下：

| 模块 | 最高分 | 说明 |
|---|---:|---|
| MA_SCORE | 35 | 看 close / MA5 / MA10 / MA20 / MA5斜率 |
| BOLL_SCORE | 20 | 看 boll_position |
| VOL_SCORE | 15 | 看 vol_ratio_1_5 和 vol_ratio_5_20 |
| RSI_SCORE | 20 | 看 rsi6 |
| BIAS_SCORE | 10 | 看 bias5_ratio |
| 合计 | 100 | 五项正向指标合计 100 分 |

说明：

```text
MA 是主趋势因子；
BOLL 和 RSI 是位置与动能确认；
VOL 是趋势有效性确认；
BIAS 是短线偏离修正。
```

---

## 7. 最终评分公式

```text
ShortTrendScore =
clamp(
  MA_SCORE
  + BOLL_SCORE
  + VOL_SCORE
  + RSI_SCORE
  + BIAS_SCORE,
  0,
  100
)
```

不需要归一化。

原因：

```text
五个正向指标最高分已经严格等于 100 分。
```

---

## 8. 输入数据要求

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

## 9. 指标计算

### 9.1 MA

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

### 9.2 VOL

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

### 9.3 BOLL

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
对于宽基和行业/主题 ETF，0.60 ~ 0.90 通常代表短线偏强但尚未极端过热。
```

---

### 9.4 BIAS

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

### 9.5 RSI

计算：

```text
RSI6
```

说明：

```text
RSI6 用于判断短线动能。
RSI6 不单独作为买卖依据，只用于趋势强弱和短线过热识别。
```

---

## 10. 分项评分规则

### 10.1 MA_SCORE，满分 35

评分规则：

```text
if close > MA5 and MA5 > MA10 and MA10 > MA20 and MA5_SLOPE_3 > 0:
    MA_SCORE = 35
else if close > MA5 and MA5 > MA10 and MA5_SLOPE_3 > 0:
    MA_SCORE = 30
else if close > MA5 and MA5_SLOPE_3 > 0:
    MA_SCORE = 22
else if close > MA5:
    MA_SCORE = 15
else if close < MA5 and MA5 < MA10:
    MA_SCORE = 0
else:
    MA_SCORE = 8
```

解释：

```text
价格站上 MA5 代表短线转强；
MA5 > MA10 > MA20 代表短线均线多头；
MA5 斜率向上代表趋势正在增强；
仅价格站上 MA5 但均线未确认时，不给高分。
```

---

### 10.2 BOLL_SCORE，满分 20

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
接近上轨不直接视为卖点，但需要结合 RSI、BIAS 和量能标签判断是否短线偏热。
```

---

### 10.3 VOL_SCORE，满分 15

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
因此 VOL 作为确认因子，不作为核心趋势因子。
```

---

### 10.4 RSI_SCORE，满分 20

评分规则：

```text
if RSI6 > 50 and RSI6 <= 75:
    RSI_SCORE = 20
else if RSI6 > 75 and RSI6 <= 85:
    RSI_SCORE = 14
else if RSI6 > 85:
    RSI_SCORE = 8
else if RSI6 >= 40 and RSI6 <= 50:
    RSI_SCORE = 10
else:
    RSI_SCORE = 3
```

解释：

```text
RSI6 在 50~75 之间代表短线多头动能健康；
RSI6 在 75~85 之间代表动能强但偏热；
RSI6 超过 85 代表短线过热，不直接归零，但应输出“RSI短线过热”标签；
RSI6 低于 40，说明短线动能较弱。
```

---

### 10.5 BIAS_SCORE，满分 10

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

## 11. 趋势等级

等级划分：

```text
if ShortTrendScore >= 85:
    TrendLevel = "STRONG_TREND"
    TrendName = "短线强趋势"
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
| `>= 85` | 短线强趋势 | 均线结构、价格位置、动能和量能整体较强 |
| `>= 75` | 短线上升趋势 | 多头结构较明显，但可能存在局部追高或量能不足 |
| `>= 60` | 震荡偏强 | 有一定强势特征，但趋势确认不足 |
| `>= 45` | 震荡观察 | 趋势不清晰，适合观察和复核 |
| `< 45` | 短线转弱 | 均线、动能或位置明显走弱 |

说明：

```text
本模型不再使用“强势进攻区”。
“进攻”属于仓位动作或交易执行层概念，应由 action.md 或 grid.md 综合判断。
```

---

## 12. 趋势标签

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

禁止在本文件输出：

```text
ATR波动放大
ATR风险扣分
波动剧烈放大
```

这些标签应进入网格或独立波动模块。

---

## 13. 输出结构建议

```json
{
  "symbol": "510300",
  "name": "沪深300ETF",
  "etfType": "BROAD_BASED",
  "tradeDate": "2026-06-25",
  "shortTrendScore": 82.0,
  "trendLevel": "UPTREND",
  "trendName": "短线上升趋势",
  "dataSufficient": true,
  "scores": {
    "maScore": 30,
    "bollScore": 20,
    "volScore": 12,
    "rsiScore": 14,
    "biasScore": 6,
    "shortTrendScore": 82.0
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
    "rsi6": 76.3
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
```

---

## 14. 实现注意事项

### 14.1 数据排序

输入 K 线必须按交易日期升序排序。

```text
oldest -> newest
```

最后一条数据作为当前交易日。

---

### 14.2 缺失数据处理

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
VOL5
VOL20
```

则返回：

```text
dataSufficient = false
```

---

### 14.3 除零保护

以下情况必须做保护：

```text
MA5 == 0
MA5_3_days_ago == 0
VOL5 == 0
VOL20 == 0
BOLL_UPPER == BOLL_LOWER
close == 0
```

出现除零风险时：

```text
对应指标返回 null
对应分数返回 0
```

---

### 14.4 分数精度

建议：

```text
内部计算使用 double；
最终 ShortTrendScore 输出保留 2 位小数。
```

---

## 15. Java 伪代码

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
    // 9. 分别计算 MA_SCORE、BOLL_SCORE、VOL_SCORE、RSI_SCORE、BIAS_SCORE
    // 10. 计算 shortTrendScore = clamp(maScore + bollScore + volScore + rsiScore + biasScore, 0, 100)
    // 11. 生成 TrendLevel、TrendName、tags
    // 12. 返回 ShortTrendScoreResult
}
```

核心计算示例：

```java
double rawScore = maScore + bollScore + volScore + rsiScore + biasScore;
double shortTrendScore = clamp(rawScore, 0.0, 100.0);
```

---

## 16. 使用建议

```text
ShortTrendScore >= 75:
    可进入短线趋势候选池

ShortTrendScore >= 85:
    标记为短线强趋势

ShortTrendScore < 60:
    不进入短线强趋势候选池

ShortTrendScore < 45:
    触发趋势复核或持仓复核提示
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
短线偏热
不适合追高
触发趋势复核
适合继续观察
```

---

## 17. 与 ETF 轮动主模型的关系

该算法不是 ETF 轮动主排序因子。

推荐 ETFMate 使用双评分体系：

```text
MomentumScore：决定哪个 ETF 更强，适合中期轮动排序
ShortTrendScore：判断当前短线趋势是否健康
```

最终排序可以在轮动模块中另行定义，例如：

```text
FinalScore = 0.7 * MomentumScore + 0.3 * ShortTrendScore
```

但该组合公式不属于本文件的趋势评分计算范围。

---

## 18. 关键结论

1. 本模型只适用于宽基 ETF、行业 ETF、主题 ETF 的短线趋势评分。
2. `ShortTrendScore` 只由 MA、BOLL、VOL、RSI、BIAS 五项构成。
3. 五项正向指标合计 100 分，不需要 `/90 * 100` 归一化。
4. ATR 不进入趋势评分，不生成 ATR 扣分，也不影响趋势等级。
5. ATR 应迁移到网格建议或独立波动模块。
6. 趋势等级不再使用“强势进攻区”，改为“短线强趋势”。
7. 系统输出应是分析与风险提示，不应输出绝对买卖指令。

