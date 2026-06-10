/**
 * SQLite 建表 DDL
 */

export const CREATE_WATCHLIST_SECURITY = `
CREATE TABLE IF NOT EXISTS watchlist_security (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  source      TEXT NOT NULL,
  group_name  TEXT NOT NULL,
  market      TEXT NOT NULL,
  security_code TEXT NOT NULL,
  security_name TEXT NOT NULL DEFAULT '',
  security_type TEXT NOT NULL DEFAULT 'STOCK',
  created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  UNIQUE(source, group_name, market, security_code)
);
`;

export const CREATE_POSITION_SNAPSHOT = `
CREATE TABLE IF NOT EXISTS position_snapshot (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  account_name      TEXT NOT NULL DEFAULT '',
  snapshot_date     TEXT NOT NULL DEFAULT '',
  market            TEXT NOT NULL DEFAULT '',
  security_code     TEXT NOT NULL,
  security_name     TEXT NOT NULL DEFAULT '',
  quantity          REAL NOT NULL DEFAULT 0,
  available_quantity REAL NOT NULL DEFAULT 0,
  cost_price        REAL,
  market_price      REAL,
  market_value      REAL,
  profit_loss       REAL,
  profit_loss_ratio REAL,
  created_at        TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_position_account_date
  ON position_snapshot(account_name, snapshot_date);
CREATE INDEX IF NOT EXISTS idx_position_security_code
  ON position_snapshot(security_code);
`;

export const CREATE_TRADE_RECORD = `
CREATE TABLE IF NOT EXISTS trade_record (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  account_name  TEXT NOT NULL DEFAULT '',
  trade_date    TEXT NOT NULL DEFAULT '',
  trade_time    TEXT NOT NULL DEFAULT '',
  market        TEXT NOT NULL DEFAULT '',
  security_code TEXT NOT NULL,
  security_name TEXT NOT NULL DEFAULT '',
  side          TEXT NOT NULL DEFAULT 'OTHER',
  quantity      REAL NOT NULL DEFAULT 0,
  price         REAL NOT NULL DEFAULT 0,
  amount        REAL,
  fee           REAL,
  order_no      TEXT NOT NULL DEFAULT '',
  contract_no   TEXT NOT NULL DEFAULT '',
  raw_source    TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_trade_account_date
  ON trade_record(account_name, trade_date);
CREATE INDEX IF NOT EXISTS idx_trade_security_code
  ON trade_record(security_code);
CREATE INDEX IF NOT EXISTS idx_trade_contract_no
  ON trade_record(contract_no);
`;

export const CREATE_SYNC_LOG = `
CREATE TABLE IF NOT EXISTS sync_log (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  sync_type   TEXT NOT NULL,
  status      TEXT NOT NULL,
  message     TEXT NOT NULL DEFAULT '',
  started_at  TEXT NOT NULL,
  finished_at TEXT
);
`;
