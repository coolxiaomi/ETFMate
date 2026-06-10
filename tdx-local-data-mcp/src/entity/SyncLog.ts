/**
 * 同步日志实体
 */
export interface SyncLog {
  id?: number;
  syncType: string;
  status: string;
  message: string;
  startedAt: string;
  finishedAt?: string | null;
}

export interface SyncLogRow {
  id: number;
  sync_type: string;
  status: string;
  message: string;
  started_at: string;
  finished_at: string | null;
}
