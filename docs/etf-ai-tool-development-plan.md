# ETFMate web-access 版开发计划

## 目标

ETFMate 是本地实时 ETF 持仓与网格交易辅助分析工具。当前采集策略统一改为使用 `$web-access` skill 操作用户已登录的 Chrome，通过 web-access CDP Proxy 读取同花顺投资账本和 Touker 网格页，再结合 `$a-stock-data` 七层证据、行情指标、持仓备注和网格参数生成中文 HTML 实时报告。

## 采集边界

- 所有联网、登录态页面读取、动态页面交互都通过 `$web-access`。
- 不再维护独立浏览器自动化栈，也不再保存独立浏览器 profile。
- 同花顺和 Touker 任一页面未登录、遇到验证码/风控/协议确认或关键数据未加载时，立即停止，不生成最终建议。
- Touker 必须滚动内部容器并按 `监控中(N)` 校验采集数量。

## 推荐流程

1. 加载 `$web-access`，运行其前置检查并确认 Proxy 可用。
2. 打开同花顺投资账本持仓/交易页：`https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO`。
3. 打开同花顺投资账本自选 ETF 池页：`https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/ISUeEwK`。
4. 打开 Touker 网格页：`https://m.touker.com/fd/conditions/monitoring`。
5. 用 `/eval` 读取 DOM、表格、页面文本、storage 和已加载结构化数据，用 `/screenshot` 留存证据。
6. 保存原始快照到 `data/raw/ths/RUN_ID/` 和 `data/raw/touker/RUN_ID/`。
7. 调用行情/指标和七层证据分析，输出 `data/raw/market/RUN_ID/analysis.json`。
8. 生成 `data/reports/RUN_ID-etf-realtime.html`。

命令入口：

```bash
etfmate run
etfmate collect --run-id 20260618-153000
etfmate analyze --run-id 20260618-153000
etfmate report --run-id 20260618-153000
```

## 数据契约

详细字段、阻塞规则、建议规则和 HTML 报告格式以 `.agents/skills/etfmate-skill/references/etfmate-domain-rules.md` 为准。
