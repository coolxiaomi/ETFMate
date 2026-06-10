/**
 * 持仓仓储
 */
import { getDb } from "../db/sqlite.js";
import type {
  PositionSnapshot,
  PositionSnapshotRow,
} from "../entity/PositionSnapshot.js";

export class PositionRepository {
  /**
   * 批量插入持仓快照
   */
  insertBatch(items: PositionSnapshot[]): number {
    const db = getDb();
    let count = 0;
    const stmt = db.prepare(
      `INSERT INTO position_snapshot
       (account_name, snapshot_date, market, security_code, security_name,
        quantity, available_quantity, cost_price, market_price, market_value,
        profit_loss, profit_loss_ratio)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    );

    const transaction = db.transaction(() => {
      for (const item of items) {
        stmt.run(
          item.accountName,
          item.snapshotDate,
          item.market,
          item.securityCode,
          item.securityName,
          item.quantity,
          item.availableQuantity,
          item.costPrice,
          item.marketPrice,
          item.marketValue,
          item.profitLoss,
          item.profitLossRatio
        );
        count++;
      }
    });
    transaction();
    return count;
  }

  /**
   * 查询持仓快照
   */
  query(
    accountName?: string,
    snapshotDate?: string
  ): PositionSnapshotRow[] {
    const db = getDb();
    let sql = `SELECT * FROM position_snapshot WHERE 1=1`;
    const params: (string | number)[] = [];

    if (accountName) {
      sql += ` AND account_name = ?`;
      params.push(accountName);
    }
    if (snapshotDate) {
      sql += ` AND snapshot_date = ?`;
      params.push(snapshotDate);
    }

    sql += ` ORDER BY snapshot_date DESC, security_code`;

    return db.prepare(sql).all(...params) as PositionSnapshotRow[];
  }

  /**
   * 查询某个证券的最新持仓
   */
  findLatestBySecurityCode(
    securityCode: string
  ): PositionSnapshotRow | undefined {
    const db = getDb();
    return db
      .prepare(
        `SELECT * FROM position_snapshot
         WHERE security_code = ?
         ORDER BY snapshot_date DESC, id DESC
         LIMIT 1`
      )
      .get(securityCode) as PositionSnapshotRow | undefined;
  }
}
