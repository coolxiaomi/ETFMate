/**
 * 自选股实体
 */
export interface WatchlistSecurity {
  id?: number;
  source: string;
  groupName: string;
  market: string;
  securityCode: string;
  securityName: string;
  securityType: string;
  createdAt?: string;
  updatedAt?: string;
}

export interface WatchlistSecurityRow {
  id: number;
  source: string;
  group_name: string;
  market: string;
  security_code: string;
  security_name: string;
  security_type: string;
  created_at: string;
  updated_at: string;
}
