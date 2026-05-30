// ChartPanel — the composed chart cockpit.
//
// Combines:
//   - CandlestickChart (candles + volume)
//   - Fibonacci retracement/extension overlay
//   - Support/Resistance overlay (scan levels preferred, else local pivots)
//   - Pattern / divergence annotations (markers)
//   - a live-price badge (useLivePrice over /ws/prices)
//   - an "AI read" button (chartApi.getAiRead) that streams a TA thesis and
//     draws the model's flagged levels on top.
//
// Because each overlay source replaces the chart's full overlay/marker set, the
// panel MERGES them here and feeds the combined arrays via the chart's
// `overlays`/`markers` props (using the pure compute helpers, not the
// clobbering declarative wrappers).

import { useMemo, useRef, useState } from 'react';
import CandlestickChart from './CandlestickChart';
import { computeFibLevels } from './FibonacciOverlay';
import {
  computeSupportResistance,
  levelsFromScanSignals,
} from './SupportResistanceOverlay';
import type { ScanSupportResistance } from './SupportResistanceOverlay';
import {
  eventsFromScanSignals,
  markersFromPatterns,
} from './PatternAnnotations';
import type { PatternEvent, ScanSignalsBlock } from './PatternAnnotations';
import { useLivePrice } from './useLivePrice';
import { getAiRead } from '../../lib/chartApi';
import type { AiReadLevel, AiReadResponse } from '../../lib/chartApi';
import type {
  Candle,
  ChartHandle,
  ChartMarker,
  ChartTheme,
  OverlayLevel,
} from './types';

export interface ChartPanelProps {
  symbol: string;
  candles: Candle[];
  /** Scan signals for this symbol (S/R + patterns). Optional. */
  scanSignals?: ScanSignalsBlock | null;
  /** Scan support/resistance block. Falls back to local derivation if absent. */
  scanSupportResistance?: ScanSupportResistance | null;
  /** Timeframe label passed through to the AI read request. */
  timeframe?: string;
  /** Extra context handed to the AI read endpoint. */
  aiReadContext?: Record<string, unknown>;
  theme?: ChartTheme;
  height?: number;
  className?: string;
  /** Initial overlay toggles. */
  showFib?: boolean;
  showSupportResistance?: boolean;
  showPatterns?: boolean;
}

const AI_READ_COLORS: Record<AiReadLevel['kind'], string> = {
  support: '#26a69a',
  resistance: '#ef5350',
  target: '#42a5f5',
  stop: '#ffa726',
  fib: '#c792ea',
  pivot: '#787b86',
};

function aiLevelsToOverlays(levels: AiReadLevel[]): OverlayLevel[] {
  return levels.map((lvl, i) => ({
    id: `ai-${i}-${lvl.kind}`,
    price: lvl.price,
    label: `AI ${lvl.label}`,
    color: AI_READ_COLORS[lvl.kind],
    lineStyle: 'large-dashed',
    lineWidth: 2,
  }));
}

function formatPrice(price: number | null): string {
  return price == null ? '—' : price.toFixed(2);
}

export function ChartPanel(props: ChartPanelProps): React.ReactElement {
  const {
    symbol,
    candles,
    scanSignals = null,
    scanSupportResistance = null,
    timeframe = '1D',
    aiReadContext,
    theme = 'dark',
    height = 480,
    className,
    showFib: initialShowFib = true,
    showSupportResistance: initialShowSR = true,
    showPatterns: initialShowPatterns = true,
  } = props;

  const chartRef = useRef<ChartHandle | null>(null);

  const [showFib, setShowFib] = useState<boolean>(initialShowFib);
  const [showSR, setShowSR] = useState<boolean>(initialShowSR);
  const [showPatterns, setShowPatterns] = useState<boolean>(initialShowPatterns);

  const [aiRead, setAiRead] = useState<AiReadResponse | null>(null);
  const [aiLoading, setAiLoading] = useState<boolean>(false);
  const [aiError, setAiError] = useState<string | null>(null);

  const live = useLivePrice(symbol);

  // ----- merged overlays (fib + S/R + AI read) -----
  const overlays = useMemo<OverlayLevel[]>(() => {
    const merged: OverlayLevel[] = [];
    if (showFib) {
      merged.push(...computeFibLevels(candles));
    }
    if (showSR) {
      merged.push(
        ...(scanSupportResistance
          ? levelsFromScanSignals(scanSupportResistance)
          : computeSupportResistance(candles)),
      );
    }
    if (aiRead) {
      merged.push(...aiLevelsToOverlays(aiRead.levels));
    }
    return merged;
  }, [candles, showFib, showSR, scanSupportResistance, aiRead]);

  // ----- merged markers (patterns / divergences) -----
  const markers = useMemo<ChartMarker[]>(() => {
    if (!showPatterns) return [];
    const events: PatternEvent[] = scanSignals
      ? eventsFromScanSignals(scanSignals)
      : [];
    return markersFromPatterns(events, candles);
  }, [candles, showPatterns, scanSignals]);

  const lastClose = candles.length > 0 ? candles[candles.length - 1].close : null;
  const badgePrice = live.price ?? lastClose;
  const change =
    badgePrice != null && lastClose != null ? badgePrice - lastClose : null;
  const changePct =
    change != null && lastClose != null && lastClose !== 0
      ? (change / lastClose) * 100
      : null;
  const up = change != null && change >= 0;

  async function handleAiRead(): Promise<void> {
    setAiLoading(true);
    setAiError(null);
    try {
      const res = await getAiRead(symbol, {
        timeframe,
        context: aiReadContext,
      });
      setAiRead(res);
    } catch {
      setAiError('AI read failed. Try again.');
    } finally {
      setAiLoading(false);
    }
  }

  function clearAiRead(): void {
    setAiRead(null);
    setAiError(null);
  }

  const palette =
    theme === 'dark'
      ? { panel: '#0b0e11', border: '#2a2e39', text: '#d1d4dc', sub: '#787b86' }
      : { panel: '#ffffff', border: '#d6dcde', text: '#131722', sub: '#6a7079' };

  return (
    <div
      className={className}
      style={{
        background: palette.panel,
        border: `1px solid ${palette.border}`,
        borderRadius: 8,
        overflow: 'hidden',
        color: palette.text,
        fontFamily: 'monospace',
      }}
    >
      {/* ---- header: symbol + live badge + AI button ---- */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          borderBottom: `1px solid ${palette.border}`,
          gap: 12,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <span style={{ fontSize: 16, fontWeight: 700 }}>{symbol.toUpperCase()}</span>
          <span style={{ fontSize: 11, color: palette.sub }}>{timeframe}</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            title={live.connected ? 'Live' : 'Disconnected'}
            style={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              background: live.connected ? '#26a69a' : '#787b86',
              display: 'inline-block',
            }}
          />
          <span style={{ fontSize: 18, fontWeight: 700 }}>{formatPrice(badgePrice)}</span>
          {changePct != null && (
            <span style={{ fontSize: 12, color: up ? '#26a69a' : '#ef5350' }}>
              {up ? '+' : ''}
              {change != null ? change.toFixed(2) : '—'} ({up ? '+' : ''}
              {changePct.toFixed(2)}%)
            </span>
          )}
        </div>
      </div>

      {/* ---- overlay toggles + AI read button ---- */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          padding: '6px 12px',
          borderBottom: `1px solid ${palette.border}`,
          fontSize: 12,
          flexWrap: 'wrap',
        }}
      >
        <Toggle label="Fib" checked={showFib} onChange={setShowFib} color={palette.sub} />
        <Toggle label="S/R" checked={showSR} onChange={setShowSR} color={palette.sub} />
        <Toggle
          label="Patterns"
          checked={showPatterns}
          onChange={setShowPatterns}
          color={palette.sub}
        />

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          {aiRead && (
            <button
              type="button"
              onClick={clearAiRead}
              style={buttonStyle(palette.border, palette.text, false)}
            >
              Clear AI
            </button>
          )}
          <button
            type="button"
            onClick={() => void handleAiRead()}
            disabled={aiLoading}
            style={buttonStyle('#42a5f5', '#0b0e11', true)}
          >
            {aiLoading ? 'Reading…' : 'AI read'}
          </button>
        </div>
      </div>

      {/* ---- chart ---- */}
      <CandlestickChart
        ref={chartRef}
        candles={candles}
        overlays={overlays}
        markers={markers}
        theme={theme}
        height={height}
      />

      {/* ---- AI read result ---- */}
      {(aiError || aiRead) && (
        <div
          style={{
            padding: '8px 12px',
            borderTop: `1px solid ${palette.border}`,
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          {aiError && <span style={{ color: '#ef5350' }}>{aiError}</span>}
          {aiRead && (
            <div>
              <div style={{ marginBottom: 4 }}>
                <span style={{ fontWeight: 700 }}>AI read</span>
                {aiRead.bias && (
                  <span
                    style={{
                      marginLeft: 8,
                      color:
                        aiRead.bias === 'bullish'
                          ? '#26a69a'
                          : aiRead.bias === 'bearish'
                            ? '#ef5350'
                            : palette.sub,
                    }}
                  >
                    {aiRead.bias}
                  </span>
                )}
              </div>
              <div style={{ color: palette.text }}>{aiRead.thesis}</div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

interface ToggleProps {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  color: string;
}

function Toggle(props: ToggleProps): React.ReactElement {
  const { label, checked, onChange, color } = props;
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer', color }}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
      />
      {label}
    </label>
  );
}

function buttonStyle(
  bg: string,
  fg: string,
  filled: boolean,
): React.CSSProperties {
  return {
    background: filled ? bg : 'transparent',
    color: filled ? fg : bg,
    border: `1px solid ${bg}`,
    borderRadius: 4,
    padding: '3px 10px',
    fontSize: 12,
    fontFamily: 'monospace',
    cursor: 'pointer',
  };
}

export default ChartPanel;
