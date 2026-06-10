/**
 * 路径安全校验
 * 防止路径穿越攻击，限制文件读取目录范围
 */
import path from "node:path";
import { AppError } from "../exception/AppError.js";

/**
 * 校验目标路径是否在允许的目录范围内
 * @param targetPath 用户提供的目标路径
 * @param allowedDir 允许的目录
 * @returns 标准化后的绝对路径
 */
export function assertWithinDir(targetPath: string, allowedDir: string): string {
  if (!targetPath || targetPath.trim() === "") {
    throw AppError.badRequest("文件路径不能为空");
  }

  // 禁止路径穿越特征
  if (targetPath.includes("..")) {
    throw AppError.forbidden(`路径不允许包含 "..": ${targetPath}`);
  }

  const resolved = path.resolve(targetPath);
  const dirResolved = path.resolve(allowedDir);

  // 确保目标路径在允许目录内
  if (!resolved.startsWith(dirResolved + path.sep) && resolved !== dirResolved) {
    throw AppError.forbidden(
      `路径 "${targetPath}" 不在允许目录 "${allowedDir}" 范围内`
    );
  }

  return resolved;
}

/**
 * 校验文件扩展名是否合法
 */
export function assertFileExtension(
  filePath: string,
  allowedExtensions: string[]
): void {
  const ext = path.extname(filePath).toLowerCase();
  const allowed = allowedExtensions.map((e) => e.toLowerCase());
  if (!allowed.includes(ext)) {
    throw AppError.badRequest(
      `不支持的文件格式 "${ext}"，支持的格式: ${allowed.join(", ")}`
    );
  }
}
