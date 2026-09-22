import React from 'react';
import { Activity, AlertTriangle, RefreshCw, Zap } from 'lucide-react';
import type { ConnectionStatus } from '../services/wsClient';
import type { MarketStats } from '../types/protocol';

interface HeaderProps {
  status: ConnectionStatus;
  stats: MarketStats;
  currentTps: number;
  isHalted?: boolean;
  availableSymbols?: string[];
  onSelectSymbol?: (symbol: string) => void;
  onSetSimulationSpeed: (tps: number) => void;
  onResetSession: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  status,
  stats,
  currentTps,
  isHalted = false,
  availableSymbols,
  onSelectSymbol,
  onSetSimulationSpeed,
  onResetSession,
}) => {
  const isUp = stats.change >= 0;

  return (
    <header className="border-b border-slate-800/80 bg-slate-950/80 px-4 py-3 backdrop-blur-md sticky top-0 z-50">
      <div className="flex flex-wrap items-center justify-between gap-4">
        {/* Left: Brand + Disclaimer Badge */}
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            <div className="h-8 w-8 rounded-lg bg-gradient-to-tr from-sky-500 to-emerald-400 p-0.5 shadow-lg shadow-sky-500/20">
              <div className="flex h-full w-full items-center justify-center rounded-[6px] bg-slate-950">
                <Activity className="h-4 w-4 text-sky-400" />
              </div>
            </div>
            <div>
              <span className="text-lg font-bold tracking-wider text-white">MARKET<span className="text-sky-400">PULSE</span></span>
              <span className="ml-2 text-[10px] font-mono tracking-widest text-slate-500 uppercase">Terminal v0.1</span>
            </div>
          </div>

          {/* Prominent Simulated Data Badge */}
          <div className="flex items-center space-x-1.5 rounded-full border border-amber-500/30 bg-amber-500/10 px-3 py-1 text-xs font-medium text-amber-300">
            <AlertTriangle className="h-3.5 w-3.5 text-amber-400 animate-pulse" />
            <span className="tracking-wide">SIMULATED DATA</span>
          </div>

          {/* Circuit Breaker Status Badge */}
          <div
            className={`flex items-center space-x-1.5 rounded-full border px-2.5 py-1 text-[11px] font-semibold tracking-wider ${
              isHalted
                ? 'border-rose-500/50 bg-rose-500/20 text-rose-300 animate-pulse'
                : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-400'
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${isHalted ? 'bg-rose-500' : 'bg-emerald-400'}`} />
            <span>{isHalted ? 'HALTED' : 'ACTIVE'}</span>
          </div>
        </div>

        {/* Center: Live Ticker & Price Header */}
        <div className="flex items-center space-x-6">
          <div className="flex items-baseline space-x-3">
            {availableSymbols && availableSymbols.length > 1 && onSelectSymbol ? (
              <select
                value={stats.symbol}
                onChange={(e) => onSelectSymbol(e.target.value)}
                className="bg-slate-900 border border-slate-700/80 rounded px-2 py-0.5 text-lg font-black tracking-wide text-sky-400 focus:outline-none focus:border-sky-500 cursor-pointer"
              >
                {availableSymbols.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-xl font-black tracking-wide text-white">{stats.symbol}</span>
            )}
            <span className="text-xs text-slate-400">Simulated Equity</span>
            <span className={`font-tabular text-2xl font-bold ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>
              ${stats.lastPrice.toFixed(2)}
            </span>
            <span className={`font-tabular text-sm font-semibold flex items-center ${isUp ? 'text-emerald-400' : 'text-rose-400'}`}>
              {isUp ? '▲' : '▼'} {stats.change >= 0 ? '+' : ''}{stats.change.toFixed(2)} ({stats.changePercent.toFixed(2)}%)
            </span>
          </div>
        </div>

        {/* Right: Simulation Controls & Status */}
        <div className="flex items-center space-x-4">
          {/* Speed Preset Buttons */}
          <div className="flex items-center space-x-1 bg-slate-900/80 p-1 rounded-lg border border-slate-800 text-xs">
            <span className="px-2 text-slate-400 font-mono text-[11px] flex items-center gap-1">
              <Zap className="w-3 h-3 text-amber-400" /> Rate:
            </span>
            {[50, 250, 1000].map((rate) => (
              <button
                key={rate}
                onClick={() => onSetSimulationSpeed(rate)}
                className={`px-2.5 py-1 rounded font-mono font-medium transition-all ${
                  currentTps === rate
                    ? 'bg-sky-500/20 text-sky-300 border border-sky-500/40 shadow-sm shadow-sky-500/20'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                }`}
                title={`Set simulation throughput to ${rate} trades/sec`}
              >
                {rate}/s
              </button>
            ))}
          </div>

          {/* Reset button */}
          <button
            onClick={onResetSession}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-700/60 bg-slate-800/60 text-xs font-medium text-slate-300 hover:bg-slate-700/80 hover:text-white transition-all shadow-sm"
            title="Reset simulation with fresh seed"
          >
            <RefreshCw className="h-3.5 w-3.5 text-slate-400" />
            <span>Reset</span>
          </button>

          {/* Connection Status Indicator */}
          <div className="flex items-center space-x-2 rounded-lg border border-slate-800 bg-slate-900/90 px-3 py-1.5 text-xs font-mono">
            <div
              className={`h-2 w-2 rounded-full ${
                status === 'CONNECTED'
                  ? 'bg-emerald-400 animate-pulse-live'
                  : status === 'CONNECTING'
                  ? 'bg-amber-400 animate-ping'
                  : 'bg-rose-500'
              }`}
            />
            <span className={status === 'CONNECTED' ? 'text-emerald-300' : 'text-slate-400'}>
              {status}
            </span>
          </div>
        </div>
      </div>
    </header>
  );
};
