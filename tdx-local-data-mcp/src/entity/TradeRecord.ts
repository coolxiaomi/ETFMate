/**
 * 交易记录实体
 */
export interface TradeRecord {
  id?: number;
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
  rawSource?: string;
  createdAt?: string;
}

export interface TradeRecordRow {
  id: number;
  account_name: string;
  trade_date: string;
  trade_time: string;
  market: string;
  security_code: string;
  security_name: string;
  side: string;
  quantity: number;
  price: number;
  amount: number | null;
  fee: number | null;
  order_no: string;
  contract_no: string;
  raw_source: string;
  created_at: string;
}
