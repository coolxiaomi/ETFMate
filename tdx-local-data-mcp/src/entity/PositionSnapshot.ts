/**
 * 持仓快照实体
 */
export interface PositionSnapshot {
  id?: number;
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
  createdAt?: string;
}

export interface PositionSnapshotRow {
  id: number;
  account_name: string;
  snapshot_date: string;
  market: string;
  security_code: string;
  security_name: string;
  quantity: number;
  available_quantity: number;
  cost_price: number | null;
  market_price: number | null;
  market_value: number | null;
  profit_loss: number | null;
  profit_loss_ratio: number | null;
  created_at: string;
}
