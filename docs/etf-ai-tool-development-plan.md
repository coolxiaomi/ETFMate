# ETFMate AI 工具开发文档

> 运行、实现、安全和分析规则的长期约定见 `docs/etfmate-operating-contract.md`。原 `.agents/skills/etfmate-skill` 目录只是 Agent 触发包装，不是可执行程序，已整理为项目文档。

## 1. 目标

开发一个本地运行的 ETF 持仓与网格交易辅助分析工具，用 Playwright 打开并读取同花顺账户页、Touker 网格设置页，用 `a-stock-data` 获取 ETF 行情和技术指标，最终生成：

- 当前持仓 ETF 的逐只买卖建议、网格调整建议和理由。
- 已配置网格 ETF 的逐只参数评估与调参建议。
- 当日交易记录复盘、问题归因和 10 分制评分。
- 可保存的每日分析报告，便于回溯策略变化。

工具定位是“分析与辅助决策”，默认不做自动下单，不绕过登录、验证码或平台风控。

## 2. 数据来源

### 2.1 同花顺账户数据

目标地址：

```text
https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO
```

需要读取：

- 当前持仓：ETF 代码、名称、持仓数量、可用数量、成本价、现价、市值、盈亏、盈亏率。
- 当日/历史交易记录：成交日期、时间、代码、名称、买卖方向、成交价、成交数量、成交金额、手续费。
- 清仓数据：已清仓 ETF、建仓日期、清仓日期、累计盈亏、收益率、持仓周期。

优先采集方式：

1. 使用 Playwright 监听页面网络响应，优先捕获 JSON 接口数据。
2. 如果接口参数或响应被加密，再退化为 DOM 表格抽取。
3. 每次采集保存原始快照，便于页面结构变化后回放调试。

### 2.2 Touker 网格设置

目标地址：

```text
https://m.touker.com/fd/conditions/monitoring
```

需要读取：

- ETF 代码、名称。
- 当前网格状态：启用/暂停、基准价、网格间距、每格金额或份额、上下边界、触发条件。
- 最近触发记录：买入/卖出触发价、触发时间、成交状态。

页面是移动端页面，Playwright 建议使用移动端 viewport 和 user agent：

- viewport：`390 x 844`
- device scale factor：`2`
- user agent：iPhone Safari 或 Chromium mobile UA

### 2.3 行情与指标数据

使用 `a-stock-data` skill 作为行情和指标数据层。根据 skill 说明，数据源优先级如下：

- K 线、盘口、成交量：优先 `mootdx`。
- ETF 实时价格、涨跌幅、换手、市值等：优先腾讯财经接口。
- 需要东方财富独有数据时，必须串行限流，避免高频请求。
- 技术指标计算使用 `pandas` 和 `stockstats`。

每只 ETF 至少计算：

- 价格类：最新价、涨跌幅、日内振幅、近 5/20/60 日涨跌幅。
- 成交量类：当日成交量、成交额、量比、VOL MA5、VOL MA20、放量/缩量判断。
- 均线：MA5、MA10、MA20、MA60、价格相对均线位置。
- BOLL：上轨、中轨、下轨、带宽、价格分位。
- ATR：ATR14、ATR 占价格比例，用于评估网格间距是否过窄或过宽。
- BIAS：BIAS6、BIAS12、BIAS24，用于判断短线偏离。
- 可选增强：RSI、MACD、近 N 日高低点、回撤幅度。

## 3. 技术架构

建议使用 Python 项目，原因是 Playwright Python、pandas、stockstats、mootdx 可以放在同一运行环境里，便于数据采集和指标分析一体化。

```text
ETFMate/
  docs/
    etf-ai-tool-development-plan.md
  src/
    etfmate/
      browser/
        session.py
        ths_account.py
        touker_grid.py
      market/
        providers.py
        indicators.py
      analysis/
        grid_advisor.py
        trade_reviewer.py
        recommendation.py
      report/
        daily_report.py
      storage/
        models.py
        repository.py
      cli.py
  data/
    raw/
      ths/
      touker/
      market/
    reports/
  runtime/
    playwright-profile/
  pyproject.toml
```

### 3.1 模块职责

`browser/session.py`

- 创建 Playwright persistent context。
- 管理登录态目录 `runtime/playwright-profile/`。
- 提供 `ensure_login(url, login_check)`，登录失效时启动有头浏览器并提示用户手动登录。

`browser/ths_account.py`

- 打开同花顺账户页。
- 抽取持仓、交易记录、清仓数据。
- 保存原始 HTML、截图、网络 JSON 快照。

`browser/touker_grid.py`

- 打开 Touker 网格监控页。
- 抽取网格参数、状态和触发记录。
- 兼容移动端 viewport。

`market/providers.py`

- 封装 `a-stock-data` 中可复用的数据获取代码。
- 统一 ETF 代码格式，例如 `510300`、`510300.SH`、`sh510300`。
- 对东方财富接口加全局串行限流。

`market/indicators.py`

- 输入 K 线 DataFrame。
- 输出 MA、BOLL、VOL、ATR、BIAS 等指标。
- 对停牌、缺失 K 线、上市时间过短等情况做降级处理。

`analysis/grid_advisor.py`

- 对比当前网格参数和波动率。
- 生成调宽、调窄、上移、下移、暂停、恢复、降低单格金额等建议。

`analysis/recommendation.py`

- 对每只 ETF 汇总持仓、网格、行情和指标。
- 输出买入、卖出、持有、减仓、暂停网格、恢复网格等建议。

`analysis/trade_reviewer.py`

- 对当日交易做复盘。
- 评估交易是否顺势、是否追涨杀跌、是否偏离网格纪律、仓位是否合理。
- 输出 10 分制评分和改进建议。

`report/daily_report.py`

- 生成 Markdown/HTML 报告。
- 报告文件建议命名为 `data/reports/YYYY-MM-DD-etf-review.md`。

## 4. 登录态与 Playwright 设计

### 4.1 登录态保存

使用 Playwright persistent context，而不是每次重新创建无状态浏览器：

```python
from playwright.sync_api import sync_playwright

def open_context(headless: bool = False):
    p = sync_playwright().start()
    context = p.chromium.launch_persistent_context(
        user_data_dir="runtime/playwright-profile",
        headless=headless,
        viewport={"width": 1280, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
    )
    return p, context
```

首次运行流程：

1. 工具打开同花顺账户页。
2. 如果检测到未登录，提示用户在浏览器窗口内手动登录。
3. 用户完成登录后按回车继续。
4. 工具验证页面是否出现持仓或账户标识。
5. 登录态保存在 `runtime/playwright-profile/`，下次优先复用。

Touker 页面同理，但建议单独封装移动端 context 参数。如果两个站点登录态互不影响，可以共用 profile；如果存在 UA 或 cookie 冲突，则拆成：

```text
runtime/playwright-profile/ths/
runtime/playwright-profile/touker/
```

### 4.2 登录检测

每个站点都需要独立的 `login_check`：

- URL 是否仍停留在登录页。
- 页面是否出现“登录”“验证码”“手机号”等未登录关键字。
- 页面是否出现账户资产、持仓、监控列表等已登录关键字。
- 如果接口返回 401/403，也视为登录失效。

### 4.3 用户操作提示

以下情况必须暂停并提示用户：

- 首次登录。
- 登录态过期。
- 出现短信验证码、滑块验证、人脸验证等人工校验。
- 页面提示风险确认、协议确认、设备验证。
- 平台要求重新授权访问账户或交易记录。

提示文案示例：

```text
请在打开的浏览器窗口中完成同花顺登录和验证码验证。完成后回到终端按 Enter 继续。
```

## 5. 数据模型

### 5.1 Position

```python
class Position:
    code: str
    name: str
    quantity: float
    available_quantity: float | None
    cost_price: float
    last_price: float
    market_value: float
    pnl: float
    pnl_pct: float
    source: str = "ths"
```

### 5.2 Trade

```python
class Trade:
    trade_date: str
    trade_time: str | None
    code: str
    name: str
    side: str  # BUY / SELL
    price: float
    quantity: float
    amount: float
    fee: float | None
    source: str = "ths"
```

### 5.3 GridConfig

```python
class GridConfig:
    code: str
    name: str
    enabled: bool
    base_price: float | None
    lower_price: float | None
    upper_price: float | None
    grid_step_pct: float | None
    grid_step_amount: float | None
    order_amount: float | None
    last_trigger_time: str | None
```

### 5.4 MarketSnapshot

```python
class MarketSnapshot:
    code: str
    name: str
    last_price: float
    pct_chg: float
    volume: float
    amount: float
    ma5: float | None
    ma10: float | None
    ma20: float | None
    ma60: float | None
    boll_upper: float | None
    boll_mid: float | None
    boll_lower: float | None
    atr14: float | None
    atr14_pct: float | None
    bias6: float | None
    bias12: float | None
    bias24: float | None
    vol_ma5: float | None
    vol_ma20: float | None
```

## 6. 分析规则

### 6.1 ETF 单只建议

每只 ETF 输出固定结构：

```text
代码/名称：
当前状态：
建议动作：
建议理由：
风险点：
下一步观察价位：
```

建议动作枚举：

- `买入`：价格靠近 BOLL 下轨，BIAS 明显负偏离，成交量没有异常放大破位，且仓位不足。
- `分批买入`：短线偏弱但进入低估/低位区，适合用网格或小仓位试探。
- `持有`：趋势和波动处于中性，现有网格参数合理。
- `减仓`：价格远离 MA20/MA60，BIAS 明显正偏离，接近 BOLL 上轨且放量滞涨。
- `卖出`：跌破关键均线且放量，或趋势明显走坏并触发风控。
- `暂停网格`：单边下跌趋势明显，价格跌破下边界且均线空头。
- `恢复网格`：价格回到 BOLL 中轨附近，ATR 回落，成交量恢复正常。

### 6.2 网格参数调整

核心原则：网格间距要跟 ETF 的真实波动率匹配，不能只用固定百分比。

参考规则：

- 如果 `grid_step_pct < 0.6 * ATR14_pct`，网格过密，建议调宽，避免噪音交易。
- 如果 `grid_step_pct > 1.8 * ATR14_pct`，网格过宽，建议调窄，否则触发频率过低。
- 如果价格长期在上半区运行且 MA20 上行，建议上移网格中心。
- 如果价格跌破 MA60 且 BOLL 带宽扩大，建议降低单格金额或暂停下沿补仓。
- 如果成交量显著萎缩，建议降低触发预期，不主动加大网格密度。
- 如果持仓浮亏超过预设阈值且仍处于下跌趋势，不建议机械加仓，优先评估仓位上限。

输出示例：

```text
510300 沪深300ETF
当前网格：间距 1.0%，每格 1000 元，区间 3.40-4.10
波动评估：ATR14 约 0.75%，BOLL 带宽中等
建议：维持间距，网格中心上移至 3.78 附近
理由：价格站上 MA20，未明显偏离 BOLL 上轨，当前间距与波动率匹配
```

### 6.3 当日交易复盘

对每笔交易评价：

- 买入是否发生在 BOLL 下半区、MA20 附近、负 BIAS 修复区。
- 卖出是否发生在 BOLL 上半区、正 BIAS 扩张区、放量冲高区。
- 是否违反网格设置，例如未到触发价手动交易。
- 是否在放量破位时补仓。
- 是否在缩量反弹时追高。
- 是否集中买入同类 ETF，造成相关性过高。
- 交易金额是否超过单日风险预算。

10 分制评分建议：

```text
基础分：6 分
+1 顺应网格纪律
+1 买卖点与技术指标匹配
+1 仓位控制合理
+1 有明确止盈/止损或下一步计划
-1 追涨或杀跌
-1 逆趋势加仓且无仓位保护
-1 同类 ETF 过度集中
-1 交易过频或手续费不划算
-1 情绪化手动偏离策略
```

最终输出：

```text
今日评分：8/10
优点：
问题：
最需要改进的一点：
明日计划：
```

## 7. 运行流程

### 7.1 每日分析

```text
1. 启动 Playwright。
2. 打开同花顺账户页，读取持仓、交易记录、清仓数据。
3. 打开 Touker 网格页，读取网格设置。
4. 合并 ETF 代码列表：持仓 ETF + 网格 ETF + 当日交易 ETF。
5. 调用 a-stock-data 获取行情和 K 线。
6. 计算 MA、BOLL、VOL、ATR、BIAS。
7. 逐只 ETF 生成建议。
8. 对当日交易复盘并评分。
9. 写入 Markdown/HTML 报告。
10. 保存原始快照和结构化 JSON。
```

### 7.2 CLI 命令设计

```bash
etfmate login ths
etfmate login touker
etfmate collect
etfmate analyze --date 2026-06-17
etfmate report --date 2026-06-17
etfmate daily
```

`etfmate daily` 等价于 `collect + analyze + report`。

## 8. 文件与数据保存

建议保存以下文件：

```text
data/raw/ths/YYYY-MM-DD/account.json
data/raw/ths/YYYY-MM-DD/trades.json
data/raw/ths/YYYY-MM-DD/closed_positions.json
data/raw/touker/YYYY-MM-DD/grids.json
data/raw/market/YYYY-MM-DD/snapshots.json
data/reports/YYYY-MM-DD-etf-review.md
data/reports/YYYY-MM-DD-etf-review.html
```

敏感信息处理：

- `runtime/playwright-profile/` 不提交 Git。
- `data/raw/` 默认不提交 Git，除非用户明确需要留档。
- 报告中可配置是否隐藏资产总额、持仓市值和交易金额。

建议 `.gitignore`：

```gitignore
runtime/
data/raw/
data/reports/*.html
.env
```

## 9. 依赖

Python 依赖：

```bash
pip install playwright pandas stockstats requests mootdx
playwright install chromium
```

可选依赖：

```bash
pip install pydantic rich jinja2
```

用途：

- `pydantic`：结构化模型校验。
- `rich`：终端表格和登录提示。
- `jinja2`：HTML 报告模板。

## 10. 风险与限制

- 两个网页都可能改版，必须保存原始快照，便于快速修复选择器或接口解析。
- 登录态可能因平台风控失效，需要人工登录。
- 不应绕过验证码、短信验证、设备验证。
- 同花顺交易账户数据敏感，报告和 raw 数据默认本地保存。
- 行情接口可能出现延迟、空值或停牌数据，建议每只 ETF 输出数据完整性标记。
- 东方财富接口需要限流，批量 ETF 分析必须串行或低并发。
- 本工具只生成建议，不自动下单，避免误交易风险。

## 11. 开发里程碑

### M1：项目骨架和登录态

- 初始化 Python 项目。
- 封装 Playwright persistent context。
- 实现同花顺和 Touker 的手动登录流程。
- 登录态保存到 `runtime/playwright-profile/`。

验收标准：

- 首次运行能打开网页登录。
- 第二次运行能复用登录态。
- 登录失效时能明确提示用户。

### M2：网页数据采集

- 采集同花顺持仓、交易记录、清仓数据。
- 采集 Touker 网格设置。
- 保存 raw JSON、HTML、截图。

验收标准：

- 能输出标准化 `Position`、`Trade`、`GridConfig`。
- 页面改版时有 raw 快照可排查。

### M3：行情和指标层

- 接入 `a-stock-data`。
- 获取 ETF 实时行情和历史 K 线。
- 计算 MA、BOLL、VOL、ATR、BIAS。

验收标准：

- 对持仓和网格中的每只 ETF 都有 `MarketSnapshot`。
- 缺失数据有明确错误说明，不中断整批分析。

### M4：建议引擎

- 实现持仓建议。
- 实现网格调整建议。
- 实现每只 ETF 的理由生成。

验收标准：

- 每只 ETF 都输出建议动作、理由、风险点和观察价位。
- 同一 ETF 同时出现在持仓和网格中时，建议能合并上下文。

### M5：交易复盘评分

- 实现当日交易逐笔评价。
- 实现 10 分制评分。
- 生成每日复盘结论。

验收标准：

- 每笔交易都有评价。
- 当日整体有分数、优点、问题和明日计划。

### M6：报告和稳定性

- 生成 Markdown/HTML 报告。
- 增加异常重试、登录失效处理、数据完整性检查。
- 增加基础单元测试和采集回放测试。

验收标准：

- `etfmate daily` 一条命令生成完整报告。
- 在一个网页采集失败时，其他数据仍能产出，并在报告里标注缺失。

## 12. 测试计划

单元测试：

- ETF 代码归一化。
- 指标计算。
- 网格参数建议规则。
- 交易评分规则。

集成测试：

- 用保存的 raw JSON 回放同花顺解析。
- 用保存的 raw JSON 回放 Touker 解析。
- 用 mock K 线验证建议输出。

人工验收：

- 首次登录流程。
- 登录态复用。
- 页面验证码中断提示。
- 每日报告内容是否覆盖所有 ETF。

## 13. 首轮实现建议

第一版不要急于做复杂 UI，先做本地 CLI 和 Markdown 报告：

1. 先完成 Playwright 登录态和数据快照保存。
2. 再完成 ETF 列表合并和行情指标。
3. 最后做建议和复盘评分。

这样即使网页字段解析还不稳定，也可以依靠 raw 快照快速迭代；行情和建议层也可以用手工 JSON 先测试。

## 14. 需要用户参与的节点

开发和运行过程中需要用户参与：

- 首次打开同花顺账户页时，手动登录。
- 首次打开 Touker 网格页时，手动登录。
- 出现短信验证码、滑块、设备验证时，手动完成验证。
- 确认是否允许本地保存登录态、账户快照和交易记录。
- 确认报告里是否需要隐藏资产金额、成交金额等敏感数据。

建议默认配置：

```text
保存登录态：是
保存 raw 快照：是
报告隐藏资产金额：否，本地使用
自动下单：否
```

## 15. 后续增强

- 增加本地 SQLite，保存每日持仓和策略变化。
- 增加 ETF 分类，识别宽基、行业、债券、货币、跨境 ETF。
- 增加相关性检查，避免持仓 ETF 高度同质化。
- 增加回测模块，评估当前网格参数在历史波动中的触发频率和收益风险比。
- 增加定时任务，在收盘后自动生成复盘报告。
- 增加飞书/邮件推送，但默认不上传原始账户数据。
