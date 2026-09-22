import React from 'react';
import { TrendingUp, TrendingDown, CheckCircle2 } from 'lucide-react';
import type { SymbolInfo } from '../types/protocol';

export interface WatchlistPriceItem {
  price: number;
  change: number;
  changePercent: number;
  volume?: number;
}

interface WatchlistProps {
  symbols: SymbolInfo[];
  selectedSymbol: string;
  onSelectSymbol: (symbol: string) => void;
  prices?: Record<string, WatchlistPriceItem>;
}

export const Watchlist: React.FC<WatchlistProps> = ({
  symbols,
  selectedSymbol,
  onSelectSymbol,
  prices = {},
}) => {
  return (
    <div className="flex items-center gap-2 overflow-x-auto py-1 px-1 bg-slate-900/60 backdrop-blur-md border border-slate-800/80 rounded-lg select-none scrollbar-thin scrollbar-thumb-slate-800">
      <div className="flex items-center gap-1.5 px-2.5 text-[11px] font-mono font-semibold uppercase tracking-wider text-slate-400 shrink-0">
        <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
        Watchlist
      </div>

      <div className="h-4 w-px bg-slate-800 shrink-0" />

      <div className="flex items-center gap-2 min-w-0 flex-1">
        {symbols.map((sym) => {
          const isSelected = sym.symbol === selectedSymbol;
          const liveData = prices[sym.symbol];
          const price = liveData?.price ?? sym.last_price;
          const change = liveData?.change ?? 0;
          const changePct = liveData?.changePercent ?? 0;
          const isUp = change >= 0;

          return (
            <button
              key={sym.symbol}
              onClick={() => onSelectSymbol(sym.symbol)}
              className={`flex items-center gap-2.5 px-3 py-1.5 rounded-md text-xs transition-all duration-150 shrink-0 border ${
                isSelected
                  ? 'bg-sky-500/15 border-sky-500/50 text-white shadow-lg shadow-sky-500/10'
                  : 'bg-slate-950/40 border-slate-800/60 text-slate-300 hover:bg-slate-800/60 hover:border-slate-700/80'
              }`}
            >
              <div className="flex items-center gap-1.5">
                <span className="font-bold tracking-wide font-mono text-sm">{sym.symbol}</span>
                {isSelected && (
                  <CheckCircle2 className="w-3.5 h-3.5 text-sky-400 inline" />
                )}
              </div>

              <div className="flex items-baseline gap-2 font-mono">
                <span className="font-semibold text-slate-100">
                  ${price.toFixed(2)}
                </span>
                <span
                  className={`text-[10px] font-semibold flex items-center gap-0.5 px-1.5 py-0.5 rounded ${
                    isUp
                      ? 'bg-emerald-500/15 text-emerald-400'
                      : 'bg-rose-500/15 text-rose-400'
                  }`}
                >
                  {isUp ? (
                    <TrendingUp className="w-2.5 h-2.5" />
                  ) : (
                    <TrendingDown className="w-2.5 h-2.5" />
                  )}
                  {isUp ? '+' : ''}
                  {changePct.toFixed(2)}%
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
};
