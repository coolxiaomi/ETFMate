---
name: etfmate-skill
description: 本地 ETF 持仓与网格交易辅助分析 skill。用于创建、完善或运行 ETFMate 工具：用 Playwright 读取同花顺账户页和 Touker 网格页，用 a-stock-data 获取 ETF 行情/K 线并计算 MA、BOLL、VOL、ATR、BIAS，生成中文持仓建议、网格调参建议、当日交易复盘评分和每日 Markdown/HTML 报告。触发场景包括 ETFMate、ETF 持仓分析、网格交易复盘、同花顺账户采集、Touker 网格设置、ETF 技术指标、每日 ETF 复盘报告、本地 CLI 工具开发。
---

# ETFMate Skill

## 核心原则

- 全部报告、终端说明和用户回答使用中文。
- 工具只做分析与辅助决策，默认不自动下单，不绕过验证码、短信、人脸、设备验证或平台风控。
- 同花顺账户数据、Touker 网格数据、raw 快照和报告默认只保存在本地。
- 任何网页采集都优先保存 raw JSON/HTML/截图，再做解析，便于页面改版后回放修复。
- 行情与 K 线优先复用 `$a-stock-data` 的数据源策略：K 线优先 mootdx，ETF 实时行情优先腾讯财经；东方财富只在独有数据时使用，并串行限流。

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

4. 按人工登录流程保存登录态：

```bash
etfmate login ths
etfmate login touker
```

5. 每日运行：

```bash
etfmate daily
```

## 开发工作流

在 ETFMate 仓库中工作时，先读取 `docs/etf-ai-tool-development-plan.md`，再读取本 skill 的 `references/etfmate-domain-rules.md`。以文档目标为准，但实现时优先保证可运行、可回放、可验证。

建议按里程碑推进：

1. M1：项目骨架和 Playwright persistent context。
2. M2：同花顺/Touker 采集，保存 raw JSON、HTML、截图。
3. M3：行情和指标层，接入 a-stock-data 数据源策略。
4. M4：持仓建议与网格参数建议。
5. M5：当日交易复盘和 10 分制评分。
6. M6：Markdown/HTML 报告、异常降级、基础测试。

每个里程碑都要能单独运行或用保存的 raw 数据回放；不要把网页采集失败扩散成整批分析失败。

## Playwright 采集约束

- 使用 persistent context 保存登录态，默认目录为 `runtime/playwright-profile/`。
- 同花顺使用桌面 viewport，目标页：
  `https://tzzb.10jqka.com.cn/pc/index.html#/myAccount/a/c60MoMO`
- Touker 使用移动端 viewport，目标页：
  `https://m.touker.com/fd/conditions/monitoring`
- 遇到登录失效、验证码、短信验证、设备验证、协议确认或风险确认时，暂停并提示用户手动完成。
- 网络响应优先捕获 JSON；无法稳定解析接口时，再退化为 DOM 表格抽取。

## 输出结构

每只 ETF 的建议必须包含：

```text
代码/名称：
当前状态：
建议动作：
建议理由：
风险点：
下一步观察价位：
```

建议动作只能从这些动作中选择或组合：`买入`、`分批买入`、`持有`、`减仓`、`卖出`、`暂停网格`、`恢复网格`。

每日复盘必须包含：

```text
今日评分：?/10
优点：
问题：
最需要改进的一点：
明日计划：
```

## 资源说明

- `scripts/health_check.py`：检查 Python 版本、Playwright、pandas、stockstats、mootdx、requests，以及本机 a-stock-data skill 是否可见。
- `scripts/scaffold_etfmate.py`：按开发文档生成 ETFMate Python CLI 项目骨架、基础模型、采集模块、指标模块、建议模块、报告模块和单元测试。
- `references/etfmate-domain-rules.md`：浓缩版数据契约、分析规则、安全边界和报告要求。做规则实现或报告生成前读取它。
