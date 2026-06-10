/**
 * 标的全貌服务
 * 聚合查询：自选股 + 持仓 + 交易统计
 */
import { WatchlistRepository } from "../repository/WatchlistRepository.js";
import { PositionRepository } from "../repository/PositionRepository.js";
import { TradeRepository } from "../repository/TradeRepository.js";
import type { WatchlistSecurityRow } from "../entity/WatchlistSecurity.js";
import type { PositionSnapshotRow } from "../entity/PositionSnapshot.js";
import type { TradeRecordRow } from "../entity/TradeRecord.js";

export interface SecurityOverview {
  securityCode: string;
  /** 是否在自选股中 */
  inWatchlist: boolean;
  /** 所属自选分组 */
  watchlistGroups: string[];
  /** 最新持仓 */
  latestPosition: PositionSnapshotRow | null;
  /** 最近交易记录 */
  recentTrades: TradeRecordRow[];
  /** 总买入金额 */
  totalBuyAmount: number;
  /** 总卖出金额 */
  totalSellAmount: number;
  /** 净买入金额 */
  netBuyAmount: number;
  /** 当前浮动盈亏 */
  unrealizedProfitLoss: number | null;
}

export class SecurityOverviewService {
  private watchlistRepo = new WatchlistRepository();
  private positionRepo = new PositionRepository();
  private tradeRepo = new TradeRepository();

  /**
   * 获取标的全貌
   */
  getOverview(securityCode: string): SecurityOverview {
    // 自选股信息
    const watchlistItems: WatchlistSecurityRow[] =
      this.watchlistRepo.findBySecurityCode(securityCode);
    const inWatchlist = watchlistItems.length > 0;
    const watchlistGroups = watchlistItems.map((w) => w.group_name);

    // 最新持仓
    const latestPosition =
      this.positionRepo.findLatestBySecurityCode(securityCode) ?? null;

    // 最近 10 条交易记录
    const recentTrades = this.tradeRepo.findBySecurityCode(securityCode, 10);

    // 买卖统计
    const aggregate = this.tradeRepo.aggregateBySecurityCode(securityCode);

    // 浮动盈亏
    const unrealizedProfitLoss = latestPosition?.profit_loss ?? null;

    return {
      securityCode,
      inWatchlist,
      watchlistGroups,
      latestPosition,
      recentTrades,
      totalBuyAmount: aggregate.totalBuyAmount,
      totalSellAmount: aggregate.totalSellAmount,
      netBuyAmount: aggregate.netBuyAmount,
      unrealizedProfitLoss,
    };
  }
}
