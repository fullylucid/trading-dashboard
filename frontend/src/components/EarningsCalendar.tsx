/**
 * EarningsCalendar Component
 * Displays upcoming earnings events with estimates vs actuals
 */

import React, { useState, useEffect } from 'react';
import './EarningsCalendar.css';

interface EarningsEvent {
  symbol: string;
  company_name: string;
  event_date: string;
  fiscal_quarter: string;
  eps_estimate?: number;
  eps_actual?: number;
  eps_surprise_pct?: number;
  status: 'upcoming' | 'reported' | 'surprise';
}

interface EarningsCalendarProps {
  daysAhead?: number;
  limit?: number;
  showHistory?: boolean;
  symbol?: string;
}

const EarningsCalendar: React.FC<EarningsCalendarProps> = ({
  daysAhead = 30,
  limit = 100,
  showHistory = false,
  symbol,
}) => {
  const [events, setEvents] = useState<EarningsEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<'upcoming' | 'history' | 'surprises'>('upcoming');

  useEffect(() => {
    fetchEarnings();
  }, [view, symbol, daysAhead, limit]);

  const fetchEarnings = async () => {
    setLoading(true);
    setError(null);
    try {
      let endpoint = '/api/earnings/upcoming';

      if (view === 'history' && symbol) {
        endpoint = `/api/earnings/history/${symbol}`;
      } else if (view === 'surprises') {
        endpoint = '/api/earnings/surprises';
      }

      const params = new URLSearchParams();
      if (view === 'upcoming') {
        params.append('days_ahead', daysAhead.toString());
      }
      params.append('limit', limit.toString());

      const response = await fetch(`${endpoint}?${params.toString()}`);
      if (!response.ok) throw new Error('Failed to fetch earnings');

      const data = await response.json();
      setEvents(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const formatDate = (dateStr: string): string => {
    return new Date(dateStr).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  };

  const getSurpriseClass = (surprise?: number): string => {
    if (!surprise) return '';
    if (surprise > 10) return 'surprise-beat';
    if (surprise < -10) return 'surprise-miss';
    return 'surprise-inline';
  };

  const getSurpriseLabel = (surprise?: number): string => {
    if (!surprise) return '-';
    if (surprise > 0) return `+${surprise.toFixed(1)}%`;
    return `${surprise.toFixed(1)}%`;
  };

  return (
    <div className="earnings-calendar">
      <div className="earnings-header">
        <h2>Earnings Calendar</h2>
        <div className="earnings-tabs">
          <button
            className={`tab ${view === 'upcoming' ? 'active' : ''}`}
            onClick={() => setView('upcoming')}
          >
            Upcoming
          </button>
          {showHistory && (
            <button
              className={`tab ${view === 'history' ? 'active' : ''}`}
              onClick={() => setView('history')}
              disabled={!symbol}
            >
              History
            </button>
          )}
          <button
            className={`tab ${view === 'surprises' ? 'active' : ''}`}
            onClick={() => setView('surprises')}
          >
            Surprises
          </button>
        </div>
      </div>

      {loading && <div className="earnings-loading">Loading earnings data...</div>}

      {error && <div className="earnings-error">Error: {error}</div>}

      {!loading && !error && events.length === 0 && (
        <div className="earnings-empty">No earnings data available</div>
      )}

      <div className="earnings-table-wrapper">
        <table className="earnings-table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Date</th>
              <th>Quarter</th>
              {view === 'upcoming' && <th>EPS Estimate</th>}
              {view !== 'upcoming' && <th>EPS Estimate</th>}
              {view !== 'upcoming' && <th>EPS Actual</th>}
              {view !== 'upcoming' && <th>Surprise</th>}
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {events.map((event, idx) => (
              <tr
                key={`${event.symbol}-${event.event_date}-${idx}`}
                className={`earnings-row ${getSurpriseClass(event.eps_surprise_pct)}`}
              >
                <td className="symbol-cell">
                  <strong>{event.symbol}</strong>
                </td>
                <td>{formatDate(event.event_date)}</td>
                <td>{event.fiscal_quarter}</td>

                {view === 'upcoming' ? (
                  <>
                    <td className="estimate-cell">
                      {event.eps_estimate !== undefined
                        ? `$${event.eps_estimate.toFixed(2)}`
                        : 'TBD'}
                    </td>
                    <td className="status-cell">
                      <span className="status-badge upcoming">Upcoming</span>
                    </td>
                  </>
                ) : (
                  <>
                    <td className="estimate-cell">
                      {event.eps_estimate !== undefined
                        ? `$${event.eps_estimate.toFixed(2)}`
                        : 'N/A'}
                    </td>
                    <td className="actual-cell">
                      {event.eps_actual !== undefined
                        ? `$${event.eps_actual.toFixed(2)}`
                        : 'N/A'}
                    </td>
                    <td className="surprise-cell">
                      <span className={`surprise-value ${getSurpriseClass(event.eps_surprise_pct)}`}>
                        {getSurpriseLabel(event.eps_surprise_pct)}
                      </span>
                    </td>
                    <td className="status-cell">
                      <span
                        className={`status-badge ${
                          event.status === 'surprise' ? 'surprise' : 'reported'
                        }`}
                      >
                        {event.status === 'surprise' ? '⭐ Surprise' : 'Reported'}
                      </span>
                    </td>
                  </>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="earnings-legend">
        <span className="legend-item">
          <span className="legend-color beat"></span>Beat
        </span>
        <span className="legend-item">
          <span className="legend-color miss"></span>Miss
        </span>
        <span className="legend-item">
          <span className="legend-color inline"></span>In Line
        </span>
      </div>
    </div>
  );
};

export default EarningsCalendar;
