import React, { useState } from 'react';
import type { MarketAnomaly, AnomalySeverity } from '../types/protocol';

interface AnomalyFeedProps {
  anomalies: MarketAnomaly[];
  onClear?: () => void;
}

const SEVERITY_COLORS: Record<AnomalySeverity, { bg: string; text: string; border: string }> = {
  CRITICAL: {
    bg: 'bg-rose-500/10',
    text: 'text-rose-400',
    border: 'border-rose-500/30',
  },
  WARNING: {
    bg: 'bg-amber-500/10',
    text: 'text-amber-400',
    border: 'border-amber-500/30',
  },
  INFO: {
    bg: 'bg-sky-500/10',
    text: 'text-sky-400',
    border: 'border-sky-500/30',
  },
};

const TYPE_LABELS: Record<string, { label: string; icon: string; badge: string }> = {
  PRICE_SHOCK: { label: 'Price Shock', icon: '⚡', badge: 'bg-amber-500/20 text-amber-300' },
  VOLUME_SURGE: { label: 'Volume Surge', icon: '🌊', badge: 'bg-purple-500/20 text-purple-300' },
  SPREAD_BLOWOUT: { label: 'Spread Blowout', icon: '↔️', badge: 'bg-cyan-500/20 text-cyan-300' },
  BOOK_IMBALANCE: { label: 'Book Imbalance', icon: '⚖️', badge: 'bg-pink-500/20 text-pink-300' },
};

function formatTime(ts_ns: number): string {
  if (!ts_ns) return '--:--:--';
  const d = new Date(Math.floor(ts_ns / 1_000_000));
  return d.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) +
    '.' +
    String(d.getMilliseconds()).padStart(3, '0');
}

export const AnomalyFeed: React.FC<AnomalyFeedProps> = ({ anomalies, onClear }) => {
  const [filter, setFilter] = useState<'ALL' | AnomalySeverity>('ALL');

  const filtered = filter === 'ALL'
    ? anomalies
    : anomalies.filter((a) => a.severity === filter);

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-lg overflow-hidden shadow-xl">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-slate-950/60 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <div className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-rose-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-rose-500"></span>
          </div>
          <h2 className="text-xs font-semibold tracking-wider text-slate-200 uppercase">
            Microstructure Anomaly Feed
          </h2>
          <span className="px-1.5 py-0.5 text-[10px] font-mono bg-slate-800 text-slate-300 rounded">
            {anomalies.length}
          </span>
        </div>

        {/* Filter Pills */}
        <div className="flex items-center gap-1">
          {(['ALL', 'CRITICAL', 'WARNING', 'INFO'] as const).map((lvl) => (
            <button
              key={lvl}
              onClick={() => setFilter(lvl)}
              className={`px-2 py-0.5 text-[10px] font-medium rounded transition-colors ${
                filter === lvl
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'bg-slate-800/60 text-slate-400 hover:text-slate-200'
              }`}
            >
              {lvl}
            </button>
          ))}
          {onClear && anomalies.length > 0 && (
            <button
              onClick={onClear}
              className="ml-2 text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
              title="Clear alerts"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Stream List */}
      <div className="flex-1 overflow-y-auto p-3 space-y-2 max-h-[360px] scrollbar-thin scrollbar-thumb-slate-800">
        {filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-slate-500">
            <span className="text-2xl mb-1">🛡️</span>
            <p className="text-xs">No active anomalies detected</p>
            <p className="text-[10px] text-slate-600 mt-0.5">
              Liquidity, spread, and price returns are within statistical bands
            </p>
          </div>
        ) : (
          filtered.slice(0, 50).map((a, idx) => {
            const anomType = a.type || a.anomaly_type || 'PRICE_SHOCK';
            const meta = TYPE_LABELS[anomType] || {
              label: anomType,
              icon: '⚠️',
              badge: 'bg-slate-700 text-slate-200',
            };
            const sev = SEVERITY_COLORS[a.severity] || SEVERITY_COLORS.INFO;

            return (
              <div
                key={`${a.seq}-${idx}`}
                className={`p-2.5 rounded border transition-all animate-fadeIn ${sev.bg} ${sev.border} hover:border-slate-700`}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs">{meta.icon}</span>
                    <span className={`px-1.5 py-0.2 rounded text-[10px] font-semibold tracking-wide ${meta.badge}`}>
                      {meta.label}
                    </span>
                    <span
                      className={`px-1.5 py-0.2 rounded text-[9px] font-bold tracking-wider ${sev.text} ${sev.bg}`}
                    >
                      {a.severity}
                    </span>
                  </div>
                  <span className="text-[10px] font-mono text-slate-400">
                    {formatTime(a.ts_ns)}
                  </span>
                </div>

                <p className="text-xs text-slate-200 font-medium leading-relaxed">
                  {a.message}
                </p>

                <div className="mt-1.5 flex items-center justify-between text-[10px] font-mono text-slate-400">
                  <span>Metric: {a.metric_value}</span>
                  <span>Threshold: {a.threshold}</span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
