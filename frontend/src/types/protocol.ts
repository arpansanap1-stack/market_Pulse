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

