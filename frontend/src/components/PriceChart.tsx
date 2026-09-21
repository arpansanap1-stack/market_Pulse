import React, { useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  LineStyle,
} from 'lightweight-charts';
import type {
  IChartApi,
  ISeriesApi,
  LogicalRange,
  UTCTimestamp,
} from 'lightweight-charts';
import type { Bar, ChartTimeframe, ChartType, Trade } from '../types/protocol';
import {
  StreamingBollingerBands,
  StreamingEMA,
  StreamingMACD,
  StreamingRSI,
  StreamingSMA,
  StreamingVWAP,
} from '../utils/indicators';

interface PriceChartProps {
  symbol: string;
  onTimeframeChange?: (timeframe: ChartTimeframe) => void;
}

export interface PriceChartHandle {
  updateWithBars: (interval: string, bars: Bar[]) => void;
  updateWithTrades: (trades: Trade[]) => void;
}

export const PriceChart = React.forwardRef<PriceChartHandle, PriceChartProps>(
  ({ symbol, onTimeframeChange }, ref) => {
    const [timeframe, setTimeframe] = useState<ChartTimeframe>('1s');
    const [chartType, setChartType] = useState<ChartType>('candlestick');

    // Overlays visibility state
    const [showSma, setShowSma] = useState(true);
    const [showEma, setShowEma] = useState(false);
    const [showBollinger, setShowBollinger] = useState(false);
    const [showVwap, setShowVwap] = useState(true);

    // Sub-panes visibility state
    const [showRsi, setShowRsi] = useState(true);
    const [showMacd, setShowMacd] = useState(false);

    // Live legend indicator values
    const [liveValues, setLiveValues] = useState<{
      price: number | null;
      sma: number | null;
      ema: number | null;
      vwap: number | null;
      rsi: number | null;
      macd: number | null;
      macdSignal: number | null;
      macdHist: number | null;
    }>({
      price: null,
      sma: null,
      ema: null,
      vwap: null,
      rsi: null,
      macd: null,
      macdSignal: null,
      macdHist: null,
    });

    // Chart container DOM refs
    const mainChartContainerRef = useRef<HTMLDivElement>(null);
    const rsiChartContainerRef = useRef<HTMLDivElement>(null);
    const macdChartContainerRef = useRef<HTMLDivElement>(null);

    // Chart API refs
    const mainChartRef = useRef<IChartApi | null>(null);
    const rsiChartRef = useRef<IChartApi | null>(null);
    const macdChartRef = useRef<IChartApi | null>(null);

    // Main Series refs
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const candleSeriesRef = useRef<ISeriesApi<any> | null>(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const areaSeriesRef = useRef<ISeriesApi<any> | null>(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const volumeSeriesRef = useRef<ISeriesApi<any> | null>(null);

    // Overlay Series refs
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const smaSeriesRef = useRef<ISeriesApi<any> | null>(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const emaSeriesRef = useRef<ISeriesApi<any> | null>(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const bbUpperSeriesRef = useRef<ISeriesApi<any> | null>(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const bbMidSeriesRef = useRef<ISeriesApi<any> | null>(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const bbLowerSeriesRef = useRef<ISeriesApi<any> | null>(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const vwapSeriesRef = useRef<ISeriesApi<any> | null>(null);

    // Sub-pane Series refs
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rsiSeriesRef = useRef<ISeriesApi<any> | null>(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const macdLineSeriesRef = useRef<ISeriesApi<any> | null>(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const macdSignalSeriesRef = useRef<ISeriesApi<any> | null>(null);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const macdHistSeriesRef = useRef<ISeriesApi<any> | null>(null);

    // Incremental streaming indicator calculators
    const streamingSma = useRef(new StreamingSMA(20));
    const streamingEma = useRef(new StreamingEMA(20));
    const streamingRsi = useRef(new StreamingRSI(14));
    const streamingMacd = useRef(new StreamingMACD(12, 26, 9));
    const streamingBb = useRef(new StreamingBollingerBands(20, 2.0));
    const streamingVwap = useRef(new StreamingVWAP());

    const activeTimeframeRef = useRef<ChartTimeframe>(timeframe);
    activeTimeframeRef.current = timeframe;

    const chartTypeRef = useRef<ChartType>(chartType);
    chartTypeRef.current = chartType;

    const isSyncingRef = useRef(false);

    // Synchronize logical ranges between main chart and sub-panes
    const syncCharts = useCallback((sourceChart: IChartApi, targetChart: IChartApi | null) => {
      if (!targetChart) return;
      const sourceTimeScale = sourceChart.timeScale();
      const targetTimeScale = targetChart.timeScale();

      sourceTimeScale.subscribeVisibleLogicalRangeChange((range: LogicalRange | null) => {
        if (isSyncingRef.current || !range) return;
        isSyncingRef.current = true;
        targetTimeScale.setVisibleLogicalRange(range);
        isSyncingRef.current = false;
      });
    }, []);

    // 1. Initialize Main Chart
    useEffect(() => {
      if (!mainChartContainerRef.current) return;
      const container = mainChartContainerRef.current;

      const chart = createChart(container, {
        layout: {
          background: { type: ColorType.Solid, color: '#090d16' },
          textColor: '#94a3b8',
          fontFamily: 'JetBrains Mono, monospace',
          fontSize: 11,
        },
        grid: {
          vertLines: { color: 'rgba(30, 41, 59, 0.35)' },
          horzLines: { color: 'rgba(30, 41, 59, 0.35)' },
        },
        timeScale: {
          borderColor: '#1e293b',
          timeVisible: true,
          secondsVisible: true,
        },
        rightPriceScale: {
          borderColor: '#1e293b',
          scaleMargins: {
            top: 0.08,
            bottom: 0.22,
          },
        },
        crosshair: {
          vertLine: {
            color: '#38bdf8',
            width: 1,
            style: LineStyle.Dashed,
            labelBackgroundColor: '#0369a1',
          },
          horzLine: {
            color: '#38bdf8',
            width: 1,
            style: LineStyle.Dashed,
            labelBackgroundColor: '#0369a1',
          },
        },
      });

      // Candlestick Series
      const candleSeries = chart.addSeries(CandlestickSeries, {
        upColor: '#10b981',
        downColor: '#ef4444',
        borderVisible: false,
        wickUpColor: '#10b981',
        wickDownColor: '#ef4444',
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      });

      // Area Series
      const areaSeries = chart.addSeries(AreaSeries, {
        topColor: 'rgba(56, 189, 248, 0.35)',
        bottomColor: 'rgba(56, 189, 248, 0.01)',
        lineColor: '#38bdf8',
        lineWidth: 2,
        visible: chartTypeRef.current === 'area',
        priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      });

      candleSeries.applyOptions({ visible: chartTypeRef.current === 'candlestick' });

      // Volume Series
      const volumeSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: '', // separate overlay price scale
      });
      volumeSeries.priceScale().applyOptions({
        scaleMargins: { top: 0.82, bottom: 0 },
      });

      // Overlays
      const smaSeries = chart.addSeries(LineSeries, {
        color: '#f59e0b', // amber
        lineWidth: 1,
        title: 'SMA 20',
        visible: showSma,
      });

      const emaSeries = chart.addSeries(LineSeries, {
        color: '#c084fc', // purple
        lineWidth: 1,
        title: 'EMA 20',
        visible: showEma,
      });

      const bbUpperSeries = chart.addSeries(LineSeries, {
        color: 'rgba(6, 182, 212, 0.6)', // cyan
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        title: 'BB Upper',
        visible: showBollinger,
      });

      const bbMidSeries = chart.addSeries(LineSeries, {
        color: '#06b6d4', // cyan
        lineWidth: 1,
        title: 'BB Mid',
        visible: showBollinger,
      });

      const bbLowerSeries = chart.addSeries(LineSeries, {
        color: 'rgba(6, 182, 212, 0.6)', // cyan
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        title: 'BB Lower',
        visible: showBollinger,
      });

      const vwapSeries = chart.addSeries(LineSeries, {
        color: '#eab308', // yellow
        lineWidth: 1,
        title: 'VWAP',
        visible: showVwap,
      });

      mainChartRef.current = chart;
      candleSeriesRef.current = candleSeries;
      areaSeriesRef.current = areaSeries;
      volumeSeriesRef.current = volumeSeries;
      smaSeriesRef.current = smaSeries;
      emaSeriesRef.current = emaSeries;
      bbUpperSeriesRef.current = bbUpperSeries;
      bbMidSeriesRef.current = bbMidSeries;
      bbLowerSeriesRef.current = bbLowerSeries;
      vwapSeriesRef.current = vwapSeries;

      const resizeObserver = new ResizeObserver((entries) => {
        if (!entries || entries.length === 0) return;
        const { width, height } = entries[0].contentRect;
        chart.applyOptions({ width, height });
      });
      resizeObserver.observe(container);

      return () => {
        resizeObserver.disconnect();
        chart.remove();
        mainChartRef.current = null;
        candleSeriesRef.current = null;
        areaSeriesRef.current = null;
        volumeSeriesRef.current = null;
        smaSeriesRef.current = null;
        emaSeriesRef.current = null;
        bbUpperSeriesRef.current = null;
        bbMidSeriesRef.current = null;
        bbLowerSeriesRef.current = null;
        vwapSeriesRef.current = null;
      };
    }, []);

    // 2. Initialize RSI Sub-pane
    useEffect(() => {
      if (!showRsi || !rsiChartContainerRef.current) return;
      const container = rsiChartContainerRef.current;

      const chart = createChart(container, {
        layout: {
          background: { type: ColorType.Solid, color: '#070a12' },
          textColor: '#94a3b8',
          fontFamily: 'JetBrains Mono, monospace',
          fontSize: 10,
        },
        grid: {
          vertLines: { color: 'rgba(30, 41, 59, 0.25)' },
          horzLines: { color: 'rgba(30, 41, 59, 0.25)' },
        },
        timeScale: {
          borderColor: '#1e293b',
          timeVisible: true,
          secondsVisible: true,
        },
        rightPriceScale: {
          borderColor: '#1e293b',
          scaleMargins: { top: 0.1, bottom: 0.1 },
        },
      });

      // Overbought / Oversold guides
      const rsiSeries = chart.addSeries(LineSeries, {
        color: '#c084fc',
        lineWidth: 2,
        priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
      });

      rsiSeries.createPriceLine({
        price: 70,
        color: 'rgba(239, 68, 68, 0.5)',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: '70',
      });

      rsiSeries.createPriceLine({
        price: 30,
        color: 'rgba(16, 185, 129, 0.5)',
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: '30',
      });

      rsiChartRef.current = chart;
      rsiSeriesRef.current = rsiSeries;

      if (mainChartRef.current) {
        syncCharts(mainChartRef.current, chart);
        syncCharts(chart, mainChartRef.current);
      }

      const resizeObserver = new ResizeObserver((entries) => {
        if (!entries || entries.length === 0) return;
        const { width, height } = entries[0].contentRect;
        chart.applyOptions({ width, height });
      });
      resizeObserver.observe(container);

      return () => {
        resizeObserver.disconnect();
        chart.remove();
        rsiChartRef.current = null;
        rsiSeriesRef.current = null;
      };
    }, [showRsi, syncCharts]);

    // 3. Initialize MACD Sub-pane
    useEffect(() => {
      if (!showMacd || !macdChartContainerRef.current) return;
      const container = macdChartContainerRef.current;

      const chart = createChart(container, {
        layout: {
          background: { type: ColorType.Solid, color: '#070a12' },
          textColor: '#94a3b8',
          fontFamily: 'JetBrains Mono, monospace',
          fontSize: 10,
        },
        grid: {
          vertLines: { color: 'rgba(30, 41, 59, 0.25)' },
          horzLines: { color: 'rgba(30, 41, 59, 0.25)' },
        },
        timeScale: {
          borderColor: '#1e293b',
          timeVisible: true,
          secondsVisible: true,
        },
        rightPriceScale: {
          borderColor: '#1e293b',
          scaleMargins: { top: 0.1, bottom: 0.1 },
        },
      });

      const histSeries = chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'price', precision: 3, minMove: 0.001 },
      });

      const macdLineSeries = chart.addSeries(LineSeries, {
        color: '#38bdf8',
        lineWidth: 2,
        priceFormat: { type: 'price', precision: 3, minMove: 0.001 },
      });

      const signalSeries = chart.addSeries(LineSeries, {
        color: '#fb923c',
        lineWidth: 1,
        lineStyle: LineStyle.Dotted,
        priceFormat: { type: 'price', precision: 3, minMove: 0.001 },
      });

      macdChartRef.current = chart;
      macdHistSeriesRef.current = histSeries;
      macdLineSeriesRef.current = macdLineSeries;
      macdSignalSeriesRef.current = signalSeries;

      if (mainChartRef.current) {
        syncCharts(mainChartRef.current, chart);
        syncCharts(chart, mainChartRef.current);
      }

      const resizeObserver = new ResizeObserver((entries) => {
        if (!entries || entries.length === 0) return;
        const { width, height } = entries[0].contentRect;
        chart.applyOptions({ width, height });
      });
      resizeObserver.observe(container);

      return () => {
        resizeObserver.disconnect();
        chart.remove();
        macdChartRef.current = null;
        macdHistSeriesRef.current = null;
        macdLineSeriesRef.current = null;
        macdSignalSeriesRef.current = null;
      };
    }, [showMacd, syncCharts]);

    // Update overlay visibility dynamically
    useEffect(() => {
      smaSeriesRef.current?.applyOptions({ visible: showSma });
    }, [showSma]);

    useEffect(() => {
      emaSeriesRef.current?.applyOptions({ visible: showEma });
    }, [showEma]);

    useEffect(() => {
      bbUpperSeriesRef.current?.applyOptions({ visible: showBollinger });
      bbMidSeriesRef.current?.applyOptions({ visible: showBollinger });
      bbLowerSeriesRef.current?.applyOptions({ visible: showBollinger });
    }, [showBollinger]);

    useEffect(() => {
      vwapSeriesRef.current?.applyOptions({ visible: showVwap });
    }, [showVwap]);

    useEffect(() => {
      if (chartType === 'candlestick') {
        candleSeriesRef.current?.applyOptions({ visible: true });
        areaSeriesRef.current?.applyOptions({ visible: false });
      } else {
        candleSeriesRef.current?.applyOptions({ visible: false });
        areaSeriesRef.current?.applyOptions({ visible: true });
      }
    }, [chartType]);

    // Fetch initial historical bars and indicators on mount or timeframe switch
    const loadHistoricalData = useCallback(async (tf: ChartTimeframe) => {
      try {
        const [barsRes, indRes] = await Promise.all([
          fetch(`http://localhost:8000/api/v1/bars?symbol=${symbol}&interval=${tf}&limit=200`),
          fetch(`http://localhost:8000/api/v1/indicators?symbol=${symbol}&interval=${tf}&limit=200`),
        ]);

        if (!barsRes.ok || !indRes.ok) return;

        const bars: Bar[] = await barsRes.json();
        const indData = await indRes.json();

        if (bars.length === 0) return;

        // Reset streaming calculators
        streamingSma.current.reset();
        streamingEma.current.reset();
        streamingRsi.current.reset();
        streamingMacd.current.reset();
        streamingBb.current.reset();
        streamingVwap.current.reset();

        const candleData = bars.map((b) => ({
          time: b.time as UTCTimestamp,
          open: b.open,
          high: b.high,
          low: b.low,
          close: b.close,
        }));

        const areaData = bars.map((b) => ({
          time: b.time as UTCTimestamp,
          value: b.close,
        }));

        const volumeData = bars.map((b) => ({
          time: b.time as UTCTimestamp,
          value: b.volume,
          color: b.close >= b.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
        }));

        candleSeriesRef.current?.setData(candleData);
        areaSeriesRef.current?.setData(areaData);
        volumeSeriesRef.current?.setData(volumeData);

        // Seed streaming calculators with historical bars
        for (const b of bars) {
          streamingSma.current.update(b.close);
          streamingEma.current.update(b.close);
          streamingRsi.current.update(b.close);
          streamingMacd.current.update(b.close);
          streamingBb.current.update(b.close);
          streamingVwap.current.update(b.close, b.volume);
        }

        // Set batch overlay indicators
        const indicators = indData.indicators || {};
        const times: number[] = indData.times || [];

        if (indicators.sma20) {
          const smaData = times
            .map((t, i) =>
              indicators.sma20[i] !== null ? { time: t as UTCTimestamp, value: indicators.sma20[i] } : null
            )
            .filter((d): d is { time: UTCTimestamp; value: number } => d !== null);
          smaSeriesRef.current?.setData(smaData);
        }

        if (indicators.ema20) {
          const emaData = times
            .map((t, i) =>
              indicators.ema20[i] !== null ? { time: t as UTCTimestamp, value: indicators.ema20[i] } : null
            )
            .filter((d): d is { time: UTCTimestamp; value: number } => d !== null);
          emaSeriesRef.current?.setData(emaData);
        }

        if (indicators.bollinger) {
          const bb = indicators.bollinger;
          const uData = times
            .map((t, i) =>
              bb.upper[i] !== null ? { time: t as UTCTimestamp, value: bb.upper[i] } : null
            )
            .filter((d): d is { time: UTCTimestamp; value: number } => d !== null);
          const mData = times
            .map((t, i) =>
              bb.middle[i] !== null ? { time: t as UTCTimestamp, value: bb.middle[i] } : null
            )
            .filter((d): d is { time: UTCTimestamp; value: number } => d !== null);
          const lData = times
            .map((t, i) =>
              bb.lower[i] !== null ? { time: t as UTCTimestamp, value: bb.lower[i] } : null
            )
            .filter((d): d is { time: UTCTimestamp; value: number } => d !== null);

          bbUpperSeriesRef.current?.setData(uData);
          bbMidSeriesRef.current?.setData(mData);
          bbLowerSeriesRef.current?.setData(lData);
        }

        if (indicators.vwap) {
          const vwapData = times
            .map((t, i) =>
              indicators.vwap[i] !== null ? { time: t as UTCTimestamp, value: indicators.vwap[i] } : null
            )
            .filter((d): d is { time: UTCTimestamp; value: number } => d !== null);
          vwapSeriesRef.current?.setData(vwapData);
        }

        // Sub-panes: RSI & MACD
        if (indicators.rsi14) {
          const rsiData = times
            .map((t, i) =>
              indicators.rsi14[i] !== null ? { time: t as UTCTimestamp, value: indicators.rsi14[i] } : null
            )
            .filter((d): d is { time: UTCTimestamp; value: number } => d !== null);
          rsiSeriesRef.current?.setData(rsiData);
        }

        if (indicators.macd) {
          const macd = indicators.macd;
          const mData = times
            .map((t, i) =>
              macd.macd[i] !== null ? { time: t as UTCTimestamp, value: macd.macd[i] } : null
            )
            .filter((d): d is { time: UTCTimestamp; value: number } => d !== null);
          const sData = times
            .map((t, i) =>
              macd.signal[i] !== null ? { time: t as UTCTimestamp, value: macd.signal[i] } : null
            )
            .filter((d): d is { time: UTCTimestamp; value: number } => d !== null);
          const hData = times
            .map((t, i) =>
              macd.histogram[i] !== null
                ? {
                    time: t as UTCTimestamp,
                    value: macd.histogram[i],
                    color: macd.histogram[i] >= 0 ? 'rgba(16, 185, 129, 0.7)' : 'rgba(239, 68, 68, 0.7)',
                  }
                : null
            )
            .filter((d): d is { time: UTCTimestamp; value: number; color: string } => d !== null);

          macdLineSeriesRef.current?.setData(mData);
          macdSignalSeriesRef.current?.setData(sData);
          macdHistSeriesRef.current?.setData(hData);
        }

        // Update live values legend
        const lastBar = bars[bars.length - 1];
        setLiveValues({
          price: lastBar.close,
          sma: streamingSma.current.update(lastBar.close),
          ema: streamingEma.current.update(lastBar.close),
          vwap: lastBar.vwap,
          rsi: streamingRsi.current.update(lastBar.close),
          macd: 0,
          macdSignal: 0,
          macdHist: 0,
        });
      } catch (err) {
        console.error('Failed to fetch historical bars:', err);
      }
    }, [symbol]);

    useEffect(() => {
      loadHistoricalData(timeframe);
    }, [timeframe, loadHistoricalData]);

    const handleTimeframeSelect = (tf: ChartTimeframe) => {
      if (tf === timeframe) return;
      setTimeframe(tf);
      if (onTimeframeChange) {
        onTimeframeChange(tf);
      }
    };

    // Imperative handle to accept streaming updates
    useImperativeHandle(ref, () => ({
      updateWithBars: (interval: string, bars: Bar[]) => {
        if (interval !== activeTimeframeRef.current || bars.length === 0) {
          return;
        }

        for (const bar of bars) {
          const time = bar.time as UTCTimestamp;

          // 1. Update Price & Volume
          candleSeriesRef.current?.update({
            time,
            open: bar.open,
            high: bar.high,
            low: bar.low,
            close: bar.close,
          });

          areaSeriesRef.current?.update({
            time,
            value: bar.close,
          });

          volumeSeriesRef.current?.update({
            time,
            value: bar.volume,
            color: bar.close >= bar.open ? 'rgba(16, 185, 129, 0.45)' : 'rgba(239, 68, 68, 0.45)',
          });

          // 2. Incremental Overlays
          const smaVal = streamingSma.current.update(bar.close);
          if (smaVal !== null) {
            smaSeriesRef.current?.update({ time, value: smaVal });
          }

          const emaVal = streamingEma.current.update(bar.close);
          if (emaVal !== null) {
            emaSeriesRef.current?.update({ time, value: emaVal });
          }

          const bbRes = streamingBb.current.update(bar.close);
          if (bbRes.upper !== null && bbRes.middle !== null && bbRes.lower !== null) {
            bbUpperSeriesRef.current?.update({ time, value: bbRes.upper });
            bbMidSeriesRef.current?.update({ time, value: bbRes.middle });
            bbLowerSeriesRef.current?.update({ time, value: bbRes.lower });
          }

          const vwapVal = streamingVwap.current.update(bar.close, bar.volume);
          if (vwapVal !== null) {
            vwapSeriesRef.current?.update({ time, value: vwapVal });
          }

          // 3. Incremental Sub-panes (RSI & MACD)
          const rsiVal = streamingRsi.current.update(bar.close);
          if (rsiVal !== null) {
            rsiSeriesRef.current?.update({ time, value: rsiVal });
          }

          const macdRes = streamingMacd.current.update(bar.close);
          if (macdRes.macd !== null && macdRes.signal !== null && macdRes.histogram !== null) {
            macdLineSeriesRef.current?.update({ time, value: macdRes.macd });
            macdSignalSeriesRef.current?.update({ time, value: macdRes.signal });
            macdHistSeriesRef.current?.update({
              time,
              value: macdRes.histogram,
              color: macdRes.histogram >= 0 ? 'rgba(16, 185, 129, 0.7)' : 'rgba(239, 68, 68, 0.7)',
            });
          }

          // Update header legend
          setLiveValues({
            price: bar.close,
            sma: smaVal,
            ema: emaVal,
            vwap: vwapVal,
            rsi: rsiVal,
            macd: macdRes.macd,
            macdSignal: macdRes.signal,
            macdHist: macdRes.histogram,
          });
        }
      },

      updateWithTrades: (_trades: Trade[]) => {
        // Trade tape fallback if needed
      },
    }));

    return (
      <div className="flex-1 h-full w-full flex flex-col bg-slate-950/70 rounded-xl border border-slate-800/80 overflow-hidden shadow-2xl">
        {/* Top Chart Toolbar */}
        <div className="flex flex-wrap items-center justify-between px-3 py-2 border-b border-slate-800/80 bg-slate-900/60 backdrop-blur-sm gap-2 text-xs">
          {/* Left: Timeframe & Chart Style Switchers */}
          <div className="flex items-center space-x-2">
            <div className="flex items-center bg-slate-950/80 rounded-lg p-0.5 border border-slate-800">
              {(['1s', '5s', '15s', '1m'] as ChartTimeframe[]).map((tf) => (
                <button
                  key={tf}
                  onClick={() => handleTimeframeSelect(tf)}
                  className={`px-2.5 py-1 rounded-md font-mono font-medium transition-all ${
                    timeframe === tf
                      ? 'bg-sky-500 text-white shadow-sm font-semibold'
                      : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                  }`}
                >
                  {tf}
                </button>
              ))}
            </div>

            <div className="h-4 w-px bg-slate-800" />

            <div className="flex items-center bg-slate-950/80 rounded-lg p-0.5 border border-slate-800">
              <button
                onClick={() => setChartType('candlestick')}
                className={`px-2.5 py-1 rounded-md font-medium transition-all ${
                  chartType === 'candlestick'
                    ? 'bg-slate-800 text-sky-400 font-semibold'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                }`}
                title="Candlestick View"
              >
                Candles
              </button>
              <button
                onClick={() => setChartType('area')}
                className={`px-2.5 py-1 rounded-md font-medium transition-all ${
                  chartType === 'area'
                    ? 'bg-slate-800 text-sky-400 font-semibold'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
                }`}
                title="Area Line View"
              >
                Line
              </button>
            </div>
          </div>

          {/* Right: Technical Indicator Overlays & Sub-panes Toggles */}
          <div className="flex items-center space-x-1.5 flex-wrap">
            <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 mr-1">Overlays</span>
            <button
              onClick={() => setShowSma(!showSma)}
              className={`px-2 py-0.5 rounded border text-[11px] font-mono transition-colors ${
                showSma
                  ? 'bg-amber-500/20 text-amber-300 border-amber-500/50'
                  : 'bg-slate-900 text-slate-400 border-slate-800 hover:border-slate-700'
              }`}
            >
              SMA(20)
            </button>
            <button
              onClick={() => setShowEma(!showEma)}
              className={`px-2 py-0.5 rounded border text-[11px] font-mono transition-colors ${
                showEma
                  ? 'bg-purple-500/20 text-purple-300 border-purple-500/50'
                  : 'bg-slate-900 text-slate-400 border-slate-800 hover:border-slate-700'
              }`}
            >
              EMA(20)
            </button>
            <button
              onClick={() => setShowBollinger(!showBollinger)}
              className={`px-2 py-0.5 rounded border text-[11px] font-mono transition-colors ${
                showBollinger
                  ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/50'
                  : 'bg-slate-900 text-slate-400 border-slate-800 hover:border-slate-700'
              }`}
            >
              Bollinger
            </button>
            <button
              onClick={() => setShowVwap(!showVwap)}
              className={`px-2 py-0.5 rounded border text-[11px] font-mono transition-colors ${
                showVwap
                  ? 'bg-yellow-500/20 text-yellow-300 border-yellow-500/50'
                  : 'bg-slate-900 text-slate-400 border-slate-800 hover:border-slate-700'
              }`}
            >
              VWAP
            </button>

            <div className="h-4 w-px bg-slate-800 mx-1" />

            <span className="text-[10px] uppercase font-bold tracking-wider text-slate-500 mr-1">Panes</span>
            <button
              onClick={() => setShowRsi(!showRsi)}
              className={`px-2 py-0.5 rounded border text-[11px] font-mono transition-colors ${
                showRsi
                  ? 'bg-violet-500/25 text-violet-300 border-violet-500/60'
                  : 'bg-slate-900 text-slate-400 border-slate-800 hover:border-slate-700'
              }`}
            >
              RSI(14)
            </button>
            <button
              onClick={() => setShowMacd(!showMacd)}
              className={`px-2 py-0.5 rounded border text-[11px] font-mono transition-colors ${
                showMacd
                  ? 'bg-sky-500/25 text-sky-300 border-sky-500/60'
                  : 'bg-slate-900 text-slate-400 border-slate-800 hover:border-slate-700'
              }`}
            >
              MACD
            </button>
          </div>
        </div>

        {/* Live Indicator Value Bar */}
        <div className="flex items-center px-4 py-1.5 bg-slate-950/90 border-b border-slate-900 text-[11px] font-mono space-x-4 overflow-x-auto text-slate-400">
          <div className="flex items-center space-x-1.5">
            <span className="text-slate-500">O/H/L/C:</span>
            <span className="text-white font-bold">{symbol}</span>
            <span className="text-sky-400">${liveValues.price?.toFixed(2) ?? '—'}</span>
          </div>
          {showSma && liveValues.sma !== null && (
            <div className="flex items-center space-x-1 text-amber-400">
              <span className="text-slate-500">SMA:</span>
              <span>${liveValues.sma.toFixed(2)}</span>
            </div>
          )}
          {showEma && liveValues.ema !== null && (
            <div className="flex items-center space-x-1 text-purple-400">
              <span className="text-slate-500">EMA:</span>
              <span>${liveValues.ema.toFixed(2)}</span>
            </div>
          )}
          {showVwap && liveValues.vwap !== null && (
            <div className="flex items-center space-x-1 text-yellow-400">
              <span className="text-slate-500">VWAP:</span>
              <span>${liveValues.vwap.toFixed(2)}</span>
            </div>
          )}
          {showRsi && liveValues.rsi !== null && (
            <div className="flex items-center space-x-1 text-violet-400">
              <span className="text-slate-500">RSI:</span>
              <span>{liveValues.rsi.toFixed(1)}</span>
            </div>
          )}
        </div>

        {/* Chart Canvas Area */}
        <div className="flex-1 flex flex-col min-h-0 w-full relative">
          {/* Main Price Chart */}
          <div
            ref={mainChartContainerRef}
            className={`w-full ${showRsi && showMacd ? 'h-[50%]' : showRsi || showMacd ? 'h-[70%]' : 'h-full'}`}
          />

          {/* RSI Sub-pane */}
          {showRsi && (
            <div className={`w-full border-t border-slate-800/80 relative ${showMacd ? 'h-[25%]' : 'h-[30%]'}`}>
              <div className="absolute top-1 left-2 z-10 flex items-center space-x-2 text-[10px] font-mono text-slate-400 bg-slate-900/80 px-2 py-0.5 rounded border border-slate-800">
                <span className="text-violet-400 font-bold">RSI (14)</span>
                {liveValues.rsi !== null && <span>{liveValues.rsi.toFixed(2)}</span>}
                <button
                  onClick={() => setShowRsi(false)}
                  className="hover:text-red-400 transition-colors ml-1"
                  title="Close RSI Pane"
                >
                  ✕
                </button>
              </div>
              <div ref={rsiChartContainerRef} className="h-full w-full" />
            </div>
          )}

          {/* MACD Sub-pane */}
          {showMacd && (
            <div className={`w-full border-t border-slate-800/80 relative ${showRsi ? 'h-[25%]' : 'h-[30%]'}`}>
              <div className="absolute top-1 left-2 z-10 flex items-center space-x-2 text-[10px] font-mono text-slate-400 bg-slate-900/80 px-2 py-0.5 rounded border border-slate-800">
                <span className="text-sky-400 font-bold">MACD (12, 26, 9)</span>
                {liveValues.macd !== null && <span>M: {liveValues.macd.toFixed(3)}</span>}
                {liveValues.macdSignal !== null && <span>S: {liveValues.macdSignal.toFixed(3)}</span>}
                {liveValues.macdHist !== null && (
                  <span className={liveValues.macdHist >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
                    H: {liveValues.macdHist.toFixed(3)}
                  </span>
                )}
                <button
                  onClick={() => setShowMacd(false)}
                  className="hover:text-red-400 transition-colors ml-1"
                  title="Close MACD Pane"
                >
                  ✕
                </button>
              </div>
              <div ref={macdChartContainerRef} className="h-full w-full" />
            </div>
          )}
        </div>
      </div>
    );
  }
);

PriceChart.displayName = 'PriceChart';
