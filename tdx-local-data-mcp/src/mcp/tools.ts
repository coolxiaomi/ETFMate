/**
 * MCP Tools 注册
 * 注册全部 8 个 MCP Tools 到 McpServer
 */
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import {
  GetWatchlistSchema,
  GetPositionsSchema,
  ImportPositionFileSchema,
  GetTradesSchema,
  ImportTradeFileSchema,
  GetSecurityOverviewSchema,
  GetSyncLogsSchema,
} from "../dto/toolDtos.js";
import { WatchlistService } from "../service/WatchlistService.js";
import { PositionService } from "../service/PositionService.js";
import { TradeService } from "../service/TradeService.js";
import { SecurityOverviewService } from "../service/SecurityOverviewService.js";
import { SyncLogService } from "../service/SyncLogService.js";
import { AppError } from "../exception/AppError.js";

function jsonResponse(data: unknown): { content: { type: "text"; text: string }[] } {
  return {
    content: [{ type: "text" as const, text: JSON.stringify(data, null, 2) }],
  };
}

function errorResponse(err: unknown): { content: { type: "text"; text: string }[]; isError: boolean } {
  const message = err instanceof AppError ? `[${err.code}] ${err.message}` : String(err);
  return {
    content: [{ type: "text" as const, text: message }],
    isError: true,
  };
}

/**
 * 注册全部 MCP Tools
 */
export function registerTools(server: McpServer): void {
  const watchlistService = new WatchlistService();
  const positionService = new PositionService();
  const tradeService = new TradeService();
  const securityOverviewService = new SecurityOverviewService();
  const syncLogService = new SyncLogService();

  // ── 1. get_watchlist ──────────────────────
  server.tool(
    "get_watchlist",
    "查询自选股列表。可按分组名称和证券类型筛选。",
    GetWatchlistSchema,
    async (params) => {
      try {
        const rows = watchlistService.getWatchlist(
          params.groupName,
          params.securityType
        );
        return jsonResponse({
          total: rows.length,
          items: rows.map((r) => ({
            groupName: r.group_name,
            market: r.market,
            securityCode: r.security_code,
            securityName: r.security_name,
            securityType: r.security_type,
          })),
        });
      } catch (err) {
        return errorResponse(err);
      }
    }
  );

  // ── 2. sync_tdx_watchlist ─────────────────
  server.tool(
    "sync_tdx_watchlist",
    "同步通达信自选股。扫描通达信 .blk 自选股文件并写入 SQLite 数据库。",
    {},
    async () => {
      try {
        const result = watchlistService.syncTdxWatchlist();
        return jsonResponse({
          success: true,
          syncedCount: result.syncedCount,
          groupCount: result.fileCount,
          warnings: result.warnings,
        });
      } catch (err) {
        return errorResponse(err);
      }
    }
  );

  // ── 3. get_positions ──────────────────────
  server.tool(
    "get_positions",
    "查询持仓快照。可按账户名称和快照日期筛选。",
    GetPositionsSchema,
    async (params) => {
      try {
        const rows = positionService.getPositions(
          params.accountName,
          params.snapshotDate
        );
        return jsonResponse({
          total: rows.length,
          items: rows.map((r) => ({
            accountName: r.account_name,
            snapshotDate: r.snapshot_date,
            market: r.market,
            securityCode: r.security_code,
            securityName: r.security_name,
            quantity: r.quantity,
            availableQuantity: r.available_quantity,
            costPrice: r.cost_price,
            marketPrice: r.market_price,
            marketValue: r.market_value,
            profitLoss: r.profit_loss,
            profitLossRatio: r.profit_loss_ratio,
          })),
        });
      } catch (err) {
        return errorResponse(err);
      }
    }
  );

  // ── 4. import_position_file ───────────────
  server.tool(
    "import_position_file",
    "导入持仓文件 (CSV/Excel)。文件必须位于持仓导入目录下。",
    ImportPositionFileSchema,
    async (params) => {
      try {
        const result = positionService.importPositionFile(params.filePath);
        return jsonResponse({
          success: true,
          importedCount: result.importedCount,
          filePath: result.filePath,
        });
      } catch (err) {
        return errorResponse(err);
      }
    }
  );

  // ── 5. get_trades ─────────────────────────
  server.tool(
    "get_trades",
    "查询交易记录。支持按账户、日期范围、证券代码、买卖方向筛选。",
    GetTradesSchema,
    async (params) => {
      try {
        const rows = tradeService.getTrades({
          accountName: params.accountName,
          startDate: params.startDate,
          endDate: params.endDate,
          securityCode: params.securityCode,
          side: params.side,
        });
        return jsonResponse({
          total: rows.length,
          items: rows.map((r) => ({
            accountName: r.account_name,
            tradeDate: r.trade_date,
            tradeTime: r.trade_time,
            market: r.market,
            securityCode: r.security_code,
            securityName: r.security_name,
            side: r.side,
            quantity: r.quantity,
            price: r.price,
            amount: r.amount,
            fee: r.fee,
            orderNo: r.order_no,
            contractNo: r.contract_no,
          })),
        });
      } catch (err) {
        return errorResponse(err);
      }
    }
  );

  // ── 6. import_trade_file ──────────────────
  server.tool(
    "import_trade_file",
    "导入交易记录文件 (CSV/Excel)。文件必须位于交易记录导入目录下。",
    ImportTradeFileSchema,
    async (params) => {
      try {
        const result = tradeService.importTradeFile(params.filePath);
        return jsonResponse({
          success: true,
          importedCount: result.importedCount,
          filePath: result.filePath,
        });
      } catch (err) {
        return errorResponse(err);
      }
    }
  );

  // ── 7. get_security_overview ──────────────
  server.tool(
    "get_security_overview",
    "查询单个标的的综合信息：自选股状态、最新持仓、最近交易、买卖统计。",
    GetSecurityOverviewSchema,
    async (params) => {
      try {
        const overview = securityOverviewService.getOverview(
          params.securityCode
        );
        return jsonResponse(overview);
      } catch (err) {
        return errorResponse(err);
      }
    }
  );

  // ── 8. get_sync_logs ──────────────────────
  server.tool(
    "get_sync_logs",
    "查询同步/导入日志。默认返回最近 20 条。",
    GetSyncLogsSchema,
    async (params) => {
      try {
        const rows = syncLogService.query(params.syncType, params.limit);
        return jsonResponse({
          total: rows.length,
          items: rows.map((r) => ({
            syncType: r.sync_type,
            status: r.status,
            message: r.message,
            startedAt: r.started_at,
            finishedAt: r.finished_at,
          })),
        });
      } catch (err) {
        return errorResponse(err);
      }
    }
  );
}
