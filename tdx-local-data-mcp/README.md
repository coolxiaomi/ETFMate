# tdx-local-data-mcp

本地 MCP Server，让 AI 工具通过 MCP 协议读取通达信/华宝证券客户端的本地投资数据。

## 项目用途

- 读取通达信自选股（.blk 文件）
- 导入持仓快照（CSV / Excel）
- 导入交易记录（CSV / Excel）
- 查询标的全貌（自选 + 持仓 + 交易统计）

## 为什么使用 MCP

MCP（Model Context Protocol）是一种标准化的 AI 工具协议。通过 MCP，AI 助手可以直接查询你的本地投资数据，用于：

- 投资复盘分析
- ETF 组合管理
- 持仓/交易数据查询

**安全原则：**

- 只读取本地文件，不连接券商交易接口
- 不自动下单
- 不保存证券账户密码
- 不执行系统命令
- 不删除用户文件

---

## 安装

### 环境要求

- Node.js 20+
- pnpm（推荐）或 npm
- Windows（通达信运行环境）

### 安装依赖

```bash
pnpm install
```

> **关于 better-sqlite3：** 该依赖包含 C++ 原生模块，需要 Windows 编译环境。如果安装失败，请先安装：
> ```bash
> npm install -g windows-build-tools
> ```
> 或者在管理员 PowerShell 中运行：
> ```powershell
> choco install visualstudio-build-tools
> ```
> 如果仍然无法编译，可以考虑使用 `sql.js` 替代（需修改 `src/db/sqlite.ts`）。

### 构建

```bash
pnpm build
```

### 启动

```bash
pnpm start
```

---

## 配置

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

编辑 `.env`：

```env
TDX_INSTALL_PATH=C:\zd_hbzq
# SQLITE_PATH=C:\zd_hbzq\tdx-local-data-mcp.db
```

### 配置项说明

| 变量 | 必填 | 说明 |
|------|------|------|
| `TDX_INSTALL_PATH` | 是 | 通达信安装根目录 |
| `SQLITE_PATH` | 否 | SQLite 数据库路径（默认在通达信目录下） |

### 默认路径推导规则

基于 `TDX_INSTALL_PATH` 自动推导：

| 路径 | 默认值 |
|------|--------|
| 自选股目录 | `${TDX_INSTALL_PATH}/T0002/blocknew` |
| 持仓导入目录 | `${TDX_INSTALL_PATH}/tdx-local-data-mcp/import/positions` |
| 交易导入目录 | `${TDX_INSTALL_PATH}/tdx-local-data-mcp/import/trades` |
| SQLite 数据库 | `${TDX_INSTALL_PATH}/tdx-local-data-mcp.db` |

导入目录不存在时会自动创建。

---

## 连接 AI 工具

### MCP 客户端配置

在支持 MCP 的 AI 工具（如 Claude Desktop、Cursor）中添加配置：

```json
{
  "mcpServers": {
    "tdx-local-data-mcp": {
      "command": "npx",
      "args": ["-y", "tdx-local-data-mcp"],
      "env": {
        "TDX_INSTALL_PATH": "C:\\zd_hbzq"
      }
    }
  }
}
```

自定义 SQLite 路径：

```json
{
  "mcpServers": {
    "tdx-local-data-mcp": {
      "command": "npx",
      "args": ["-y", "tdx-local-data-mcp"],
      "env": {
        "TDX_INSTALL_PATH": "C:\\zd_hbzq",
        "SQLITE_PATH": "D:/data/tdx-local-data-mcp.db"
      }
    }
  }
}
```

---

## MCP Tools 说明

### 1. `get_watchlist` - 查询自选股

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `groupName` | string | 否 | 自选股分组名称 |
| `securityType` | string | 否 | 证券类型: `ETF`, `STOCK` |

**返回：** groupName, market, securityCode, securityName, securityType

---

### 2. `sync_tdx_watchlist` - 同步通达信自选股

无参数。

扫描通达信 `.blk` 自选股文件，解析并写入 SQLite。

**返回：** syncedCount, groupCount, warnings

---

### 3. `get_positions` - 查询持仓

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `accountName` | string | 否 | 账户名称 |
| `snapshotDate` | string | 否 | 快照日期 yyyy-MM-dd |

**返回：** accountName, snapshotDate, market, securityCode, securityName, quantity, availableQuantity, costPrice, marketPrice, marketValue, profitLoss, profitLossRatio

---

### 4. `import_position_file` - 导入持仓文件

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `filePath` | string | 是 | CSV 或 Excel 文件路径 |

文件必须位于持仓导入目录下。

**返回：** importedCount, filePath

---

### 5. `get_trades` - 查询交易记录

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `accountName` | string | 否 | 账户名称 |
| `startDate` | string | 否 | 开始日期 yyyy-MM-dd |
| `endDate` | string | 否 | 结束日期 yyyy-MM-dd |
| `securityCode` | string | 否 | 证券代码 |
| `side` | string | 否 | 买卖方向: `BUY`, `SELL`, `OTHER` |

**返回：** accountName, tradeDate, tradeTime, market, securityCode, securityName, side, quantity, price, amount, fee, orderNo, contractNo

---

### 6. `import_trade_file` - 导入交易记录文件

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `filePath` | string | 是 | CSV 或 Excel 文件路径 |

文件必须位于交易记录导入目录下。

**返回：** importedCount, filePath

---

### 7. `get_security_overview` - 标的全貌

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `securityCode` | string | 是 | 证券代码 (6位数字) |

**返回：**
- `inWatchlist` - 是否在自选股中
- `watchlistGroups` - 所属自选分组列表
- `latestPosition` - 最新持仓
- `recentTrades` - 最近 10 条交易记录
- `totalBuyAmount` / `totalSellAmount` / `netBuyAmount` - 买卖统计
- `unrealizedProfitLoss` - 当前浮动盈亏

---

### 8. `get_sync_logs` - 同步日志

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `syncType` | string | 否 | 同步类型筛选 |
| `limit` | number | 否 | 返回条数 (默认 20) |

**返回：** syncType, status, message, startedAt, finishedAt

---

## 通达信自选股目录

通达信自选股保存在：

```
{TDX安装目录}/T0002/blocknew/
```

每个 `.blk` 文件对应一个自选分组，文件名即分组名。

文件格式示例：

```
0|000001
1|600000
0|159915
1|510300
```

- `0` = 深市 (SZ)
- `1` = 沪市 (SH)

---

## 持仓 CSV 示例格式

```csv
账户名称,快照日期,市场,证券代码,证券名称,持仓数量,可用数量,成本价,现价,市值,盈亏,盈亏比例
华宝证券,2025-06-09,SH,510300,沪深300ETF,1000,1000,4.050,4.120,4120.00,70.00,1.73%
```

**支持的中文表头：** 证券代码/代码/股票代码/基金代码、持仓数量/当前持仓/数量、成本价/成本价格/持仓成本价、现价/最新价/市价、盈亏/浮动盈亏/参考盈亏 等。

---

## 交易记录 CSV 示例格式

```csv
账户名称,交易日期,交易时间,市场,证券代码,证券名称,买卖方向,成交数量,成交价格,成交金额,手续费,委托编号,合同编号
华宝证券,2025-06-06,09:35:12,SH,510300,沪深300ETF,买入,1000,4.050,4050.00,1.22,100001,200001
```

**支持的中文表头：** 交易日期/成交日期、买卖方向/操作/买卖/业务名称、成交数量/数量/发生数量、成交价格/价格/成交均价 等。

**日期格式：** 支持 `yyyy-MM-dd`、`yyyy/MM/dd`、`yyyyMMdd`

**方向标准化：** 买入/申购 → `BUY`，卖出/赎回 → `SELL`，其他 → `OTHER`

---

## 安全边界

| 操作 | 允许路径 |
|------|----------|
| 同步自选股 | 只读 `${TDX_INSTALL_PATH}/T0002/blocknew/` |
| 导入持仓 | 只读 `${TDX_INSTALL_PATH}/tdx-local-data-mcp/import/positions/` |
| 导入交易 | 只读 `${TDX_INSTALL_PATH}/tdx-local-data-mcp/import/trades/` |

**禁止操作：**

- 禁止路径穿越 (`../`)
- 禁止读取任意路径
- 禁止删除文件
- 禁止执行系统命令

---

## 后续扩展建议

- ETF 行情数据（日线/分钟线）
- 投资复盘分析数据
- 收益率计算
- 组合风险评估
- 更多数据源支持

---

## 发布到 npm

```bash
# 登录 npm
npm login --registry=https://registry.npmjs.org/

# 构建并发布
pnpm build
npm publish

# 或使用快捷命令
pnpm release        # 发布 patch 版本
pnpm release:minor  # 发布 minor 版本
pnpm release:major  # 发布 major 版本
```

详细发布指南请参阅 [PUBLISH.md](./PUBLISH.md)

---

## License

MIT
