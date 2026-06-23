# ETFMate 实时 ETF 投资报告评价与 Python 优化方案

## 1. 背景

当前报告名称为“实时 ETF 持仓与网格分析”，报告生成时间为 2026-06-23 14:45:08。

报告覆盖内容包括：

* 同花顺持仓：16 只
* Touker 网格：16 个
* 自选 ETF 池：2 只
* 全部分析标的：17 只
* 当前总仓位：64.81%
* Top3 仓位：22.62%
* 最大单一 ETF 仓位：8.21%
* 报告结论分类：

  * 持有：12 只
  * 观察/等待：1 只
  * 减仓：3 只
  * 风控复核：1 只
* 网格建议：

  * 降买：9 只
  * 维持：7 只
  * 无网格：1 只
* 交易复盘：

  * 近 30 日交易 125 笔
  * 报告提示交易笔数偏多，需要检查手续费和策略偏离

本优化方案面向 Python 代码实现，目标是提升报告的金融逻辑一致性、风险控制能力、可解释性、代码可维护性和后续回测能力。

---

## 2. 总体评价

### 2.1 优点

当前报告已经具备较好的个人 ETF 持仓诊断雏形，尤其适合“ETF 持仓 + 网格条件单 + 技术趋势评分”的半自动化复盘场景。

主要优点如下：

1. **数据维度较完整**

   报告已经整合了：

   * 同花顺持仓
   * 同花顺自选 ETF 池
   * Touker 网格配置
   * 实时行情
   * K 线数据
   * 交易记录
   * 七层证据
   * AI 综合研判占位

   这说明系统已经具备从“数据采集”到“策略判断”再到“报告输出”的基本闭环。

2. **技术指标体系较丰富**

   单只 ETF 分析中包含：

   * MA 均线
   * BOLL 布林带
   * VOL 成交量
   * ATR 波动率
   * BIAS 乖离率
   * RSI 相对强弱
   * MACD 动能
   * 中期动量
   * 风险评分

   这些指标可以覆盖短线趋势、波动风险、超买超卖和网格间距校准。

3. **有初步风险约束**

   报告已经识别：

   * 低成交额标的限制新增买入
   * RSI 短线过热避免追高
   * 跌破 MA5、MA20、MA60 等趋势转弱信号
   * 高风险标的触发风控复核
   * 网格买入数量需要降速
   * 当前持仓很小时，买卖数量不应明显超过现有持仓

4. **报告有数据完整性披露**

   报告在末尾披露了数据来源、采集完整性、七层证据接入进度和 AI 研判启用情况。这一点非常重要，有助于避免伪精确和过度决策。

5. **网格参数和技术指标已开始联动**

   报告不是单独输出技术评分，而是尝试把 ATR 波动率、BOLL 位置、买卖触发比例、买卖数量结合起来。这是网格策略优化的正确方向。

---

## 3. 核心问题

### 3.1 规则结论、目标仓位、执行动作之间存在冲突

这是当前报告最需要优先修复的问题。

例如部分标的出现以下情况：

* 趋势评分很低
* 风险等级为 HIGH
* 目标仓位为 0%
* 但最终动作仍为“持有”
* 原因是“目标仓位与当前仓位差小于 5%，不做频繁微调”

这种逻辑会导致一个问题：

> 当系统已经判断目标仓位为 0%，且风险等级为 HIGH 时，不应该再简单因为仓位差小于阈值而维持持有，至少应进入“减仓候选”或“风控复核”。

建议将“微调阈值”逻辑放到最后，但不能覆盖高风险规则。

错误逻辑示例：

```text
目标仓位 = 0%
当前仓位 = 3.36%
差值 < 5%
所以继续 HOLD
```

建议修正为：

```text
如果 risk_level == HIGH 且 target_weight == 0:
    action = RISK_REVIEW 或 REDUCE
    不允许被 min_adjust_threshold 覆盖
```

---

### 3.2 目标仓位过高，缺少组合层面的仓位预算约束

报告中多只 ETF 的基础目标仓位出现 10%、25%、40% 等值。

问题在于：

* 当前组合已经有 16 只持仓
* 总仓位已经 64.81%
* 多个行业主题 ETF 同时给出较高目标仓位
* 没看到组合层面的最大总仓位、单主题上限、相关性上限、行业集中度上限

如果每只 ETF 独立计算目标仓位，很容易出现“单标的看起来合理，组合层面过度暴露”的问题。

建议新增组合级约束：

```yaml
portfolio_risk_limits:
  max_total_position: 0.70
  max_single_etf_weight: 0.08
  max_theme_weight: 0.15
  max_high_risk_weight: 0.10
  max_same_index_family_weight: 0.12
  min_cash_buffer: 0.30
```

目标仓位必须经过组合约束二次压缩。

---

### 3.3 加仓逻辑表达不清，HOLD_OR_ADD 容易误导

当前报告中有些 ETF 显示：

* 仓位动作：HOLD_OR_ADD / 持有观察
* 目标仓位高于当前仓位
* 但加仓确认条件不足
* 执行计划又写“先持有，等待回踩或量能/ATR确认”

这会造成用户理解困难：

> 到底是可以加仓，还是不能加仓？

建议拆分动作枚举：

```python
class Action(Enum):
    WATCH = "观察"
    HOLD = "持有"
    HOLD_WAIT_ADD = "持有，等待加仓确认"
    ADD_SMALL = "小额试探"
    ADD_STEP = "分步加仓"
    REDUCE = "减仓"
    RISK_REVIEW = "风控复核"
    STOP_BUY = "暂停买入"
```

不要再使用模糊的 `HOLD_OR_ADD`。

---

### 3.4 AI 研判模块目前大多是占位信息，降低报告可信度

报告中大量出现：

```text
AI：待宿主AI复核
置信度：0%
最终倾向：保持规则建议
研判：宿主 AI 研判基于旧规则，需按最新规则重新复核
```

如果 AI 模块没有真正参与判断，不建议在每只 ETF 明细中大段展示。

建议：

* AI 未启用时，只显示一行：

  * `AI复核：未启用，本次完全采用规则引擎`
* AI 启用但置信度低时，只显示：

  * `AI复核：低置信度，仅作备注，不改变动作`
* AI 启用且置信度达标时，才进入详细展示

建议规则：

```python
if ai_enabled is False:
    ai_block.visible = False
elif ai_confidence < 0.6:
    ai_block.mode = "summary_only"
else:
    ai_block.mode = "full"
```

---

### 3.5 七层证据平均置信度较低，但报告仍输出较明确动作

报告披露七层证据平均置信度约 25%，同时多处提示缺少：

* 研报预期层
* 热点信号层
* 新闻舆情层
* 基础数据层
* 公告事件层

在证据不足的情况下，建议动作强度应系统性降级。

例如：

```python
if evidence_confidence < 0.3:
    allow_add = False
    max_action_strength = "HOLD"
    report_warning.append("证据置信度不足，禁止主动加仓")
```

建议动作强度分层：

| 证据置信度     | 允许动作             |
| --------- | ---------------- |
| < 30%     | 仅允许观察、持有、减仓、风控复核 |
| 30% - 60% | 允许小额试探，不允许扩大仓位   |
| 60% - 80% | 允许分步加仓           |
| > 80%     | 可执行正常策略动作        |

---

### 3.6 网格建议和持仓动作之间需要更强联动

当前报告中存在：

* 持仓动作：持有
* 网格动作：降低买
* 风险等级：HIGH
* 目标仓位：0%
* 但仍保留买触发

对于趋势明显转弱、目标仓位为 0%、风险等级 HIGH 的 ETF，建议网格买入不只是“降低买”，而应明确进入：

* 暂停买入
* 仅保留卖出
* 或人工确认是否关闭买触发

建议网格动作枚举：

```python
class GridAction(Enum):
    KEEP = "维持"
    LOWER_BUY = "降低买入"
    PAUSE_BUY = "暂停买入"
    SELL_ONLY = "只保留卖出"
    TIGHTEN_SELL = "卖出更积极"
    DISABLE_GRID = "建议关闭网格"
    MANUAL_REVIEW = "人工复核"
```

建议规则：

```python
if risk_level == "HIGH" and target_weight == 0:
    grid_action = GridAction.SELL_ONLY

if price_below_ma20 and price_below_ma60 and trend_score < 30:
    grid_action = GridAction.PAUSE_BUY

if unrealized_pnl < -0.10 and trend_score < 30:
    grid_action = GridAction.MANUAL_REVIEW
```

---

### 3.7 交易复盘模块太粗，需要从“笔数多”升级为“策略质量评估”

当前报告已经提示近 30 日交易 125 笔，交易笔数偏多。

但现在还缺少以下关键指标：

* 单笔平均收益
* 单笔平均手续费
* 手续费 / 毛收益比例
* 网格成交胜率
* 买入后 N 日收益
* 卖出后 N 日是否继续上涨
* 是否频繁低效交易
* 是否出现越跌越买导致仓位过高
* 是否出现小额交易过多但收益不足

建议新增交易质量指标：

```python
@dataclass
class TradeReviewMetrics:
    period: str
    trade_count: int
    buy_amount: float
    sell_amount: float
    fee: float
    realized_pnl: float | None
    avg_trade_amount: float
    fee_to_turnover_ratio: float
    estimated_grid_profit: float | None
    ineffective_trade_count: int
    overtrading_flag: bool
```

建议增加判断：

```python
if trade_count_30d > 80:
    warning.append("近30日交易笔数过多，建议降低网格频率")

if avg_trade_amount < 500:
    warning.append("单笔金额过小，手续费和滑点可能侵蚀收益")

if fee_to_turnover_ratio > 0.001:
    warning.append("手续费占成交额比例偏高")
```

---

## 4. 金融逻辑优化方案

### 4.1 建立三层决策架构

建议把当前单只 ETF 决策拆成三层：

```text
第一层：标的层评分
    趋势、动量、波动、成交额、技术位置、证据置信度

第二层：组合层约束
    总仓位、主题集中度、相关性、单标的上限、高风险资产上限

第三层：执行层动作
    是否加仓、是否减仓、是否暂停网格买入、是否只卖不买、是否人工复核
```

对应 Python 模块：

```text
etfmate/
  analysis/
    indicator_engine.py
    score_engine.py
    decision_engine.py
    portfolio_risk_engine.py
    grid_engine.py
    trade_review_engine.py
  report/
    markdown_renderer.py
    html_renderer.py
  models/
    etf.py
    position.py
    grid.py
    decision.py
    portfolio.py
  config/
    risk_limits.yaml
    score_rules.yaml
  tests/
    test_decision_engine.py
    test_grid_engine.py
    test_portfolio_risk_engine.py
```

---

### 4.2 优化单只 ETF 评分体系

当前评分主要偏短线趋势，建议调整为：

```text
总分 = 趋势分 * 35%
     + 动量分 * 20%
     + 波动风险分 * 15%
     + 流动性分 * 10%
     + 估值/宏观适配分 * 10%
     + 证据置信度分 * 10%
```

建议不要只依赖 MA、BOLL、RSI、BIAS。

ETF 尤其需要考虑：

* 跟踪指数类型
* 行业主题景气度
* 宽基 / 行业 / 主题 / 跨境 / 商品属性
* 成交额和流动性
* 跟踪误差
* 规模
* 费率
* 同主题重复持仓
* 宏观因子敏感度

建议 ETF 类型权重不同：

```yaml
etf_type_weights:
  broad_index:
    trend: 0.30
    momentum: 0.20
    volatility: 0.15
    liquidity: 0.15
    macro: 0.10
    evidence: 0.10

  sector_theme:
    trend: 0.35
    momentum: 0.20
    volatility: 0.15
    liquidity: 0.10
    macro: 0.10
    evidence: 0.10

  commodity:
    trend: 0.30
    momentum: 0.15
    volatility: 0.20
    liquidity: 0.10
    macro: 0.15
    evidence: 0.10

  cross_border:
    trend: 0.25
    momentum: 0.20
    volatility: 0.15
    liquidity: 0.10
    fx_macro: 0.20
    evidence: 0.10
```

---

### 4.3 引入组合相关性和主题去重

当前报告已经提示部分同主题 ETF 可能重合，例如人工智能 ETF 和科创创业 ETF 之间可能存在较高持仓重合。

建议增加 ETF 归类：

```yaml
theme_groups:
  ai_semiconductor:
    - 159141
    - 159516
    - 515230
    - 159781
    - 562950

  new_energy_power:
    - 159326
    - 159566

  precious_metal:
    - 518880

  broad_index:
    - 510500

  overseas:
    - 159687
    - 513120
```

组合层限制：

```python
if theme_weight > max_theme_weight:
    suppress_add = True
    reason.append("同主题 ETF 仓位过高，禁止继续加仓")
```

同主题 ETF 选择优先级：

```text
1. 流动性更好
2. 跟踪误差更低
3. 费率更低
4. 趋势评分更高
5. 当前亏损压力更低
6. 与已有持仓相关性更低
```

---

### 4.4 优化目标仓位计算

当前目标仓位容易偏高，建议采用“基础仓位 × 多因子折扣”的方式。

```python
target_weight = base_weight
target_weight *= trend_multiplier
target_weight *= risk_multiplier
target_weight *= liquidity_multiplier
target_weight *= evidence_multiplier
target_weight *= portfolio_multiplier
```

示例：

```python
def calc_target_weight(etf, portfolio):
    base = get_base_weight(etf.etf_type)

    trend_multiplier = get_trend_multiplier(etf.trend_score)
    risk_multiplier = get_risk_multiplier(etf.risk_level)
    liquidity_multiplier = get_liquidity_multiplier(etf.avg_amount_20d)
    evidence_multiplier = get_evidence_multiplier(etf.evidence_confidence)
    portfolio_multiplier = get_portfolio_multiplier(etf, portfolio)

    target = (
        base
        * trend_multiplier
        * risk_multiplier
        * liquidity_multiplier
        * evidence_multiplier
        * portfolio_multiplier
    )

    return clamp(target, 0, get_single_etf_cap(etf))
```

建议基础仓位：

```yaml
base_weight:
  broad_index: 0.10
  sector_theme: 0.05
  narrow_theme: 0.03
  commodity: 0.05
  cross_border: 0.04
```

建议单标的上限：

```yaml
single_etf_cap:
  broad_index: 0.12
  sector_theme: 0.08
  narrow_theme: 0.05
  commodity: 0.08
  cross_border: 0.06
```

---

### 4.5 优化减仓规则

当前部分标的目标仓位为 0，但因为微调阈值而没有输出减仓。建议新增强制风控规则。

```python
def force_risk_action(etf):
    if etf.risk_level == "HIGH" and etf.target_weight == 0:
        return "RISK_REVIEW"

    if etf.trend_score < 30 and etf.current_weight > 0.03:
        return "REDUCE"

    if etf.price_below_ma20 and etf.price_below_ma60 and etf.current_weight > 0.02:
        return "REDUCE"

    if etf.unrealized_pnl < -0.10 and etf.trend_score < 35:
        return "RISK_REVIEW"

    return None
```

减仓数量建议：

```python
def calc_reduce_amount(position, target_weight, portfolio_value, lot_size=100):
    target_value = portfolio_value * target_weight
    reduce_value = max(0, position.market_value - target_value)
    raw_shares = reduce_value / position.price

    shares = int(raw_shares // lot_size) * lot_size

    return min(shares, position.shares)
```

---

### 4.6 优化加仓规则

建议加仓必须同时满足：

```text
1. 趋势评分 >= 65
2. 风险等级不是 HIGH
3. 证据置信度 >= 30%
4. 未接近 BOLL 上轨
5. RSI6 不处于明显过热区
6. 当前价格没有显著远离 MA20
7. 组合总仓位未超过上限
8. 同主题仓位未超过上限
9. 近 30 日交易频率没有过高
```

建议规则：

```python
def can_add(etf, portfolio):
    checks = []

    checks.append(etf.trend_score >= 65)
    checks.append(etf.risk_level != "HIGH")
    checks.append(etf.evidence_confidence >= 0.30)
    checks.append(etf.boll_position < 0.85)
    checks.append(etf.rsi6 < 80)
    checks.append(abs(etf.price / etf.ma20 - 1) < 0.08)
    checks.append(portfolio.total_position < portfolio.max_total_position)
    checks.append(portfolio.theme_weight(etf.theme) < portfolio.max_theme_weight)
    checks.append(portfolio.trade_count_30d < portfolio.max_trade_count_30d)

    return all(checks)
```

加仓动作分层：

```python
if can_add(etf, portfolio):
    if etf.evidence_confidence >= 0.6 and etf.trend_score >= 75:
        action = "ADD_STEP"
    else:
        action = "ADD_SMALL"
else:
    action = "HOLD_WAIT_ADD"
```

---

## 5. 报告结构优化方案

### 5.1 首页需要增加组合级结论

建议首页新增：

```markdown
## 组合总览

- 当前总仓位：
- 现金缓冲：
- 单标的最大仓位：
- Top3 仓位：
- 高风险标的仓位：
- 同主题集中度最高：
- 本次建议：
  - 可加仓：
  - 仅持有：
  - 建议减仓：
  - 风控复核：
  - 暂停买入：
- 今日最重要风险：
- 今日不建议执行的动作：
```

---

### 5.2 增加“今日优先处理事项”

建议把报告从“罗列所有标的”改成“先处理最重要问题”。

```markdown
## 今日优先处理事项

### P0：必须人工复核
- 风控复核标的
- 高风险但仍有网格买入的标的
- 目标仓位为 0 但仍持仓的标的

### P1：需要调网格
- 买触发比例明显小于 ATR 建议值
- 卖触发比例过宽
- 买入数量明显大于当前合理仓位

### P2：继续观察
- 趋势评分 50-65
- 加仓条件不足
- 证据置信度不足
```

---

### 5.3 每只 ETF 输出应压缩为三段

当前单只 ETF 内容较长，建议压缩为：

```markdown
### 159141 科创创业人工智能ETF永赢

#### 结论
- 动作：持有 / 暂停新增买入
- 风险等级：LOW
- 当前仓位：8.21%
- 目标仓位：8.21%
- 网格：降低买入
- 置信度：30%

#### 关键证据
- 趋势：站上 MA20/MA60，短线偏强
- 风险：20 日成交额低于门槛，限制新增买入
- 位置：BOLL 分位偏高，不宜追价
- 组合：与同主题 ETF 可能重合

#### 执行建议
- 不主动加仓
- 网格买入数量降至建议值
- 跌破 MA20 转谨慎
- 接近 BOLL 上轨时优先卖出
```

---

## 6. Python 代码改造建议

### 6.1 建议目录结构

```text
etfmate/
  __init__.py

  config/
    risk_limits.yaml
    score_rules.yaml
    grid_rules.yaml
    theme_groups.yaml

  data/
    providers/
      ths_provider.py
      touker_provider.py
      quote_provider.py
      kline_provider.py

  models/
    etf.py
    position.py
    grid.py
    indicator.py
    decision.py
    portfolio.py
    trade.py
    report.py

  engines/
    indicator_engine.py
    score_engine.py
    evidence_engine.py
    decision_engine.py
    portfolio_risk_engine.py
    grid_engine.py
    trade_review_engine.py

  reports/
    markdown_renderer.py
    html_renderer.py
    json_renderer.py

  tests/
    test_score_engine.py
    test_decision_engine.py
    test_grid_engine.py
    test_portfolio_risk_engine.py
    test_trade_review_engine.py
```

---

### 6.2 核心数据模型

```python
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Action(Enum):
    WATCH = "WATCH"
    HOLD = "HOLD"
    HOLD_WAIT_ADD = "HOLD_WAIT_ADD"
    ADD_SMALL = "ADD_SMALL"
    ADD_STEP = "ADD_STEP"
    REDUCE = "REDUCE"
    RISK_REVIEW = "RISK_REVIEW"
    STOP_BUY = "STOP_BUY"


class RiskLevel(Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class GridAction(Enum):
    KEEP = "KEEP"
    LOWER_BUY = "LOWER_BUY"
    PAUSE_BUY = "PAUSE_BUY"
    SELL_ONLY = "SELL_ONLY"
    TIGHTEN_SELL = "TIGHTEN_SELL"
    MANUAL_REVIEW = "MANUAL_REVIEW"


@dataclass
class ETFMetrics:
    code: str
    name: str
    etf_type: str
    theme: str

    price: float
    ma5: Optional[float]
    ma10: Optional[float]
    ma20: Optional[float]
    ma60: Optional[float]
    ma200: Optional[float]

    boll_upper: Optional[float]
    boll_middle: Optional[float]
    boll_lower: Optional[float]
    boll_position: Optional[float]

    rsi6: Optional[float]
    rsi14: Optional[float]
    bias6: Optional[float]
    bias12: Optional[float]
    bias24: Optional[float]
    atr14: Optional[float]
    atr30: Optional[float]

    volume_ratio: Optional[float]
    avg_amount_20d: Optional[float]
    evidence_confidence: float


@dataclass
class Position:
    code: str
    shares: int
    cost: float
    market_value: float
    weight: float
    unrealized_pnl_pct: float


@dataclass
class ETFDecision:
    code: str
    action: Action
    risk_level: RiskLevel
    grid_action: GridAction
    current_weight: float
    target_weight: float
    adjusted_weight: float
    trend_score: float
    evidence_confidence: float
    reasons: list[str]
    warnings: list[str]
```

---

### 6.3 决策引擎建议流程

```python
def make_decision(etf, position, portfolio, config):
    indicators = calc_indicators(etf)
    score = calc_score(etf, indicators, config.score_rules)

    risk_level = calc_risk_level(etf, indicators, score)
    raw_target_weight = calc_raw_target_weight(etf, score, risk_level, config)
    target_weight = apply_portfolio_constraints(
        etf=etf,
        position=position,
        portfolio=portfolio,
        raw_target_weight=raw_target_weight,
        config=config,
    )

    forced_action = check_force_risk_action(
        etf=etf,
        position=position,
        score=score,
        risk_level=risk_level,
        target_weight=target_weight,
    )

    if forced_action:
        action = forced_action
    else:
        action = decide_normal_action(
            etf=etf,
            position=position,
            portfolio=portfolio,
            score=score,
            risk_level=risk_level,
            target_weight=target_weight,
        )

    grid_action = decide_grid_action(
        etf=etf,
        position=position,
        action=action,
        risk_level=risk_level,
        target_weight=target_weight,
        config=config,
    )

    return ETFDecision(
        code=etf.code,
        action=action,
        risk_level=risk_level,
        grid_action=grid_action,
        current_weight=position.weight if position else 0,
        target_weight=target_weight,
        adjusted_weight=calc_adjusted_weight(position, target_weight),
        trend_score=score.trend_score,
        evidence_confidence=etf.evidence_confidence,
        reasons=build_reasons(...),
        warnings=build_warnings(...),
    )
```

---

## 7. 必须修复的 P0 问题

### P0-1：目标仓位为 0 且风险 HIGH 时，不能输出普通 HOLD

验收标准：

```text
输入：
- risk_level = HIGH
- target_weight = 0
- current_weight > 0

输出：
- action 必须为 REDUCE 或 RISK_REVIEW
- grid_action 必须为 PAUSE_BUY、SELL_ONLY 或 MANUAL_REVIEW
```

---

### P0-2：AI 未启用时，不要展示大段 AI 占位内容

验收标准：

```text
当 ai_enabled = False 或 ai_confidence = 0 时：
- 单标的不展示完整 AI 块
- 只展示“AI复核未启用，本次采用规则引擎”
```

---

### P0-3：目标仓位必须经过组合级约束

验收标准：

```text
当组合总仓位超过 max_total_position：
- 禁止新增 ADD_SMALL / ADD_STEP
- 动作降级为 HOLD_WAIT_ADD 或 HOLD
```

---

### P0-4：网格买入必须受风险等级约束

验收标准：

```text
当 risk_level = HIGH 且 trend_score < 30：
- 不允许 grid_action = KEEP
- 不允许继续正常买入
- 应输出 PAUSE_BUY / SELL_ONLY / MANUAL_REVIEW
```

---

## 8. P1 优化项

### P1-1：新增组合风险总览

输出字段：

```text
total_position
cash_buffer
top1_weight
top3_weight
high_risk_weight
theme_exposure
same_theme_overlap
allowed_add_budget
risk_warning_count
```

---

### P1-2：新增同主题 ETF 去重

输出示例：

```markdown
同主题 ETF 重合提示：
- 159141、159781、515230、159516 均与 AI / 科创 / 半导体方向相关
- 当前主题暴露偏高
- 建议优先保留流动性更好、趋势更强、费率更低的标的
```

---

### P1-3：交易复盘升级

新增指标：

```text
avg_trade_amount
fee_to_turnover_ratio
estimated_grid_profit
ineffective_trade_count
buy_after_drop_count
sell_before_rise_count
overtrading_flag
```

---

### P1-4：报告首页增加“今日最重要 3 件事”

例如：

```markdown
今日最重要 3 件事：

1. 检查 HIGH 风险且仍保留买入网格的 ETF
2. 暂停证据置信度不足标的的主动加仓
3. 近 30 日交易频率偏高，降低网格触发频率或提高单笔金额门槛
```

---

## 9. P2 优化项

### P2-1：引入回测模块

建议至少回测：

```text
1. 趋势评分 >= 65 后买入，未来 5/10/20 日收益
2. RSI6 > 80 时继续买入的结果
3. BOLL 分位 > 85% 时买入的结果
4. 低于 MA20/MA60 后继续网格买入的结果
5. 当前网格间距相对 ATR 的收益差异
```

---

### P2-2：增加 JSON 输出，方便后续自动化处理

建议每次生成：

```text
report.html
report.md
report.json
decisions.json
risk_events.json
grid_adjustments.json
trade_review.json
```

---

### P2-3：增加规则版本号

每份报告必须输出：

```yaml
rule_version: "2026.06.23-v1"
score_rule_version: "score-2026.06"
grid_rule_version: "grid-2026.06"
risk_rule_version: "risk-2026.06"
generated_at: "2026-06-23 14:45:08"
```

否则后续很难判断历史报告是按哪套规则生成。

---

## 10. 测试用例建议

### 10.1 高风险目标仓位为 0

```python
def test_high_risk_zero_target_should_not_hold():
    etf.risk_level = "HIGH"
    etf.trend_score = 21
    position.weight = 0.0336
    target_weight = 0

    decision = make_decision(etf, position, portfolio, config)

    assert decision.action in {Action.REDUCE, Action.RISK_REVIEW}
    assert decision.grid_action in {
        GridAction.PAUSE_BUY,
        GridAction.SELL_ONLY,
        GridAction.MANUAL_REVIEW,
    }
```

---

### 10.2 证据置信度不足时禁止加仓

```python
def test_low_evidence_confidence_should_block_add():
    etf.trend_score = 77
    etf.evidence_confidence = 0.22
    etf.risk_level = "LOW"
    position.weight = 0.025
    target_weight = 0.40

    decision = make_decision(etf, position, portfolio, config)

    assert decision.action != Action.ADD_STEP
    assert "证据置信度不足" in decision.warnings
```

---

### 10.3 组合仓位超限时禁止新增买入

```python
def test_portfolio_exposure_limit_should_block_add():
    portfolio.total_position = 0.72
    portfolio.max_total_position = 0.70

    etf.trend_score = 80
    etf.risk_level = "LOW"

    decision = make_decision(etf, position, portfolio, config)

    assert decision.action in {Action.HOLD, Action.HOLD_WAIT_ADD}
    assert "组合总仓位超过上限" in decision.warnings
```

---

### 10.4 同主题仓位超限时禁止加仓

```python
def test_theme_exposure_limit_should_block_add():
    portfolio.theme_weights = {
        "ai_semiconductor": 0.18
    }
    config.max_theme_weight = 0.15

    etf.theme = "ai_semiconductor"
    etf.trend_score = 75

    decision = make_decision(etf, position, portfolio, config)

    assert decision.action in {Action.HOLD, Action.HOLD_WAIT_ADD}
    assert "同主题仓位过高" in decision.warnings
```

---

## 11. Codex 实施顺序

建议按以下顺序开发：

```text
第一阶段：修复决策一致性
1. 重构 Action 枚举
2. 新增 force_risk_action
3. 修复 HIGH + target 0 仍 HOLD 的问题
4. 增加单元测试

第二阶段：引入组合风险约束
1. 新增 PortfolioRiskEngine
2. 配置 max_total_position / max_single_etf_weight / max_theme_weight
3. 所有 target_weight 经过组合约束
4. 首页输出组合风险总览

第三阶段：重构网格建议
1. 新增 GridAction 枚举
2. 高风险标的支持 PAUSE_BUY / SELL_ONLY
3. ATR 与网格间距联动
4. 当前持仓很小时限制买卖数量

第四阶段：优化报告展示
1. 首页增加今日优先处理事项
2. 压缩单 ETF 明细
3. AI 未启用时隐藏占位块
4. 数据完整性和规则版本号固定输出

第五阶段：交易复盘升级
1. 计算近 7 / 30 日交易质量
2. 识别过度交易
3. 识别小额低效网格交易
4. 给出网格频率调整建议
```

---

## 12. 最终目标

优化后的报告应该从“技术指标罗列型报告”升级为“组合风险驱动型 ETF 决策报告”。

目标效果：

```text
1. 先看组合风险，再看单只 ETF。
2. 先处理高风险和规则冲突，再看加仓机会。
3. 任何加仓必须经过证据置信度、组合仓位和同主题集中度约束。
4. 高风险标的不能因为微调阈值而继续普通持有。
5. 网格买入必须服从趋势风险和目标仓位。
6. AI 未真正启用时不制造伪智能结论。
7. 所有结论都能追溯到规则版本和数据来源。
```

本报告仅作为策略分析系统优化建议，不构成具体投资建议。
