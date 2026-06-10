```text
请为我生成一个完整可运行的本地 MCP Server 项目。

项目名称：
tdx-local-data-mcp

技术栈：
- TypeScript
- Node.js 20+
- MCP TypeScript SDK
- SQLite
- Windows 本地运行
- pnpm 或 npm 均可，优先 pnpm

项目目标：
让 AI 工具通过 MCP 调用本机工具，读取、同步、查询通达信/华宝证券客户端相关的本地投资数据。

需要支持的数据：
1. 通达信自选股
2. 持仓股
3. 交易记录
4. 后续可扩展 ETF 行情数据、投资复盘分析数据

重要原则：
- 这是本地数据 MCP 工具，不是交易系统
- 只读取本地文件
- 不连接券商交易接口
- 不自动下单
- 不保存证券账户密码
- 不执行系统命令
- 不删除用户文件

请生成完整项目，不要只给片段。

---

## 一、项目结构

请生成类似结构：

tdx-local-data-mcp/
├─ package.json
├─ tsconfig.json
├─ README.md
├─ .env.example
├─ data/
│  └─ .gitkeep
├─ examples/
│  ├─ positions.csv
│  └─ trades.csv
├─ src/
│  ├─ index.ts
│  ├─ config/
│  │  └─ appConfig.ts
│  ├─ mcp/
│  │  └─ tools.ts
│  ├─ db/
│  │  ├─ sqlite.ts
│  │  └─ schema.ts
│  ├─ entity/
│  │  ├─ WatchlistSecurity.ts
│  │  ├─ PositionSnapshot.ts
│  │  ├─ TradeRecord.ts
│  │  └─ SyncLog.ts
│  ├─ service/
│  │  ├─ WatchlistService.ts
│  │  ├─ PositionService.ts
│  │  ├─ TradeService.ts
│  │  ├─ SecurityOverviewService.ts
│  │  └─ SyncLogService.ts
│  ├─ parser/
│  │  ├─ TdxBlkParser.ts
│  │  ├─ CsvParser.ts
│  │  └─ ExcelParser.ts
│  ├─ repository/
│  │  ├─ WatchlistRepository.ts
│  │  ├─ PositionRepository.ts
│  │  ├─ TradeRepository.ts
│  │  └─ SyncLogRepository.ts
│  ├─ dto/
│  │  └─ toolDtos.ts
│  ├─ util/
│  │  ├─ pathGuard.ts
│  │  ├─ fieldMapper.ts
│  │  ├─ dateUtil.ts
│  │  └─ securityCodeUtil.ts
│  └─ exception/
│     └─ AppError.ts

---

## 二、配置方式

使用 .env 配置。

默认情况下只需要配置一个通达信安装根目录：

TDX_INSTALL_PATH=D:/new_tdx

其他路径全部基于 TDX_INSTALL_PATH 自动推导，不需要用户配置。

默认推导规则：

- TDX_WATCHLIST_PATH = ${TDX_INSTALL_PATH}/T0002/blocknew
- TDX_POSITION_IMPORT_DIR = ${TDX_INSTALL_PATH}/tdx-local-data-mcp/import/positions
- TDX_TRADE_IMPORT_DIR = ${TDX_INSTALL_PATH}/tdx-local-data-mcp/import/trades
- SQLITE_PATH = ${TDX_INSTALL_PATH}/tdx-local-data-mcp.db

SQLITE_PATH 支持用户单独配置。

如果用户配置了 SQLITE_PATH，则使用用户配置的路径。
如果用户没有配置 SQLITE_PATH，则默认放到通达信安装根目录下：

${TDX_INSTALL_PATH}/tdx-local-data-mcp.db

.env.example 只需要包含：

TDX_INSTALL_PATH=D:/new_tdx
# SQLITE_PATH=D:/new_tdx/tdx-local-data-mcp.db

要求：
- 程序启动时读取配置
- TDX_INSTALL_PATH 必填
- SQLITE_PATH 可选
- 如果 SQLite 数据库不存在，自动创建
- 如果导入目录不存在，自动创建
- 路径要兼容 Windows
- README 中说明默认路径推导规则

---

## 三、SQLite 表设计

请实现自动初始化 SQL，创建以下表。

### watchlist_security

字段：
- id INTEGER PRIMARY KEY AUTOINCREMENT
- source TEXT
- group_name TEXT
- market TEXT
- security_code TEXT
- security_name TEXT
- security_type TEXT
- created_at TEXT
- updated_at TEXT

唯一约束：
source + group_name + market + security_code

### position_snapshot

字段：
- id INTEGER PRIMARY KEY AUTOINCREMENT
- account_name TEXT
- snapshot_date TEXT
- market TEXT
- security_code TEXT
- security_name TEXT
- quantity REAL
- available_quantity REAL
- cost_price REAL
- market_price REAL
- market_value REAL
- profit_loss REAL
- profit_loss_ratio REAL
- created_at TEXT

索引：
account_name + snapshot_date
security_code

### trade_record

字段：
- id INTEGER PRIMARY KEY AUTOINCREMENT
- account_name TEXT
- trade_date TEXT
- trade_time TEXT
- market TEXT
- security_code TEXT
- security_name TEXT
- side TEXT
- quantity REAL
- price REAL
- amount REAL
- fee REAL
- order_no TEXT
- contract_no TEXT
- raw_source TEXT
- created_at TEXT

索引：
account_name + trade_date
security_code
contract_no

### sync_log

字段：
- id INTEGER PRIMARY KEY AUTOINCREMENT
- sync_type TEXT
- status TEXT
- message TEXT
- started_at TEXT
- finished_at TEXT

---

## 四、MCP Tools 设计

请实现以下 MCP Tools。

### 1. get_watchlist

参数：
- groupName?: string
- securityType?: string

功能：
查询自选股列表。

返回：
- groupName
- market
- securityCode
- securityName
- securityType

---

### 2. sync_tdx_watchlist

参数：
无

功能：
扫描默认自选股目录：

${TDX_INSTALL_PATH}/T0002/blocknew

解析通达信 .blk 自选股文件，并写入 SQLite。

要求：
- 记录 sync_log
- 失败时返回明确错误
- 不删除旧数据，可以 upsert
- source 固定为 tdx

---

### 3. get_positions

参数：
- accountName?: string
- snapshotDate?: string

功能：
查询持仓快照。

返回：
- accountName
- snapshotDate
- market
- securityCode
- securityName
- quantity
- availableQuantity
- costPrice
- marketPrice
- marketValue
- profitLoss
- profitLossRatio

---

### 4. import_position_file

参数：
- filePath: string

功能：
导入持仓 CSV 或 Excel 文件。

要求：
- filePath 必须在默认持仓导入目录下：

${TDX_INSTALL_PATH}/tdx-local-data-mcp/import/positions

- 支持 .csv、.xlsx、.xls
- 支持中文字段名映射
- 导入后写入 position_snapshot
- 记录 sync_log

---

### 5. get_trades

参数：
- accountName?: string
- startDate?: string
- endDate?: string
- securityCode?: string
- side?: string

功能：
查询交易记录。

返回：
- accountName
- tradeDate
- tradeTime
- market
- securityCode
- securityName
- side
- quantity
- price
- amount
- fee
- orderNo
- contractNo

---

### 6. import_trade_file

参数：
- filePath: string

功能：
导入交易记录 CSV 或 Excel 文件。

要求：
- filePath 必须在默认交易记录导入目录下：

${TDX_INSTALL_PATH}/tdx-local-data-mcp/import/trades

- 支持 .csv、.xlsx、.xls
- 支持中文字段名映射
- 导入后写入 trade_record
- 记录 sync_log

---

### 7. get_security_overview

参数：
- securityCode: string

功能：
查询单个标的的综合信息。

返回：
- 是否在自选股中
- 所属自选分组
- 最新持仓情况
- 最近 10 条交易记录
- 总买入金额
- 总卖出金额
- 净买入金额
- 当前浮动盈亏，如果有持仓数据

---

### 8. get_sync_logs

参数：
- syncType?: string
- limit?: number

功能：
查询同步/导入日志。

默认 limit = 20。

---

## 五、通达信 .blk 自选股解析

请实现 TdxBlkParser。

要求：
- 扫描 .blk 文件
- 每一行可能是类似：
  0|000001
  1|600000
  0|159915
  1|510300

市场规则：
- 0 表示深市
- 1 表示沪市

转换规则：
- market=SZ 或 SH
- security_code 保留 6 位代码
- security_type 简单判断：
  - 以 51、56、58 开头，通常为沪市 ETF
  - 以 15、16、18 开头，通常为深市 ETF
  - 其他默认 STOCK
- security_name 第一阶段可以为空，后续预留扩展
- group_name 使用 .blk 文件名，不含扩展名

要求：
- 解析时忽略空行
- 忽略非法代码
- 代码必须是 6 位数字
- 保留错误日志，但不要因为单行错误导致整体失败

---

## 六、CSV / Excel 字段映射

请实现 fieldMapper。

需要支持这些中文字段名。

### 通用

证券代码：
- 证券代码
- 代码
- 股票代码
- 基金代码
- 标的代码

证券名称：
- 证券名称
- 名称
- 股票名称
- 基金名称
- 标的名称

账户名称：
- 账户
- 账户名称
- 资金账号
- 股东账号

市场：
- 市场
- 交易市场
- 证券市场

### 持仓字段

快照日期：
- 快照日期
- 日期
- 持仓日期

持仓数量：
- 持仓数量
- 当前持仓
- 数量
- 证券数量

可用数量：
- 可用数量
- 可用余额
- 可卖数量

成本价：
- 成本价
- 成本价格
- 持仓成本价

现价：
- 现价
- 最新价
- 市价

市值：
- 市值
- 参考市值
- 最新市值

盈亏：
- 盈亏
- 浮动盈亏
- 参考盈亏

盈亏比例：
- 盈亏比例
- 盈亏率
- 参考盈亏比例

### 交易字段

交易日期：
- 交易日期
- 成交日期
- 日期

交易时间：
- 交易时间
- 成交时间
- 时间

买卖方向：
- 买卖方向
- 操作
- 买卖
- 业务名称

成交数量：
- 成交数量
- 数量
- 发生数量

成交价格：
- 成交价格
- 价格
- 成交均价

成交金额：
- 成交金额
- 金额
- 发生金额

手续费：
- 手续费
- 费用
- 佣金

委托编号：
- 委托编号
- 订单号
- 委托号

合同编号：
- 合同编号
- 成交编号
- 合同号

要求：
- 字段映射要集中管理
- CSV/Excel 表头允许有空格
- 数字字段要支持逗号、百分号、空字符串
- 日期支持 yyyy-MM-dd、yyyy/MM/dd、yyyyMMdd
- 方向字段统一成 BUY、SELL、OTHER

---

## 七、安全边界

必须实现 pathGuard。

要求：
- import_position_file 的 filePath 只能位于：

${TDX_INSTALL_PATH}/tdx-local-data-mcp/import/positions

- import_trade_file 的 filePath 只能位于：

${TDX_INSTALL_PATH}/tdx-local-data-mcp/import/trades

- sync_tdx_watchlist 只能扫描：

${TDX_INSTALL_PATH}/T0002/blocknew

- 禁止读取任意路径
- 禁止路径穿越，例如 ../
- 禁止删除文件
- 禁止执行系统命令
- 所有文件读取异常都要返回友好错误

---

## 八、依赖建议

可以使用这些依赖：

- @modelcontextprotocol/sdk
- zod
- better-sqlite3 或 sqlite/sqlite3
- csv-parse
- xlsx
- dotenv
- fast-glob

请根据 TypeScript 项目最佳实践选择依赖。

要求：
- 如果 better-sqlite3 在 Windows 编译麻烦，请在 README 中说明替代方案
- 代码要尽量简单可靠

---

## 九、README.md 要求

README 必须包含：

1. 项目用途
2. 为什么使用 MCP
3. 安装依赖
4. 配置 .env
5. 默认目录说明
6. 初始化/启动项目
7. 如何连接到支持 MCP 的 AI 工具
8. 每个 MCP Tool 的参数和返回说明
9. 通达信自选股目录说明
10. 持仓 CSV/Excel 示例格式
11. 交易记录 CSV/Excel 示例格式
12. 安全边界说明
13. 后续扩展建议

MCP 客户端配置示例请包含：

{
  "mcpServers": {
    "tdx-local-data-mcp": {
      "command": "node",
      "args": ["D:/path/to/tdx-local-data-mcp/dist/index.js"],
      "env": {
        "TDX_INSTALL_PATH": "D:/new_tdx"
      }
    }
  }
}

如果用户想自定义 SQLite 路径，可以这样配置：

{
  "mcpServers": {
    "tdx-local-data-mcp": {
      "command": "node",
      "args": ["D:/path/to/tdx-local-data-mcp/dist/index.js"],
      "env": {
        "TDX_INSTALL_PATH": "D:/new_tdx",
        "SQLITE_PATH": "D:/data/tdx-local-data-mcp.db"
      }
    }
  }
}

---

## 十、示例数据

请在 examples 目录生成：

positions.csv

字段示例：
账户名称,快照日期,市场,证券代码,证券名称,持仓数量,可用数量,成本价,现价,市值,盈亏,盈亏比例

trades.csv

字段示例：
账户名称,交易日期,交易时间,市场,证券代码,证券名称,买卖方向,成交数量,成交价格,成交金额,手续费,委托编号,合同编号

---

## 十一、代码质量要求

- TypeScript 严格模式
- 函数命名清晰
- 模块边界清晰
- MCP Tool 参数使用 zod 校验
- 错误处理统一
- SQLite 操作封装在 repository
- 业务逻辑封装在 service
- 文件解析封装在 parser
- 不要写伪代码
- 不要省略关键文件
- 项目应能执行：

pnpm install
pnpm build
pnpm start

或者：

npm install
npm run build
npm start

---

## 十二、优先级

如果一次生成不完，请按以下顺序生成：

第一版最小可运行：
1. MCP Server 启动
2. 基于 TDX_INSTALL_PATH 推导默认路径
3. SQLite 初始化
4. sync_tdx_watchlist
5. get_watchlist
6. README

第二版：
1. import_position_file
2. get_positions
3. CSV/Excel 持仓解析

第三版：
1. import_trade_file
2. get_trades
3. get_security_overview
4. get_sync_logs

请先输出完整项目结构，再逐个输出完整代码文件。
```
