/**
 * 日期工具
 */

/**
 * 获取当前时间的 ISO 格式字符串 (yyyy-MM-dd HH:mm:ss)
 */
export function nowString(): string {
  return formatDateTime(new Date());
}

/**
 * 格式化 Date 为 yyyy-MM-dd HH:mm:ss
 */
export function formatDateTime(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  const hh = String(date.getHours()).padStart(2, "0");
  const mm = String(date.getMinutes()).padStart(2, "0");
  const ss = String(date.getSeconds()).padStart(2, "0");
  return `${y}-${m}-${d} ${hh}:${mm}:${ss}`;
}

/**
 * 格式化 Date 为 yyyy-MM-dd
 */
export function formatDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/**
 * 解析多种日期格式，返回 yyyy-MM-dd 字符串
 * 支持：yyyy-MM-dd, yyyy/MM/dd, yyyyMMdd
 */
export function parseDate(input: string | undefined | null): string | null {
  if (!input) return null;
  const trimmed = input.trim();
  if (!trimmed) return null;

  // yyyy-MM-dd or yyyy/MM/dd
  const dashMatch = trimmed.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/);
  if (dashMatch) {
    const [, y, m, d] = dashMatch;
    return `${y}-${m.padStart(2, "0")}-${d.padStart(2, "0")}`;
  }

  // yyyyMMdd
  const compactMatch = trimmed.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (compactMatch) {
    const [, y, m, d] = compactMatch;
    return `${y}-${m}-${d}`;
  }

  return null;
}

/**
 * 解析时间字符串，支持 HH:mm:ss 或 HH:mm
 */
export function parseTime(input: string | undefined | null): string | null {
  if (!input) return null;
  const trimmed = input.trim();
  if (!trimmed) return null;

  const match = trimmed.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/);
  if (match) {
    const hh = match[1].padStart(2, "0");
    const mm = match[2];
    const ss = match[3] ?? "00";
    return `${hh}:${mm}:${ss}`;
  }

  return null;
}
