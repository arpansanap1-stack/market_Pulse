import React, { useEffect, useMemo, useState } from 'react';
import { Layers, ArrowDown, ArrowUp } from 'lucide-react';
import type { BookDeltaItem, BookLevel, BookSnapshot } from '../types/protocol';

interface DepthLadderProps {
  symbol: string;
  deltas: BookDeltaItem[];
  levels?: number;
}

interface ProcessedLevel extends BookLevel {
  cumulativeQty: number;
  depthPct: number;
}

export const DepthLadder: React.FC<DepthLadderProps> = ({ symbol, deltas, levels = 10 }) => {
  // Bids map: price_ticks -> BookLevel
  const [bidsMap, setBidsMap] = useState<Map<number, BookLevel>>(new Map());
  // Asks map: price_ticks -> BookLevel
  const [asksMap, setAsksMap] = useState<Map<number, BookLevel>>(new Map());
  // Set of recently updated price_ticks for subtle flash animation
  const [flashTicks, setFlashTicks] = useState<Set<number>>(new Set());

  // 1. Initial snapshot fetch
  useEffect(() => {
    let isMounted = true;
    const fetchSnapshot = async () => {
      try {
        const res = await fetch(`http://localhost:8000/api/v1/book?symbol=${symbol}&levels=${levels}`);
        if (!res.ok) return;
        const data: BookSnapshot = await res.json();
        if (!isMounted) return;

        const newBids = new Map<number, BookLevel>();
        for (const b of data.bids) {
          newBids.set(b.price_ticks, b);
        }

        const newAsks = new Map<number, BookLevel>();
        for (const a of data.asks) {
          newAsks.set(a.price_ticks, a);
        }

        setBidsMap(newBids);
        setAsksMap(newAsks);
      } catch (err) {
        console.error('Failed to fetch initial book snapshot:', err);
      }
    };

    fetchSnapshot();
    return () => {
      isMounted = false;
    };
  }, [symbol, levels]);

  // 2. Process incoming live WebSocket deltas
  useEffect(() => {
    if (!deltas || deltas.length === 0) return;

    const updatedTicks = new Set<number>();

    setBidsMap((prevBids) => {
      let modified = false;
      const nextBids = new Map(prevBids);

      for (const d of deltas) {
        if (d.side === 'BUY') {
          updatedTicks.add(d.price_ticks);
          if (d.qty === 0) {
            if (nextBids.has(d.price_ticks)) {
              nextBids.delete(d.price_ticks);
              modified = true;
            }
          } else {
            nextBids.set(d.price_ticks, {
              price: d.price,
              price_ticks: d.price_ticks,
              qty: d.qty,
            });
            modified = true;
          }
        }
      }
      return modified ? nextBids : prevBids;
    });

    setAsksMap((prevAsks) => {
      let modified = false;
      const nextAsks = new Map(prevAsks);

      for (const d of deltas) {
        if (d.side === 'SELL') {
          updatedTicks.add(d.price_ticks);
          if (d.qty === 0) {
            if (nextAsks.has(d.price_ticks)) {
              nextAsks.delete(d.price_ticks);
              modified = true;
            }
          } else {
            nextAsks.set(d.price_ticks, {
              price: d.price,
              price_ticks: d.price_ticks,
              qty: d.qty,
            });
            modified = true;
          }
        }
      }
      return modified ? nextAsks : prevAsks;
    });

    if (updatedTicks.size > 0) {
      setFlashTicks(updatedTicks);
      const timer = setTimeout(() => {
        setFlashTicks(new Set());
      }, 350);
      return () => clearTimeout(timer);
    }
  }, [deltas]);

  // 3. Compute top N levels and cumulative depth
  const { processedAsks, processedBids, bestAsk, bestBid, spread, spreadBps } = useMemo(() => {
    // Sort asks ascending by price (lowest ask is best ask)
    const sortedAsks = Array.from(asksMap.values())
      .sort((a, b) => a.price_ticks - b.price_ticks)
      .slice(0, levels);

    // Sort bids descending by price (highest bid is best bid)
    const sortedBids = Array.from(bidsMap.values())
      .sort((a, b) => b.price_ticks - a.price_ticks)
      .slice(0, levels);

    const bAsk = sortedAsks.length > 0 ? sortedAsks[0] : null;
    const bBid = sortedBids.length > 0 ? sortedBids[0] : null;

    const sp = bAsk && bBid ? bAsk.price - bBid.price : null;
    const spBps = sp !== null && bBid && bBid.price > 0 ? (sp / bBid.price) * 10000 : null;

    // Calculate cumulative depth for asks
    let askCum = 0;
    const asksWithCum = sortedAsks.map((a) => {
      askCum += a.qty;
      return { ...a, cumulativeQty: askCum };
    });

    // Calculate cumulative depth for bids
    let bidCum = 0;
    const bidsWithCum = sortedBids.map((b) => {
      bidCum += b.qty;
      return { ...b, cumulativeQty: bidCum };
    });

    const maxCum = Math.max(askCum, bidCum, 1);

    // Add depth percentage (0 - 100)
    const processedBidsList: ProcessedLevel[] = bidsWithCum.map((b) => ({
      ...b,
      depthPct: Math.min(100, Math.round((b.cumulativeQty / maxCum) * 100)),
    }));

    // For display, asks are usually displayed with the lowest ask (best ask) at the bottom,
    // so we reverse the ascending list so higher asks are on top
    const processedAsksList: ProcessedLevel[] = [...asksWithCum]
      .reverse()
      .map((a) => ({
        ...a,
        depthPct: Math.min(100, Math.round((a.cumulativeQty / maxCum) * 100)),
      }));

    return {
      processedAsks: processedAsksList,
      processedBids: processedBidsList,
      bestAsk: bAsk,
      bestBid: bBid,
      spread: sp,
      spreadBps: spBps,
    };
  }, [asksMap, bidsMap, levels]);

  return (
    <div className="flex flex-col h-full bg-slate-950/60 rounded-xl border border-slate-800/80 overflow-hidden shadow-inner font-mono text-xs">
      {/* Ladder Header */}
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-800 bg-slate-900/60 text-xs font-semibold text-slate-300">
        <div className="flex items-center space-x-2">
          <Layers className="w-3.5 h-3.5 text-indigo-400" />
          <span className="tracking-wide uppercase text-slate-400">Order Book</span>
          <span className="text-[10px] bg-slate-800 text-slate-400 px-1.5 py-0.5 rounded font-mono">
            L2 Depth
          </span>
        </div>
        <div className="text-[11px] font-mono text-slate-400 flex items-center gap-1.5">
          <span>Spread:</span>
          {spread !== null ? (
            <span className="font-bold text-amber-400">
              ${spread.toFixed(2)} ({spreadBps?.toFixed(1)} bps)
            </span>
          ) : (
            <span className="text-slate-500">—</span>
          )}
        </div>
      </div>

      {/* Column Headers */}
      <div className="grid grid-cols-3 px-3 py-1.5 border-b border-slate-800/50 text-[11px] font-mono text-slate-500 bg-slate-950/40 select-none">
        <div>PRICE ($)</div>
        <div className="text-right">SIZE</div>
        <div className="text-right">TOTAL</div>
      </div>

      {/* Asks (Sell Orders - Red) */}
      <div className="flex-1 flex flex-col justify-end overflow-hidden divide-y divide-slate-900/40">
        {processedAsks.length === 0 ? (
          <div className="py-4 text-center text-slate-600 text-[11px]">No asks</div>
        ) : (
          processedAsks.map((ask) => {
            const isFlashing = flashTicks.has(ask.price_ticks);
            return (
              <div
                key={`ask-${ask.price_ticks}`}
                className={`relative grid grid-cols-3 px-3 py-1 text-[11px] items-center transition-colors ${
                  isFlashing ? 'bg-rose-900/40' : 'hover:bg-slate-900/40'
                }`}
              >
                {/* Visual Depth Bar overlay from right */}
                <div
                  className="absolute top-0 right-0 bottom-0 bg-rose-500/15 pointer-events-none transition-all duration-150"
                  style={{ width: `${ask.depthPct}%` }}
                />
                <span className="relative font-bold text-rose-400">
                  ${ask.price.toFixed(2)}
                </span>
                <span className="relative text-right text-slate-300">
                  {ask.qty.toLocaleString()}
                </span>
                <span className="relative text-right text-slate-400">
                  {ask.cumulativeQty.toLocaleString()}
                </span>
              </div>
            );
          })
        )}
      </div>

      {/* Spread / Mid Row Divider */}
      <div className="px-3 py-1.5 bg-slate-900/90 border-y border-slate-800/80 flex items-center justify-between text-[11px] font-bold">
        <div className="flex items-center gap-2">
          <span className="text-slate-400">MID:</span>
          <span className="text-slate-100">
            {bestBid && bestAsk
              ? `$${((bestBid.price + bestAsk.price) / 2).toFixed(2)}`
              : '—'}
          </span>
        </div>
        <div className="flex items-center gap-3 text-slate-400">
          <div className="flex items-center gap-1 text-emerald-400">
            <ArrowUp className="w-3 h-3" />
            <span>${bestBid ? bestBid.price.toFixed(2) : '—'}</span>
          </div>
          <div className="flex items-center gap-1 text-rose-400">
            <ArrowDown className="w-3 h-3" />
            <span>${bestAsk ? bestAsk.price.toFixed(2) : '—'}</span>
          </div>
        </div>
      </div>

      {/* Bids (Buy Orders - Green) */}
      <div className="flex-1 flex flex-col justify-start overflow-hidden divide-y divide-slate-900/40">
        {processedBids.length === 0 ? (
          <div className="py-4 text-center text-slate-600 text-[11px]">No bids</div>
        ) : (
          processedBids.map((bid) => {
            const isFlashing = flashTicks.has(bid.price_ticks);
            return (
              <div
                key={`bid-${bid.price_ticks}`}
                className={`relative grid grid-cols-3 px-3 py-1 text-[11px] items-center transition-colors ${
                  isFlashing ? 'bg-emerald-900/40' : 'hover:bg-slate-900/40'
                }`}
              >
                {/* Visual Depth Bar overlay from right */}
                <div
                  className="absolute top-0 right-0 bottom-0 bg-emerald-500/15 pointer-events-none transition-all duration-150"
                  style={{ width: `${bid.depthPct}%` }}
                />
                <span className="relative font-bold text-emerald-400">
                  ${bid.price.toFixed(2)}
                </span>
                <span className="relative text-right text-slate-300">
                  {bid.qty.toLocaleString()}
                </span>
                <span className="relative text-right text-slate-400">
                  {bid.cumulativeQty.toLocaleString()}
                </span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};
