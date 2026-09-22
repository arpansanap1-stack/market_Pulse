/**
 * MarketPulse Protocol & Message Types
 * Conforms to docs/PROTOCOL.md specification.
 */

export type Side = 'BUY' | 'SELL';

export type STPPolicy = 'CANCEL_NEWEST' | 'CANCEL_OLDEST' | 'DECREMENT_AND_CANCEL' | 'NONE';

export interface Trade {
  seq: number;
  ts_ns: number;
  symbol: string;
  trade_id: string;
  price_ticks: number;
  price: number;
  qty: number;
  aggressor_side: Side;
  buyer_participant_id?: string;
  seller_participant_id?: string;
}

export interface TradesChannelData {
  trades: Trade[];
}

export type MessageType =
  | 'SUBSCRIBE'
  | 'UNSUBSCRIBE'
  | 'DATA'
  | 'SNAPSHOT'
  | 'DELTA'
  | 'ACK'
  | 'PING'
  | 'PONG'
  | 'ERROR';

export interface WebSocketEnvelope<T = unknown> {
  version: number;
  type: MessageType;
  channel?: string;
  seq?: number;
  ts?: number;
  data?: T;
}

export interface SymbolInfo {
  symbol: string;
  name: string;
  tick_size: number;
  last_price: number;
  active: boolean;
}

export interface MarketStats {
  symbol: string;
  lastPrice: number;
  previousClose: number;
  change: number;
  changePercent: number;
  high: number;
  low: number;
  volume: number;
  tradesCount: number;
  tradesPerSec: number;
}

export interface Bar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  trade_count: number;
  vwap: number;
}

export interface BarsChannelData {
  bars: Bar[];
}

export interface IndicatorValues {
  symbol: string;
  interval: string;
  times: number[];
  indicators: {
    sma20: (number | null)[];
    ema20: (number | null)[];
    rsi14: (number | null)[];
    macd: {
      macd: (number | null)[];
      signal: (number | null)[];
      histogram: (number | null)[];
    };
    bollinger: {
      upper: (number | null)[];
      middle: (number | null)[];
      lower: (number | null)[];
    };
    vwap: (number | null)[];
  };
}

export type ChartTimeframe = '1s' | '5s' | '15s' | '1m';
export type ChartType = 'candlestick' | 'area';

export interface BookLevel {
  price: number;
  price_ticks: number;
  qty: number;
}

export interface BookSnapshot {
  symbol: string;
  bids: BookLevel[];
  asks: BookLevel[];
  best_bid: number | null;
  best_ask: number | null;
  spread: number | null;
  spread_ticks: number | null;
  mid_price: number | null;
  is_halted?: boolean;
}

export interface BookDeltaItem {
  seq: number;
  ts_ns: number;
  symbol: string;
  side: Side;
  price_ticks: number;
  price: number;
  qty: number;
}

export interface BookChannelData {
  deltas: BookDeltaItem[];
}

export type AnomalyType =
  | 'PRICE_SHOCK'
  | 'VOLUME_SURGE'
  | 'SPREAD_BLOWOUT'
  | 'BOOK_IMBALANCE';

export type AnomalySeverity = 'INFO' | 'WARNING' | 'CRITICAL';

export interface MarketAnomaly {
  seq: number;
  ts_ns: number;
  symbol: string;
  type: AnomalyType;
  anomaly_type?: AnomalyType;
  severity: AnomalySeverity;
  metric_value: number;
  threshold: number;
  message: string;
}

export interface AnomaliesChannelData {
  anomalies: MarketAnomaly[];
}

export interface MarketEventPayload {
  seq: number;
  ts_ns: number;
  symbol: string;
  kind: string;
  params: Record<string, unknown>;
}

export interface MarketEventsChannelData {
  market_events: MarketEventPayload[];
}

export interface ScenarioDefinition {
  id: string;
  name: string;
  description: string;
  category: string;
  default_params: Record<string, unknown>;
}

export interface STPStats {
  cancel_newest: number;
  cancel_oldest: number;
  decrement_and_cancel: number;
  total_prevented: number;
}

export interface MarketStatus {
  symbol: string;
  is_halted: boolean;
  status: 'ACTIVE' | 'HALTED';
  latest_price: number;
  stp_stats?: STPStats;
}

