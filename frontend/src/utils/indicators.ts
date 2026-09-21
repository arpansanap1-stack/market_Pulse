/**
 * Pure TypeScript Streaming & Batch Indicator Utilities
 * Matches backend math exactly (ADR-009).
 */

export interface BollingerResult {
  upper: number | null;
  middle: number | null;
  lower: number | null;
}

export interface MACDResult {
  macd: number | null;
  signal: number | null;
  histogram: number | null;
}

export class StreamingSMA {
  private period: number;
  private window: number[] = [];
  private sum = 0;

  constructor(period: number) {
    this.period = period;
  }

  update(price: number): number | null {
    this.window.push(price);
    this.sum += price;
    if (this.window.length > this.period) {
      this.sum -= this.window.shift()!;
    }
    return this.window.length >= this.period ? this.sum / this.period : null;
  }

  reset(): void {
    this.window = [];
    this.sum = 0;
  }
}

export class StreamingEMA {
  private period: number;
  private currentEma: number | null = null;
  private count = 0;
  private warmupSum = 0;
  private alpha: number;

  constructor(period: number) {
    this.period = period;
    this.alpha = 2 / (period + 1);
  }

  update(price: number): number | null {
    this.count++;
    if (this.count < this.period) {
      this.warmupSum += price;
      return null;
    }
    if (this.count === this.period) {
      this.warmupSum += price;
      this.currentEma = this.warmupSum / this.period;
      return this.currentEma;
    }
    this.currentEma = this.alpha * price + (1 - this.alpha) * this.currentEma!;
    return this.currentEma;
  }

  reset(): void {
    this.currentEma = null;
    this.count = 0;
    this.warmupSum = 0;
  }
}

export class StreamingRSI {
  private period: number;
  private lastPrice: number | null = null;
  private gains: number[] = [];
  private losses: number[] = [];
  private avgGain: number | null = null;
  private avgLoss: number | null = null;
  private count = 0;

  constructor(period = 14) {
    this.period = period;
  }

  update(price: number): number | null {
    if (this.lastPrice === null) {
      this.lastPrice = price;
      return null;
    }

    const diff = price - this.lastPrice;
    this.lastPrice = price;
    const gain = Math.max(0, diff);
    const loss = Math.max(0, -diff);

    this.count++;

    if (this.count < this.period) {
      this.gains.push(gain);
      this.losses.push(loss);
      return null;
    }

    if (this.count === this.period) {
      this.gains.push(gain);
      this.losses.push(loss);
      this.avgGain = this.gains.reduce((a, b) => a + b, 0) / this.period;
      this.avgLoss = this.losses.reduce((a, b) => a + b, 0) / this.period;
    } else {
      this.avgGain = (this.avgGain! * (this.period - 1) + gain) / this.period;
      this.avgLoss = (this.avgLoss! * (this.period - 1) + loss) / this.period;
    }

    if (this.avgLoss === 0) {
      return this.avgGain > 0 ? 100 : 50;
    }

    const rs = this.avgGain / this.avgLoss;
    return 100 - 100 / (1 + rs);
  }

  reset(): void {
    this.lastPrice = null;
    this.gains = [];
    this.losses = [];
    this.avgGain = null;
    this.avgLoss = null;
    this.count = 0;
  }
}

export class StreamingMACD {
  private fastEma: StreamingEMA;
  private slowEma: StreamingEMA;
  private signalEma: StreamingEMA;

  constructor(fast = 12, slow = 26, signal = 9) {
    this.fastEma = new StreamingEMA(fast);
    this.slowEma = new StreamingEMA(slow);
    this.signalEma = new StreamingEMA(signal);
  }

  update(price: number): MACDResult {
    const fastVal = this.fastEma.update(price);
    const slowVal = this.slowEma.update(price);

    if (fastVal === null || slowVal === null) {
      return { macd: null, signal: null, histogram: null };
    }

    const macd = fastVal - slowVal;
    const signal = this.signalEma.update(macd);
    const histogram = signal !== null ? macd - signal : null;

    return { macd, signal, histogram };
  }

  reset(): void {
    this.fastEma.reset();
    this.slowEma.reset();
    this.signalEma.reset();
  }
}

export class StreamingBollingerBands {
  private period: number;
  private numStd: number;
  private window: number[] = [];
  private sum = 0;
  private sumSq = 0;

  constructor(period = 20, numStd = 2.0) {
    this.period = period;
    this.numStd = numStd;
  }

  update(price: number): BollingerResult {
    if (this.window.length === this.period) {
      const oldest = this.window.shift()!;
      this.sum += price - oldest;
      this.sumSq += price * price - oldest * oldest;
    } else {
      this.sum += price;
      this.sumSq += price * price;
    }
    this.window.push(price);

    if (this.window.length < this.period) {
      return { upper: null, middle: null, lower: null };
    }

    const middle = this.sum / this.period;
    const variance = Math.max(0, this.sumSq / this.period - middle * middle);
    const stdDev = Math.sqrt(variance);

    return {
      upper: middle + this.numStd * stdDev,
      middle,
      lower: middle - this.numStd * stdDev,
    };
  }

  reset(): void {
    this.window = [];
    this.sum = 0;
    this.sumSq = 0;
  }
}

export class StreamingVWAP {
  private cumPv = 0;
  private cumV = 0;

  update(price: number, volume: number): number | null {
    if (volume <= 0) {
      return this.cumV > 0 ? this.cumPv / this.cumV : null;
    }
    this.cumPv += price * volume;
    this.cumV += volume;
    return this.cumPv / this.cumV;
  }

  reset(): void {
    this.cumPv = 0;
    this.cumV = 0;
  }
}
