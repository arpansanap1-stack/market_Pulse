/**
 * MarketPulse Protocol & Message Types
 * Conforms to docs/PROTOCOL.md specification.
 */

export type Side = 'BUY' | 'SELL';

export interface Trade {
  seq: number;
  ts_ns: number;
  symbol: string;
  trade_id: string;
  price_ticks: number;
  price: number;
  qty: number;
  aggressor_side: Side;
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
