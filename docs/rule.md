可以。下面这套规则适合 **A股 ETF 中低频决策**，目标是：**不预测涨跌，只做趋势、动量、风控、仓位再平衡**。A股/基金通常有涨跌幅限制，交易规则也要考虑 T+1，所以下面规则避免日内频繁交易。上交所规则里“股票和基金”涨跌幅通常按前收盘价 ±10% 计算；沪深港通资料也显示 SZSE-listed ETF 通常为 ±10%，部分深市 ETF 为 ±20%。([上海证券交易所][1])

## 1. 输出动作枚举

```text
BUY      新买入
ADD      已持仓，加仓
HOLD     继续持有
REDUCE   减仓
SELL     清仓
WATCH    观察，不操作
FORBID   禁止交易
```

## 2. 必要输入字段

### 行情数据

```json
{
  "code": "510300",
  "name": "沪深300ETF",
  "close": 3.85,
  "preClose": 3.80,
  "volume": 123456789,
  "amount": 560000000,
  "kline": [
    {"date": "2026-06-01", "open": 3.7, "high": 3.9, "low": 3.6, "close": 3.85, "amount": 560000000}
  ]
}
```

### 持仓数据

```json
{
  "code": "510300",
  "name": "沪深300ETF",
  "quantity": 10000,
  "costPrice": 3.6,
  "marketValue": 38500,
  "profitRate": 0.0694,
  "positionRatio": 0.25,
  "availableQuantity": 10000
}
```

### 同花顺自选 ETF 池

同花顺投资账本里的“自选”列表也是分析 universe。自选中可能包含已持仓、未持仓、股票、可转债、港股或其他标的，进入分析前必须过滤：

```text
自选 ETF 池主来源：
https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/ISUeEwK

持仓/交易/备注来源：
https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO
```

自选 ETF 池必须优先从自选 URL 采集；只有自选页没有解析出标的时，才允许使用持仓页缓存或 DOM 作为兜底来源。

```text
保留：
ETF
LOF
场内基金
REITs/场内基金类产品
商品 ETF
黄金 ETF
跨境 / QDII ETF
债券 ETF
货币 ETF

过滤：
A股股票
可转债
港股股票
其他非ETF/LOF/场内基金标的
```

识别优先级：

```text
1. 优先按场内基金代码段识别：15 / 16 / 50 / 51 / 52 / 56 / 58 开头。
2. 名称包含 ETF / LOF / 基金 / REIT 时作为辅助确认。
3. 名称包含 HK / 港股 / QDII / 纳指 / 标普 / 恒生科技等跨境特征，但代码是 A股场内基金段时，视为跨境 / QDII ETF，保留；如果是港股股票代码，过滤。
4. 11 / 12 / 123 / 127 / 128 等可转债代码段和名称含“转债/可转债”的标的直接过滤。
5. 名称包含黄金、商品、豆粕、能源化工等商品特征，但代码是 A股场内基金段时，视为商品 / 黄金 ETF，保留并进入分析。
```

未持仓但来自自选 ETF 池的标的也要生成行情快照、规则评分、AI 复核输入和报告建议。输出必须包含：

```text
来源：自选ETF池
当前状态：未持仓
建议：分批买入 / 观察 / 禁止交易
参考入场价：MA20、BOLL中轨、BOLL下轨或等待指标补齐
建仓比例：规则目标仓位；首笔不超过目标仓位约 1/3 或单格小仓位
```

缺少现金数据时，不假设现金充足，不给满仓建议。

## 3. 核心指标

每只 ETF 计算：

```text
MA5
MA10
MA20
MA60
MA120

RET5   = close / close_5_days_ago - 1
RET20  = close / close_20_days_ago - 1
RET60  = close / close_60_days_ago - 1

RSI14
ATR14
MAX_DRAWDOWN_60
AMOUNT_AVG20
VOLUME_RATIO = 今日成交额 / 20日平均成交额
```

## 4. 先做交易过滤

任何 ETF 满足下面条件，直接 `FORBID`：

```text
K线不足 120 日
最近20日平均成交额 < 5000万
当前价格 <= 0
今日涨幅 >= 9.5%    // 接近涨停，不追
今日跌幅 <= -9.5%   // 接近跌停，不接飞刀
停牌、无最新价、无成交额
```

如果你主要做宽基/行业/跨境 ETF，可以把成交额门槛设为：

```text
宽基ETF：2亿
行业ETF：8000万
主题ETF：5000万
商品/黄金/跨境/QDII/债券/货币ETF：纳入分析，但阈值和解释单独分层，不作为自选池过滤条件
```

## 5. 趋势评分 trendScore

```text
close > MA20       +20
MA20 > MA60        +20
MA60 > MA120       +20
MA20 斜率 > 0      +20
close > MA120      +20
```

满分 100。

判断：

```text
trendScore >= 80  强趋势
trendScore >= 60  中等趋势
trendScore >= 40  震荡
trendScore < 40   弱趋势
```

## 6. 动量评分 momentumScore

```text
RET20 > 0           +20
RET60 > 0           +20
RET20 排名进入前30% +25
RET60 排名进入前30% +25
今日未放量大跌       +10
```

其中“放量大跌”：

```text
今日涨跌幅 < -2%
且
VOLUME_RATIO > 1.5
```

满分 100。

## 7. 风险评分 riskScore

风险分越高越危险：

```text
RSI14 > 80                     +20
close 距离 MA20 偏离 > 8%       +20
MAX_DRAWDOWN_60 > 15%           +20
ATR14 / close > 3%              +20
连续3日下跌且累计跌幅 > 5%       +20
```

判断：

```text
riskScore >= 70 高风险
riskScore >= 40 中风险
riskScore < 40  低风险
```

## 8. 综合评分 totalScore

```text
totalScore = trendScore * 0.45
           + momentumScore * 0.35
           - riskScore * 0.20
```

建议：

```text
totalScore >= 70   可买/可加
50 ~ 70            持有/观察
30 ~ 50            减仓
< 30               卖出
```

## 9. 买入规则 BUY

未持仓时：

```text
IF
  trendScore >= 80
  AND momentumScore >= 70
  AND riskScore < 60
  AND close > MA20
  AND RET20 排名进入前30%
  AND 当前现金比例 > 15%
THEN BUY
```

买入仓位：

```text
基础仓位 = 10%

如果 totalScore >= 80，加到 15%
如果 riskScore >= 50，降到 5%
如果 close 距 MA20 > 8%，只 WATCH，不买
```

## 10. 加仓规则 ADD

已持仓时：

```text
IF
  当前持仓比例 < 目标仓位
  AND trendScore >= 80
  AND momentumScore >= 70
  AND close > MA20
  AND profitRate > -3%
  AND riskScore < 60
THEN ADD
```

加仓比例：

```text
每次加 5% ~ 10%
单只 ETF 最大仓位不超过 30%
同类 ETF 合计不超过 40%
```

## 11. 持有规则 HOLD

```text
IF
  close >= MA20
  AND trendScore >= 60
  AND totalScore >= 50
THEN HOLD
```

或者：

```text
IF
  close < MA20
  BUT close > MA60
  AND profitRate > 0
  AND riskScore < 60
THEN HOLD
```

## 12. 减仓规则 REDUCE

```text
IF
  close < MA20
  AND trendScore < 60
THEN REDUCE 30%
```

```text
IF
  profitRate > 15%
  AND RSI14 > 80
  AND close 距 MA20 > 10%
THEN REDUCE 20%   // 止盈减仓
```

```text
IF
  单只ETF仓位 > 30%
THEN REDUCE 到 25%
```

## 13. 清仓规则 SELL

```text
IF
  close < MA60
  AND MA20 < MA60
  AND trendScore < 40
THEN SELL
```

```text
IF
  profitRate <= -8%
  AND close < MA20
THEN SELL
```

```text
IF
  MAX_DRAWDOWN_60 > 20%
  AND close < MA60
THEN SELL
```

## 14. 仓位规则

组合总仓位：

```text
强趋势市场：ETF总仓位 70% ~ 90%
普通市场：ETF总仓位 40% ~ 70%
弱趋势市场：ETF总仓位 10% ~ 40%
```

单只限制：

```text
单只 ETF 最大 30%
单只 ETF 初始买入 5% ~ 10%
单次加仓最多 10%
单次减仓 20% ~ 50%
```

同类限制：

```text
沪深300 / 中证500 / 创业板 / 科创板：权益宽基
证券 / 半导体 / 医药 / 新能源：行业主题
纳指 / 标普 / 恒生科技：跨境
黄金 / 商品 / 债券 / 货币：防守资产
```

```text
同类 ETF 合计不超过 40%
主题 ETF 合计不超过 30%
跨境 ETF 合计不超过 40%
```

## 15. 最终决策优先级

按这个顺序执行：

```text
1. FORBID
2. SELL
3. REDUCE
4. ADD
5. BUY
6. HOLD
7. WATCH
```

也就是说：**风控优先于买入**。

## 16. 代码里的核心伪代码

```python
def decide(etf, position, portfolio):
    if is_forbidden(etf):
        return "FORBID"

    trend = calc_trend_score(etf)
    momentum = calc_momentum_score(etf)
    risk = calc_risk_score(etf)

    total = trend * 0.45 + momentum * 0.35 - risk * 0.20

    has_position = position is not None and position["marketValue"] > 0

    if has_position:
        if etf.close < etf.ma60 and etf.ma20 < etf.ma60 and trend < 40:
            return "SELL"

        if position["profitRate"] <= -0.08 and etf.close < etf.ma20:
            return "SELL"

        if etf.close < etf.ma20 and trend < 60:
            return "REDUCE"

        if position["profitRate"] > 0.15 and etf.rsi14 > 80 and deviation(etf.close, etf.ma20) > 0.10:
            return "REDUCE"

        if position["positionRatio"] < target_ratio(total, risk) and trend >= 80 and momentum >= 70 and risk < 60:
            return "ADD"

        return "HOLD"

    else:
        if trend >= 80 and momentum >= 70 and risk < 60 and portfolio["cashRatio"] > 0.15:
            if deviation(etf.close, etf.ma20) <= 0.08:
                return "BUY"
            else:
                return "WATCH"

        return "WATCH"
```

## 17. 建议你先用这套参数

```json
{
  "minKlineDays": 120,
  "minAmountAvg20": 50000000,
  "maxSinglePosition": 0.30,
  "maxCategoryPosition": 0.40,
  "initialBuyRatio": 0.10,
  "addRatio": 0.05,
  "stopLoss": -0.08,
  "takeProfit": 0.15,
  "maDeviationLimit": 0.08,
  "strongTrendScore": 80,
  "buyMomentumScore": 70,
  "maxBuyRiskScore": 60
}
```

这套规则最适合你当前阶段：**简单、可解释、低成本、可本地化、容易转成 Skill**。

## 18. ETFMate 落地优化

这份规则在 ETFMate 中不应作为唯一决策源，而应作为“规则引擎”的核心骨架。实际报告采用：

```text
真实采集数据 → 指标计算 → 交易过滤 → 趋势/动量/风险评分 → 仓位/网格约束 → 生成 AI 复核输入 → 宿主 AI 综合研判回写 → 报告展示
```

落地时做以下调整：

```text
1. ETF 类型分层：宽基、行业主题、跨境、商品、债券、货币 ETF 使用不同流动性和仓位阈值。
2. 可用数量优先：同花顺可用数量为 0 时，不输出可立即执行的减仓/卖出份额。
3. 清仓降级：宽基/防守类 ETF 的弱势信号优先降级为减仓或暂停买入侧，不机械清仓。
4. 网格独立约束：网格买入侧必须服从趋势、风险、仓位上限、Touker 最大持仓和流动性约束。
5. AI 只做复核：AI 综合研判只基于已采集证据解释冲突和降级动作，不绕过硬过滤，不编造未接入数据。
6. 不配置额外 API：ETFMate 作为 skill 运行时，直接使用 Codex/Claude Code/opencode 等宿主 AI 当前会话模型；本地 CLI 只生成 `ai_review_input.json` 并读取宿主写回的 `ai_judgements.json`。
7. 自选池扩展：同花顺自选 ETF 池中的未持仓标的进入同一套规则，但只能给保守的建仓/等待计划；报告必须展示来源、过滤口径、目标仓位和参考入场价。
```

AI 综合研判的输出应只包含：

```text
AI 动作倾向
置信度
与规则建议的冲突点
必须遵守的风控护栏
最终倾向：保持规则建议 / 降级为保守 / 需要人工确认
```

[1]: https://english.sse.com.cn/start/sserules/stocks/trading/c/10644064/files/7d100419dcca456b97cabaf2dfd3b904.pdf?utm_source=chatgpt.com "Trading Rules of Shanghai Stock Exchange (2023 Revision)"
