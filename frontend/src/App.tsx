import React, { useEffect, useRef, useState } from 'react';
import { Header } from './components/Header';
import { MarketStatsCards } from './components/MarketStats';
import { PriceChart } from './components/PriceChart';
import type { PriceChartHandle } from './components/PriceChart';
import { TradeTape } from './components/TradeTape';
import { MarketPulseWebSocketClient } from './services/wsClient';
import type { ConnectionStatus } from './services/wsClient';
import type { MarketStats, Trade } from './types/protocol';

export const App: React.FC = () => {
  const [status, setStatus] = useState<ConnectionStatus>('CONNECTING');
  const [currentTps, setCurrentTps] = useState<number>(50);
  const [recentTrades, setRecentTrades] = useState<Trade[]>([]);
  const [stats, setStats] = useState<MarketStats>({
    symbol: 'AAPL',
    lastPrice: 150.0,
    previousClose: 150.0,
    change: 0.0,
    changePercent: 0.0,
    high: 150.0,
    low: 150.0,
    volume: 0,
    tradesCount: 0,
    tradesPerSec: 50,
  });

  const chartRef = useRef<PriceChartHandle | null>(null);
  const clientRef = useRef<MarketPulseWebSocketClient | null>(null);
  const statsRef = useRef<MarketStats>(stats);
  statsRef.current = stats;

  useEffect(() => {
    const client = new MarketPulseWebSocketClient();
    clientRef.current = client;

    const unsubscribeStatus = client.onStatusChange((newStatus) => {
      setStatus(newStatus);
    });

    const unsubscribeTrades = client.onTradesBatch((newTrades) => {
      if (newTrades.length === 0) return;

      // 1. Update Lightweight Charts directly (out-of-React-state for 60fps performance)
      if (chartRef.current) {
        chartRef.current.updateWithTrades(newTrades);
      }

      // 2. Update stats and tape in throttled React state
      const latestTrade = newTrades[newTrades.length - 1];
      const prevStats = statsRef.current;

      let newHigh = prevStats.high;
      let newLow = prevStats.low;
      let batchVolume = 0;

      for (const t of newTrades) {
        if (t.price > newHigh) newHigh = t.price;
        if (t.price < newLow) newLow = t.price;
        batchVolume += t.qty;
      }

      const diff = latestTrade.price - prevStats.previousClose;
      const diffPercent = prevStats.previousClose > 0 ? (diff / prevStats.previousClose) * 100 : 0;

      setStats({
        ...prevStats,
        lastPrice: latestTrade.price,
        change: diff,
        changePercent: diffPercent,
        high: newHigh,
        low: newLow,
        volume: prevStats.volume + batchVolume,
        tradesCount: prevStats.tradesCount + newTrades.length,
      });

      // Update capped trade tape (keep last 50 trades)
      setRecentTrades((prev) => {
        const combined = [...newTrades, ...prev];
        return combined.slice(0, 50);
      });
    });

    // Subscribe to symbol channel
    client.subscribe('trades:AAPL');
    client.connect();

    return () => {
      unsubscribeStatus();
      unsubscribeTrades();
      client.disconnect();
      clientRef.current = null;
    };
  }, []);

  const handleSetSpeed = async (tps: number) => {
    setCurrentTps(tps);
    try {
      await fetch('http://localhost:8000/api/v1/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          seed: 42,
          symbol: 'AAPL',
          trades_per_sec: tps,
          initial_price: stats.lastPrice,
        }),
      });
    } catch (err) {
      console.error('Failed to update session speed:', err);
    }
  };

  const handleResetSession = async () => {
    const newSeed = Math.floor(Math.random() * 10000);
    try {
      await fetch('http://localhost:8000/api/v1/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          seed: newSeed,
          symbol: 'AAPL',
          trades_per_sec: currentTps,
          initial_price: 150.0,
        }),
      });
      setStats({
        symbol: 'AAPL',
        lastPrice: 150.0,
        previousClose: 150.0,
        change: 0.0,
        changePercent: 0.0,
        high: 150.0,
        low: 150.0,
        volume: 0,
        tradesCount: 0,
        tradesPerSec: currentTps,
      });
      setRecentTrades([]);
    } catch (err) {
      console.error('Failed to reset session:', err);
    }
  };

  return (
    <div className="flex flex-col h-screen w-screen bg-slate-950 text-slate-100 overflow-hidden select-none">
      {/* Top Status & Controls Header */}
      <Header
        status={status}
        stats={stats}
        currentTps={currentTps}
        onSetSimulationSpeed={handleSetSpeed}
        onResetSession={handleResetSession}
      />

      {/* Main Terminal Workspace Layout */}
      <div className="flex-1 flex flex-col p-4 gap-4 overflow-hidden min-h-0">
        {/* Top Metric Cards */}
        <MarketStatsCards stats={stats} />

        {/* Center Grid: Chart + Trade Tape */}
        <div className="flex-1 grid grid-cols-1 lg:grid-cols-3 gap-4 min-h-0">
          {/* Main Chart Pane (2 Columns) */}
          <div className="lg:col-span-2 h-full flex flex-col min-h-0">
            <PriceChart ref={chartRef} symbol={stats.symbol} />
          </div>

          {/* Right Tape Pane (1 Column) */}
          <div className="lg:col-span-1 h-full flex flex-col min-h-0">
            <TradeTape trades={recentTrades} />
          </div>
        </div>
      </div>
    </div>
  );
};

export default App;
