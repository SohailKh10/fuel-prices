#!/usr/bin/env python3
"""
Writes crude.json: daily closing prices for Brent and WTI crude, in USD per barrel.

Output shape (oldest first, same style as rates.json):

    [
      {"date": "2026-10-20", "brent": 91.42, "wti": 86.10},
      {"date": "2026-10-21", "brent": 92.37, "wti": 86.37}
    ]

Source: Yahoo's v8 chart endpoint (same one scrape_metals.py uses, no API key).
    BZ=F  ICE Brent front-month futures
    CL=F  NYMEX WTI front-month futures

History is MERGED with the existing file, never replaced, so the dataset keeps
growing past Yahoo's 2-year window. If Yahoo fails, the old file is left
untouched and the script exits 0 so the rest of the workflow still runs.
"""
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

BUILD = "crude-scraper v1.0"
OUTPUT_FILE = Path(__file__).parent / "crude.json"
CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=2y&interval=1d"
SYMBOLS = {"brent": "BZ=F", "wti": "CL=F"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def fetch_series(symbol):
    """Return {date: close} for one symbol. Raises on a bad response."""
    resp = requests.get(CHART_URL.format(symbol=symbol), headers=HEADERS, timeout=25)
    resp.raise_for_status()
    result = (resp.json().get("chart") or {}).get("result") or []
    if not result:
        raise RuntimeError(f"no result block for {symbol}")
    block = result[0]
    stamps = block.get("timestamp") or []
    closes = (((block.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    if not stamps or len(stamps) != len(closes):
        raise RuntimeError(f"timestamp/close mismatch for {symbol}")

    # Date each bar in the exchange's own timezone, so a US close is not
    # pushed onto the next calendar day.
    offset = timedelta(seconds=(block.get("meta") or {}).get("gmtoffset", 0))
    out = {}
    for ts, close in zip(stamps, closes):
        if close is None:  # holidays come back as null
            continue
        # Negative prices are real (WTI, April 2020), so only reject absurd values.
        if not -100 < float(close) < 1000:
            continue
        day = (datetime.fromtimestamp(ts, timezone.utc) + offset).strftime("%Y-%m-%d")
        out[day] = round(float(close), 2)
    if len(out) < 30:
        raise RuntimeError(f"only {len(out)} rows for {symbol}")
    return out


def fetch_with_retry(symbol, tries=3):
    last = None
    for attempt in range(1, tries + 1):
        try:
            return fetch_series(symbol)
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"  {symbol}: attempt {attempt} failed: {exc}")
            time.sleep(4 * attempt)
    raise RuntimeError(f"{symbol} failed after {tries} tries: {last}")


def load_existing():
    if not OUTPUT_FILE.exists():
        return {}
    try:
        rows = json.loads(OUTPUT_FILE.read_text())
        return {r["date"]: r for r in rows if isinstance(r, dict) and "date" in r}
    except Exception as exc:  # noqa: BLE001
        print(f"note: could not read existing {OUTPUT_FILE.name}: {exc}")
        return {}


def main():
    print(BUILD)
    fresh = {}
    for key, symbol in SYMBOLS.items():
        try:
            fresh[key] = fetch_with_retry(symbol)
            print(f"  {key}: {len(fresh[key])} rows, latest {max(fresh[key])}")
        except Exception as exc:  # noqa: BLE001
            print(f"  {key}: {exc}")

    if not fresh:
        print("No crude data fetched; keeping the existing file unchanged.")
        return 0

    merged = load_existing()
    for key, series in fresh.items():
        for day, price in series.items():
            row = merged.setdefault(day, {"date": day})
            row[key] = price

    rows = sorted(merged.values(), key=lambda r: r["date"])
    OUTPUT_FILE.write_text(json.dumps(rows, indent=1) + "\n")
    print(f"Wrote {OUTPUT_FILE.name}: {len(rows)} rows, latest {rows[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
