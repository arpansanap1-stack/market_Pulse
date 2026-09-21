import React, { useState } from 'react';
import type { MarketStatus } from '../types/protocol';

interface ScenarioControlsProps {
  marketStatus?: MarketStatus | null;
  onInject: (scenarioId: string, params?: Record<string, unknown>) => Promise<void>;
}

interface ScenarioButton {
  id: string;
  name: string;
  badge: string;
  color: string;
  icon: string;
  params?: Record<string, unknown>;
  description: string;
}

const PRESET_SCENARIOS: ScenarioButton[] = [
  {
    id: 'earnings_shock_positive',
    name: 'Earnings Beat (+5%)',
    badge: 'Valuation',
    color: 'bg-emerald-600 hover:bg-emerald-500 text-white',
    icon: '🚀',
    params: { jump_pct: 0.05, volatility_mult: 2.5 },
    description: 'Sudden +5% valuation jump, volume spike & wider spreads',
  },
  {
    id: 'earnings_shock_negative',
    name: 'Earnings Miss (-5%)',
    badge: 'Valuation',
    color: 'bg-rose-600 hover:bg-rose-500 text-white',
    icon: '📉',
    params: { jump_pct: -0.05, volatility_mult: 2.5 },
    description: 'Sudden -5% valuation drop, aggressive sell pressure',
  },
  {
    id: 'flash_crash',
    name: 'Flash Crash (-10%)',
    badge: 'Crisis',
    color: 'bg-amber-600 hover:bg-amber-500 text-white',
    icon: '⚡',
    params: { crash_pct: -0.10, halt_duration_s: 5.0 },
    description: 'Cascade of market sells triggers -10% drop and LULD circuit breaker halt',
  },
  {
    id: 'high_volatility_regime',
    name: 'High Volatility (3x)',
    badge: 'Regime',
    color: 'bg-purple-600 hover:bg-purple-500 text-white',
    icon: '🌪️',
    params: { regime: 'HIGH', multiplier: 3.0 },
    description: 'Macro uncertainty triples price jitter and quoting spreads',
  },
  {
    id: 'normal_volatility_regime',
    name: 'Normal Volatility',
    badge: 'Regime',
    color: 'bg-slate-700 hover:bg-slate-600 text-slate-100',
    icon: '⚖️',
    params: { regime: 'NORMAL', multiplier: 1.0 },
    description: 'Return to standard baseline volatility and tight spreads',
  },
];

export const ScenarioControls: React.FC<ScenarioControlsProps> = ({
  marketStatus,
  onInject,
}) => {
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [lastAction, setLastAction] = useState<string | null>(null);

  const isHalted = marketStatus?.is_halted ?? false;

  const handleTrigger = async (id: string, name: string, params?: Record<string, unknown>) => {
    try {
      setLoadingId(id);
      await onInject(id, params);
      setLastAction(`Injected: ${name}`);
      setTimeout(() => setLastAction(null), 3500);
    } catch (err) {
      setLastAction(`Failed to inject ${name}`);
    } finally {
      setLoadingId(null);
    }
  };

  return (
    <div className="flex flex-col bg-slate-900 border border-slate-800 rounded-lg p-3.5 shadow-xl">
      {/* Header with Circuit Breaker Status */}
      <div className="flex items-center justify-between pb-3 mb-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          <span className="text-base">🧪</span>
          <div>
            <h3 className="text-xs font-semibold tracking-wider text-slate-200 uppercase">
              Exogenous Market Scenarios
            </h3>
            <p className="text-[10px] text-slate-400">
              Stress-test the limit order book with macroeconomic shocks & regulatory halts
            </p>
          </div>
        </div>

        {/* Circuit Breaker Status Badge */}
        <div className="flex items-center gap-2">
          <div
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold tracking-wider border ${
              isHalted
                ? 'bg-rose-500/20 text-rose-300 border-rose-500/40 animate-pulse'
                : 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30'
            }`}
          >
            <span className={`h-2 w-2 rounded-full ${isHalted ? 'bg-rose-500' : 'bg-emerald-400'}`} />
            {isHalted ? 'HALTED (CIRCUIT BREAKER)' : 'MARKET ACTIVE'}
          </div>
        </div>
      </div>

      {/* Preset Action Grid */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
        {PRESET_SCENARIOS.map((scenario) => {
          const isLoading = loadingId === scenario.id;
          return (
            <button
              key={scenario.id}
              onClick={() => handleTrigger(scenario.id, scenario.name, scenario.params)}
              disabled={isLoading}
              title={scenario.description}
              className={`flex flex-col text-left p-2.5 rounded border border-transparent transition-all shadow-sm ${scenario.color} disabled:opacity-50`}
            >
              <div className="flex items-center justify-between w-full mb-1">
                <span className="text-sm">{scenario.icon}</span>
                <span className="text-[9px] uppercase font-bold tracking-wider opacity-80">
                  {scenario.badge}
                </span>
              </div>
              <span className="text-xs font-semibold leading-tight">{scenario.name}</span>
              <span className="text-[9px] opacity-75 mt-0.5 line-clamp-1">
                {isLoading ? 'Injecting...' : scenario.description}
              </span>
            </button>
          );
        })}
      </div>

      {/* Manual Circuit Breaker Controls */}
      <div className="flex items-center justify-between mt-3 pt-2.5 border-t border-slate-800/80">
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-slate-400 font-medium">Circuit Breaker Control:</span>
          {isHalted ? (
            <button
              onClick={() => handleTrigger('resume_trading', 'Resume Trading')}
              disabled={loadingId === 'resume_trading'}
              className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs font-medium transition-colors shadow-sm"
            >
              ▶️ Resume Trading
            </button>
          ) : (
            <button
              onClick={() => handleTrigger('halt_trading', 'Regulatory Halt', { reason: 'MANUAL_LULD' })}
              disabled={loadingId === 'halt_trading'}
              className="px-3 py-1 bg-rose-700 hover:bg-rose-600 text-white rounded text-xs font-medium transition-colors shadow-sm"
            >
              🛑 Halt Trading (LULD)
            </button>
          )}
        </div>

        {lastAction && (
          <span className="text-[11px] font-mono text-indigo-300 animate-pulse">
            {lastAction}
          </span>
        )}
      </div>
    </div>
  );
};
