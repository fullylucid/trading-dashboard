// Tiny media-query hook so inline-styled pages can react to viewport width.
//
// The dashboard's analytics pages style with inline `style={{...}}` objects,
// which can't hold CSS @media rules. Rather than rewrite them into CSS modules,
// these pages read a boolean and flip a `gridTemplateColumns` (or any other
// style) between mobile and desktop. The breakpoint is single-sourced in
// ../layout (MOBILE_QUERY) so it can't drift across pages.

import { useEffect, useState } from 'react';
import { MOBILE_QUERY } from '../layout';

/** Reactive `window.matchMedia(query).matches`. SSR-safe (defaults to false). */
export function useMediaQuery(query: string): boolean {
  const get = (): boolean =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(query).matches
      : false;

  const [matches, setMatches] = useState<boolean>(get);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const mql = window.matchMedia(query);
    const onChange = (e: MediaQueryListEvent): void => setMatches(e.matches);
    setMatches(mql.matches); // sync in case the query changed between render and effect
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}

/** True on phone-width / small-tablet-portrait viewports (single-column layouts). */
export function useIsMobile(): boolean {
  return useMediaQuery(MOBILE_QUERY);
}
