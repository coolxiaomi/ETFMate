/**
 * 中文字段名 → 标准字段名映射
 * CSV / Excel 表头允许有空格，数字字段支持逗号、百分号、空字符串
 */

import { normalizeSide } from "./securityCodeUtil.js";
import { parseDate, parseTime } from "./dateUtil.js";

// ────────────────────────────────────────────
//  映射表定义:  标准字段名 → 中文别名列表
// ────────────────────────────────────────────

const FIELD_ALIASES: Record<string, string[]> = {
  // 通用
  securityCode: ["证券代码", "代码", "股票代码", "基金代码", "标的代码"],
  securityName: ["证券名称", "名称", "股票名称", "基金名称", "标的名称"],
  accountName: ["账户", "账户名称", "资金账号", "股东账号"],
  market: ["市场", "交易市场", "证券市场"],

  // 持仓
  snapshotDate: ["快照日期", "日期", "持仓日期"],
  quantity: ["持仓数量", "当前持仓", "数量", "证券数量"],
  availableQuantity: ["可用数量", "可用余额", "可卖数量"],
  costPrice: ["成本价", "成本价格", "持仓成本价"],
  marketPrice: ["现价", "最新价", "市价"],
  marketValue: ["市值", "参考市值", "最新市值"],
  profitLoss: ["盈亏", "浮动盈亏", "参考盈亏"],
  profitLossRatio: ["盈亏比例", "盈亏率", "参考盈亏比例"],

  // 交易
  tradeDate: ["交易日期", "成交日期"],
  tradeTime: ["交易时间", "成交时间", "时间"],
  side: ["买卖方向", "操作", "买卖", "业务名称"],
  tradeQuantity: ["成交数量", "发生数量"],
  price: ["成交价格", "价格", "成交均价"],
  amount: ["成交金额", "金额", "发生金额"],
  fee: ["手续费", "费用", "佣金"],
  orderNo: ["委托编号", "订单号", "委托号"],
  contractNo: ["合同编号", "成交编号", "合同号"],
};

// 构建反向映射:  中文别名(trimmed) → 标准字段名
const aliasToField = new Map<string, string>();
for (const [stdField, aliases] of Object.entries(FIELD_ALIASES)) {
  for (const alias of aliases) {
    aliasToField.set(alias.trim(), stdField);
  }
}

/**
 * 表头列名 → 标准字段名 的映射结果
 */
export interface FieldMapping {
  /** 原始列名 → 标准字段名 */
  columnMap: Map<string, string>;
  /** 未识别的列名列表 */
  unmapped: string[];
}

/**
 * 根据表头行构建字段映射
 */
export function buildFieldMapping(headers: string[]): FieldMapping {
  const columnMap = new Map<string, string>();
  const unmapped: string[] = [];

  for (const header of headers) {
    const trimmed = header.trim();
    const stdField = aliasToField.get(trimmed);
    if (stdField) {
      columnMap.set(header, stdField);
    } else {
      unmapped.push(header);
    }
  }

  return { columnMap, unmapped };
}

/**
 * 将一行原始数据按映射转为标准字段对象
 */
export function mapRow(
  row: Record<string, string>,
  mapping: FieldMapping
): Record<string, string> {
  const result: Record<string, string> = {};
  for (const [originalCol, stdField] of mapping.columnMap) {
    const raw = row[originalCol] ?? "";
    result[stdField] = raw.trim();
  }
  return result;
}

// ────────────────────────────────────────────
//  数字清洗
// ────────────────────────────────────────────

/**
 * 清洗数字字符串：去除逗号、百分号、空格
 * 返回 number 或 null
 */
export function cleanNumber(input: string | undefined | null): number | null {
  if (input === undefined || input === null) return null;
  const trimmed = input.trim();
  if (trimmed === "" || trimmed === "-") return null;
  const cleaned = trimmed.replace(/,/g, "").replace(/%/g, "");
  const num = Number(cleaned);
  return Number.isFinite(num) ? num : null;
}

// ────────────────────────────────────────────
//  行数据标准化
// ────────────────────────────────────────────

/**
 * 标准化持仓行数据
 */
export function normalizePositionRow(raw: Record<string, string>): {
  accountName: string;
  snapshotDate: string;
  market: string;
  securityCode: string;
  securityName: string;
  quantity: number;
  availableQuantity: number;
  costPrice: number | null;
  marketPrice: number | null;
  marketValue: number | null;
  profitLoss: number | null;
  profitLossRatio: number | null;
} {
  return {
    accountName: raw["accountName"] ?? "",
    snapshotDate: parseDate(raw["snapshotDate"]) ?? "",
    market: raw["market"] ?? "",
    securityCode: raw["securityCode"] ?? "",
    securityName: raw["securityName"] ?? "",
    quantity: cleanNumber(raw["quantity"]) ?? 0,
    availableQuantity: cleanNumber(raw["availableQuantity"]) ?? 0,
    costPrice: cleanNumber(raw["costPrice"]),
    marketPrice: cleanNumber(raw["marketPrice"]),
    marketValue: cleanNumber(raw["marketValue"]),
    profitLoss: cleanNumber(raw["profitLoss"]),
    profitLossRatio: cleanNumber(raw["profitLossRatio"]),
  };
}

/**
 * 标准化交易行数据
 */
export function normalizeTradeRow(raw: Record<string, string>): {
  accountName: string;
  tradeDate: string;
  tradeTime: string;
  market: string;
  securityCode: string;
  securityName: string;
  side: string;
  quantity: number;
  price: number;
  amount: number | null;
  fee: number | null;
  orderNo: string;
  contractNo: string;
} {
  return {
    accountName: raw["accountName"] ?? "",
    tradeDate: parseDate(raw["tradeDate"]) ?? parseDate(raw["snapshotDate"]) ?? "",
    tradeTime: parseTime(raw["tradeTime"]) ?? "",
    market: raw["market"] ?? "",
    securityCode: raw["securityCode"] ?? "",
    securityName: raw["securityName"] ?? "",
    side: normalizeSide(raw["side"]),
    quantity: cleanNumber(raw["tradeQuantity"] ?? raw["quantity"]) ?? 0,
    price: cleanNumber(raw["price"]) ?? 0,
    amount: cleanNumber(raw["amount"]),
    fee: cleanNumber(raw["fee"]),
    orderNo: raw["orderNo"] ?? "",
    contractNo: raw["contractNo"] ?? "",
  };
}
