/**
 * 交易记录仓储
 */
import { getDb } from "../db/sqlite.js";
import type { TradeRecord, TradeRecordRow } from "../entity/TradeRecord.js";

export class TradeRepository {
  /**
   * 批量插入交易记录
   */
  insertBatch(items: TradeRecord[]): number {
    const db = getDb();
    let count = 0;
    const stmt = db.prepare(
      `INSERT INTO trade_record
       (account_name, trade_date, trade_time, market, security_code, security_name,
        side, quantity, price, amount, fee, order_no, contract_no, raw_source)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
    );

    const transaction = db.transaction(() => {
      for (const item of items) {
        stmt.run(
          item.accountName,
          item.tradeDate,
          item.tradeTime,
          item.market,
          item.securityCode,
          item.securityName,
          item.side,
          item.quantity,
          item.price,
          item.amount,
          item.fee,
          item.orderNo,
          item.contractNo,
          item.rawSource ?? ""
        );
        count++;
      }
    });
    transaction();
    return count;
  }

  /**
   * 查询交易记录
   */
  query(params: {
    accountName?: string;
    startDate?: string;
    endDate?: string;
    securityCode?: string;
    side?: string;
  }): TradeRecordRow[] {
    const db = getDb();
    let sql = `SELECT * FROM trade_record WHERE 1=1`;
    const queryParams: (string | number)[] = [];

    if (params.accountName) {
      sql += ` AND account_name = ?`;
      queryParams.push(params.accountName);
    }
    if (params.startDate) {
      sql += ` AND trade_date >= ?`;
      queryParams.push(params.startDate);
    }
    if (params.endDate) {
      sql += ` AND trade_date <= ?`;
      queryParams.push(params.endDate);
    }
    if (params.securityCode) {
      sql += ` AND security_code = ?`;
      queryParams.push(params.securityCode);
    }
    if (params.side) {
      sql += ` AND side = ?`;
      queryParams.push(params.side);
    }

    sql += ` ORDER BY trade_date DESC, trade_time DESC`;

    return db.prepare(sql).all(...queryParams) as TradeRecordRow[];
  }

  /**
   * 查询某证券的交易记录
   */
  findBySecurityCode(securityCode: string, limit: number = 10): TradeRecordRow[] {
    const db = getDb();
    return db
      .prepare(
        `SELECT * FROM trade_record
         WHERE security_code = ?
         ORDER BY trade_date DESC, trade_time DESC
         LIMIT ?`
      )
      .all(securityCode, limit) as TradeRecordRow[];
  }

  /**
   * 统计某证券的买卖金额
   */
  aggregateBySecurityCode(securityCode: string): {
    totalBuyAmount: number;
    totalSellAmount: number;
    netBuyAmount: number;
  } {
    const db = getDb();
    const rows = db
      .prepare(
        `SELECT side, SUM(COALESCE(amount, 0)) as total_amount
         FROM trade_record
         WHERE security_code = ?
         GROUP BY side`
      )
      .all(securityCode) as { side: string; total_amount: number }[];

    let totalBuyAmount = 0;
    let totalSellAmount = 0;

    for (const row of rows) {
      if (row.side === "BUY") {
        totalBuyAmount = row.total_amount ?? 0;
      } else if (row.side === "SELL") {
        totalSellAmount = row.total_amount ?? 0;
      }
    }

    return {
      totalBuyAmount,
      totalSellAmount,
      netBuyAmount: totalBuyAmount - totalSellAmount,
    };
  }
}
