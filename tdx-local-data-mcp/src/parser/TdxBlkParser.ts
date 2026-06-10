/**
 * 通达信 .blk 自选股文件解析器
 *
 * .blk 文件格式支持两种：
 * 1. "{marketId}|{code}" - 带管道符分隔
 * 2. "{marketId}{code}" - 7 位字符，第 1 位是市场，后 6 位是代码
 * marketId: 0=深市(SZ), 1=沪市(SH)
 */
import fs from "node:fs";
import path from "node:path";
import fg from "fast-glob";
import type { WatchlistSecurity } from "../entity/WatchlistSecurity.js";
import {
  isValidSecurityCode,
  marketFromTdxId,
  inferSecurityType,
} from "../util/securityCodeUtil.js";

export interface BlkParseResult {
  /** 解析出的自选股列表 */
  items: WatchlistSecurity[];
  /** 警告信息 */
  warnings: string[];
}

/**
 * 解析单行 .blk 数据
 * 支持两种格式：
 * - "0|000001" (带管道符)
 * - "0000001" (7位字符，首位是市场)
 */
function parseBlkLine(
  line: string
): { market: string; code: string } | null {
  const trimmed = line.trim();
  if (!trimmed) return null;

  let tdxId: string;
  let code: string;

  if (trimmed.includes("|")) {
    // 格式 1: market|code
    const parts = trimmed.split("|");
    if (parts.length < 2) return null;
    tdxId = parts[0].trim();
    code = parts[1].trim();
  } else if (/^[01]\d{6}$/.test(trimmed)) {
    // 格式 2: 7 位字符，首位是市场
    tdxId = trimmed[0];
    code = trimmed.substring(1);
  } else {
    return null;
  }

  if (!isValidSecurityCode(code)) return null;

  const market = marketFromTdxId(tdxId);
  if (!market) return null;

  return { market, code };
}

/**
 * 解析单个 .blk 文件
 */
export function parseBlkFile(
  filePath: string,
  groupName: string,
  source: string = "tdx"
): BlkParseResult {
  const items: WatchlistSecurity[] = [];
  const warnings: string[] = [];

  let content: string;
  try {
    // 通达信 .blk 文件通常是 GBK 编码，但内容是纯数字和管道符
    // 数字和管道符在 GBK/UTF-8 中编码相同，直接用 UTF-8 读取即可
    content = fs.readFileSync(filePath, "utf-8");
  } catch (err) {
    warnings.push(`无法读取文件 ${filePath}: ${String(err)}`);
    return { items, warnings };
  }

  const lines = content.split(/\r?\n/);

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) continue;

    const result = parseBlkLine(line);
    if (!result) {
      warnings.push(`${filePath}:${i + 1} 格式错误: "${line.trim()}"`);
      continue;
    }

    items.push({
      source,
      groupName,
      market: result.market,
      securityCode: result.code,
      securityName: "",
      securityType: inferSecurityType(result.code),
    });
  }

  return { items, warnings };
}

/**
 * 扫描自选股目录，解析所有 .blk 文件
 */
export function scanWatchlistDir(
  watchlistDir: string,
  source: string = "tdx"
): BlkParseResult {
  const allItems: WatchlistSecurity[] = [];
  const allWarnings: string[] = [];

  if (!fs.existsSync(watchlistDir)) {
    allWarnings.push(`自选股目录不存在: ${watchlistDir}`);
    return { items: allItems, warnings: allWarnings };
  }

  const blkFiles = fg.sync("*.blk", {
    cwd: watchlistDir,
    absolute: true,
    caseSensitiveMatch: false,
  });

  if (blkFiles.length === 0) {
    allWarnings.push(`自选股目录中未找到 .blk 文件: ${watchlistDir}`);
    return { items: allItems, warnings: allWarnings };
  }

  for (const blkFile of blkFiles) {
    const groupName = path.basename(blkFile, path.extname(blkFile));
    const result = parseBlkFile(blkFile, groupName, source);
    allItems.push(...result.items);
    allWarnings.push(...result.warnings);
  }

  return { items: allItems, warnings: allWarnings };
}
