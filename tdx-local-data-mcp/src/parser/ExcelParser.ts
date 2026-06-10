/**
 * Excel 解析器 (.xlsx / .xls)
 */
import fs from "node:fs";
import * as XLSX from "xlsx";
import { AppError } from "../exception/AppError.js";

/**
 * 解析 Excel 文件，返回行数组（每行为 Record<string, string>）
 */
export function parseExcelFile(
  filePath: string,
  sheetName?: string
): { headers: string[]; rows: Record<string, string>[] } {
  let buffer: Buffer;
  try {
    buffer = fs.readFileSync(filePath);
  } catch (err) {
    throw AppError.internal(`无法读取文件 ${filePath}: ${String(err)}`, err);
  }

  let workbook: XLSX.WorkBook;
  try {
    workbook = XLSX.read(buffer, { type: "buffer" });
  } catch (err) {
    throw AppError.parseError(`Excel 解析失败: ${String(err)}`, err);
  }

  // 选择工作表
  const targetSheet = sheetName ?? workbook.SheetNames[0];
  if (!targetSheet) {
    throw AppError.parseError("Excel 文件中没有工作表");
  }

  const sheet = workbook.Sheets[targetSheet];
  if (!sheet) {
    throw AppError.parseError(`未找到工作表: ${targetSheet}`);
  }

  // 转为 JSON（首行为表头）
  const jsonData = XLSX.utils.sheet_to_json<unknown[]>(sheet, {
    header: 1,
    defval: "",
  }) as unknown[][];

  if (jsonData.length === 0) {
    return { headers: [], rows: [] };
  }

  // 第一行为表头
  const headers = (jsonData[0] as unknown[]).map((h) => String(h).trim());

  // 后续行为数据
  const rows: Record<string, string>[] = [];
  for (let i = 1; i < jsonData.length; i++) {
    const rowArr = jsonData[i] as unknown[];
    if (!rowArr || rowArr.length === 0) continue;

    const rowObj: Record<string, string> = {};
    for (let j = 0; j < headers.length; j++) {
      const val = rowArr[j];
      rowObj[headers[j]] = val !== undefined && val !== null ? String(val).trim() : "";
    }
    rows.push(rowObj);
  }

  return { headers, rows };
}
