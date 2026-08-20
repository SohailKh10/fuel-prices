#!/usr/bin/env python3
"""
Writes metals-history.json: one year of daily closing prices for gold, silver,
platinum and palladium, in USD per troy ounce.

Why this runs in the Action rather than in the browser
------------------------------------------------------
The website itself cannot fetch this. stooq.com blocks automated access and
sends no CORS headers, so a browser request from the site is refused. Running
it here sidesteps both problems: the Action fetches server-side and commits a
plain JSON file that the site can read from raw.githubusercontent.com.

Source: Yahoo's v8 chart endpoint, which needs no API key. It does reject
requests without a browser-like User-Agent, hence the header below.
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

OUTPUT_FILE = Path(__file__).parent / "metals-history.json"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=1y&interval=1d"
SYMBOLS = {
    "XAU": "XAUUSD=X",   # gold spot
    "XAG": "XAGUSD=X",   # silver spot
    "XPT": "XPTUSD=X",   # platinum spot
    "XPD": "XPDUSD=X",   # palladium spot
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def fetch_series(code, symbol):
    """Return {date: close} for one metal, or {} if the feed misbehaves."""
    resp = requests.get(CHART_URL.format(symbol=symbol), headers=HEADERS, timeout=25)
    resp.raise_for_status()
    payload = resp.json()

    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError(f"no result block for {symbol}")

    block = result[0]
    stamps = block.get("timestamp") or []
    quotes = ((block.get("indicators") or {}).get("quote") or [{}])[0]
    closes = quotes.get("close") or []
    if len(stamps) != len(closes) or not stamps:
        raise RuntimeError(f"timestamp/close mismatch for {symbol}")

    out = {}
    for ts, close in zip(stamps, closes):
        if close is None:          # market holidays come back as null
            continue
        day = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
        out[day] = round(float(close), 2)

    if len(out) < 30:
        raise RuntimeError(f"only {len(out)} usable points for {symbol}")
    return out


def main():
    series = {}
    for code, symbol in SYMBOLS.items():
        try:
            series[code] = fetch_series(code, symbol)
            print(f"{code} ({symbol}): {len(series[code])} daily closes")
        except Exception as exc:
            print(f"{code} ({symbol}): skipped — {exc}", file=sys.stderr)
        time.sleep(1)              # be gentle with an unofficial endpoint

    if not series:
        print("No metal data retrieved; leaving the existing file untouched.", file=sys.stderr)
        sys.exit(1)

    # Merge into rows keyed by date, so the site can read them like fuel rows.
    dates = sorted({d for prices in series.values() for d in prices})
    rows = []
    for day in dates:
        row = {"date": day}
        for code, prices in series.items():
            if day in prices:
                row[code] = prices[day]
        if len(row) > 1:
            rows.append(row)

    OUTPUT_FILE.write_text(json.dumps(rows, indent=2) + "\n")
    print(f"Wrote {len(rows)} rows to metals-history.json "
          f"({rows[0]['date']} to {rows[-1]['date']})")


if __name__ == "__main__":
    main()
