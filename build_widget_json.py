#!/usr/bin/env python3
"""
Writes widget.json: one small file with everything a phone widget needs.

A home-screen widget refreshes on the OS's schedule, on battery, often on
mobile data. Making it call four different APIs and do its own maths is slow
and drains power. So this does the work once, here, and publishes a single
file the widget can read in one request.

Output shape (deliberately flat and tiny):

    {
      "updated": "2026-08-20T09:00:00+05:00",
      "fuel":     {"date": "2026-08-20", "petrol": 337.51, "diesel": 363.06},
      "usd_pkr":  277.7,
      "gold":     {"usd_oz": 4495.6, "pkr_tola": 468163},
      "silver":   {"usd_oz": 67.21,  "pkr_tola": 6999}
    }
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

OUTPUT_FILE = Path(__file__).parent / "widget.json"
RATES_FILE = Path(__file__).parent / "rates.json"
PKT = timezone(timedelta(hours=5))

FX_URL = "https://open.er-api.com/v6/latest/USD"
GOLD_URL = "https://api.gold-api.com/price/{code}"

TOLA_PER_OZ = 11.6638038 / 31.1034768
HEADERS = {"User-Agent": "RateToday-widget-builder/1.0"}


def latest_fuel():
    if not RATES_FILE.exists():
        return None
    rows = json.loads(RATES_FILE.read_text())
    if not rows:
        return None
    row = rows[-1]
    out = {"date": row["date"]}
    for key in ("petrol", "diesel", "kerosene", "ldo"):
        if key in row:
            out[key] = row[key]
    return out


def usd_pkr():
    r = requests.get(FX_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    rate = (r.json().get("rates") or {}).get("PKR")
    if not rate:
        raise RuntimeError("PKR missing from the FX response")
    return round(float(rate), 2)


def metal(code, pkr_per_usd):
    r = requests.get(GOLD_URL.format(code=code), headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    price = data.get("price") or data.get("ask") or data.get("rate")
    if not price:
        raise RuntimeError(f"no price for {code}")
    usd_oz = round(float(price), 2)
    return {"usd_oz": usd_oz, "pkr_tola": round(usd_oz * TOLA_PER_OZ * pkr_per_usd)}


def main():
    payload = {"updated": datetime.now(PKT).isoformat(timespec="seconds")}

    fuel = latest_fuel()
    if fuel:
        payload["fuel"] = fuel
    else:
        print("Warning: no rates.json rows, fuel omitted.", file=sys.stderr)

    try:
        pkr = usd_pkr()
        payload["usd_pkr"] = pkr
    except Exception as exc:
        print(f"FX skipped: {exc}", file=sys.stderr)
        pkr = None

    if pkr:
        for code, name in (("XAU", "gold"), ("XAG", "silver")):
            try:
                payload[name] = metal(code, pkr)
            except Exception as exc:
                print(f"{name} skipped: {exc}", file=sys.stderr)

    if len(payload) == 1:
        print("Nothing to publish.", file=sys.stderr)
        sys.exit(1)

    OUTPUT_FILE.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Wrote widget.json ({OUTPUT_FILE.stat().st_size} bytes): "
          f"{', '.join(k for k in payload if k != 'updated')}")


if __name__ == "__main__":
    main()
