import type {
  Bar,
  BookDeltaItem,
  MarketAnomaly,
  MarketEventPayload,
  Trade,
  WebSocketEnvelope,
} from '../types/protocol';
import type { PortfolioSummary } from '../types/portfolio';

export type ConnectionStatus = 'CONNECTED' | 'CONNECTING' | 'DISCONNECTED';

type MessageHandler = (envelope: WebSocketEnvelope) => void;
type TradesBatchHandler = (trades: Trade[]) => void;
type BarsBatchHandler = (interval: string, bars: Bar[]) => void;
type BookBatchHandler = (deltas: BookDeltaItem[]) => void;
type AnomaliesBatchHandler = (anomalies: MarketAnomaly[]) => void;
type MarketEventsBatchHandler = (events: MarketEventPayload[]) => void;
type PortfolioUpdateHandler = (portfolio: PortfolioSummary) => void;
type StatusHandler = (status: ConnectionStatus) => void;

export class MarketPulseWebSocketClient {
  private url: string;
  private ws: WebSocket | null = null;
  private status: ConnectionStatus = 'DISCONNECTED';
  private subscriptions: Set<string> = new Set();
  private reconnectTimeout: number | null = null;
  private pingInterval: number | null = null;
  private retryDelayMs = 1000;
  private maxRetryDelayMs = 15000;

  private onMessageCallbacks: Set<MessageHandler> = new Set();
  private onTradesBatchCallbacks: Set<TradesBatchHandler> = new Set();
  private onBarsBatchCallbacks: Set<BarsBatchHandler> = new Set();
  private onBookBatchCallbacks: Set<BookBatchHandler> = new Set();
  private onAnomaliesBatchCallbacks: Set<AnomaliesBatchHandler> = new Set();
  private onMarketEventsBatchCallbacks: Set<MarketEventsBatchHandler> = new Set();
  private onPortfolioUpdateCallbacks: Set<PortfolioUpdateHandler> = new Set();
  private onStatusCallbacks: Set<StatusHandler> = new Set();

  constructor(url?: string) {
    if (url) {
      this.url = url;
    } else {
      const isHttps = window.location.protocol === 'https:';
      const host = window.location.hostname || 'localhost';
      this.url = `${isHttps ? 'wss:' : 'ws:'}//${host}:8000/ws`;
    }
  }

  public connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.setStatus('CONNECTING');

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        this.setStatus('CONNECTED');
        this.retryDelayMs = 1000;
        this.startHeartbeat();

        // Resubscribe to all tracked channels
        for (const channel of this.subscriptions) {
          this.send({
            version: 1,
            type: 'SUBSCRIBE',
            channel,
          });
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const envelope: WebSocketEnvelope = JSON.parse(event.data);
          this.handleMessage(envelope);
        } catch (err) {
          console.error('Failed to parse WebSocket message:', err);
        }
      };

      this.ws.onclose = () => {
        this.cleanup();
        this.setStatus('DISCONNECTED');
        this.scheduleReconnect();
      };

      this.ws.onerror = (err) => {
        console.warn('WebSocket connection error:', err);
        this.ws?.close();
      };
    } catch (err) {
      console.error('WebSocket initialization error:', err);
      this.setStatus('DISCONNECTED');
      this.scheduleReconnect();
    }
  }

  public disconnect(): void {
    this.cleanup();
    if (this.reconnectTimeout) {
      window.clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.setStatus('DISCONNECTED');
  }

  public subscribe(channel: string): void {
    this.subscriptions.add(channel);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.send({
        version: 1,
        type: 'SUBSCRIBE',
        channel,
      });
    }
  }

  public unsubscribe(channel: string): void {
    this.subscriptions.delete(channel);
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.send({
        version: 1,
        type: 'UNSUBSCRIBE',
        channel,
      });
    }
  }

  public onTradesBatch(handler: TradesBatchHandler): () => void {
    this.onTradesBatchCallbacks.add(handler);
    return () => this.onTradesBatchCallbacks.delete(handler);
  }

  public onBarsBatch(handler: BarsBatchHandler): () => void {
    this.onBarsBatchCallbacks.add(handler);
    return () => this.onBarsBatchCallbacks.delete(handler);
  }

  public onBookBatch(handler: BookBatchHandler): () => void {
    this.onBookBatchCallbacks.add(handler);
    return () => this.onBookBatchCallbacks.delete(handler);
  }

  public onAnomaliesBatch(handler: AnomaliesBatchHandler): () => void {
    this.onAnomaliesBatchCallbacks.add(handler);
    return () => this.onAnomaliesBatchCallbacks.delete(handler);
  }

  public onMarketEventsBatch(handler: MarketEventsBatchHandler): () => void {
    this.onMarketEventsBatchCallbacks.add(handler);
    return () => this.onMarketEventsBatchCallbacks.delete(handler);
  }

  public onPortfolioUpdate(handler: PortfolioUpdateHandler): () => void {
    this.onPortfolioUpdateCallbacks.add(handler);
    return () => this.onPortfolioUpdateCallbacks.delete(handler);
  }

  public onStatusChange(handler: StatusHandler): () => void {
    this.onStatusCallbacks.add(handler);
    handler(this.status);
    return () => this.onStatusCallbacks.delete(handler);
  }

  public onMessage(handler: MessageHandler): () => void {
    this.onMessageCallbacks.add(handler);
    return () => this.onMessageCallbacks.delete(handler);
  }

  private send(envelope: WebSocketEnvelope): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(envelope));
    }
  }

  private handleMessage(envelope: WebSocketEnvelope): void {
    // Notify generic message callbacks
    for (const cb of this.onMessageCallbacks) {
      cb(envelope);
    }

    // Handle batched trades
    if (envelope.type === 'DATA' && envelope.channel?.startsWith('trades:')) {
      const data = envelope.data as { trades?: Trade[] } | undefined;
      if (data?.trades && Array.isArray(data.trades) && data.trades.length > 0) {
        for (const cb of this.onTradesBatchCallbacks) {
          cb(data.trades);
        }
      }
    }

    // Handle batched bars
    if (envelope.type === 'DATA' && envelope.channel?.startsWith('bars:')) {
      const parts = envelope.channel.split(':');
      const interval = parts[2] || '1s';
      const data = envelope.data as { bars?: Bar[] } | undefined;
      if (data?.bars && Array.isArray(data.bars) && data.bars.length > 0) {
        for (const cb of this.onBarsBatchCallbacks) {
          cb(interval, data.bars);
        }
      }
    }

    // Handle batched book deltas
    if (envelope.type === 'DATA' && envelope.channel?.startsWith('book:')) {
      const data = envelope.data as { deltas?: BookDeltaItem[] } | undefined;
      if (data?.deltas && Array.isArray(data.deltas) && data.deltas.length > 0) {
        for (const cb of this.onBookBatchCallbacks) {
          cb(data.deltas);
        }
      }
    }

    // Handle batched anomalies
    if (envelope.type === 'DATA' && envelope.channel?.startsWith('anomalies:')) {
      const data = envelope.data as { anomalies?: MarketAnomaly[] } | undefined;
      if (data?.anomalies && Array.isArray(data.anomalies) && data.anomalies.length > 0) {
        for (const cb of this.onAnomaliesBatchCallbacks) {
          cb(data.anomalies);
        }
      }
    }

    // Handle batched market events
    if (envelope.type === 'DATA' && envelope.channel?.startsWith('events:')) {
      const data = envelope.data as { market_events?: MarketEventPayload[] } | undefined;
      if (data?.market_events && Array.isArray(data.market_events) && data.market_events.length > 0) {
        for (const cb of this.onMarketEventsBatchCallbacks) {
          cb(data.market_events);
        }
      }
    }

    // Handle portfolio snapshots
    if (envelope.type === 'DATA' && envelope.channel === 'portfolio:user') {
      const data = envelope.data as { portfolio?: PortfolioSummary } | PortfolioSummary | undefined;
      if (data) {
        const summary =
          'portfolio' in data && data.portfolio ? data.portfolio : (data as PortfolioSummary);
        for (const cb of this.onPortfolioUpdateCallbacks) {
          cb(summary);
        }
      }
    }
  }

  private setStatus(status: ConnectionStatus): void {
    if (this.status !== status) {
      this.status = status;
      for (const cb of this.onStatusCallbacks) {
        cb(status);
      }
    }
  }

  private startHeartbeat(): void {
    if (this.pingInterval) {
      window.clearInterval(this.pingInterval);
    }
    this.pingInterval = window.setInterval(() => {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        this.send({
          version: 1,
          type: 'PING',
        });
      }
    }, 15000);
  }

  private cleanup(): void {
    if (this.pingInterval) {
      window.clearInterval(this.pingInterval);
      this.pingInterval = null;
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimeout) {
      return;
    }
    this.reconnectTimeout = window.setTimeout(() => {
      this.reconnectTimeout = null;
      this.connect();
      this.retryDelayMs = Math.min(this.retryDelayMs * 1.5, this.maxRetryDelayMs);
    }, this.retryDelayMs);
  }
}
