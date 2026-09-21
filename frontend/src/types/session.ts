export interface SessionMetadata {
  session_id: string;
  symbol: string;
  seed: number;
  config: Record<string, unknown>;
  start_ts_ns: number;
  end_ts_ns: number | null;
  total_events: number;
  status: 'ACTIVE' | 'STOPPED' | 'COMPLETED';
  created_at_utc: string;
}

export interface ActiveSessionStatus {
  mode: 'LIVE' | 'REPLAY' | 'PAUSED' | 'STOPPED';
  session_id: string;
  symbol: string;
  current_seq: number;
  total_events: number;
  speed_multiplier: number;
  is_paused: boolean;
  latest_price: number;
  is_halted: boolean;
}
