// useLivePrice — typed hook over the /ws/prices WebSocket.
//
// Auth: same-origin WebSocket; the session cookie is sent automatically by the
// browser on the upgrade request (same mechanism the messenger relies on).
// Subscribes to a single symbol, exposes the latest trade price + connection
// state, and transparently reconnects with backoff. Fully cleans up on unmount
// or when the symbol changes.

import { useEffect, useRef, useState } from 'react';

export interface LivePrice {
  /** Latest trade/quote price, or null until the first tick arrives. */
  price: number | null;
  /** Epoch ms of the latest tick, or null. */
  timestamp: number | null;
  /** Symbol the price belongs to (echoes the requested symbol). */
  symbol: string;
  /** True once the socket is open and subscribed. */
  connected: boolean;
}

/** Inbound message shape from /ws/prices. Tolerant of field-name variants. */
interface PriceMessage {
  type?: string;
  symbol?: string;
  s?: string;
  price?: number;
  p?: number;
  last?: number;
  timestamp?: number;
  t?: number;
}

const MIN_RECONNECT_MS = 1000;
const MAX_RECONNECT_MS = 15000;

function pricesWsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/ws/prices`;
}

function extractSymbol(msg: PriceMessage): string | undefined {
  return msg.symbol ?? msg.s;
}

function extractPrice(msg: PriceMessage): number | undefined {
  return msg.price ?? msg.p ?? msg.last;
}

function extractTimestamp(msg: PriceMessage): number {
  return msg.timestamp ?? msg.t ?? Date.now();
}

/**
 * Subscribe to live prices for `symbol`. Pass `null`/empty to disable (closes
 * any open socket and stays idle).
 */
export function useLivePrice(symbol: string | null): LivePrice {
  const [price, setPrice] = useState<number | null>(null);
  const [timestamp, setTimestamp] = useState<number | null>(null);
  const [connected, setConnected] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<number | null>(null);
  const reconnectDelayRef = useRef<number>(MIN_RECONNECT_MS);
  // Guards against state updates / reconnects after teardown.
  const activeRef = useRef<boolean>(true);

  useEffect(() => {
    activeRef.current = true;
    // Reset price state whenever the subscribed symbol changes.
    setPrice(null);
    setTimestamp(null);
    setConnected(false);

    if (!symbol) {
      return () => {
        activeRef.current = false;
      };
    }

    const clearReconnect = (): void => {
      if (reconnectTimerRef.current !== null) {
        window.clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
    };

    const connect = (): void => {
      if (!activeRef.current) return;

      const ws = new WebSocket(pricesWsUrl());
      wsRef.current = ws;

      ws.onopen = () => {
        if (!activeRef.current) {
          ws.close();
          return;
        }
        reconnectDelayRef.current = MIN_RECONNECT_MS;
        setConnected(true);
        ws.send(JSON.stringify({ action: 'subscribe', symbols: [symbol] }));
      };

      ws.onmessage = (evt: MessageEvent<string>) => {
        if (!activeRef.current) return;
        try {
          const msg = JSON.parse(evt.data) as PriceMessage;
          if (msg.type && msg.type !== 'price' && msg.type !== 'trade' && msg.type !== 'quote') {
            return;
          }
          const msgSymbol = extractSymbol(msg);
          if (msgSymbol && msgSymbol.toUpperCase() !== symbol.toUpperCase()) return;
          const nextPrice = extractPrice(msg);
          if (typeof nextPrice !== 'number' || Number.isNaN(nextPrice)) return;
          setPrice(nextPrice);
          setTimestamp(extractTimestamp(msg));
        } catch {
          /* ignore malformed frames */
        }
      };

      const scheduleReconnect = (): void => {
        if (!activeRef.current) return;
        clearReconnect();
        const delay = reconnectDelayRef.current;
        reconnectDelayRef.current = Math.min(delay * 2, MAX_RECONNECT_MS);
        reconnectTimerRef.current = window.setTimeout(connect, delay);
      };

      ws.onclose = () => {
        if (wsRef.current === ws) wsRef.current = null;
        setConnected(false);
        scheduleReconnect();
      };

      ws.onerror = () => {
        // Let onclose drive reconnection; just force the socket shut.
        ws.close();
      };
    };

    connect();

    return () => {
      activeRef.current = false;
      clearReconnect();
      const ws = wsRef.current;
      if (ws) {
        ws.onopen = null;
        ws.onmessage = null;
        ws.onclose = null;
        ws.onerror = null;
        try {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: 'unsubscribe', symbols: [symbol] }));
          }
        } catch {
          /* ignore */
        }
        ws.close();
        wsRef.current = null;
      }
    };
  }, [symbol]);

  return { price, timestamp, symbol: symbol ?? '', connected };
}

export default useLivePrice;
