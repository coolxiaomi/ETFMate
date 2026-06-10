/**
 * SQLite 连接管理
 * 自动建表，单例模式
 */
import Database from "better-sqlite3";
import path from "node:path";
import fs from "node:fs";
import { loadConfig } from "../config/appConfig.js";
import {
  CREATE_WATCHLIST_SECURITY,
  CREATE_POSITION_SNAPSHOT,
  CREATE_TRADE_RECORD,
  CREATE_SYNC_LOG,
} from "./schema.js";

let dbInstance: Database.Database | null = null;

/**
 * 获取数据库连接（单例）
 */
export function getDb(): Database.Database {
  if (dbInstance) return dbInstance;

  const config = loadConfig();
  const dbDir = path.dirname(config.sqlitePath);

  // 确保数据库目录存在
  if (!fs.existsSync(dbDir)) {
    fs.mkdirSync(dbDir, { recursive: true });
  }

  dbInstance = new Database(config.sqlitePath);

  // 开启 WAL 模式提高并发性能
  dbInstance.pragma("journal_mode = WAL");

  // 自动建表
  initSchema(dbInstance);

  return dbInstance;
}

/**
 * 初始化表结构
 */
function initSchema(db: Database.Database): void {
  db.exec(CREATE_WATCHLIST_SECURITY);
  db.exec(CREATE_POSITION_SNAPSHOT);
  db.exec(CREATE_TRADE_RECORD);
  db.exec(CREATE_SYNC_LOG);
}

/**
 * 关闭数据库连接
 */
export function closeDb(): void {
  if (dbInstance) {
    dbInstance.close();
    dbInstance = null;
  }
}
