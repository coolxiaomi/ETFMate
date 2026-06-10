/**
 * 自选股仓储
 */
import { getDb } from "../db/sqlite.js";
import { nowString } from "../util/dateUtil.js";
import type {
  WatchlistSecurity,
  WatchlistSecurityRow,
} from "../entity/WatchlistSecurity.js";

export class WatchlistRepository {
  /**
   * Upsert 自选股记录
   */
  upsert(item: WatchlistSecurity): void {
    const db = getDb();
    const now = nowString();
    db.prepare(
      `INSERT INTO watchlist_security (source, group_name, market, security_code, security_name, security_type, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(source, group_name, market, security_code)
       DO UPDATE SET security_name = excluded.security_name,
                     security_type = excluded.security_type,
                     updated_at = excluded.updated_at`
    ).run(
      item.source,
      item.groupName,
      item.market,
      item.securityCode,
      item.securityName,
      item.securityType,
      now,
      now
    );
  }

  /**
   * 批量 Upsert
   */
  upsertBatch(items: WatchlistSecurity[]): number {
    const db = getDb();
    let count = 0;
    const transaction = db.transaction(() => {
      for (const item of items) {
        this.upsert(item);
        count++;
      }
    });
    transaction();
    return count;
  }

  /**
   * 查询自选股列表
   */
  query(groupName?: string, securityType?: string): WatchlistSecurityRow[] {
    const db = getDb();
    let sql = `SELECT * FROM watchlist_security WHERE 1=1`;
    const params: (string | number)[] = [];

    if (groupName) {
      sql += ` AND group_name = ?`;
      params.push(groupName);
    }
    if (securityType) {
      sql += ` AND security_type = ?`;
      params.push(securityType);
    }

    sql += ` ORDER BY group_name, market, security_code`;

    return db.prepare(sql).all(...params) as WatchlistSecurityRow[];
  }

  /**
   * 查询某证券是否在自选股中
   */
  findBySecurityCode(securityCode: string): WatchlistSecurityRow[] {
    const db = getDb();
    return db
      .prepare(
        `SELECT * FROM watchlist_security WHERE security_code = ?`
      )
      .all(securityCode) as WatchlistSecurityRow[];
  }
}
