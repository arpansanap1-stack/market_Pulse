import React, { useEffect, useRef, useState } from 'react';
import { AnomalyFeed } from './components/AnomalyFeed';
import { DepthLadder } from './components/DepthLadder';
import { Header } from './components/Header';
import { MarketStatsCards } from './components/MarketStats';
import { OrderTicket } from './components/OrderTicket';
import { PortfolioPanel } from './components/PortfolioPanel';
import { PriceChart } from './components/PriceChart';
import type { PriceChartHandle } from './components/PriceChart';
import { ReplayControls } from './components/ReplayControls';
import { ScenarioControls } from './components/ScenarioControls';
import { TradeTape } from './components/TradeTape';
import { MarketPulseWebSocketClient } from './services/wsClient';
import type { ConnectionStatus } from './services/wsClient';
import type {
  BookDeltaItem,
  ChartTimeframe,
  MarketAnomaly,
  MarketStats,
  MarketStatus,
  Trade,
} from './types/protocol';
import type { ActiveSessionStatus, SessionMetadata } from './types/session';
import type { PortfolioSummary } from './types/portfolio';

export const App: React.FC = () => {
  const [status, setStatus] = useState<ConnectionStatus>('CONNECTING');
  const [currentTps, setCurrentTps] = useState<number>(50);
  const [currentTimeframe, setCurrentTimeframe] = useState<ChartTimeframe>('1s');
  const [recentTrades, setRecentTrades] = useState<Trade[]>([]);
  const [bookDeltas, setBookDeltas] = useState<BookDeltaItem[]>([]);
  const [anomalies, setAnomalies] = useState<MarketAnomaly[]>([]);
  const [marketStatus, setMarketStatus] = useState<MarketStatus | null>(null);
  const [rightPanelTab, setRightPanelTab] = useState<'TICKET' | 'ANOMALIES' | 'TAPE'>('TICKET');
  const [sessionStatus, setSessionStatus] = useState<ActiveSessionStatus | null>(null);
  const [sessions, setSessions] = useState<SessionMetadata[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [topOfBook, setTopOfBook] = useState<{ bestBid: number | null; bestAsk: number | null }>({
    bestBid: null,
    bestAsk: null,
  });

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
  const currentTimeframeRef = useRef<ChartTimeframe>(currentTimeframe);
  currentTimeframeRef.current = currentTimeframe;

  const fetchSessionStatus = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/v1/sessions/active');
      if (res.ok) {
        const data = await res.json();
        setSessionStatus(data);
      }
    } catch {
      // ignore network errors
    }
  };

  const fetchSessions = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/v1/sessions?limit=50');
      if (res.ok) {
        const data = await res.json();
        setSessions(data);
      }
    } catch {
      // ignore network errors
    }
  };

  const fetchPortfolio = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/v1/portfolio');
      if (res.ok) {
        const data: PortfolioSummary = await res.json();
        setPortfolio(data);
      }
    } catch {
      // ignore network errors
    }
  };

  const fetchTopOfBook = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/v1/book?symbol=AAPL&levels=1');
      if (res.ok) {
        const data = await res.json();
        const tickSize = 0.01;
        setTopOfBook({
          bestBid: data.best_bid ? Number((data.best_bid * tickSize).toFixed(2)) : null,
          bestAsk: data.best_ask ? Number((data.best_ask * tickSize).toFixed(2)) : null,
        });
      }
    } catch {
      // ignore network errors
    }
  };

  // Fetch initial market status and session list
  useEffect(() => {
    fetch('http://localhost:8000/api/v1/market-status?symbol=AAPL')
      .then((res) => (res.ok ? res.json() : null))
      .then((data: MarketStatus | null) => {
        if (data) setMarketStatus(data);
      })
      .catch(() => {});

    fetchSessionStatus();
    fetchSessions();
    fetchPortfolio();
    fetchTopOfBook();

    const interval = setInterval(fetchSessionStatus, 800);
    const bookInterval = setInterval(fetchTopOfBook, 2000);
    return () => {
      clearInterval(interval);
      clearInterval(bookInterval);
    };
  }, []);


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

    const unsubscribeBars = client.onBarsBatch((interval, newBars) => {
      if (chartRef.current) {
        chartRef.current.updateWithBars(interval, newBars);
      }
    });

    const unsubscribeBook = client.onBookBatch((deltas) => {
      setBookDeltas(deltas);
    });

    const unsubscribeAnomalies = client.onAnomaliesBatch((newAnoms) => {
      setAnomalies((prev) => [...newAnoms, ...prev].slice(0, 100));
    });

    const unsubscribeMarketEvents = client.onMarketEventsBatch((events) => {
      for (const evt of events) {
        if (evt.kind === 'HALT') {
          setMarketStatus((prev) => ({
            symbol: prev?.symbol || 'AAPL',
            latest_price: prev?.latest_price || statsRef.current.lastPrice,
            is_halted: true,
            status: 'HALTED',
          }));
        } else if (evt.kind === 'RESUME') {
          setMarketStatus((prev) => ({
            symbol: prev?.symbol || 'AAPL',
            latest_price: prev?.latest_price || statsRef.current.lastPrice,
            is_halted: false,
            status: 'ACTIVE',
          }));
        }
      }
    });

    const unsubscribePortfolio = client.onPortfolioUpdate((newPortfolio) => {
      setPortfolio(newPortfolio);
    });

    // Subscribe to symbol trades, order book, bar interval, anomalies, and events
    client.subscribe('trades:AAPL');
    client.subscribe('book:AAPL');
    client.subscribe(`bars:AAPL:${currentTimeframeRef.current}`);
    client.subscribe('anomalies:AAPL');
    client.subscribe('events:market');
    client.subscribe('portfolio:user');
    client.connect();

    return () => {
      unsubscribeStatus();
      unsubscribeTrades();
      unsubscribeBars();
      unsubscribeBook();
      unsubscribeAnomalies();
      unsubscribeMarketEvents();
      unsubscribePortfolio();
      client.disconnect();
      clientRef.current = null;
    };
  }, []);

  const handleTimeframeChange = (newTf: ChartTimeframe) => {
    if (clientRef.current) {
      clientRef.current.unsubscribe(`bars:${stats.symbol}:${currentTimeframeRef.current}`);
      clientRef.current.subscribe(`bars:${stats.symbol}:${newTf}`);
    }
    setCurrentTimeframe(newTf);
  };

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
      setBookDeltas([]);
      setAnomalies([]);
      setMarketStatus({
        symbol: 'AAPL',
        is_halted: false,
        status: 'ACTIVE',
        latest_price: 150.0,
      });
    } catch (err) {
      console.error('Failed to reset session:', err);
    }
  };

  const handleStartReplay = async (sessionId: string, speed: number = 1.0, seekSeq: number = 1) => {
    try {
      await fetch(`http://localhost:8000/api/v1/sessions/${sessionId}/replay`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ speed_multiplier: speed, seek_seq: seekSeq }),
      });
      setRecentTrades([]);
      setBookDeltas([]);
      setAnomalies([]);
      await fetchSessionStatus();
    } catch (err) {
      console.error('Failed to start replay:', err);
    }
  };

  const handlePauseReplay = async () => {
    if (!sessionStatus?.session_id) return;
    try {
      await fetch(`http://localhost:8000/api/v1/sessions/${sessionStatus.session_id}/pause`, {
        method: 'POST',
      });
      await fetchSessionStatus();
    } catch (err) {
      console.error('Failed to pause replay:', err);
    }
  };

  const handleResumeReplay = async () => {
    if (!sessionStatus?.session_id) return;
    try {
      await fetch(`http://localhost:8000/api/v1/sessions/${sessionStatus.session_id}/resume`, {
        method: 'POST',
      });
      await fetchSessionStatus();
    } catch (err) {
      console.error('Failed to resume replay:', err);
    }
  };

  const handleSeekReplay = async (targetSeq: number) => {
    if (!sessionStatus?.session_id) return;
    try {
      await fetch(`http://localhost:8000/api/v1/sessions/${sessionStatus.session_id}/seek`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_seq: targetSeq }),
      });
      await fetchSessionStatus();
    } catch (err) {
      console.error('Failed to seek replay:', err);
    }
  };

  const handleSetReplaySpeed = async (speed: number) => {
    if (!sessionStatus?.session_id) return;
    try {
      await fetch(`http://localhost:8000/api/v1/sessions/${sessionStatus.session_id}/speed`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ speed_multiplier: speed }),
      });
      await fetchSessionStatus();
    } catch (err) {
      console.error('Failed to set replay speed:', err);
    }
  };

  const handleReturnToLive = async () => {
    try {
      await fetch('http://localhost:8000/api/v1/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          seed: 42,
          symbol: 'AAPL',
          trades_per_sec: currentTps,
          initial_price: stats.lastPrice || 150.0,
        }),
      });
      setRecentTrades([]);
      setBookDeltas([]);
      setAnomalies([]);
      await fetchSessionStatus();
      await fetchSessions();
    } catch (err) {
      console.error('Failed to return to live mode:', err);
    }
  };

  const handleInjectScenario = async (scenarioId: string, params?: Record<string, unknown>) => {
    try {
      const res = await fetch('http://localhost:8000/api/v1/scenarios/inject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scenario_id: scenarioId,
          symbol: stats.symbol,
          params: params || {},
        }),
      });
      if (res.ok) {
        const data = await res.json();
        if (typeof data.is_halted === 'boolean') {
          setMarketStatus((prev) => ({
            symbol: prev?.symbol || stats.symbol,
            latest_price: prev?.latest_price || stats.lastPrice,
            is_halted: data.is_halted,
            status: data.is_halted ? 'HALTED' : 'ACTIVE',
          }));
        }
      }
    } catch (err) {
      console.error('Failed to inject scenario:', err);
      throw err;
    }
  };

  return (
    <div className="flex flex-col h-screen w-screen bg-slate-950 text-slate-100 overflow-hidden select-none">
      {/* Top Status & Controls Header */}
      <Header
        status={status}
        stats={stats}
        currentTps={currentTps}
        isHalted={marketStatus?.is_halted}
        onSetSimulationSpeed={handleSetSpeed}
        onResetSession={handleResetSession}
      />

      {/* Main Terminal Workspace Layout */}
      <div className="flex-1 flex flex-col p-4 gap-3.5 overflow-y-auto min-h-0">
        {/* Top Metric Cards */}
        <MarketStatsCards stats={stats} />

        {/* Historical Session Persistence & Replay Scrubber */}
        <ReplayControls
          sessionStatus={sessionStatus}
          sessions={sessions}
          onStartReplay={handleStartReplay}
          onPause={handlePauseReplay}
          onResume={handleResumeReplay}
          onSeek={handleSeekReplay}
          onSetSpeed={handleSetReplaySpeed}
          onReturnToLive={handleReturnToLive}
          onRefreshSessions={fetchSessions}
        />

        {/* Exogenous Market Scenarios & Circuit Breaker Launcher */}
        <ScenarioControls
          marketStatus={marketStatus}
          onInject={handleInjectScenario}
        />

        {/* Center 12-Column Grid: Chart (6) + Order Book (3) + Tabbed Panel (3) */}
        <div className="grid grid-cols-12 gap-3.5 min-h-[500px]">
          {/* Main Chart Pane (6 Columns) */}
          <div className="col-span-12 lg:col-span-6 xl:col-span-6 h-full flex flex-col min-h-0">
            <PriceChart
              ref={chartRef}
              symbol={stats.symbol}
              onTimeframeChange={handleTimeframeChange}
            />
          </div>

          {/* L2 Order Book Depth Ladder (3 Columns) */}
          <div className="col-span-12 sm:col-span-6 lg:col-span-3 xl:col-span-3 h-full flex flex-col min-h-0">
            <DepthLadder symbol={stats.symbol} deltas={bookDeltas} levels={10} />
          </div>

          {/* Right Tabbed Panel: Order Ticket vs Microstructure Anomalies vs Trade Tape (3 Columns) */}
          <div className="col-span-12 sm:col-span-6 lg:col-span-3 xl:col-span-3 h-full flex flex-col min-h-0 bg-slate-900 border border-slate-800 rounded-lg overflow-hidden shadow-xl">
            {/* Panel Selector Tabs */}
            <div className="flex items-center border-b border-slate-800 bg-slate-950/70 p-1">
              <button
                onClick={() => setRightPanelTab('TICKET')}
                className={`flex-1 py-1.5 text-xs font-semibold rounded transition-colors flex items-center justify-center gap-1 ${
                  rightPanelTab === 'TICKET'
                    ? 'bg-slate-800 text-cyan-400 shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <span>🎫 Trade</span>
              </button>
              <button
                onClick={() => setRightPanelTab('ANOMALIES')}
                className={`flex-1 py-1.5 text-xs font-semibold rounded transition-colors flex items-center justify-center gap-1 ${
                  rightPanelTab === 'ANOMALIES'
                    ? 'bg-slate-800 text-sky-400 shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <span>⚡ Alert</span>
                {anomalies.length > 0 && (
                  <span className="px-1.5 py-0.2 rounded-full text-[9px] font-mono bg-rose-500/20 text-rose-300">
                    {anomalies.length}
                  </span>
                )}
              </button>
              <button
                onClick={() => setRightPanelTab('TAPE')}
                className={`flex-1 py-1.5 text-xs font-semibold rounded transition-colors flex items-center justify-center gap-1 ${
                  rightPanelTab === 'TAPE'
                    ? 'bg-slate-800 text-sky-400 shadow-sm'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <span>📜 Tape</span>
                <span className="px-1.5 py-0.2 rounded-full text-[9px] font-mono bg-slate-700 text-slate-300">
                  {recentTrades.length}
                </span>
              </button>
            </div>

            {/* Tab Contents */}
            <div className="flex-1 min-h-0 overflow-y-auto">
              {rightPanelTab === 'TICKET' ? (
                <div className="p-2">
                  <OrderTicket
                    symbol={stats.symbol}
                    bestBid={topOfBook.bestBid}
                    bestAsk={topOfBook.bestAsk}
                    lastPrice={stats.lastPrice}
                    availableCash={portfolio?.cash ?? 100000.0}
                    onOrderSubmitted={() => {
                      fetchPortfolio();
                    }}
                  />
                </div>
              ) : rightPanelTab === 'ANOMALIES' ? (
                <AnomalyFeed
                  anomalies={anomalies}
                  onClear={() => setAnomalies([])}
                />
              ) : (
                <TradeTape trades={recentTrades} />
              )}
            </div>
          </div>
        </div>

        {/* Portfolio & OMS Panel: Cash, Equity, Positions, Open Orders, and Trade History */}
        <div className="shrink-0">
          <PortfolioPanel
            portfolio={portfolio}
            onRefreshPortfolio={fetchPortfolio}
          />
        </div>
      </div>
    </div>
  );
};

export default App;
