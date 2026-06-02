import { useEffect, useRef } from 'react';

/**
 * Reusable embed for TradingView's free widgets (no Advanced-Charts license needed).
 * Injects the widget's external script with its config as the script body, the way
 * TradingView's copy-paste snippets do — wrapped for React (idempotent re-mounts).
 */
export default function TVWidget({
  script,
  config,
  height = 400,
  title,
}: {
  script: string;            // e.g. "ticker-tape", "market-overview", "stock-heatmap"
  config: Record<string, unknown>;
  height?: number | string;
  title?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const cfgKey = JSON.stringify(config);

  useEffect(() => {
    const host = ref.current;
    if (!host) return;
    host.innerHTML = '';
    const widget = document.createElement('div');
    widget.className = 'tradingview-widget-container__widget';
    widget.style.height = typeof height === 'number' ? `${height}px` : height;
    const s = document.createElement('script');
    s.src = `https://s3.tradingview.com/external-embedding/embed-widget-${script}.js`;
    s.type = 'text/javascript';
    s.async = true;
    s.innerHTML = JSON.stringify({ width: '100%', height: '100%', colorTheme: 'dark', locale: 'en', ...config });
    host.appendChild(widget);
    host.appendChild(s);
    return () => { host.innerHTML = ''; };
  }, [script, cfgKey, height]);

  return (
    <div style={{ marginBottom: 14 }}>
      {title && <div style={{ fontSize: 12, color: 'rgba(0,255,65,0.55)', marginBottom: 6, textTransform: 'uppercase', letterSpacing: 1 }}>{title}</div>}
      <div
        ref={ref}
        className="tradingview-widget-container"
        style={{ height: typeof height === 'number' ? `${height}px` : height, border: '1px solid rgba(0,255,65,0.3)', borderRadius: 6, overflow: 'hidden' }}
      />
    </div>
  );
}
