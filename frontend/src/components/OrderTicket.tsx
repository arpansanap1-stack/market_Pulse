import React, { useState } from 'react';
import { Send, AlertCircle, CheckCircle2, Sliders, ShieldCheck, Zap } from 'lucide-react';
import type { Side, STPPolicy } from '../types/protocol';
import type {
  OrderRecord,
  OrderType,
  TimeInForce,
  OrderSubmitPayload,
  OCOSubmitPayload,
} from '../types/portfolio';

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
  const [isOCO, setIsOCO] = useState<boolean>(false);

  // Inputs
  const [priceStr, setPriceStr] = useState<string>(
    lastPrice ? lastPrice.toFixed(2) : '150.00'
  );
  const [stopPriceStr, setStopPriceStr] = useState<string>(
    lastPrice ? (lastPrice * 0.97).toFixed(2) : '145.00'
  );
  const [tpPriceStr, setTpPriceStr] = useState<string>(
    lastPrice ? (lastPrice * 1.05).toFixed(2) : '160.00'
  );
  const [trailOffsetStr, setTrailOffsetStr] = useState<string>('2.00');
  const [qtyStr, setQtyStr] = useState<string>('10');
  const [tif, setTif] = useState<TimeInForce>('GTC');
  const [stp, setStp] = useState<STPPolicy>('CANCEL_NEWEST');
  const [participantId] = useState<string>('user_trader');
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [feedback, setFeedback] = useState<{
    type: 'success' | 'error';
    message: string;
  } | null>(null);

  const parsedPrice = parseFloat(priceStr) || 0;
  const parsedStopPrice = parseFloat(stopPriceStr) || 0;
  const parsedTpPrice = parseFloat(tpPriceStr) || 0;
  const parsedTrailOffset = parseFloat(trailOffsetStr) || 0;
  const parsedQty = parseInt(qtyStr, 10) || 0;

  // Reference price for cost estimation
  const effectivePrice =
    orderType === 'LIMIT' || orderType === 'STOP_LIMIT'
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

    if (!isOCO) {
      // Single order validation
      if ((orderType === 'LIMIT' || orderType === 'STOP_LIMIT') && parsedPrice <= 0) {
        setFeedback({ type: 'error', message: 'Limit price must be greater than 0' });
        return;
      }
      if (
        (orderType === 'STOP_LOSS' || orderType === 'STOP_LIMIT' || orderType === 'TAKE_PROFIT') &&
        parsedStopPrice <= 0
      ) {
        setFeedback({ type: 'error', message: 'Stop/Trigger price must be greater than 0' });
        return;
      }
      if (orderType === 'TRAILING_STOP' && parsedTrailOffset <= 0) {
        setFeedback({ type: 'error', message: 'Trailing offset must be greater than 0' });
        return;
      }
      if (hasInsufficientFunds) {
        setFeedback({
          type: 'error',
          message: `Insufficient funds: requires $${estimatedTotal.toFixed(2)}, available $${availableCash.toFixed(2)}`,
        });
        return;
      }
    } else {
      // OCO validation
      if (parsedTpPrice <= 0) {
        setFeedback({ type: 'error', message: 'Take-Profit target must be greater than 0' });
        return;
      }
      if (parsedStopPrice <= 0) {
        setFeedback({ type: 'error', message: 'Stop-Loss price must be greater than 0' });
        return;
      }
      if (side === 'SELL' && parsedStopPrice >= parsedTpPrice) {
        setFeedback({ type: 'error', message: 'For SELL OCO, Take-Profit must be above Stop-Loss' });
        return;
      }
      if (side === 'BUY' && parsedStopPrice <= parsedTpPrice) {
        setFeedback({ type: 'error', message: 'For BUY OCO, Take-Profit must be below Stop-Loss' });
        return;
      }
    }

    setSubmitting(true);
    try {
      if (isOCO) {
        // Atomic OCO submission
        const ocoPayload: OCOSubmitPayload = {
          order_a: {
            symbol,
            side,
            order_type: 'TAKE_PROFIT',
            stop_price: parsedTpPrice,
            qty: parsedQty,
            tif,
            participant_id: participantId,
            stp,
          },
          order_b: {
            symbol,
            side,
            order_type: 'STOP_LOSS',
            stop_price: parsedStopPrice,
            qty: parsedQty,
            tif,
            participant_id: participantId,
            stp,
          },
        };

        const res = await fetch('http://localhost:8000/api/v1/orders/oco', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(ocoPayload),
        });

        if (!res.ok) {
          const errorData = await res.json().catch(() => ({ detail: 'Failed to submit OCO bracket' }));
          throw new Error(errorData.detail || `Server error (${res.status})`);
        }

        const ocoRes = await res.json();
        setFeedback({
          type: 'success',
          message: `OCO Bracket submitted [${ocoRes.oco_group_id.slice(0, 10)}] (TP: $${parsedTpPrice.toFixed(2)}, SL: $${parsedStopPrice.toFixed(2)})`,
        });

        if (onOrderSubmitted && ocoRes.order_a) {
          onOrderSubmitted(ocoRes.order_a);
        }
      } else {
        // Single order submission
        const payload: OrderSubmitPayload = {
          symbol,
          side,
          order_type: orderType,
          price: (orderType === 'LIMIT' || orderType === 'STOP_LIMIT') ? parsedPrice : null,
          stop_price:
            (orderType === 'STOP_LOSS' || orderType === 'STOP_LIMIT' || orderType === 'TAKE_PROFIT')
              ? parsedStopPrice
              : null,
          trail_offset: orderType === 'TRAILING_STOP' ? parsedTrailOffset : null,
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
              Direct OMS & Trigger Engine
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

        {/* Mode Selector: Normal Order Types vs OCO Bracket */}
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] font-mono text-slate-400 uppercase">Mode</span>
          <button
            type="button"
            onClick={() => setIsOCO(!isOCO)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-mono border transition-all ${
              isOCO
                ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50 shadow-sm shadow-cyan-950'
                : 'bg-slate-950 text-slate-400 border-slate-800 hover:text-slate-200'
            }`}
          >
            <Zap size={11} className={isOCO ? 'text-cyan-400 fill-cyan-400/30' : 'text-slate-500'} />
            <span>OCO Bracket</span>
          </button>
        </div>

        {/* Order Type Selector (when not in OCO mode) */}
        {!isOCO ? (
          <div className="flex flex-col gap-1">
            <span className="text-[11px] font-mono text-slate-400 uppercase">Order Type</span>
            <div className="grid grid-cols-5 gap-1 bg-slate-950 rounded border border-slate-800 p-0.5 text-[10px] font-mono text-center">
              {(
                [
                  { id: 'LIMIT', label: 'LIMIT' },
                  { id: 'MARKET', label: 'MKT' },
                  { id: 'STOP_LOSS', label: 'STOP' },
                  { id: 'STOP_LIMIT', label: 'STOP LMT' },
                  { id: 'TRAILING_STOP', label: 'TRAIL' },
                ] as const
              ).map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setOrderType(t.id)}
                  className={`py-1 rounded transition-colors ${
                    orderType === t.id
                      ? 'bg-slate-800 text-cyan-400 font-semibold border border-cyan-500/30'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="bg-cyan-950/30 border border-cyan-800/40 rounded p-2 text-[11px] font-mono text-cyan-300 flex items-center gap-2">
            <Zap size={14} className="text-cyan-400 shrink-0" />
            <span>
              One-Cancels-the-Other: Submits Take-Profit target and Stop-Loss. If either executes, the other is canceled automatically.
            </span>
          </div>
        )}

        {/* OCO Inputs */}
        {isOCO ? (
          <div className="flex flex-col gap-2.5 p-2 bg-slate-950/70 border border-slate-800/80 rounded">
            {/* Take Profit Target */}
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between text-[11px] font-mono">
                <span className="text-emerald-400 font-medium">Take-Profit Target ($)</span>
                {lastPrice && (
                  <button
                    type="button"
                    onClick={() => setTpPriceStr((lastPrice * 1.05).toFixed(2))}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-emerald-400 border border-slate-700"
                  >
                    +5% (${(lastPrice * 1.05).toFixed(2)})
                  </button>
                )}
              </div>
              <div className="relative flex items-center">
                <span className="absolute left-2.5 text-slate-500 font-mono text-xs">$</span>
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={tpPriceStr}
                  onChange={(e) => setTpPriceStr(e.target.value)}
                  className="w-full pl-6 pr-3 py-1.5 bg-slate-900 border border-slate-800 rounded text-xs font-mono text-slate-100 focus:outline-none focus:border-cyan-500"
                  placeholder="0.00"
                  required
                />
              </div>
            </div>

            {/* Stop Loss Trigger */}
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between text-[11px] font-mono">
                <span className="text-rose-400 font-medium">Stop-Loss Trigger ($)</span>
                {lastPrice && (
                  <button
                    type="button"
                    onClick={() => setStopPriceStr((lastPrice * 0.95).toFixed(2))}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-rose-400 border border-slate-700"
                  >
                    -5% (${(lastPrice * 0.95).toFixed(2)})
                  </button>
                )}
              </div>
              <div className="relative flex items-center">
                <span className="absolute left-2.5 text-slate-500 font-mono text-xs">$</span>
                <input
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={stopPriceStr}
                  onChange={(e) => setStopPriceStr(e.target.value)}
                  className="w-full pl-6 pr-3 py-1.5 bg-slate-900 border border-slate-800 rounded text-xs font-mono text-slate-100 focus:outline-none focus:border-cyan-500"
                  placeholder="0.00"
                  required
                />
              </div>
            </div>
          </div>
        ) : (
          /* Single Order Type Specific Inputs */
          <>
            {/* Stop Activation Price (for STOP_LOSS and STOP_LIMIT) */}
            {(orderType === 'STOP_LOSS' || orderType === 'STOP_LIMIT') && (
              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between text-[11px] font-mono">
                  <span className="text-rose-400 font-medium">Stop Activation Price ($)</span>
                  {lastPrice && (
                    <button
                      type="button"
                      onClick={() =>
                        setStopPriceStr(
                          (side === 'SELL' ? lastPrice * 0.97 : lastPrice * 1.03).toFixed(2)
                        )
                      }
                      className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
                    >
                      {side === 'SELL' ? '-3%' : '+3%'}
                    </button>
                  )}
                </div>
                <div className="relative flex items-center">
                  <span className="absolute left-2.5 text-slate-500 font-mono text-xs">$</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    value={stopPriceStr}
                    onChange={(e) => setStopPriceStr(e.target.value)}
                    className="w-full pl-6 pr-3 py-1.5 bg-slate-950 border border-slate-800 rounded text-xs font-mono text-slate-100 focus:outline-none focus:border-cyan-500"
                    placeholder="0.00"
                    required
                  />
                </div>
                <span className="text-[10px] font-mono text-slate-500">
                  {side === 'SELL'
                    ? `Triggers when trade price ≤ $${parsedStopPrice.toFixed(2)}`
                    : `Triggers when trade price ≥ $${parsedStopPrice.toFixed(2)}`}
                </span>
              </div>
            )}

            {/* Trailing Offset (for TRAILING_STOP) */}
            {orderType === 'TRAILING_STOP' && (
              <div className="flex flex-col gap-1">
                <div className="flex items-center justify-between text-[11px] font-mono">
                  <span className="text-cyan-400 font-medium">Trailing Offset ($)</span>
                  <div className="flex items-center gap-1">
                    {['1.00', '2.00', '5.00'].map((val) => (
                      <button
                        key={val}
                        type="button"
                        onClick={() => setTrailOffsetStr(val)}
                        className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700"
                      >
                        ${val}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="relative flex items-center">
                  <span className="absolute left-2.5 text-slate-500 font-mono text-xs">$</span>
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    value={trailOffsetStr}
                    onChange={(e) => setTrailOffsetStr(e.target.value)}
                    className="w-full pl-6 pr-3 py-1.5 bg-slate-950 border border-slate-800 rounded text-xs font-mono text-slate-100 focus:outline-none focus:border-cyan-500"
                    placeholder="2.00"
                    required
                  />
                </div>
                <span className="text-[10px] font-mono text-slate-500">
                  Stop dynamically tracks market high/low and ratchets by ${parsedTrailOffset.toFixed(2)}
                </span>
              </div>
            )}

            {/* Limit Price Input (for LIMIT and STOP_LIMIT) */}
            {(orderType === 'LIMIT' || orderType === 'STOP_LIMIT') && (
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
            )}

            {/* Reference Price Display for Market orders */}
            {orderType === 'MARKET' && (
              <div className="bg-slate-950/60 border border-slate-800/80 rounded p-2 text-xs font-mono text-slate-400 flex items-center justify-between">
                <span>Reference Price</span>
                <span className="text-slate-200 font-semibold">
                  ${effectivePrice > 0 ? effectivePrice.toFixed(2) : '---'}
                </span>
              </div>
            )}
          </>
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
                  className="text-[10px] px-1.5 py-0.5 rounded bg-cyan-950/60 hover:bg-cyan-900/60 text-cyan-400 border border-cyan-800/50"
                  title="Max quantity within available cash"
                >
                  MAX
                </button>
              )}
            </div>
          </div>
          <input
            type="number"
            min="1"
            step="1"
            value={qtyStr}
            onChange={(e) => setQtyStr(e.target.value)}
            className="w-full px-3 py-1.5 bg-slate-950 border border-slate-800 rounded text-xs font-mono text-slate-100 focus:outline-none focus:border-cyan-500"
            placeholder="10"
            required
          />
        </div>

        {/* Order Execution Settings (TIF & STP) */}
        <div className="grid grid-cols-2 gap-2 pt-1">
          {/* TIF Policy */}
          <div className="flex flex-col gap-1">
            <span className="text-[10px] font-mono text-slate-400 uppercase">Time In Force</span>
            <select
              value={tif}
              onChange={(e) => setTif(e.target.value as TimeInForce)}
              className="w-full px-2 py-1 bg-slate-950 border border-slate-800 rounded text-[11px] font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
            >
              <option value="GTC">GTC (Good 'Til Cancel)</option>
              <option value="IOC">IOC (Immediate Or Cancel)</option>
              <option value="FOK">FOK (Fill Or Kill)</option>
            </select>
          </div>

          {/* Self-Trade Prevention Policy (STP) */}
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-1 text-[10px] font-mono text-slate-400 uppercase">
              <ShieldCheck size={11} className="text-cyan-400" />
              <span>STP Policy</span>
            </div>
            <select
              value={stp}
              onChange={(e) => setStp(e.target.value as STPPolicy)}
              className="w-full px-2 py-1 bg-slate-950 border border-slate-800 rounded text-[11px] font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
            >
              <option value="CANCEL_NEWEST">Cancel Newest</option>
              <option value="CANCEL_OLDEST">Cancel Oldest</option>
              <option value="DECREMENT_AND_CANCEL">Decrement & Cancel</option>
              <option value="NONE">None (Permit Match)</option>
            </select>
          </div>
        </div>

        {/* Estimated Total / Purchasing Power Banner */}
        <div className="p-2 bg-slate-950/80 rounded border border-slate-800/80 flex items-center justify-between text-xs font-mono">
          <span className="text-slate-400">Estimated Value</span>
          <span
            className={`font-semibold ${
              hasInsufficientFunds ? 'text-rose-400' : 'text-slate-200'
            }`}
          >
            ${estimatedTotal.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
          </span>
        </div>

        {/* Feedback Alert */}
        {feedback && (
          <div
            className={`p-2.5 rounded border text-xs font-mono flex items-start gap-2 ${
              feedback.type === 'success'
                ? 'bg-emerald-950/40 border-emerald-800/50 text-emerald-300'
                : 'bg-rose-950/40 border-rose-800/50 text-rose-300'
            }`}
          >
            {feedback.type === 'success' ? (
              <CheckCircle2 size={15} className="text-emerald-400 shrink-0 mt-0.5" />
            ) : (
              <AlertCircle size={15} className="text-rose-400 shrink-0 mt-0.5" />
            )}
            <div className="break-words flex-1">{feedback.message}</div>
          </div>
        )}

        {/* Submit Button */}
        <button
          type="submit"
          disabled={submitting || hasInsufficientFunds}
          className={`w-full py-2.5 rounded-lg text-xs font-bold uppercase tracking-wider transition-all flex items-center justify-center gap-2 shadow-lg ${
            isOCO
              ? 'bg-cyan-600 hover:bg-cyan-500 text-white shadow-cyan-950'
              : side === 'BUY'
              ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-emerald-950'
              : 'bg-rose-600 hover:bg-rose-500 text-white shadow-rose-950'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          {submitting ? (
            <>
              <Sliders size={14} className="animate-spin" />
              <span>Routing Order...</span>
            </>
          ) : isOCO ? (
            <>
              <Zap size={14} />
              <span>Submit OCO Bracket ({side} {parsedQty} {symbol})</span>
            </>
          ) : (
            <>
              <Send size={14} />
              <span>
                {side} {parsedQty} {symbol} ({orderType.replace('_', ' ')})
              </span>
            </>
          )}
        </button>
      </form>
    </div>
  );
};
