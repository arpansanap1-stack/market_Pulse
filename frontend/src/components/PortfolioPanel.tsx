import React, { useState, useEffect } from 'react';
import {
  Wallet,
  TrendingUp,
  TrendingDown,
  RotateCcw,
  Clock,
  Briefcase,
  Layers,
  History,
  AlertTriangle,
} from 'lucide-react';
import type {
  OrderRecord,
  PortfolioSummary,
  PositionItem,
  UserTradeRecord,
} from '../types/portfolio';

interface PortfolioPanelProps {
  portfolio: PortfolioSummary | null;
  onRefreshPortfolio?: () => void;
  onOrderCanceled?: (orderId: string) => void;
}

type SubTab = 'positions' | 'orders' | 'trades';

export const PortfolioPanel: React.FC<PortfolioPanelProps> = ({
  portfolio,
  onRefreshPortfolio,
  onOrderCanceled,
}) => {
  const [activeTab, setActiveTab] = useState<SubTab>('positions');
  const [openOrders, setOpenOrders] = useState<OrderRecord[]>([]);
  const [tradeHistory, setTradeHistory] = useState<UserTradeRecord[]>([]);
  const [cancelingId, setCancelingId] = useState<string | null>(null);
  const [showResetConfirm, setShowResetConfirm] = useState<boolean>(false);
  const [resetting, setResetting] = useState<boolean>(false);

  // Fetch open orders
  const fetchOpenOrders = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/v1/orders?status=open');
      if (res.ok) {
        const data = await res.json();
        setOpenOrders(data);
      }
    } catch (err) {
      console.error('Failed to fetch open orders:', err);
    }
  };

  // Fetch trade history
  const fetchTrades = async () => {
    try {
      const res = await fetch('http://localhost:8000/api/v1/portfolio/trades?limit=50');
      if (res.ok) {
        const data = await res.json();
        setTradeHistory(data);
      }
    } catch (err) {
      console.error('Failed to fetch user trades:', err);
    }
  };

  // Fetch on mount and tab switch
  useEffect(() => {
    if (activeTab === 'orders') {
      fetchOpenOrders();
    } else if (activeTab === 'trades') {
      fetchTrades();
    }
  }, [activeTab]);

  // Periodic refresh of open orders & trades every 3s
  useEffect(() => {
    const timer = setInterval(() => {
      if (activeTab === 'orders') {
        fetchOpenOrders();
      } else if (activeTab === 'trades') {
        fetchTrades();
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [activeTab]);

  const handleCancelOrder = async (orderId: string) => {
    setCancelingId(orderId);
    try {
      const res = await fetch(`http://localhost:8000/api/v1/orders/${orderId}`, {
        method: 'DELETE',
      });
      if (res.ok) {
        setOpenOrders((prev) => prev.filter((o) => o.order_id !== orderId));
        if (onOrderCanceled) {
          onOrderCanceled(orderId);
        }
        if (onRefreshPortfolio) {
          onRefreshPortfolio();
        }
      }
    } catch (err) {
      console.error('Failed to cancel order:', err);
    } finally {
      setCancelingId(null);
    }
  };

  const handleResetPortfolio = async () => {
    setResetting(true);
    try {
      const res = await fetch('http://localhost:8000/api/v1/portfolio/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ initial_cash: 100000.0 }),
      });
      if (res.ok) {
        setShowResetConfirm(false);
        setOpenOrders([]);
        setTradeHistory([]);
        if (onRefreshPortfolio) {
          onRefreshPortfolio();
        }
      }
    } catch (err) {
      console.error('Failed to reset portfolio:', err);
    } finally {
      setResetting(false);
    }
  };

  const equity = portfolio?.equity ?? 100000.0;
  const cash = portfolio?.cash ?? 100000.0;
  const initialCash = portfolio?.initial_cash ?? 100000.0;
  const realizedPnl = portfolio?.realized_pnl ?? 0.0;
  const unrealizedPnl = portfolio?.unrealized_pnl ?? 0.0;
  const totalPnl = portfolio?.total_pnl ?? (realizedPnl + unrealizedPnl);
  const totalReturnPct = initialCash > 0 ? (totalPnl / initialCash) * 100 : 0;
  const positions: PositionItem[] = portfolio?.positions ?? [];

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg flex flex-col shadow-xl overflow-hidden">
      {/* Top Banner: Financial Chips */}
      <div className="p-3 bg-slate-950/80 border-b border-slate-800 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-md bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <Wallet size={16} />
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider font-mono text-slate-400">
              Paper Trading Portfolio
            </div>
            <div className="text-sm font-mono font-bold text-slate-100 flex items-center gap-1.5">
              ${equity.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              <span className="text-[10px] font-normal text-slate-400">Total Equity</span>
            </div>
          </div>
        </div>

        {/* Stats Chips */}
        <div className="flex flex-wrap items-center gap-2 text-xs font-mono">
          <div className="px-2.5 py-1 rounded bg-slate-900 border border-slate-800 flex flex-col">
            <span className="text-[9px] uppercase text-slate-400">Cash Balance</span>
            <span className="text-slate-200 font-semibold">
              ${cash.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>

          <div className="px-2.5 py-1 rounded bg-slate-900 border border-slate-800 flex flex-col">
            <span className="text-[9px] uppercase text-slate-400">Unrealized P&L</span>
            <span
              className={`font-semibold flex items-center gap-0.5 ${
                unrealizedPnl > 0
                  ? 'text-emerald-400'
                  : unrealizedPnl < 0
                  ? 'text-rose-400'
                  : 'text-slate-400'
              }`}
            >
              {unrealizedPnl > 0 ? '+' : ''}${unrealizedPnl.toFixed(2)}
            </span>
          </div>

          <div className="px-2.5 py-1 rounded bg-slate-900 border border-slate-800 flex flex-col">
            <span className="text-[9px] uppercase text-slate-400">Realized P&L</span>
            <span
              className={`font-semibold flex items-center gap-0.5 ${
                realizedPnl > 0
                  ? 'text-emerald-400'
                  : realizedPnl < 0
                  ? 'text-rose-400'
                  : 'text-slate-400'
              }`}
            >
              {realizedPnl > 0 ? '+' : ''}${realizedPnl.toFixed(2)}
            </span>
          </div>

          <div className="px-2.5 py-1 rounded bg-slate-900 border border-slate-800 flex flex-col">
            <span className="text-[9px] uppercase text-slate-400">Total Return</span>
            <span
              className={`font-bold flex items-center gap-0.5 ${
                totalPnl > 0
                  ? 'text-emerald-400'
                  : totalPnl < 0
                  ? 'text-rose-400'
                  : 'text-slate-300'
              }`}
            >
              {totalPnl >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
              {totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)} ({totalReturnPct >= 0 ? '+' : ''}
              {totalReturnPct.toFixed(2)}%)
            </span>
          </div>

          <button
            type="button"
            onClick={() => setShowResetConfirm(true)}
            className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-slate-200 border border-slate-700 transition-colors ml-1"
            title="Reset Portfolio to $100,000"
          >
            <RotateCcw size={14} />
          </button>
        </div>
      </div>

      {/* Reset Confirmation Bar */}
      {showResetConfirm && (
        <div className="bg-rose-950/60 border-b border-rose-800/80 px-4 py-2 flex items-center justify-between text-xs font-mono text-rose-200">
          <div className="flex items-center gap-2">
            <AlertTriangle size={14} className="text-rose-400 shrink-0" />
            <span>Reset portfolio to initial $100,000 and clear all positions/orders?</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={resetting}
              onClick={handleResetPortfolio}
              className="px-2.5 py-1 bg-rose-600 hover:bg-rose-500 text-white rounded font-semibold text-[11px] transition-colors disabled:opacity-50"
            >
              {resetting ? 'Resetting...' : 'Yes, Reset'}
            </button>
            <button
              type="button"
              onClick={() => setShowResetConfirm(false)}
              className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-[11px] transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Sub-tab Navigation */}
      <div className="flex items-center border-b border-slate-800 px-3 bg-slate-900/90 text-xs font-mono">
        <button
          type="button"
          onClick={() => setActiveTab('positions')}
          className={`py-2 px-3 flex items-center gap-1.5 border-b-2 font-medium transition-all ${
            activeTab === 'positions'
              ? 'border-cyan-500 text-cyan-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Briefcase size={13} />
          <span>Positions ({positions.filter((p) => p.qty !== 0).length})</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('orders')}
          className={`py-2 px-3 flex items-center gap-1.5 border-b-2 font-medium transition-all ${
            activeTab === 'orders'
              ? 'border-cyan-500 text-cyan-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Clock size={13} />
          <span>Open Orders ({openOrders.length})</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('trades')}
          className={`py-2 px-3 flex items-center gap-1.5 border-b-2 font-medium transition-all ${
            activeTab === 'trades'
              ? 'border-cyan-500 text-cyan-400'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <History size={13} />
          <span>Trade History ({tradeHistory.length})</span>
        </button>
      </div>

      {/* Tab Contents */}
      <div className="p-3 overflow-x-auto min-h-[160px] max-h-[260px] overflow-y-auto">
        {/* 1. POSITIONS TAB */}
        {activeTab === 'positions' && (
          <div>
            {positions.filter((p) => p.qty !== 0).length === 0 ? (
              <div className="py-8 flex flex-col items-center justify-center text-slate-500 text-xs font-mono gap-1">
                <Layers size={20} className="text-slate-600 mb-1" />
                <span>No active positions</span>
                <span className="text-[11px] text-slate-600">
                  Use the Order Ticket to submit your first trade
                </span>
              </div>
            ) : (
              <table className="w-full text-left text-xs font-mono">
                <thead>
                  <tr className="text-slate-400 text-[10px] uppercase border-b border-slate-800">
                    <th className="pb-1.5 font-medium">Symbol</th>
                    <th className="pb-1.5 font-medium">Side</th>
                    <th className="pb-1.5 font-medium text-right">Shares</th>
                    <th className="pb-1.5 font-medium text-right">Avg Entry</th>
                    <th className="pb-1.5 font-medium text-right">Mark Price</th>
                    <th className="pb-1.5 font-medium text-right">Market Value</th>
                    <th className="pb-1.5 font-medium text-right">Unrealized P&L</th>
                    <th className="pb-1.5 font-medium text-right">Realized P&L</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {positions
                    .filter((p) => p.qty !== 0)
                    .map((pos) => {
                      const isLong = pos.qty > 0;
                      const returnPct =
                        pos.avg_entry_price > 0
                          ? ((pos.current_price - pos.avg_entry_price) / pos.avg_entry_price) *
                            (isLong ? 100 : -100)
                          : 0;

                      return (
                        <tr key={pos.symbol} className="hover:bg-slate-800/40 transition-colors">
                          <td className="py-2 font-bold text-slate-200">{pos.symbol}</td>
                          <td className="py-2">
                            <span
                              className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                                isLong
                                  ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/50'
                                  : 'bg-rose-950/60 text-rose-400 border border-rose-800/50'
                              }`}
                            >
                              {isLong ? 'LONG' : 'SHORT'}
                            </span>
                          </td>
                          <td className="py-2 text-right font-semibold text-slate-200">
                            {Math.abs(pos.qty)}
                          </td>
                          <td className="py-2 text-right text-slate-300">
                            ${pos.avg_entry_price.toFixed(2)}
                          </td>
                          <td className="py-2 text-right text-slate-300">
                            ${pos.current_price.toFixed(2)}
                          </td>
                          <td className="py-2 text-right text-slate-200">
                            ${pos.market_value.toLocaleString(undefined, {
                              minimumFractionDigits: 2,
                              maximumFractionDigits: 2,
                            })}
                          </td>
                          <td
                            className={`py-2 text-right font-semibold ${
                              pos.unrealized_pnl > 0
                                ? 'text-emerald-400'
                                : pos.unrealized_pnl < 0
                                ? 'text-rose-400'
                                : 'text-slate-400'
                            }`}
                          >
                            {pos.unrealized_pnl > 0 ? '+' : ''}${pos.unrealized_pnl.toFixed(2)} (
                            {returnPct > 0 ? '+' : ''}
                            {returnPct.toFixed(2)}%)
                          </td>
                          <td
                            className={`py-2 text-right font-semibold ${
                              pos.realized_pnl > 0
                                ? 'text-emerald-400'
                                : pos.realized_pnl < 0
                                ? 'text-rose-400'
                                : 'text-slate-400'
                            }`}
                          >
                            {pos.realized_pnl > 0 ? '+' : ''}${pos.realized_pnl.toFixed(2)}
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* 2. OPEN ORDERS TAB */}
        {activeTab === 'orders' && (
          <div>
            {openOrders.length === 0 ? (
              <div className="py-8 flex flex-col items-center justify-center text-slate-500 text-xs font-mono gap-1">
                <Clock size={20} className="text-slate-600 mb-1" />
                <span>No open resting orders</span>
                <span className="text-[11px] text-slate-600">
                  All placed orders have been filled or canceled
                </span>
              </div>
            ) : (
              <table className="w-full text-left text-xs font-mono">
                <thead>
                  <tr className="text-slate-400 text-[10px] uppercase border-b border-slate-800">
                    <th className="pb-1.5 font-medium">Order ID</th>
                    <th className="pb-1.5 font-medium">Symbol</th>
                    <th className="pb-1.5 font-medium">Side</th>
                    <th className="pb-1.5 font-medium">Type</th>
                    <th className="pb-1.5 font-medium">Status</th>
                    <th className="pb-1.5 font-medium text-right">Price / Trigger</th>
                    <th className="pb-1.5 font-medium text-right">Qty</th>
                    <th className="pb-1.5 font-medium text-right">Filled</th>
                    <th className="pb-1.5 font-medium text-center">TIF</th>
                    <th className="pb-1.5 font-medium text-center">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {openOrders.map((order) => {
                    const isBuy = order.side === 'BUY';
                    return (
                      <tr key={order.order_id} className="hover:bg-slate-800/40 transition-colors">
                        <td className="py-2 text-slate-300 text-[11px] font-mono">
                          <div className="flex flex-col">
                            <span>{order.order_id}</span>
                            {order.oco_group_id && (
                              <span className="text-[9px] font-mono text-cyan-400 bg-cyan-950/60 px-1 rounded border border-cyan-800/40 w-fit mt-0.5">
                                OCO: {order.oco_group_id.slice(0, 8)}
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="py-2 font-bold text-slate-200">{order.symbol}</td>
                        <td className="py-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                              isBuy
                                ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/50'
                                : 'bg-rose-950/60 text-rose-400 border border-rose-800/50'
                            }`}
                          >
                            {order.side}
                          </span>
                        </td>
                        <td className="py-2 text-slate-300 text-[11px]">
                          {order.order_type.replace('_', ' ')}
                        </td>
                        <td className="py-2">
                          {order.status === 'UNTRIGGERED' ? (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-amber-950/60 text-amber-400 border border-amber-800/50">
                              WORKING TRIGGER
                            </span>
                          ) : order.status === 'TRIGGERED' ? (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-blue-950/60 text-blue-400 border border-blue-800/50">
                              TRIGGERED
                            </span>
                          ) : (
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-slate-800 text-slate-300 border border-slate-700">
                              {order.status}
                            </span>
                          )}
                        </td>
                        <td className="py-2 text-right">
                          {order.order_type === 'STOP_LOSS' && (
                            <span className="text-rose-400 font-semibold text-[11px]">
                              Stop ${order.stop_price?.toFixed(2)} → MKT
                            </span>
                          )}
                          {order.order_type === 'STOP_LIMIT' && (
                            <span className="text-amber-400 font-semibold text-[11px]">
                              Stop ${order.stop_price?.toFixed(2)} | Lmt ${order.price?.toFixed(2)}
                            </span>
                          )}
                          {order.order_type === 'TAKE_PROFIT' && (
                            <span className="text-emerald-400 font-semibold text-[11px]">
                              TP ${order.stop_price?.toFixed(2)} → MKT
                            </span>
                          )}
                          {order.order_type === 'TAKE_PROFIT_LIMIT' && (
                            <span className="text-emerald-400 font-semibold text-[11px]">
                              TP ${order.stop_price?.toFixed(2)} | Lmt ${order.price?.toFixed(2)}
                            </span>
                          )}
                          {order.order_type === 'TRAILING_STOP' && (
                            <div className="flex flex-col text-right">
                              <span className="text-cyan-400 font-semibold text-[11px]">
                                Trail ${order.trail_offset?.toFixed(2)}
                              </span>
                              <span className="text-[10px] text-slate-400">
                                Stop: ${order.current_stop ? order.current_stop.toFixed(2) : 'calc...'}
                              </span>
                            </div>
                          )}
                          {(order.order_type === 'LIMIT' || order.order_type === 'MARKET') && (
                            <span className="font-semibold text-slate-200">
                              {order.price ? `$${order.price.toFixed(2)}` : 'MKT'}
                            </span>
                          )}
                        </td>
                        <td className="py-2 text-right text-slate-200">{order.qty}</td>
                        <td className="py-2 text-right text-slate-400">{order.filled_qty}</td>
                        <td className="py-2 text-center text-[10px] text-slate-400">{order.tif}</td>
                        <td className="py-2 text-center">
                          <button
                            type="button"
                            disabled={cancelingId === order.order_id}
                            onClick={() => handleCancelOrder(order.order_id)}
                            className="px-2 py-0.5 rounded bg-rose-950/60 hover:bg-rose-900/80 text-rose-300 border border-rose-800/60 text-[11px] font-semibold transition-colors disabled:opacity-50"
                          >
                            {cancelingId === order.order_id ? '...' : 'Cancel'}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}

        {/* 3. TRADE HISTORY TAB */}
        {activeTab === 'trades' && (
          <div>
            {tradeHistory.length === 0 ? (
              <div className="py-8 flex flex-col items-center justify-center text-slate-500 text-xs font-mono gap-1">
                <History size={20} className="text-slate-600 mb-1" />
                <span>No trades recorded</span>
                <span className="text-[11px] text-slate-600">
                  Executed fills will appear here in chronological order
                </span>
              </div>
            ) : (
              <table className="w-full text-left text-xs font-mono">
                <thead>
                  <tr className="text-slate-400 text-[10px] uppercase border-b border-slate-800">
                    <th className="pb-1.5 font-medium">Trade ID</th>
                    <th className="pb-1.5 font-medium">Symbol</th>
                    <th className="pb-1.5 font-medium">Side</th>
                    <th className="pb-1.5 font-medium text-right">Price</th>
                    <th className="pb-1.5 font-medium text-right">Qty</th>
                    <th className="pb-1.5 font-medium text-right">Total Value</th>
                    <th className="pb-1.5 font-medium text-right">Order Ref</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/60">
                  {tradeHistory.map((trade) => {
                    const isBuy = trade.side === 'BUY';
                    const tradeValue = trade.price * trade.qty;
                    return (
                      <tr key={trade.trade_id} className="hover:bg-slate-800/40 transition-colors">
                        <td className="py-2 text-slate-400 text-[11px]">{trade.trade_id}</td>
                        <td className="py-2 font-bold text-slate-200">{trade.symbol}</td>
                        <td className="py-2">
                          <span
                            className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
                              isBuy
                                ? 'bg-emerald-950/60 text-emerald-400 border border-emerald-800/50'
                                : 'bg-rose-950/60 text-rose-400 border border-rose-800/50'
                            }`}
                          >
                            {trade.side}
                          </span>
                        </td>
                        <td className="py-2 text-right font-semibold text-slate-200">
                          ${trade.price.toFixed(2)}
                        </td>
                        <td className="py-2 text-right text-slate-200">{trade.qty}</td>
                        <td className="py-2 text-right text-slate-200">
                          ${tradeValue.toLocaleString(undefined, {
                            minimumFractionDigits: 2,
                            maximumFractionDigits: 2,
                          })}
                        </td>
                        <td className="py-2 text-right text-slate-500 text-[10px]">
                          {trade.order_id}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
