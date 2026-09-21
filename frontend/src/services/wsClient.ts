import type { Trade, WebSocketEnvelope } from '../types/protocol';

export type ConnectionStatus = 'CONNECTED' | 'CONNECTING' | 'DISCONNECTED';

type MessageHandler = (envelope: WebSocketEnvelope) => void;
type TradesBatchHandler = (trades: Trade[]) => void;
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
