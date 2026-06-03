// Single source of truth for the fixed "chrome" that floats OVER page content.
// Anything position:fixed that overlays the page is declared here so scroll
// containers can reserve clearance — otherwise content slides under it and gets
// blocked (e.g. the Crack-a-Dawn brief's last lines under the bottom ticker).
//
// Rule of thumb: when you add a fixed/sticky element on top of others, add its
// extent here and let the shell (App.tsx <main>) reserve the space — don't
// hand-roll a magic padding number on each page.

export const BANNER_H = 28;   // SystemBanner — fixed, top, full width
export const TICKER_H = 43;   // GlobalTicker — fixed, bottom: 42px widget + 1px top border
export const NAV_BTN_H = 44;  // floating ☰ nav button (top:12) hangs to ~42px down

// Clearance the shell reserves around routed page content.
// Top must clear the taller of the banner and the ☰ button.
export const CHROME_TOP = Math.max(BANNER_H, NAV_BTN_H);
export const CHROME_BOTTOM = TICKER_H;
