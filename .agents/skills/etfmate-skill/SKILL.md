---
name: etfmate-skill
description: 本地 ETF 实时持仓与网格交易辅助分析 skill。用于创建、完善或运行 ETFMate 工具：先用 Playwright/CDP 连接用户已打开且已登录的 Chrome，实时读取同花顺投资账本和 Touker 网格页，再结合 a-stock-data 七层数据架构、行情指标、持仓备注和网格参数生成中文 HTML 实时分析报告。触发场景包括 ETFMate、ETF 实时分析、同花顺投资账本采集、Touker 网格设置、ETF 持仓建议、网格调参建议、Playwright 连接已登录 Chrome、多层证据分析、本地 CLI 工具开发。
---

# ETFMate Skill

## 核心原则

- 全部报告、终端说明和用户回答使用中文。
- ETFMate 是“实时分析”工具，不是日度批处理。每次运行都是一次全新的实时采集和分析，报告必须显示具体分析日期时间，不写“每日报告/日度报告”。
- 工具只做分析与辅助决策，默认不自动下单，不绕过验证码、短信、人脸、设备验证或平台风控。
- 正式分析必须同时拿到同花顺投资账本持仓/交易数据和 Touker 网格数据。任一核心源未登录、未加载或未采齐时立即停止，不生成最终建议，不用手工样例或指定代码替代。
- 行情和技术指标交给 `$a-stock-data` 或当前项目行情适配器自行决策数据源；本 skill 不固定要求腾讯、mootdx、百度或东方财富的优先级。
- 分析必须按 `$a-stock-data` 七层架构组织证据：行情技术、研报预期、热点信号、资金筹码、新闻舆情、基础数据、公告事件。当前实现拿不到的层必须明确标记为“待接入/缺失”，并降低建议强度；不得用技术指标冒充研报、新闻、公告等深层结论。
- 同花顺投资账本持仓“备注”列是用户本人对 ETF 的看法，分析时必须读取并作为辅助信号。市场指标与备注一致时可以增强建议置信度；不一致时必须指出冲突并降低动作强度。

## 实时运行流程

每次运行 ETFMate 必须按以下顺序执行，不能跳步：

1. 先检测 Chrome CDP 是否可用。默认端点是 `http://127.0.0.1:9222`，也可用 `ETFMATE_CDP_URL` 覆盖。必须验证 `/json/version` 返回包含 `webSocketDebuggerUrl` 的 JSON；404、空响应或无该字段都视为不可用。
2. 如果 Chrome 没打开、端口不可用或不是有效 DevTools HTTP API，立即停止。提示用户用独立 profile 打开 Chrome，开启远程调试，并在同一浏览器里登录同花顺投资账本和 Touker。
3. Chrome 可连接后，先进入同花顺投资账本和 Touker 页面采集数据。此时仍不要分析。
4. 如果任一页面是登录页、验证码页、风控页、协议确认页或页面未加载出关键数据，立即停止并提示用户手动处理；用户处理后重新运行或继续同一流程。
5. 只有同花顺持仓/交易和 Touker 网格都采集成功，才继续行情指标、建议生成和 HTML 报告。

推荐运行命令：

```bash
etfmate run
```

调试或回放某次实时快照时，使用 `run_id`：

```bash
etfmate collect --run-id 20260618-153000
etfmate analyze --run-id 20260618-153000
etfmate report --run-id 20260618-153000
```

不要把 `daily`、`--date`、`--codes` 或 `data/manual/*.example.json` 作为正式分析流程。

## Playwright / Chrome CDP 约束

- 首选连接用户已经打开、允许远程调试、且已登录两个站点的 Chrome：`playwright.chromium.connect_over_cdp`。
- 不要自动新开 Playwright 自带浏览器来替代用户登录态。需要新开时，也必须让用户在同一个可验证 CDP profile 内完成同花顺和 Touker 登录。
- 若 `9222/json/version` 返回 404，先枚举 Chrome 监听端口并逐个验证，不要反复重试同一个坏端口。
- 可用端点必须返回 `webSocketDebuggerUrl`；只监听了 TCP 端口不代表 Playwright 可连接。
- 同花顺目标页：`https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO`
- Touker 目标页：`https://m.touker.com/fd/conditions/monitoring`
- Touker 移动端可能只渲染可见卡片。必须定位内部滚动容器并滚动读取，按 ETF 代码去重，直到采集数量与页面“监控中(N)”一致。

用户需要打开调试 Chrome 时，给出：

```powershell
& "$env:ProgramFiles\Google\Chrome\Application\chrome.exe" `
  --remote-debugging-port=9222 `
  --remote-debugging-address=127.0.0.1 `
  --user-data-dir="$PWD\runtime\chrome-cdp-profile"
```

随后提示用户在该 Chrome 中打开 `chrome://inspect/#remote-debugging`，开启 `Allow remote debugging for this browser instance`，并登录同花顺投资账本和 Touker。

## 分析要求

运行或修改分析逻辑前读取 `references/etfmate-domain-rules.md`。

高层要求：

- 同一只 ETF 的持仓建议、技术指标、用户备注判断和 Touker 网格建议必须放在同一个 ETF 小节。
- 报告默认生成 HTML，页面结构和 CSS 以模板文件为维护入口。
- 技术分析至少覆盖 BOLL、MA5/10/20/60/200、真实波幅(ATR)7/14/30/60、乖离率(BIAS)6/12/24、成交量/VOL。可按需要增加换手、量比、振幅、趋势强弱、相关性或重合度等维度。
- 每只 ETF 的建议必须同时引用七层证据摘要、当前持仓规模、用户备注、Touker 网格参数和数据缺失情况。缺少研报/资金/新闻/公告等深层证据时，只能给保守建议或分批建议，不要给“满仓买入/全部卖出”这类强动作。
- 建议动作必须考虑当前持仓数量、可用数量、仓位占比、市值、成本、浮盈亏、用户备注和网格参数。不得出现“持有 100 份却建议建仓/加仓 1000 份”这类明显脱离持仓规模的建议。
- 如果多个 ETF 主题或成分股高度重合，要提示压缩重复标的，并给出保留/替换方法，例如优先保留流动性、费率、规模、跟踪误差或策略暴露更合适的一只。
- 网格建议的主动作必须互斥。趋势风险触发“暂停网格”时，不要同时给“调窄网格”作为主建议；调宽/调窄只在仍适合运行网格时使用。

## HTML 报告要求

- 标题使用“实时 ETF 持仓与网格分析”，显示具体分析时间。
- 页面提供 ETF 快速导航，点击代码/名称可跳转到对应 ETF 小节。
- 每个 ETF 标题行直接带现价、涨跌、持仓、浮盈亏和网格状态，后方基础信息使用小字号。
- ETF 小节内使用两张紧凑表格：持仓/技术/动作表和网格表；不要额外显示“持仓/指标”“网格”表格小标题。
- 持仓/技术/动作表必须包含紧凑的“七层证据”合并行，展示置信度、总分、各层状态和缺失层；不要拆成多个大表。
- 盈利用红色、亏损用绿色；买入/加仓用红色，减仓/卖出用绿色，暂停/调参/风险提醒用橙色或深红色。
- BOLL 参考值按 `上: ...；中: ...；下: ...`；MA 当前值按 `5: ...；10: ...；20: ...；60: ...；200: ...`；ATR 当前值按 `7: ...；14: ...；30: ...；60: ...`；BIAS 当前值按 `6: +x.xx%；12: -x.xx%；24: +x.xx%`，参考文案用 `+涨得快,-跌得深`。
- 持仓表“动作”和“总述”行合并当前/参考/提醒单元格；网格表“动作”行合并当前/建议/提醒单元格。
- 单只 ETF 总述不要展示 `quote:tencent;kline:tencent` 等内部 source key。数据完整性表里也要用人能看懂的来源描述。
- HTML 页面不要写入 ShareOne 发布提示。用户明确要求发布时，再使用 `$shareone` skill。

## 资源说明

- `scripts/health_check.py`：检查 Python、Playwright、pandas、stockstats、mootdx、requests 和 a-stock-data skill 可见性。
- `scripts/scaffold_etfmate.py`：生成或补齐 ETFMate Python CLI 项目骨架。维护该脚本时必须保持实时 `run/run_id` 流程，不要回退到 `daily/date`。
- `references/etfmate-domain-rules.md`：数据契约、分析规则、安全边界和报告要求。
