---
name: etfmate-skill
description: 本地 ETF 持仓与网格交易辅助分析 skill。用于创建、完善或运行 ETFMate 工具：用 Playwright 读取同花顺账户页和 Touker 网格页，用 a-stock-data 获取 ETF 行情/K 线并计算 MA、BOLL、VOL、ATR、BIAS，生成中文持仓建议、网格调参建议、当日交易复盘评分和每日 Markdown/HTML 报告。触发场景包括 ETFMate、ETF 持仓分析、网格交易复盘、同花顺账户采集、Touker 网格设置、ETF 技术指标、每日 ETF 复盘报告、本地 CLI 工具开发。
---

# ETFMate Skill

## 核心原则

- 全部报告、终端说明和用户回答使用中文。
- 工具只做分析与辅助决策，默认不自动下单，不绕过验证码、短信、人脸、设备验证或平台风控。
- 同花顺账户数据、Touker 网格数据、raw 快照和报告默认只保存在本地。
- 结构化 raw JSON 是必需产物；HTML/截图只在首次接入、解析失败、登录态排查、页面改版排查时保存，不要把截图当作分析前置条件。
- 行情与 K 线优先复用 `$a-stock-data` 的数据源策略：K 线优先 mootdx，ETF 实时行情优先腾讯财经；东方财富只在独有数据时使用，并串行限流。
- 不要用手工样例数据或只用同花顺持仓生成最终建议。用户要的是“同花顺持仓/交易 + Touker 网格 + a-stock-data 行情指标”的综合结论；Touker 没有采齐时必须停下来等用户登录或处理验证。

## 快速开始

1. 先运行环境检查：

```bash
python .agents/skills/etfmate-skill/scripts/health_check.py
```

2. 在空仓库或缺少项目骨架时生成 ETFMate Python 项目：

```bash
python .agents/skills/etfmate-skill/scripts/scaffold_etfmate.py --root .
```

脚本默认只创建缺失文件；需要重建模板时再使用 `--force`。

3. 安装项目依赖并初始化浏览器：

```bash
python -m pip install -e .
python -m playwright install chromium
```

4. 先连接用户已经打开的 Chrome。默认使用 `playwright.chromium.connect_over_cdp("http://127.0.0.1:9222")`，复用真实浏览器里的登录态和页面；不要优先启动 Playwright 自带的新浏览器。

如果连接不上，提示用户用独立 User Data Dir 打开 Chrome，避免反复出现“允许远程调试吗？”确认：

```powershell
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --user-data-dir="$PWD\runtime\chrome-cdp-profile"
```

随后在这个 Chrome 中打开 `chrome://inspect/#remote-debugging`，开启 `Allow remote debugging for this browser instance`，再回到终端继续。遇到登录页、验证码、协议确认或风控时，停下来等用户手动完成；用户回复已登录后，从同一个 Chrome 会话继续，不要跳过 Touker 直接分析。

```bash
etfmate login ths
etfmate login touker
```

5. 每日运行。`daily` 的验收标准是同花顺持仓/交易与 Touker 监控中网格都采集成功；任一核心源失败时输出阻塞原因，不生成最终买卖建议。

```bash
etfmate daily
```

## 开发工作流

在 ETFMate 仓库中工作时，先读取 `docs/etf-ai-tool-development-plan.md`，再读取本 skill 的 `references/etfmate-domain-rules.md`。以文档目标为准，但实现时优先保证可运行、可回放、可验证。

建议按里程碑推进：

1. M1：项目骨架和 Playwright Chrome CDP 连接。
2. M2：同花顺/Touker 采集，保存结构化 raw JSON；仅在调试需要时保存 HTML/截图。
3. M3：行情和指标层，接入 a-stock-data 数据源策略。
4. M4：持仓建议与网格参数建议。
5. M5：当日交易复盘和 10 分制评分。
6. M6：Markdown/HTML 报告、异常降级、基础测试。

每个里程碑都要能单独运行或用保存的 raw 数据回放；不要把网页采集失败扩散成整批分析失败。

## Playwright / Chrome CDP 采集约束

- 首选连接用户已打开且允许远程调试的 Chrome：`playwright.chromium.connect_over_cdp`，默认端点 `http://127.0.0.1:9222`，允许用环境变量或 CLI 参数覆盖。
- 如果 CDP 端点不可用，不要自动新开 Playwright 浏览器继续采集；先提示用户按上面的命令用 `runtime/chrome-cdp-profile/` 作为独立 User Data Dir 打开 Chrome，并到 `chrome://inspect/#remote-debugging` 开启远程调试。
- 复用同一个独立 Chrome profile 保存同花顺和 Touker 登录态。不要读取 cookies、localStorage、密码或浏览器配置文件，只通过页面文本、DOM、网络响应和必要截图采集。
- 同花顺使用桌面 viewport，目标页：
  `https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO`
- Touker 优先在同一 Chrome 会话中新开标签页，并设置窄屏 viewport；如果站点强依赖移动 UA，再提示用户在该 Chrome 中切换设备模拟或移动端页面。目标页：
  `https://m.touker.com/fd/conditions/monitoring`
- 遇到登录失效、验证码、短信验证、设备验证、协议确认或风险确认时，暂停并提示用户手动完成。
- 网络响应优先捕获 JSON；无法稳定解析接口时，再退化为 DOM 表格抽取。
- Touker 监控页可能显示“监控中(19)”但移动端只渲染部分可见卡片。必须定位内部滚动容器（例如 `van-tab__panel` 一类容器），滚动/读取 `innerText` 并按 ETF 代码去重，直到采集数量与页面括号数量一致。
- Touker 的条件单支持买入/卖出间距不对称、买入/卖出数量不对等。采集字段必须保留：`sell_rise_pct`、`sell_pullback_pct`、`buy_fall_pct`、`buy_rebound_pct`、`buy_quantity`、`sell_quantity`、`order_quantity`、`min_base_quantity`、`max_position_quantity`、`enabled/status`。

## 输出结构

报告优先追求可读性，不强制所有数据都用 Markdown 表格。ETF 数量少或字段很多时，用“单只 ETF 小节 + 关键指标短行 + 动作/理由/风险/观察价位”的结构；只有数值列稳定、横向比较清楚时才使用紧凑表格。避免把长理由、风险点和下一步计划塞进宽表格。

每只 ETF 至少覆盖：代码/名称、持仓数量、市值、仓位占比、成本价、现价、浮盈亏率、BOLL 分位、MA20/MA60 状态、ATR14%、BIAS6、建议动作、理由、风险点、观察价位。

建议动作只能从这些动作中选择或组合：`买入`、`分批买入`、`持有`、`减仓`、`卖出`、`暂停网格`、`恢复网格`。

网格建议必须给出可执行数值，不要只写“调宽/调窄”。输出至少包含：当前买入触发、建议买入触发范围、当前卖出触发、建议卖出触发范围、当前委托股数、建议买入股数、建议卖出股数、依据。建议值用 ATR14、BOLL 位置、趋势、持仓市值/仓位上限推导，例如：

```text
买入下跌间距建议 = clamp(0.9 * ATR14_pct, 2.0%, 8.0%)
卖出上升间距建议 = clamp(0.8 * ATR14_pct, 2.0%, 8.0%)
趋势低于 MA60：买入股数降为当前 0-50%，卖出股数维持或提高到 100-150%
价格接近 BOLL 上轨且正 BIAS：卖出间距下调，卖出股数提高，买入暂停或降额
价格接近 BOLL 下轨且负 BIAS：买入间距可略收窄，但总仓位接近上限时不加量
```

复盘必须分周期输出：

```text
当日复盘：只看分析日交易记录
三日复盘：最近 3 个交易日
7日复盘：最近 7 个自然日/交易日可用记录
30日复盘：最近 30 日
```

每个周期都要包含评分、交易笔数、买入金额、卖出金额、优点、问题、最需要改进的一点、下一步计划。周期很多时可用表格汇总金额和评分，再用短段落写问题和计划；不要强制所有字段进入同一张宽表。

报告生成后，询问用户是否使用 `$shareone` 发布报告。用户同意后再按 shareone skill 的安全提示和确认流程发布，发布名称使用 `ETFMate-report-YYYY-MM-DD`。

## 资源说明

- `scripts/health_check.py`：检查 Python 版本、Playwright、pandas、stockstats、mootdx、requests，以及本机 a-stock-data skill 是否可见。
- `scripts/scaffold_etfmate.py`：按开发文档生成 ETFMate Python CLI 项目骨架、基础模型、采集模块、指标模块、建议模块、报告模块和单元测试。
- `references/etfmate-domain-rules.md`：浓缩版数据契约、分析规则、安全边界和报告要求。做规则实现或报告生成前读取它。

## 本次实战沉淀

- 不要在未采集 Touker 的情况下用 `--codes` 或样例 JSON 生成“最终建议”；这会偏离用户目标。
- 如果 Touker 停在登录页，必须停下来等待用户手动登录；用户确认后继续同一页面，不要绕过登录。
- `data/manual/*.example.json` 只适合开发单元测试，不适合作为真实分析输入；面向用户的每日分析默认不创建它。
- 百度 K 线可能返回 403；ETF K 线应按 `mootdx -> 腾讯 K 线 -> 百度 K 线` 降级，实时行情仍优先腾讯。
- PowerShell 写 JSON 可能产生 UTF-8 BOM；读取本地 JSON 用 `utf-8-sig` 兼容。
