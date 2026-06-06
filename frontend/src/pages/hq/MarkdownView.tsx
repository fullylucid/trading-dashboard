// Minimal, dependency-free markdown renderer for the HQ doc/memory browser.
//
// Deliberately small: we render the operator's own trusted, local, git-tracked docs behind
// SSO — not arbitrary input — so the goal is "readable", not a full CommonMark engine. It
// builds React nodes (never dangerouslySetInnerHTML, so no XSS surface) and covers the
// subset our BLUEPRINT/roadmap/README/memory files actually use: headings, fenced + inline
// code, bold/italic, links, bullet/numbered lists, blockquotes, hr, paragraphs. Mermaid/
// other fenced blocks render as plain code for now (interactive diagrams are a later slice).
import { Fragment, type ReactNode } from 'react';
import { GREEN, DIM, FAINT, BLUE } from './ui';

const mono = "'SFMono-Regular', Consolas, monospace";

// Optional [[wikilink]] renderer. When provided, `[[name]]` / `[[name|label]]` become whatever
// node the caller returns (the memory browser returns an in-app <Link>); otherwise they render
// as plain dim text. This is what makes the [[link]] graph navigable inside HQ.
export type WikiLinkRenderer = (name: string, label: string, key: string) => ReactNode;

const HEADING_SIZES = [22, 19, 16, 14, 13, 12];

export default function MarkdownView({
  source,
  renderWikiLink,
}: {
  source: string;
  renderWikiLink?: WikiLinkRenderer;
}) {
  // inline: wikilink / code / bold / italic / link — defined here so it closes over renderWikiLink
  function renderInline(text: string, keyBase: string): ReactNode[] {
    const out: ReactNode[] = [];
    // wikilink first so [[x]] isn't mis-tokenized; then code/bold/italic/md-link
    const re = /(\[\[[^\]]+\]\])|(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*]+\*)|(\[[^\]]+\]\([^)]+\))/g;
    let last = 0;
    let m: RegExpExecArray | null;
    let i = 0;
    while ((m = re.exec(text)) !== null) {
      if (m.index > last) out.push(<Fragment key={`${keyBase}-t${i}`}>{text.slice(last, m.index)}</Fragment>);
      const tok = m[0];
      if (tok.startsWith('[[')) {
        const inner = tok.slice(2, -2);
        const [name, alias] = inner.split('|');
        const label = (alias ?? name).trim();
        const target = name.trim();
        out.push(
          renderWikiLink
            ? <Fragment key={`${keyBase}-w${i}`}>{renderWikiLink(target, label, `${keyBase}-w${i}`)}</Fragment>
            : <span key={`${keyBase}-w${i}`} style={{ color: DIM }}>[[{label}]]</span>,
        );
      } else if (tok.startsWith('`')) {
        out.push(
          <code key={`${keyBase}-c${i}`} style={{ background: 'rgba(0,255,65,0.1)', padding: '0 4px', borderRadius: 3, color: GREEN }}>
            {tok.slice(1, -1)}
          </code>,
        );
      } else if (tok.startsWith('**')) {
        out.push(<strong key={`${keyBase}-b${i}`} style={{ color: GREEN }}>{tok.slice(2, -2)}</strong>);
      } else if (tok.startsWith('*')) {
        out.push(<em key={`${keyBase}-i${i}`}>{tok.slice(1, -1)}</em>);
      } else {
        const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(tok)!;
        out.push(
          <a key={`${keyBase}-a${i}`} href={mm[2]} target="_blank" rel="noreferrer" style={{ color: BLUE }}>
            {mm[1]}
          </a>,
        );
      }
      last = m.index + tok.length;
      i += 1;
    }
    if (last < text.length) out.push(<Fragment key={`${keyBase}-tEnd`}>{text.slice(last)}</Fragment>);
    return out;
  }

  const lines = source.replace(/\r\n/g, '\n').split('\n');
  const blocks: ReactNode[] = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // fenced code
    if (/^\s*```/.test(line)) {
      const buf: string[] = [];
      i += 1;
      while (i < lines.length && !/^\s*```/.test(lines[i])) {
        buf.push(lines[i]);
        i += 1;
      }
      i += 1; // closing fence
      blocks.push(
        <pre
          key={key++}
          style={{
            background: 'rgba(0,255,65,0.05)', border: `1px solid ${FAINT}`, borderRadius: 4,
            padding: '8px 10px', overflowX: 'auto', fontFamily: mono, fontSize: 12, color: 'rgba(0,255,65,0.85)',
          }}
        >
          {buf.join('\n')}
        </pre>,
      );
      continue;
    }

    // heading
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) {
      const level = h[1].length;
      blocks.push(
        <div
          key={key++}
          style={{
            fontSize: HEADING_SIZES[level - 1], fontWeight: 700, color: GREEN,
            margin: level <= 2 ? '16px 0 8px' : '12px 0 6px',
            borderBottom: level === 1 ? `1px solid ${FAINT}` : 'none', paddingBottom: level === 1 ? 4 : 0,
          }}
        >
          {renderInline(h[2], `h${key}`)}
        </div>,
      );
      i += 1;
      continue;
    }

    // horizontal rule
    if (/^\s*(---|\*\*\*|___)\s*$/.test(line)) {
      blocks.push(<hr key={key++} style={{ border: 'none', borderTop: `1px solid ${FAINT}`, margin: '12px 0' }} />);
      i += 1;
      continue;
    }

    // blockquote
    if (/^\s*>\s?/.test(line)) {
      const buf: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        buf.push(lines[i].replace(/^\s*>\s?/, ''));
        i += 1;
      }
      blocks.push(
        <blockquote
          key={key++}
          style={{ borderLeft: `3px solid ${FAINT}`, margin: '8px 0', padding: '2px 0 2px 10px', color: DIM }}
        >
          {renderInline(buf.join(' '), `q${key}`)}
        </blockquote>,
      );
      continue;
    }

    // lists (consume a contiguous run; ordered if the first marker is numeric)
    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const items: string[] = [];
      const ordered = /^\s*\d+\.\s+/.test(line);
      while (i < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*+]|\d+\.)\s+/, ''));
        i += 1;
      }
      const liStyle: React.CSSProperties = { margin: '2px 0', lineHeight: 1.4 };
      const listStyle: React.CSSProperties = { margin: '6px 0', paddingLeft: 22, color: 'rgba(0,255,65,0.85)' };
      blocks.push(
        ordered ? (
          <ol key={key++} style={listStyle}>
            {items.map((it, n) => <li key={n} style={liStyle}>{renderInline(it, `li${key}-${n}`)}</li>)}
          </ol>
        ) : (
          <ul key={key++} style={listStyle}>
            {items.map((it, n) => <li key={n} style={liStyle}>{renderInline(it, `li${key}-${n}`)}</li>)}
          </ul>
        ),
      );
      continue;
    }

    // blank line
    if (/^\s*$/.test(line)) {
      i += 1;
      continue;
    }

    // paragraph (gather until blank/structural line)
    const para: string[] = [];
    while (
      i < lines.length &&
      !/^\s*$/.test(lines[i]) &&
      !/^\s*```/.test(lines[i]) &&
      !/^#{1,6}\s/.test(lines[i]) &&
      !/^\s*(---|\*\*\*|___)\s*$/.test(lines[i]) &&
      !/^\s*>\s?/.test(lines[i]) &&
      !/^\s*([-*+]|\d+\.)\s+/.test(lines[i])
    ) {
      para.push(lines[i]);
      i += 1;
    }
    blocks.push(
      <p key={key++} style={{ margin: '6px 0', lineHeight: 1.5, color: 'rgba(0,255,65,0.85)' }}>
        {renderInline(para.join(' '), `p${key}`)}
      </p>,
    );
  }

  return <div style={{ fontFamily: mono, fontSize: 13 }}>{blocks}</div>;
}
