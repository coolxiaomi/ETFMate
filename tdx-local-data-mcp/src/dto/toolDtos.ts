/**
 * MCP Tool 参数 Zod Schema 定义
 */
import { z } from "zod";

// ────────────────────────────────────────────
//  get_watchlist
// ────────────────────────────────────────────
export const GetWatchlistSchema = {
  groupName: z.string().optional().describe("自选股分组名称"),
  securityType: z
    .string()
    .optional()
    .describe("证券类型筛选: ETF, STOCK"),
};

// ────────────────────────────────────────────
//  sync_tdx_watchlist
// ────────────────────────────────────────────
export const SyncTdxWatchlistSchema = {};

// ────────────────────────────────────────────
//  get_positions
// ────────────────────────────────────────────
export const GetPositionsSchema = {
  accountName: z.string().optional().describe("账户名称"),
  snapshotDate: z.string().optional().describe("快照日期 yyyy-MM-dd"),
};

// ────────────────────────────────────────────
//  import_position_file
// ────────────────────────────────────────────
export const ImportPositionFileSchema = {
  filePath: z.string().describe("持仓文件路径 (CSV 或 Excel)"),
};

// ────────────────────────────────────────────
//  get_trades
// ────────────────────────────────────────────
export const GetTradesSchema = {
  accountName: z.string().optional().describe("账户名称"),
  startDate: z.string().optional().describe("开始日期 yyyy-MM-dd"),
  endDate: z.string().optional().describe("结束日期 yyyy-MM-dd"),
  securityCode: z.string().optional().describe("证券代码"),
  side: z
    .string()
    .optional()
    .describe("买卖方向: BUY, SELL, OTHER"),
};

// ────────────────────────────────────────────
//  import_trade_file
// ────────────────────────────────────────────
export const ImportTradeFileSchema = {
  filePath: z.string().describe("交易记录文件路径 (CSV 或 Excel)"),
};

// ────────────────────────────────────────────
//  get_security_overview
// ────────────────────────────────────────────
export const GetSecurityOverviewSchema = {
  securityCode: z.string().describe("证券代码 (6 位数字)"),
};

// ────────────────────────────────────────────
//  get_sync_logs
// ────────────────────────────────────────────
export const GetSyncLogsSchema = {
  syncType: z.string().optional().describe("同步类型筛选"),
  limit: z.number().optional().default(20).describe("返回条数限制，默认 20"),
};
