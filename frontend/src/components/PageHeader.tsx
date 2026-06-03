import type { ReactNode } from 'react';

const GREEN = '#00ff41';

/**
 * Centered page title shown at the top of every tab, sitting clear below the
 * fixed system-stats banner (clearance reserved by the shell <main>, see ../layout).
 *
 * - `title`    — the tab title (text/emoji), centered, terminal-green.
 * - `subtitle` — optional one-line description under the title.
 * - `children` — optional action controls (selectors, inputs, buttons), centered
 *                in a row beneath the title. Keeps per-page controls but unifies
 *                the heading so titles don't drift left/right per tab.
 */
export default function PageHeader({
  title,
  subtitle,
  children,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header style={{ textAlign: 'center', margin: '4px 0 20px' }}>
      <h1
        style={{
          fontSize: 22,
          fontWeight: 700,
          margin: 0,
          color: GREEN,
          textShadow: `0 0 8px ${GREEN}`,
          fontFamily: 'monospace',
          letterSpacing: 0.5,
        }}
      >
        {title}
      </h1>
      {subtitle != null && (
        <div style={{ fontSize: 12, color: 'rgba(0,255,65,0.6)', marginTop: 5, fontFamily: 'monospace' }}>
          {subtitle}
        </div>
      )}
      {children != null && (
        <div
          style={{
            marginTop: 12,
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            gap: 8,
            flexWrap: 'wrap',
          }}
        >
          {children}
        </div>
      )}
    </header>
  );
}
