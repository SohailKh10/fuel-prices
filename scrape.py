#!/usr/bin/env python3
"""
Scrapes today's official Pakistan petrol & diesel prices from PSO's website
and writes/updates rates.json in this repo.

Runs daily via GitHub Actions (see .github/workflows/update-fuel-prices.yml).
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

PSO_URL = "https://psopk.com/en/fuels/fuel-prices"
OUTPUT_FILE = Path(__file__).parent / "rates.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def parse_price(text):
    """Extract a float from strings like 'Rs.336.03/Ltr'."""
    match = re.search(r"[\d,]+\.?\d*", text)
    if not match:
        return None
    return float(match.group(0).replace(",", ""))


def scrape():
    resp = requests.get(PSO_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    page_text = soup.get_text(" ", strip=True)

    # Find the most recent "Effective From: <date>" label for the POL (petrol/diesel) table
    date_match = re.search(r"Effective From:\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})", page_text)
    effective_date = None
    if date_match:
        try:
            effective_date = datetime.strptime(date_match.group(1), "%B %d, %Y").strftime("%Y-%m-%d")
        except ValueError:
            effective_date = None

    petrol_match = re.search(r"PREMIER EURO 5\s*Rs\.?\s*([\d,]+\.?\d*)", page_text, re.IGNORECASE)
    diesel_match = re.search(r"HI-CETANE DIESEL EURO 5\s*Rs\.?\s*([\d,]+\.?\d*)", page_text, re.IGNORECASE)

    if not petrol_match or not diesel_match:
        raise RuntimeError("Could not find petrol/diesel prices on the PSO page — site structure may have changed.")

    petrol = float(petrol_match.group(1).replace(",", ""))
    diesel = float(diesel_match.group(1).replace(",", ""))

    if not effective_date:
        effective_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    return effective_date, petrol, diesel


def load_history():
    if OUTPUT_FILE.exists():
        return json.loads(OUTPUT_FILE.read_text())
    return []


def save_history(history):
    OUTPUT_FILE.write_text(json.dumps(history, indent=2))


def main():
    try:
        effective_date, petrol, diesel = scrape()
    except Exception as exc:
        print(f"Scrape failed: {exc}", file=sys.stderr)
        sys.exit(1)

    history = load_history()

    # De-dupe: only append if this date isn't already recorded
    if not any(entry["date"] == effective_date for entry in history):
        history.append({"date": effective_date, "petrol": petrol, "diesel": diesel})
        history.sort(key=lambda e: e["date"])
        save_history(history)
        print(f"Added {effective_date}: petrol={petrol}, diesel={diesel}")
    else:
        print(f"{effective_date} already recorded — no change.")


if __name__ == "__main__":
    main()
