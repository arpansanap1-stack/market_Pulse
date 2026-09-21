import React, { useEffect, useRef } from 'react';
import {
  AreaSeries,
  ColorType,
  createChart,
  HistogramSeries,
} from 'lightweight-charts';
import type {
  IChartApi,
  ISeriesApi,
  UTCTimestamp,
} from 'lightweight-charts';
import type { Trade } from '../types/protocol';

interface PriceChartProps {
  symbol: string;
}

export interface PriceChartHandle {
  updateWithTrades: (trades: Trade[]) => void;
}

export const PriceChart = React.forwardRef<PriceChartHandle, PriceChartProps>(
  ({ symbol }, ref) => {
    const chartContainerRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const areaSeriesRef = useRef<ISeriesApi<any> | null>(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const volumeSeriesRef = useRef<ISeriesApi<any> | null>(null);
    const lastTimeRef = useRef<number>(0);
    const accumulatedVolumeRef = useRef<number>(0);

    useEffect(() => {
      if (!chartContainerRef.current) return;

      const container = chartContainerRef.current;

      const chart = createChart(container, {
        layout: {
          background: { type: ColorType.Solid, color: '#0e131f' },
          textColor: '#94a3b8',
          fontFamily: 'JetBrains Mono, monospace',
          fontSize: 11,
        },
        grid: {
          vertLines: { color: 'rgba(30, 41, 59, 0.4)' },
          horzLines: { color: 'rgba(30, 41, 59, 0.4)' },
        },
        timeScale: {
          borderColor: '#1e293b',
          timeVisible: true,
          secondsVisible: true,
        },
        rightPriceScale: {
          borderColor: '#1e293b',
          scaleMargins: {
            top: 0.1,
            bottom: 0.25,
          },
        },
        crosshair: {
          vertLine: {
            color: '#38bdf8',
            width: 1,
            style: 2,
            labelBackgroundColor: '#0369a1',
          },
          horzLine: {
            color: '#38bdf8',
            width: 1,
            style: 2,
            labelBackgroundColor: '#0369a1',
          },
        },
      });

      // Price Area Series with sleek gradient in Lightweight Charts v5
      const areaSeries = chart.addSeries(AreaSeries, {
        topColor: 'rgba(56, 189, 248, 0.35)',
        bottomColor: 'rgba(56, 189, 248, 0.02)',
        lineColor: '#38bdf8',
        lineWidth: 2,
        priceFormat: {
          type: 'price',
          precision: 2,
          minMove: 0.01,
        },
      });

      // Volume histogram on bottom sub-layer in Lightweight Charts v5
      const volumeSeries = chart.addSeries(HistogramSeries, {
        color: '#10b981',
        priceFormat: {
          type: 'volume',
        },
        priceScaleId: '', // Separate price scale overlay
      });

      volumeSeries.priceScale().applyOptions({
        scaleMargins: {
          top: 0.82,
          bottom: 0,
        },
      });

      chartRef.current = chart;
      areaSeriesRef.current = areaSeries;
      volumeSeriesRef.current = volumeSeries;

      // Responsive resize handling
      const resizeObserver = new ResizeObserver((entries) => {
        if (!entries || entries.length === 0) return;
        const { width, height } = entries[0].contentRect;
        chart.applyOptions({ width, height });
      });

      resizeObserver.observe(container);

      return () => {
        resizeObserver.disconnect();
        chart.remove();
        chartRef.current = null;
        areaSeriesRef.current = null;
        volumeSeriesRef.current = null;
      };
    }, []);

    // Expose direct imperative update to avoid React state overhead
    React.useImperativeHandle(ref, () => ({
      updateWithTrades: (trades: Trade[]) => {
        if (!areaSeriesRef.current || !volumeSeriesRef.current || trades.length === 0) {
          return;
        }

        const areaSeries = areaSeriesRef.current;
        const volumeSeries = volumeSeriesRef.current;

        for (const trade of trades) {
          const tradeSec = Math.floor(trade.ts_ns / 1_000_000_000);
          const time = Math.max(lastTimeRef.current, tradeSec) as UTCTimestamp;

          if (time === lastTimeRef.current) {
            accumulatedVolumeRef.current += trade.qty;
          } else {
            accumulatedVolumeRef.current = trade.qty;
            lastTimeRef.current = time;
          }

          areaSeries.update({
            time,
            value: trade.price,
          });

          volumeSeries.update({
            time,
            value: accumulatedVolumeRef.current,
            color: trade.aggressor_side === 'BUY' ? 'rgba(16, 185, 129, 0.45)' : 'rgba(239, 68, 68, 0.45)',
          });
        }
      },
    }));

    return (
      <div className="relative flex-1 h-full w-full bg-slate-950/60 rounded-xl border border-slate-800/80 overflow-hidden shadow-inner">
        <div className="absolute top-3 left-4 z-10 flex items-center space-x-2 bg-slate-900/80 backdrop-blur-md px-3 py-1 rounded-md border border-slate-800 text-xs">
          <span className="font-bold text-white tracking-wider">{symbol}</span>
          <span className="text-slate-500">•</span>
          <span className="text-sky-400 font-mono">Live Price (GBM Stub)</span>
        </div>
        <div ref={chartContainerRef} className="h-full w-full" />
      </div>
    );
  }
);

PriceChart.displayName = 'PriceChart';
