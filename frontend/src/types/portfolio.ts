/**
 * Portfolio Management and Order Management System (OMS/PMS) Types.
 */

import type { Side } from './protocol';

export type OrderStatus =
  | 'PENDING'
  | 'OPEN'
  | 'PARTIALLY_FILLED'
  | 'FILLED'
  | 'CANCELED'
  | 'REJECTED';

export type OrderType = 'LIMIT' | 'MARKET';

export type TimeInForce = 'GTC' | 'IOC' | 'FOK';

export interface OrderRecord {
  order_id: string;
  symbol: string;
  side: Side;
  order_type: OrderType;
  price: number | null;
  price_ticks: number | null;
  qty: number;
  filled_qty: number;
  remaining_qty: number;
  status: OrderStatus;
  tif: TimeInForce;
  created_ts_ns: number;
  updated_ts_ns: number;
  rejection_reason?: string | null;
}

export interface PositionItem {
  symbol: string;
  qty: number;
  avg_entry_price: number;
  avg_entry_price_ticks: number;
  current_price: number;
  current_price_ticks: number;
  market_value: number;
  market_value_ticks: number;
  unrealized_pnl: number;
  unrealized_pnl_ticks: number;
  realized_pnl: number;
  realized_pnl_ticks: number;
  total_pnl: number;
  total_pnl_ticks: number;
}

export interface PortfolioSummary {
  cash: number;
  cash_ticks: number;
  equity: number;
  equity_ticks: number;
  initial_cash: number;
  initial_cash_ticks: number;
  realized_pnl: number;
  realized_pnl_ticks: number;
  unrealized_pnl: number;
  unrealized_pnl_ticks: number;
  total_pnl: number;
  total_pnl_ticks: number;
  positions: PositionItem[];
}

export interface UserTradeRecord {
  trade_id: string;
  order_id: string;
  symbol: string;
  side: Side;
  price: number;
  price_ticks: number;
  qty: number;
  ts_ns: number;
}

export interface OrderSubmitPayload {
  symbol: string;
  side: Side;
  order_type: OrderType;
  price?: number | null;
  qty: number;
  tif?: TimeInForce;
}
