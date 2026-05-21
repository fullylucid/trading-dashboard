import { create } from 'zustand';

const useStore = create((set) => ({
  // Watchlist state
  watchlist: [],
  setWatchlist: (watchlist) => set({ watchlist }),
  updatePrice: (symbol, priceData) =>
    set((state) => ({
      watchlist: state.watchlist.map((item) =>
        item.symbol === symbol ? { ...item, ...priceData } : item
      ),
    })),

  // Signals
  signals: {},
  setSignal: (symbol, signal) =>
    set((state) => ({
      signals: { ...state.signals, [symbol]: signal },
    })),

  // Regime
  regime: null,
  setRegime: (regime) => set({ regime }),

  // Health
  health: null,
  setHealth: (health) => set({ health }),

  // UI state
  selectedSymbol: null,
  setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol }),

  // WebSocket connections
  priceWsConnected: false,
  setPriceWsConnected: (connected) => set({ priceWsConnected: connected }),

  signalWsConnected: false,
  setSignalWsConnected: (connected) => set({ signalWsConnected: connected }),
}));

export default useStore;
