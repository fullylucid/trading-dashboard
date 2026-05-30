// backgroundBands — a Lightweight-Charts v5 pane primitive that paints vertical
// background shading bands across time intervals on the main price pane.
//
// Used by MultiPaneChart to render regime (HMM state) and sector-rotation phase
// context *behind* the candles. Implemented as an `IPanePrimitive` so it draws
// directly to the chart canvas (via `drawBackground`, z-order "bottom") and
// stays perfectly aligned with the time scale on zoom/pan.
//
// Pure render-only: band geometry (time → color) is supplied by the caller;
// this module owns none of the regime/sector math.

import type {
  IChartApi,
  IPanePrimitive,
  IPanePrimitivePaneView,
  IPrimitivePaneRenderer,
  ITimeScaleApi,
  PaneAttachedParameter,
  PrimitivePaneViewZOrder,
  Time,
  UTCTimestamp,
} from 'lightweight-charts';
import type { CanvasRenderingTarget2D } from 'fancy-canvas';
import type { ShadeBand } from '../types';

/** Optional text styling for band labels. */
export interface BandLabelStyle {
  font: string;
  color: string;
}

const DEFAULT_LABEL_STYLE: BandLabelStyle = {
  font: '11px monospace',
  color: 'rgba(209, 212, 220, 0.85)',
};

/** A band resolved to pixel x-coordinates for the current viewport. */
interface ResolvedBand {
  left: number;
  right: number;
  color: string;
  label?: string;
}

function resolveBands(
  bands: ShadeBand[],
  timeScale: ITimeScaleApi<Time>,
  canvasWidth: number,
): ResolvedBand[] {
  const resolved: ResolvedBand[] = [];
  for (const band of bands) {
    const fromX = timeScale.timeToCoordinate(band.fromTime as UTCTimestamp);
    // Open-ended bands run to the right edge of the pane.
    const toX =
      band.toTime == null
        ? canvasWidth
        : timeScale.timeToCoordinate(band.toTime as UTCTimestamp);

    // If an endpoint is off-screen, timeToCoordinate returns null. Clamp to the
    // visible canvas so partially-visible bands still paint.
    const left = fromX == null ? 0 : fromX;
    const right = toX == null ? canvasWidth : toX;
    if (right <= 0 || left >= canvasWidth) continue;

    resolved.push({
      left: Math.max(0, Math.min(left, right)),
      right: Math.min(canvasWidth, Math.max(left, right)),
      color: band.color,
      label: band.label,
    });
  }
  return resolved;
}

class BackgroundBandsRenderer implements IPrimitivePaneRenderer {
  private _bands: ResolvedBand[];
  private readonly _labelStyle: BandLabelStyle;

  public constructor(bands: ResolvedBand[], labelStyle: BandLabelStyle) {
    this._bands = bands;
    this._labelStyle = labelStyle;
  }

  // Painting on the *background* keeps shading behind candles, grid and series.
  public drawBackground(target: CanvasRenderingTarget2D): void {
    const bands = this._bands;
    if (bands.length === 0) return;

    target.useBitmapCoordinateSpace((scope) => {
      const { context: ctx, horizontalPixelRatio: hr, verticalPixelRatio: vr } = scope;
      const height = scope.bitmapSize.height;

      for (const band of bands) {
        const x = Math.round(band.left * hr);
        const w = Math.round((band.right - band.left) * hr);
        if (w <= 0) continue;
        ctx.fillStyle = band.color;
        ctx.fillRect(x, 0, w, height);
      }

      // Labels drawn on top of the fills (still behind candles).
      ctx.textBaseline = 'top';
      ctx.fillStyle = this._labelStyle.color;
      // Scale the font to bitmap space so it stays crisp on HiDPI.
      const px = Math.round(11 * vr);
      ctx.font = this._labelStyle.font.replace('11px', `${px}px`);
      for (const band of bands) {
        if (!band.label) continue;
        const x = Math.round(band.left * hr) + Math.round(4 * hr);
        ctx.fillText(band.label, x, Math.round(4 * vr));
      }
    });
  }

  // No foreground drawing — shading lives entirely in the background layer.
  public draw(): void {
    // intentionally empty
  }

  public update(bands: ResolvedBand[]): void {
    this._bands = bands;
  }
}

class BackgroundBandsPaneView implements IPanePrimitivePaneView {
  private readonly _renderer: BackgroundBandsRenderer;

  public constructor(renderer: BackgroundBandsRenderer) {
    this._renderer = renderer;
  }

  public zOrder(): PrimitivePaneViewZOrder {
    return 'bottom';
  }

  public renderer(): IPrimitivePaneRenderer {
    return this._renderer;
  }
}

/**
 * Background shading primitive. Attach via `pane.attachPrimitive(...)` (main
 * pane), call {@link BackgroundBands.setBands} to update, and `detach()` /
 * `pane.detachPrimitive(...)` on teardown.
 */
export class BackgroundBands implements IPanePrimitive<Time> {
  private _bands: ShadeBand[] = [];
  private _chart: IChartApi | null = null;
  private _requestUpdate: (() => void) | null = null;
  private readonly _labelStyle: BandLabelStyle;
  private readonly _renderer: BackgroundBandsRenderer;
  private readonly _paneView: BackgroundBandsPaneView;
  private readonly _views: readonly IPanePrimitivePaneView[];

  public constructor(labelStyle: BandLabelStyle = DEFAULT_LABEL_STYLE) {
    this._labelStyle = labelStyle;
    this._renderer = new BackgroundBandsRenderer([], labelStyle);
    this._paneView = new BackgroundBandsPaneView(this._renderer);
    // Stable array reference (library caches on identity).
    this._views = [this._paneView];
  }

  public attached(param: PaneAttachedParameter<Time>): void {
    this._chart = param.chart as unknown as IChartApi;
    this._requestUpdate = param.requestUpdate;
    this._recompute();
  }

  public detached(): void {
    this._chart = null;
    this._requestUpdate = null;
    this._bands = [];
  }

  public setBands(bands: ShadeBand[]): void {
    this._bands = bands;
    this._recompute();
    this._requestUpdate?.();
  }

  public updateAllViews(): void {
    this._recompute();
  }

  public paneViews(): readonly IPanePrimitivePaneView[] {
    return this._views;
  }

  private _recompute(): void {
    const chart = this._chart;
    if (!chart) {
      this._renderer.update([]);
      return;
    }
    const timeScale = chart.timeScale();
    const width = timeScale.width();
    this._renderer.update(resolveBands(this._bands, timeScale, width));
  }

  /** Expose the label style (read-only) for callers that want to theme it. */
  public get labelStyle(): BandLabelStyle {
    return this._labelStyle;
  }
}
