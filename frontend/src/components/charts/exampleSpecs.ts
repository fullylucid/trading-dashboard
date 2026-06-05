// exampleSpecs — a few ready-made indicator specs so the custom-indicator
// pipeline is demoable end-to-end before the persisted "arsenal" exists. Each is
// a plain spec (data, not code) the backend engine can compute. They also double
// as worked examples of the spec grammar for the future AI spec-author prompt.

import type { IndicatorSpec } from '../../lib/indicatorApi';
import { vwapSpec } from './chartLayers';

export const EXAMPLE_SPECS: IndicatorSpec[] = [
  vwapSpec(),
  {
    name: 'EMA Ribbon',
    short_name: 'RIBBON',
    pane: 'overlay',
    precision: 2,
    steps: [
      { id: 'c', op: 'series', ref: 'close' },
      { id: 'e8', op: 'ema', input: 'c', period: 8 },
      { id: 'e21', op: 'ema', input: 'c', period: 21 },
      { id: 'e55', op: 'ema', input: 'c', period: 55 },
    ],
    plots: [
      { step: 'e8', label: 'EMA8', color: '#00ff41' },
      { step: 'e21', label: 'EMA21', color: '#ffcc00' },
      { step: 'e55', label: 'EMA55', color: '#ff3b3b' },
    ],
  },
  {
    name: 'Bollinger (spec)',
    short_name: 'BOLLs',
    pane: 'overlay',
    precision: 2,
    steps: [
      { id: 'c', op: 'series', ref: 'close' },
      { id: 'mid', op: 'sma', input: 'c', period: 20 },
      { id: 'sd', op: 'stddev', input: 'c', period: 20 },
      { id: 'band', op: 'mul', inputs: ['sd', 2] },
      { id: 'upper', op: 'add', inputs: ['mid', 'band'] },
      { id: 'lower', op: 'sub', inputs: ['mid', 'band'] },
    ],
    plots: [
      { step: 'upper', label: 'Upper', color: '#00ff41' },
      { step: 'mid', label: 'Mid', color: '#888888' },
      { step: 'lower', label: 'Lower', color: '#00ff41' },
    ],
  },
  {
    name: 'Price / SMA50 ratio',
    short_name: 'P/SMA',
    pane: 'separate',
    precision: 3,
    steps: [
      { id: 'c', op: 'series', ref: 'close' },
      { id: 'ma', op: 'sma', input: 'c', period: 50 },
      { id: 'ratio', op: 'div', inputs: ['c', 'ma'] },
    ],
    plots: [{ step: 'ratio', label: 'Close/SMA50', type: 'line', color: '#00ff41' }],
  },
];
