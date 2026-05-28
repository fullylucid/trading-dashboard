#!/usr/bin/env python3
"""Format a portfolio scan result JSON into a Telegram message.

Usage:
  python3 _format_scan_msg.py <final_json_path> <narrative_text>

Prints the formatted message to stdout. Reads the scan job JSON from disk
(avoids bash quoting hell with multi-KB JSON blobs).
"""
import json, sys, datetime, zoneinfo

def fmt_items(items, n=3):
    lines, csv = [], []
    for it in (items or [])[:n]:
        sym = it.get("symbol", "?")
        sc = it.get("composite_score") or it.get("scores", {}).get("combined") or 0
        try:
            sc_f = float(sc)
        except Exception:
            sc_f = 0.0
        lines.append(f"• {sym}  {sc_f:.2f}")
        csv.append(sym)
    return ("\n".join(lines) or "—"), (", ".join(csv) or "—")

def main():
    if len(sys.argv) < 2:
        print("usage: _format_scan_msg.py <final_json_path> [narrative]", file=sys.stderr)
        sys.exit(2)
    path = sys.argv[1]
    narrative = sys.argv[2] if len(sys.argv) > 2 else ""

    with open(path) as f:
        d = json.load(f)
    result = d.get("result") or {}
    pv = result.get("portfolio_value") or 0
    try:
        pv_str = f"${float(pv):,.2f}"
    except Exception:
        pv_str = "$0.00"
    scanned = (result.get("tickers_scanned")
               or (d.get("progress") or {}).get("scanned")
               or 0)

    buys = result.get("top_buys") or result.get("buys") or []
    sells = result.get("top_sells") or result.get("sells") or []
    bblock, bcsv = fmt_items(buys)
    sblock, scsv = fmt_items(sells)

    if not narrative:
        narrative = f"Premarket scan complete — {bcsv} bid, {scsv} offered."

    now = datetime.datetime.now(zoneinfo.ZoneInfo("America/Los_Angeles"))
    now_str = now.strftime("%Y-%m-%d %H:%M PT")

    msg = (
        f"🕷️ Tradeskeebot — Pre-Market Scan\n"
        f"{now_str}  ·  {scanned} tickers\n"
        f"\n"
        f"💼 Portfolio: {pv_str}\n"
        f"\n"
        f"🟢 *Top Buys*\n{bblock}\n"
        f"\n"
        f"🔴 *Top Trims / Sells*\n{sblock}\n"
        f"\n"
        f"🧠 {narrative}"
    )
    sys.stdout.write(msg)

    # Also emit the buy/sell CSVs to a sidecar so the bash script can build the
    # narrative prompt without re-parsing JSON.
    sidecar = path + ".csv"
    with open(sidecar, "w") as f:
        f.write(f"BUYS_CSV={bcsv}\nSELLS_CSV={scsv}\nPORTFOLIO_VALUE={pv_str}\n")

if __name__ == "__main__":
    main()
