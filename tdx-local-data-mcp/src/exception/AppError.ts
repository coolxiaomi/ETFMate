/**
 * 应用统一异常类
 */
export class AppError extends Error {
  public readonly code: string;

  constructor(code: string, message: string, cause?: unknown) {
    super(message);
    this.name = "AppError";
    this.code = code;
    if (cause !== undefined) {
      this.cause = cause;
    }
  }

  static badRequest(message: string, cause?: unknown): AppError {
    return new AppError("BAD_REQUEST", message, cause);
  }

  static notFound(message: string, cause?: unknown): AppError {
    return new AppError("NOT_FOUND", message, cause);
  }

  static forbidden(message: string, cause?: unknown): AppError {
    return new AppError("FORBIDDEN", message, cause);
  }

  static internal(message: string, cause?: unknown): AppError {
    return new AppError("INTERNAL_ERROR", message, cause);
  }

  static parseError(message: string, cause?: unknown): AppError {
    return new AppError("PARSE_ERROR", message, cause);
  }
}
