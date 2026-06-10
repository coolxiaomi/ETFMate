/**
 * 持仓服务
 */
import path from "node:path";
import { loadConfig } from "../config/appConfig.js";
import { PositionRepository } from "../repository/PositionRepository.js";
import { SyncLogService } from "./SyncLogService.js";
import { assertWithinDir, assertFileExtension } from "../util/pathGuard.js";
import {
  buildFieldMapping,
  mapRow,
  normalizePositionRow,
} from "../util/fieldMapper.js";
import { parseCsvFile } from "../parser/CsvParser.js";
import { parseExcelFile } from "../parser/ExcelParser.js";
import type { PositionSnapshotRow } from "../entity/PositionSnapshot.js";

export class PositionService {
  private repo = new PositionRepository();
  private syncLog = new SyncLogService();

  /**
   * 导入持仓文件
   */
  importPositionFile(filePath: string): {
    importedCount: number;
    filePath: string;
  } {
    const config = loadConfig();

    // 路径安全校验
    const safePath = assertWithinDir(filePath, config.positionImportDir);
    assertFileExtension(safePath, [".csv", ".xlsx", ".xls"]);

    const logId = this.syncLog.start(
      "import_position_file",
      `开始导入持仓文件: ${safePath}`
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
      if (!mapping.columnMap.has([...mapping.columnMap.keys()].find(k => mapping.columnMap.get(k) === "securityCode") ?? "__none__")) {
        this.syncLog.fail(logId, `缺少必填字段: 证券代码。可用表头: ${parsed.headers.join(", ")}`);
        throw new Error(`缺少必填字段: 证券代码。文件中可用表头: ${parsed.headers.join(", ")}`);
      }

      // 转换数据
      const snapshots = parsed.rows
        .map((row) => {
          const mapped = mapRow(row, mapping);
          return normalizePositionRow(mapped);
        })
        .filter((s) => s.securityCode !== "");

      const count = this.repo.insertBatch(snapshots);
      const msg = `导入成功: ${count} 条持仓记录`;
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
   * 查询持仓
   */
  getPositions(
    accountName?: string,
    snapshotDate?: string
  ): PositionSnapshotRow[] {
    return this.repo.query(accountName, snapshotDate);
  }
}
