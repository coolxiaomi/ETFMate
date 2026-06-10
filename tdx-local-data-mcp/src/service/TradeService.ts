/**
 * 交易记录服务
 */
import path from "node:path";
import { loadConfig } from "../config/appConfig.js";
import { TradeRepository } from "../repository/TradeRepository.js";
import { SyncLogService } from "./SyncLogService.js";
import { assertWithinDir, assertFileExtension } from "../util/pathGuard.js";
import {
  buildFieldMapping,
  mapRow,
  normalizeTradeRow,
} from "../util/fieldMapper.js";
import { parseCsvFile } from "../parser/CsvParser.js";
import { parseExcelFile } from "../parser/ExcelParser.js";
import type { TradeRecordRow } from "../entity/TradeRecord.js";

export class TradeService {
  private repo = new TradeRepository();
  private syncLog = new SyncLogService();

  /**
   * 导入交易记录文件
   */
  importTradeFile(filePath: string): {
    importedCount: number;
    filePath: string;
  } {
    const config = loadConfig();

    // 路径安全校验
    const safePath = assertWithinDir(filePath, config.tradeImportDir);
    assertFileExtension(safePath, [".csv", ".xlsx", ".xls"]);

    const logId = this.syncLog.start(
      "import_trade_file",
      `开始导入交易文件: ${safePath}`
    );

    try {
      // 解析文件
      const ext = path.extname(safePath).toLowerCase();
      const parsed =
        ext === ".csv"
          ? parseCsvFile(safePath)
          : parseExcelFile(safePath);

      if (parsed.rows.length === 0) {
        this.syncLog.fail(logId, "文件中无数据行");
        return { importedCount: 0, filePath: safePath };
      }

      // 字段映射
      const mapping = buildFieldMapping(parsed.headers);

      // 检查必填字段
      const hasSecurityCode = [...mapping.columnMap.values()].includes("securityCode");
      if (!hasSecurityCode) {
        this.syncLog.fail(logId, `缺少必填字段: 证券代码。可用表头: ${parsed.headers.join(", ")}`);
        throw new Error(`缺少必填字段: 证券代码。文件中可用表头: ${parsed.headers.join(", ")}`);
      }

      // 转换数据
      const records = parsed.rows
        .map((row) => {
          const mapped = mapRow(row, mapping);
          return normalizeTradeRow(mapped);
        })
        .filter((r) => r.securityCode !== "");

      const count = this.repo.insertBatch(records);
      const msg = `导入成功: ${count} 条交易记录`;
      this.syncLog.success(logId, msg);

      return { importedCount: count, filePath: safePath };
    } catch (err) {
      if (String(err).includes("缺少必填字段")) throw err;
      const msg = `导入失败: ${String(err)}`;
      this.syncLog.fail(logId, msg);
      throw err;
    }
  }

  /**
   * 查询交易记录
   */
  getTrades(params: {
    accountName?: string;
    startDate?: string;
    endDate?: string;
    securityCode?: string;
    side?: string;
  }): TradeRecordRow[] {
    return this.repo.query(params);
  }
}
