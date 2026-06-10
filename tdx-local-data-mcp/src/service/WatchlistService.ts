/**
 * 自选股服务
 */
import { loadConfig } from "../config/appConfig.js";
import { WatchlistRepository } from "../repository/WatchlistRepository.js";
import { SyncLogService } from "./SyncLogService.js";
import { scanWatchlistDir } from "../parser/TdxBlkParser.js";
import type { WatchlistSecurityRow } from "../entity/WatchlistSecurity.js";

export class WatchlistService {
  private repo = new WatchlistRepository();
  private syncLog = new SyncLogService();

  /**
   * 同步通达信自选股
   */
  syncTdxWatchlist(): {
    syncedCount: number;
    warnings: string[];
    fileCount: number;
  } {
    const config = loadConfig();
    const logId = this.syncLog.start(
      "sync_tdx_watchlist",
      `开始同步自选股: ${config.watchlistPath}`
    );

    try {
      const result = scanWatchlistDir(config.watchlistPath, "tdx");

      if (result.items.length === 0) {
        const msg =
          result.warnings.length > 0
            ? `未找到自选股数据。警告: ${result.warnings.join("; ")}`
            : "未找到自选股数据";
        this.syncLog.fail(logId, msg);
        return { syncedCount: 0, warnings: result.warnings, fileCount: 0 };
      }

      // 统计分组数量
      const groups = new Set(result.items.map((i) => i.groupName));

      const count = this.repo.upsertBatch(result.items);
      const msg = `同步成功: ${count} 条自选股, ${groups.size} 个分组${
        result.warnings.length > 0
          ? `, 警告: ${result.warnings.join("; ")}`
          : ""
      }`;
      this.syncLog.success(logId, msg);

      return {
        syncedCount: count,
        warnings: result.warnings,
        fileCount: groups.size,
      };
    } catch (err) {
      const msg = `同步失败: ${String(err)}`;
      this.syncLog.fail(logId, msg);
      throw err;
    }
  }

  /**
   * 查询自选股列表
   */
  getWatchlist(
    groupName?: string,
    securityType?: string
  ): WatchlistSecurityRow[] {
    return this.repo.query(groupName, securityType);
  }

  /**
   * 查询某证券是否在自选股中
   */
  findBySecurityCode(securityCode: string): WatchlistSecurityRow[] {
    return this.repo.findBySecurityCode(securityCode);
  }
}
