import { Link, useParams } from 'react-router-dom';
import PageHeader from '../../components/PageHeader';
import HeadConsole from './HeadConsole';
import { GREEN, BLUE } from './ui';

// Standalone single-head console page (/hq/console/:name) — a page wrapper around HeadConsole
// (the chat + composer core). The deck view (/hq/console) renders the same HeadConsole per
// swipe screen. See CONSOLE.md.

export default function ConsoleView() {
  const { name = '' } = useParams();
  return (
    <div style={{ maxWidth: 860, margin: '0 auto', padding: '0 12px 16px', fontFamily: 'monospace', color: GREEN, height: 'calc(100vh - 120px)', display: 'flex', flexDirection: 'column' }}>
      <PageHeader title={`🛰️ ${name}`} subtitle="console" />
      <div style={{ marginBottom: 8, display: 'flex', gap: 12, flex: '0 0 auto' }}>
        <Link to="/hq/console" style={{ color: BLUE, fontSize: 12, textDecoration: 'none' }}>← all consoles</Link>
        <Link to="/hq" style={{ color: BLUE, fontSize: 12, textDecoration: 'none' }}>fleet</Link>
        <Link to={`/hq/head/${name}`} style={{ color: BLUE, fontSize: 12, textDecoration: 'none' }}>head detail ↗</Link>
      </div>
      <div style={{ flex: 1, minHeight: 0 }}>
        <HeadConsole name={name} active />
      </div>
    </div>
  );
}
