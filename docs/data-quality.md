# ETFMate 数据质量闸门

本文档定义正式分析前的数据完整性机制。目标不是在报告里提示“数据不完整”，而是在数据不完整时直接停止 `analyze`、`report` 和后续发布，避免生成无意义报告。

## 1. 闸门位置

正式流程必须经过三道质量闸：

```text
collect 后：校验同花顺和 Touker 原始采集结果
analyze 前：重新校验原始采集结果，避免复用坏快照
report 前：校验原始采集结果 + analysis.json，避免旧分析或手工文件绕过
```

实现入口：

```text
src/etfmate/analysis/data_quality.py
src/etfmate/cli.py
```

质量报告固定写入：

```text
data/raw/market/RUN_ID/data_quality.json
```

当 `status=FAIL` 时，CLI 必须返回失败，不生成最终分析、HTML 报告或 ShareOne 发布产物。

## 2. P0 硬阻断

以下任一情况必须停止：

1. 同花顺当前持仓为空，或持仓数量均为 0。
2. 当前持仓缺少代码、名称、数量、市值、现价、成本价等关键字段。
3. 同花顺账户资产摘要或总资产缺失，无法确认资金仓位口径。
4. 同花顺持仓备注/看法列整体未识别。
5. 同花顺自选 ETF 池为空，或只识别到持仓缓存。
6. 同花顺持仓、清仓、交易记录、自选 ETF 池任一滚动列表未确认到底。
7. 交易记录缺少“本月、近三月、近半年、今年、自定义”任一 tab 快照。
8. 自选 ETF 池来源 URL 不是预期同花顺自选页。
9. Touker 网格为空。
10. Touker 未识别到页面 `监控中(N)`，或识别数量少于页面数量。
11. Touker 网格缺少代码、名称、基准价、现价、买入下跌、买入反弹、卖出上升、卖出回落、委托/买入/卖出数量等关键字段。
12. 行情快照缺少 universe 代码，或任一 universe 标的缺少最新价、成交额、MA20、MA60、BOLL 中轨、ATR14%、RSI6、K 线天数。
13. 行情 `data_quality` 包含 `missing` 或 `error`。
14. 规则建议或网格建议缺少 universe 代码。
15. 规则建议缺少 `rule_decision`。

## 3. 降级但不硬阻断

以下问题写入 `warnings`，用于排查，但不单独阻断：

1. 单条持仓未识别备注/看法字段，但其他持仓已识别到该列。
2. Touker 未识别最小底仓或最大持仓字段。
3. `analysis.json` 未记录 `ai_review_input_path`。

如果这些 warning 频繁出现，应优先修复采集器，而不是在报告里解释。

## 4. 采集器完整性信号

滚动加载页面必须在快照中写入：

```text
scroll_complete = true / false
scroll_steps
scroll_stop_reason
```

缺少 `scroll_complete` 或 `scroll_complete=false` 都不能进入正式分析。虚拟列表、内部滚动容器或首屏数据只能作为调试证据，不能生成最终建议。

Touker 还必须保存：

```text
expected_count = 页面“监控中(N)”识别数量
```

`expected_count` 缺失时视为无法确认采集完整，必须停止。

## 5. 运行和排查

正式运行：

```bash
python -m etfmate.cli --root . run
```

如果失败，先查看：

```text
data/raw/market/RUN_ID/data_quality.json
data/raw/ths/RUN_ID/
data/raw/touker/RUN_ID/
```

不要通过手工补字段、删掉错误项、直接调用 `report --run-id` 的方式绕过。`report` 入口也会重新执行质量闸门。

## 6. 回归测试

修改采集、CLI、报告、规则 universe 或字段契约时，至少运行：

```bash
python -m pytest -q tests/test_data_quality.py
python -m pytest -q tests/test_decision_consistency.py
```

数据质量测试应覆盖：

1. 完整采集通过。
2. 持仓字段缺失阻断。
3. 自选 ETF 池缺失阻断。
4. Touker 核心字段缺失阻断。
5. 分析结果缺少 universe 行情、规则建议或网格建议阻断。
