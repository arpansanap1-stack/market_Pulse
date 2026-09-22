import React, { useState } from 'react';
import { Send, AlertCircle, CheckCircle2, RefreshCw } from 'lucide-react';
import type { Side, STPPolicy } from '../types/protocol';
import type { OrderRecord, OrderType, TimeInForce, OrderSubmitPayload } from '../types/portfolio';

interface OrderTicketProps {
  symbol: string;
  bestBid?: number | null;
  bestAsk?: number | null;
  lastPrice?: number | null;
  availableCash: number;
  onOrderSubmitted?: (order: OrderRecord) => void;
}

export const OrderTicket: React.FC<OrderTicketProps> = ({
  symbol,
  bestBid,
  bestAsk,
  lastPrice,
  availableCash,
  onOrderSubmitted,
}) => {
  const [side, setSide] = useState<Side>('BUY');
  const [orderType, setOrderType] = useState<OrderType>('LIMIT');
  const [priceStr, setPriceStr] = useState<string>(
    lastPrice ? lastPrice.toFixed(2) : '150.00'
  );
  const [qtyStr, setQtyStr] = useState<string>('10');
  const [tif, setTif] = useState<TimeInForce>('GTC');
  const [stp, setStp] = useState<STPPolicy>('CANCEL_NEWEST');
  const [participantId] = useState<string>('user_trader');
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [feedback, setFeedback] = useState<{
    type: 'success' | 'error';
    message: string;
  } | null>(null);

  // Update default price if user hasn't typed anything and lastPrice arrives
  const parsedPrice = parseFloat(priceStr) || 0;
  const parsedQty = parseInt(qtyStr, 10) || 0;

  // Reference price for cost estimation
  const effectivePrice =
    orderType === 'LIMIT'
      ? parsedPrice
      : (side === 'BUY' ? bestAsk || lastPrice || 0 : bestBid || lastPrice || 0);

  const estimatedTotal = parsedQty * effectivePrice;
  const hasInsufficientFunds =
    side === 'BUY' && estimatedTotal > availableCash && availableCash > 0;

  const handlePriceQuickFill = (targetPrice: number | null | undefined) => {
    if (targetPrice && targetPrice > 0) {
      setPriceStr(targetPrice.toFixed(2));
    }
  };

  const handleQtyPreset = (amount: number) => {
    setQtyStr((prev) => {
      const curr = parseInt(prev, 10) || 0;
      return String(Math.max(1, curr + amount));
    });
  };

  const handleMaxQty = () => {
    if (side === 'BUY') {
      const price = effectivePrice > 0 ? effectivePrice : (lastPrice || 1);
      const maxShares = Math.floor(availableCash / price);
      setQtyStr(String(Math.max(1, maxShares)));
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFeedback(null);

    if (parsedQty <= 0) {
      setFeedback({ type: 'error', message: 'Quantity must be greater than 0' });
      return;
    }

    if (orderType === 'LIMIT' && parsedPrice <= 0) {
      setFeedback({ type: 'error', message: 'Limit price must be greater than 0' });
      return;
    }

    if (hasInsufficientFunds) {
      setFeedback({
        type: 'error',
        message: `Insufficient funds: requires $${estimatedTotal.toFixed(2)}, available $${availableCash.toFixed(2)}`,
      });
      return;
    }

    setSubmitting(true);
    try {
      const payload: OrderSubmitPayload = {
        symbol,
        side,
        order_type: orderType,
        price: orderType === 'LIMIT' ? parsedPrice : null,
        qty: parsedQty,
        tif,
        participant_id: participantId,
        stp,
      };

      const res = await fetch('http://localhost:8000/api/v1/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errorData = await res.json().catch(() => ({ detail: 'Failed to submit order' }));
        throw new Error(errorData.detail || `Server error (${res.status})`);
      }

      const orderResult: OrderRecord = await res.json();
      if (orderResult.status === 'CANCELED' && orderResult.reject_reason?.startsWith('STP_')) {
        setFeedback({
          type: 'error',
          message: `Self-Trade Prevented: ${orderResult.reject_reason}`,
        });
      } else {
        setFeedback({
          type: 'success',
          message: `${side} ${parsedQty} ${symbol} submitted [${orderResult.status}]`,
        });
      }

      if (onOrderSubmitted) {
        onOrderSubmitted(orderResult);
      }

      // Auto-hide success message after 4s
      setTimeout(() => {
        setFeedback((prev) => (prev?.type === 'success' ? null : prev));
      }, 4000);
    } catch (err) {
      setFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'Order submission failed',
      });
    } finally {
      setSubmitting(false);
    }
  };

  const midPrice =
    bestBid && bestAsk ? Number(((bestBid + bestAsk) / 2).toFixed(2)) : null;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 flex flex-col gap-3 shadow-xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-2.5">
        <div className="flex items-center gap-2">
          <div className="p-1.5 rounded-md bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
            <Send size={15} />
          </div>
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-200">
              Order Ticket
            </h3>
            <span className="text-[10px] text-slate-400 font-mono">
              Direct Matching Engine OMS
            </span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase tracking-wider text-slate-400 font-mono">
            Avail Cash
          </div>
          <div className="text-xs font-mono font-semibold text-emerald-400">
            ${availableCash.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </div>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        {/* Buy / Sell Tabs */}
        <div className="grid grid-cols-2 gap-1.5 p-1 bg-slate-950 rounded-lg border border-slate-800/80">
          <button
            type="button"
            onClick={() => setSide('BUY')}
            className={`py-1.5 text-xs font-semibold rounded-md transition-all ${
              side === 'BUY'
                ? 'bg-emerald-600 text-white shadow-md shadow-emerald-950'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            BUY
          </button>
          <button
            type="button"
            onClick={() => setSide('SELL')}
            className={`py-1.5 text-xs font-semibold rounded-md transition-all ${
              side === 'SELL'
                ? 'bg-rose-600 text-white shadow-md shadow-rose-950'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-900'
            }`}
          >
            SELL
          </button>
        </div>

        {/* Order Type: LIMIT vs MARKET */}
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-mono text-slate-400 uppercase">Type</span>
          <div className="flex bg-slate-950 rounded border border-slate-800 p-0.5 text-[11px] font-mono">
            <button
              type="button"
              onClick={() => setOrderType('LIMIT')}
              className={`px-3 py-1 rounded transition-colors ${
                orderType === 'LIMIT'
                  ? 'bg-slate-800 text-slate-100 font-semibold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              LIMIT
            </button>
            <button
              type="button"
              onClick={() => setOrderType('MARKET')}
              className={`px-3 py-1 rounded transition-colors ${
                orderType === 'MARKET'
                  ? 'bg-slate-800 text-slate-100 font-semibold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              MARKET
            </button>
          </div>
        </div>

        {/* Limit Price Input & Quick-fill pills */}
        {orderType === 'LIMIT' ? (
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-[11px] font-mono">
              <span className="text-slate-400">Limit Price ($)</span>
              <div className="flex items-center gap-1">
                {bestBid && (
                  <button
                    type="button"
                    onClick={() => handlePriceQuickFill(bestBid)}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-emerald-400 border border-slate-700"
                    title={`Best Bid: $${bestBid.toFixed(2)}`}
                  >
                    Bid {bestBid.toFixed(2)}
                  </button>
                )}
                {midPrice && (
                  <button
                    type="button"
                    onClick={() => handlePriceQuickFill(midPrice)}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-cyan-400 border border-slate-700"
                    title={`Mid Price: $${midPrice.toFixed(2)}`}
                  >
                    Mid
                  </button>
                )}
                {bestAsk && (
                  <button
                    type="button"
                    onClick={() => handlePriceQuickFill(bestAsk)}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-rose-400 border border-slate-700"
                    title={`Best Ask: $${bestAsk.toFixed(2)}`}
                  >
                    Ask {bestAsk.toFixed(2)}
                  </button>
                )}
              </div>
            </div>
            <div className="relative flex items-center">
              <span className="absolute left-2.5 text-slate-500 font-mono text-xs">$</span>
              <input
                type="number"
                step="0.01"
                min="0.01"
                value={priceStr}
                onChange={(e) => setPriceStr(e.target.value)}
                className="w-full pl-6 pr-3 py-1.5 bg-slate-950 border border-slate-800 rounded text-xs font-mono text-slate-100 focus:outline-none focus:border-cyan-500"
                placeholder="0.00"
                required
              />
            </div>
          </div>
        ) : (
          <div className="bg-slate-950/60 border border-slate-800/80 rounded p-2 text-xs font-mono text-slate-400 flex items-center justify-between">
            <span>Reference Price</span>
            <span className="text-slate-200 font-semibold">
              ${effectivePrice > 0 ? effectivePrice.toFixed(2) : '---'}
            </span>
          </div>
        )}

        {/* Quantity Input & Preset buttons */}
        <div className="flex flex-col gap-1">
          <div className="flex items-center justify-between text-[11px] font-mono">
            <span className="text-slate-400">Quantity (Shares)</span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={() => handleQtyPreset(1)}
                className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
              >
                +1
              </button>
              <button
                type="button"
                onClick={() => handleQtyPreset(10)}
                className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
              >
                +10
              </button>
              <button
                type="button"
                onClick={() => handleQtyPreset(50)}
                className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
              >
                +50
              </button>
              {side === 'BUY' && (
                <button
                  type="button"
                  onClick={handleMaxQty}
                  className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-900/40 hover:bg-cyan-800/50 text-cyan-300 border border-cyan-700/50 font-bold"
                >
                  MAX
                </button>
              )}
            </div>
          </div>
          <input
            type="number"
            step="1"
            min="1"
            value={qtyStr}
            onChange={(e) => setQtyStr(e.target.value)}
            className="w-full px-3 py-1.5 bg-slate-950 border border-slate-800 rounded text-xs font-mono text-slate-100 focus:outline-none focus:border-cyan-500"
            placeholder="10"
            required
          />
        </div>

        {/* Time In Force (TIF) */}
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-mono text-slate-400 uppercase">TIF</span>
          <div className="flex bg-slate-950 rounded border border-slate-800 p-0.5 text-[10px] font-mono">
            {(['GTC', 'IOC', 'FOK'] as TimeInForce[]).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTif(t)}
                className={`px-2 py-0.5 rounded transition-colors ${
                  tif === t
                    ? 'bg-slate-800 text-cyan-400 font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {/* Self-Trade Prevention (STP) Policy */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1">
            <span className="text-[11px] font-mono text-slate-400 uppercase">STP</span>
            <span
              className="text-[9px] text-slate-500 font-mono hidden sm:inline"
              title="Self-Trade Prevention policy: protects against unintended wash trading"
            >
              (Wash Guard)
            </span>
          </div>
          <div className="flex bg-slate-950 rounded border border-slate-800 p-0.5 text-[10px] font-mono">
            {(
              [
                { id: 'CANCEL_NEWEST', label: 'CN', title: 'Cancel Newest: cancels incoming order to protect resting book' },
                { id: 'CANCEL_OLDEST', label: 'CO', title: 'Cancel Oldest: cancels resting order and lets aggressor match/rest' },
                { id: 'DECREMENT_AND_CANCEL', label: 'DC', title: 'Decrement & Cancel: offsets overlapping volume' },
                { id: 'NONE', label: 'None', title: 'None: self-trades permitted (wash trading allowed)' },
              ] as const
            ).map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => setStp(opt.id)}
                title={opt.title}
                className={`px-1.5 py-0.5 rounded transition-colors ${
                  stp === opt.id
                    ? 'bg-slate-800 text-amber-400 font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Estimated Value & Summary */}
        <div className="bg-slate-950/70 border border-slate-800/80 rounded p-2 flex flex-col gap-1 text-[11px] font-mono">
          <div className="flex items-center justify-between text-slate-400">
            <span>Est. Order Value</span>
            <span className="text-slate-200 font-semibold">
              ${estimatedTotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
          </div>
          {hasInsufficientFunds && (
            <div className="flex items-center gap-1 text-rose-400 text-[10px] pt-1 border-t border-slate-800">
              <AlertCircle size={12} className="shrink-0" />
              <span>Exceeds cash balance (${availableCash.toFixed(2)})</span>
            </div>
          )}
        </div>

        {/* Feedback Alert */}
        {feedback && (
          <div
            className={`p-2 rounded text-xs flex items-center gap-1.5 font-mono ${
              feedback.type === 'success'
                ? 'bg-emerald-950/40 text-emerald-300 border border-emerald-800/60'
                : 'bg-rose-950/40 text-rose-300 border border-rose-800/60'
            }`}
          >
            {feedback.type === 'success' ? (
              <CheckCircle2 size={13} className="shrink-0 text-emerald-400" />
            ) : (
              <AlertCircle size={13} className="shrink-0 text-rose-400" />
            )}
            <span className="truncate">{feedback.message}</span>
          </div>
        )}

        {/* Submit Button */}
        <button
          type="submit"
          disabled={submitting || hasInsufficientFunds}
          className={`w-full py-2 px-3 rounded-lg text-xs font-semibold font-mono uppercase tracking-wider flex items-center justify-center gap-1.5 transition-all shadow-md active:scale-[0.99] disabled:opacity-50 disabled:cursor-not-allowed ${
            side === 'BUY'
              ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-950'
              : 'bg-rose-600 hover:bg-rose-500 text-white shadow-rose-950'
          }`}
        >
          {submitting ? (
            <>
              <RefreshCw size={13} className="animate-spin" />
              <span>Routing Order...</span>
            </>
          ) : (
            <span>
              {side} {parsedQty} {symbol} {orderType === 'LIMIT' ? `@ $${parsedPrice.toFixed(2)}` : '(MKT)'}
            </span>
          )}
        </button>
      </form>
    </div>
  );
};
