/**
 * 同步日志服务
 */
import { SyncLogRepository } from "../repository/SyncLogRepository.js";
import type { SyncLogRow } from "../entity/SyncLog.js";

export class SyncLogService {
  private repo = new SyncLogRepository();

  /**
   * 记录同步开始
   */
  start(syncType: string, message: string = ""): number {
    return this.repo.create(syncType, "RUNNING", message);
  }

  /**
   * 记录同步成功
   */
  success(id: number, message: string = ""): void {
    this.repo.finish(id, "SUCCESS", message);
  }

  /**
   * 记录同步失败
   */
  fail(id: number, message: string): void {
    this.repo.finish(id, "FAILED", message);
  }

  /**
   * 查询同步日志
   */
  query(syncType?: string, limit: number = 20): SyncLogRow[] {
    return this.repo.query(syncType, limit);
  }
}
