/**
 * CSV 解析器
 * 支持 GBK 编码（券商导出常见编码）
 */
import fs from "node:fs";
import { parse } from "csv-parse/sync";
import { AppError } from "../exception/AppError.js";

/**
 * 解析 CSV 文件，返回行数组（每行为 Record<string, string>）
 * 自动检测 BOM 并尝试 GBK 解码
 */
export function parseCsvFile(
  filePath: string
): { headers: string[]; rows: Record<string, string>[] } {
  let buffer: Buffer;
  try {
    buffer = fs.readFileSync(filePath);
  } catch (err) {
    throw AppError.internal(`无法读取文件 ${filePath}: ${String(err)}`, err);
  }

  let text: string;

  // 检查 UTF-8 BOM
  if (buffer[0] === 0xef && buffer[1] === 0xbb && buffer[2] === 0xbf) {
    text = buffer.subarray(3).toString("utf-8");
  } else {
    // 尝试 UTF-8 解码，检查是否有乱码
    text = buffer.toString("utf-8");

    // 如果包含替换字符或中文乱码特征，尝试 GBK
    if (containsMojibake(text)) {
      try {
        text = new TextDecoder("gbk").decode(buffer);
      } catch {
        // GBK 解码失败，继续使用 UTF-8 结果
      }
    }
  }

  let records: Record<string, string>[];
  let headers: string[];

  try {
    records = parse(text, {
      columns: (hdrs: string[]) => {
        headers = hdrs;
        return hdrs.map((h: string) => h.trim());
      },
      skip_empty_lines: true,
      trim: true,
      relax_column_count: true,
    }) as Record<string, string>[];
  } catch (err) {
    throw AppError.parseError(`CSV 解析失败: ${String(err)}`, err);
  }

  return { headers: headers!, rows: records };
}

/**
 * 简单的乱码检测：检查是否包含常见的 UTF-8 替换字符
 */
function containsMojibake(text: string): boolean {
  // 包含 Unicode 替换字符 U+FFFD
  if (text.includes("\uFFFD")) return true;
  // 包含常见的 GBK 乱码模式
  if (/\x00/.test(text)) return true;
  return false;
}
