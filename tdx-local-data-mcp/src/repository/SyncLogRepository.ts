/**
 * 同步日志仓储
 */
import { getDb } from "../db/sqlite.js";
import { nowString } from "../util/dateUtil.js";
import type { SyncLogRow } from "../entity/SyncLog.js";

export class SyncLogRepository {
  /**
   * 创建同步日志，返回日志 ID
   */
  create(syncType: string, status: string, message: string = ""): number {
    const db = getDb();
    const startedAt = nowString();
    const stmt = db.prepare(
      `INSERT INTO sync_log (sync_type, status, message, started_at)
       VALUES (?, ?, ?, ?)`
    );
    const result = stmt.run(syncType, status, message, startedAt);
    return Number(result.lastInsertRowid);
  }

  /**
   * 更新同步日志为完成状态
   */
  finish(id: number, status: string, message: string = ""): void {
    const db = getDb();
    const finishedAt = nowString();
    db.prepare(
      `UPDATE sync_log SET status = ?, message = ?, finished_at = ? WHERE id = ?`
    ).run(status, message, finishedAt, id);
  }

  /**
   * 查询同步日志
   */
  query(syncType?: string, limit: number = 20): SyncLogRow[] {
    const db = getDb();
    if (syncType) {
      return db
        .prepare(
          `SELECT * FROM sync_log WHERE sync_type = ? ORDER BY id DESC LIMIT ?`
        )
        .all(syncType, limit) as SyncLogRow[];
    }
    return db
      .prepare(`SELECT * FROM sync_log ORDER BY id DESC LIMIT ?`)
      .all(limit) as SyncLogRow[];
  }
}
