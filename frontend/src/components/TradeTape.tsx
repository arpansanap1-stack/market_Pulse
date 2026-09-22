import React from 'react';
import { ArrowDownRight, ArrowUpRight, Clock } from 'lucide-react';
import type { Trade } from '../types/protocol';

interface TradeTapeProps {
  trades: Trade[];
}

const getParticipantBadge = (pid?: string): { label: string; className: string } | null => {
  if (!pid) return null;
  if (pid === 'user_trader' || pid.startsWith('usr_') || pid.startsWith('desk_')) {
    return { label: 'YOU', className: 'bg-amber-500/20 text-amber-300 border-amber-500/40 font-bold' };
  }
  if (pid.startsWith('mm_')) {
    return { label: 'MM', className: 'bg-blue-500/20 text-blue-300 border-blue-500/30' };
  }
  if (pid.startsWith('noise_')) {
    return { label: 'NOISE', className: 'bg-purple-500/20 text-purple-300 border-purple-500/30' };
  }
  if (pid.startsWith('trend_')) {
    return { label: 'MOMENTUM', className: 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30' };
  }
  return { label: pid.slice(0, 6).toUpperCase(), className: 'bg-slate-800 text-slate-300 border-slate-700' };
};

export const TradeTape: React.FC<TradeTapeProps> = ({ trades }) => {
  return (
    <div className="flex flex-col h-full bg-slate-950/60 rounded-xl border border-slate-800/80 overflow-hidden shadow-inner">
      {/* Tape Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800 bg-slate-900/60 text-xs font-semibold text-slate-300">
        <div className="flex items-center space-x-2">
          <Clock className="w-3.5 h-3.5 text-sky-400" />
          <span className="tracking-wide uppercase text-slate-400">Trade Tape</span>
        </div>
        <span className="font-mono text-[11px] text-slate-500">Last {trades.length} fills</span>
      </div>

      {/* Column Headers */}
      <div className="grid grid-cols-5 px-3 py-1.5 border-b border-slate-800/50 text-[10px] font-mono text-slate-500 bg-slate-950/40 select-none">
        <div>TIME</div>
        <div className="text-right">PRICE</div>
        <div className="text-right">SIZE</div>
        <div className="text-center">PARTICIPANTS</div>
        <div className="text-right">SIDE</div>
      </div>

      {/* Trades Scrollable Body */}
      <div className="flex-1 overflow-y-auto divide-y divide-slate-900/60">
        {trades.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-slate-500 text-xs font-mono">
            <span>Awaiting trade stream...</span>
          </div>
        ) : (
          trades.map((trade) => {
            const isBuy = trade.aggressor_side === 'BUY';
            const date = new Date(Math.floor(trade.ts_ns / 1_000_000));
            const timeStr =
              date.toTimeString().split(' ')[0] +
              '.' +
              String(Math.floor((trade.ts_ns / 1_000_000) % 1000)).padStart(3, '0');

            const buyerBadge = getParticipantBadge(trade.buyer_participant_id);
            const sellerBadge = getParticipantBadge(trade.seller_participant_id);

            return (
              <div
                key={`${trade.trade_id}-${trade.seq}`}
                className={`grid grid-cols-5 px-3 py-1.5 text-xs font-mono items-center transition-colors hover:bg-slate-900/50 ${
                  isBuy ? 'hover:bg-emerald-950/20' : 'hover:bg-rose-950/20'
                }`}
              >
                <span className="text-slate-400 text-[10px]">{timeStr}</span>
                <span
                  className={`text-right font-bold font-tabular ${
                    isBuy ? 'text-emerald-400' : 'text-rose-400'
                  }`}
                >
                  ${trade.price.toFixed(2)}
                </span>
                <span className="text-right font-tabular text-slate-300">
                  {trade.qty.toLocaleString()}
                </span>
                <div className="flex items-center justify-center gap-1">
                  {buyerBadge ? (
                    <span
                      title={`Buyer: ${trade.buyer_participant_id || 'Anonymous'}`}
                      className={`px-1 py-0.5 rounded border text-[9px] leading-none ${buyerBadge.className}`}
                    >
                      {buyerBadge.label}
                    </span>
                  ) : (
                    <span className="text-slate-600 text-[9px]">-</span>
                  )}
                  <span className="text-slate-600 text-[8px]">&bull;</span>
                  {sellerBadge ? (
                    <span
                      title={`Seller: ${trade.seller_participant_id || 'Anonymous'}`}
                      className={`px-1 py-0.5 rounded border text-[9px] leading-none ${sellerBadge.className}`}
                    >
                      {sellerBadge.label}
                    </span>
                  ) : (
                    <span className="text-slate-600 text-[9px]">-</span>
                  )}
                </div>
                <span
                  className={`text-right font-semibold flex items-center justify-end gap-0.5 ${
                    isBuy ? 'text-emerald-400' : 'text-rose-400'
                  }`}
                >
                  {isBuy ? (
                    <>
                      <span>BUY</span>
                      <ArrowUpRight className="w-3 h-3 text-emerald-400" />
                    </>
                  ) : (
                    <>
                      <span>SELL</span>
                      <ArrowDownRight className="w-3 h-3 text-rose-400" />
                    </>
                  )}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
