import React from 'react';
import { BarChart3, DollarSign, TrendingDown, TrendingUp } from 'lucide-react';
import type { MarketStats } from '../types/protocol';

interface MarketStatsProps {
  stats: MarketStats;
}

export const MarketStatsCards: React.FC<MarketStatsProps> = ({ stats }) => {
  const cards = [
    {
      title: 'Session High',
      value: `$${stats.high.toFixed(2)}`,
      icon: TrendingUp,
      color: 'text-emerald-400',
      bgColor: 'bg-emerald-500/10',
      borderColor: 'border-emerald-500/20',
    },
    {
      title: 'Session Low',
      value: `$${stats.low.toFixed(2)}`,
      icon: TrendingDown,
      color: 'text-rose-400',
      bgColor: 'bg-rose-500/10',
      borderColor: 'border-rose-500/20',
    },
    {
      title: 'Total Volume',
      value: stats.volume.toLocaleString(),
      icon: BarChart3,
      color: 'text-sky-400',
      bgColor: 'bg-sky-500/10',
      borderColor: 'border-sky-500/20',
    },
    {
      title: 'Total Fills',
      value: stats.tradesCount.toLocaleString(),
      icon: DollarSign,
      color: 'text-amber-400',
      bgColor: 'bg-amber-500/10',
      borderColor: 'border-amber-500/20',
    },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <div
            key={card.title}
            className={`flex items-center space-x-3 p-3 rounded-xl border bg-slate-900/60 backdrop-blur-md ${card.borderColor}`}
          >
            <div className={`p-2 rounded-lg ${card.bgColor}`}>
              <Icon className={`w-4 h-4 ${card.color}`} />
            </div>
            <div>
              <div className="text-[11px] font-medium text-slate-400 uppercase tracking-wider">
                {card.title}
              </div>
              <div className="text-base font-bold font-tabular text-white tracking-tight">
                {card.value}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
};
