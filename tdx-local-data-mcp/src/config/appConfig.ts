/**
 * 应用配置
 * 读取 .env，推导默认路径，校验必填项
 */
import path from "node:path";
import fs from "node:fs";
import dotenv from "dotenv";
import { AppError } from "../exception/AppError.js";

export interface AppConfig {
  /** 通达信安装根目录 (必填) */
  tdxInstallPath: string;
  /** 自选股目录 */
  watchlistPath: string;
  /** 持仓导入目录 */
  positionImportDir: string;
  /** 交易记录导入目录 */
  tradeImportDir: string;
  /** SQLite 数据库路径 */
  sqlitePath: string;
}

let cachedConfig: AppConfig | null = null;

/**
 * 加载并返回应用配置（单例）
 */
export function loadConfig(): AppConfig {
  if (cachedConfig) return cachedConfig;

  // 尝试从多个位置加载 .env
  dotenv.config(); // 默认从 process.cwd() 加载
  dotenv.config({ path: path.resolve(import.meta.dirname, "../../.env") }); // 项目根目录

  const tdxInstallPath = process.env["TDX_INSTALL_PATH"];
  if (!tdxInstallPath || tdxInstallPath.trim() === "") {
    throw AppError.badRequest(
      "环境变量 TDX_INSTALL_PATH 未配置，请在 .env 文件中设置"
    );
  }

  const resolvedInstallPath = path.resolve(tdxInstallPath);

  // 校验通达信安装目录存在
  if (!fs.existsSync(resolvedInstallPath)) {
    throw AppError.badRequest(
      `通达信安装目录不存在: ${resolvedInstallPath}`
    );
  }

  // 推导默认路径
  const watchlistPath = path.join(resolvedInstallPath, "T0002", "blocknew");
  const positionImportDir = path.join(
    resolvedInstallPath,
    "tdx-local-data-mcp",
    "import",
    "positions"
  );
  const tradeImportDir = path.join(
    resolvedInstallPath,
    "tdx-local-data-mcp",
    "import",
    "trades"
  );

  // SQLITE_PATH: 用户配置优先，否则默认在通达信安装目录下
  const sqlitePath =
    process.env["SQLITE_PATH"]?.trim() ||
    path.join(resolvedInstallPath, "tdx-local-data-mcp.db");

  // 自动创建导入目录
  ensureDir(positionImportDir);
  ensureDir(tradeImportDir);

  cachedConfig = {
    tdxInstallPath: resolvedInstallPath,
    watchlistPath,
    positionImportDir,
    tradeImportDir,
    sqlitePath,
  };

  return cachedConfig;
}

function ensureDir(dir: string): void {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}
