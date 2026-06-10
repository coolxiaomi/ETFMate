/**
 * 证券代码工具
 */

/**
 * 校验是否为合法的 6 位证券代码
 */
export function isValidSecurityCode(code: string): boolean {
  return /^\d{6}$/.test(code);
}

/**
 * 根据通达信市场编号转换为标准市场代码
 * 0 = 深市 (SZ), 1 = 沪市 (SH)
 */
export function marketFromTdxId(tdxId: string): string | null {
  if (tdxId === "0") return "SZ";
  if (tdxId === "1") return "SH";
  return null;
}

/**
 * 根据证券代码判断证券类型
 */
export function inferSecurityType(code: string): string {
  const prefix2 = code.substring(0, 2);

  // 沪市 ETF: 51, 56, 58 开头
  if (prefix2 === "51" || prefix2 === "56" || prefix2 === "58") {
    return "ETF";
  }

  // 深市 ETF: 15, 16, 18 开头
  if (prefix2 === "15" || prefix2 === "16" || prefix2 === "18") {
    return "ETF";
  }

  return "STOCK";
}

/**
 * 标准化市场代码
 * 支持输入 SH/SZ/sh/sz/沪/深 等
 */
export function normalizeMarket(input: string | undefined | null): string | null {
  if (!input) return null;
  const trimmed = input.trim().toUpperCase();
  if (trimmed === "SH" || trimmed === "沪" || trimmed === "上海") return "SH";
  if (trimmed === "SZ" || trimmed === "深" || trimmed === "深圳") return "SZ";
  return null;
}

/**
 * 标准化买卖方向
 */
export function normalizeSide(input: string | undefined | null): string {
  if (!input) return "OTHER";
  const trimmed = input.trim();

  const buyKeywords = ["买入", "申购", "买", "B", "BUY", "buy", "Buy"];
  const sellKeywords = ["卖出", "赎回", "卖", "S", "SELL", "sell", "Sell"];

  if (buyKeywords.some((k) => trimmed.includes(k))) return "BUY";
  if (sellKeywords.some((k) => trimmed.includes(k))) return "SELL";

  return "OTHER";
}
