#!/usr/bin/env python3
"""
Scrapes today's official Pakistan petrol, diesel, kerosene (SKO) and LDO
prices from PSO's website and writes/updates rates.json in this repo.
Runs daily via GitHub Actions (see .github/workflows/update-fuel-prices.yml).

Note: HOBC / High Octane is intentionally not scraped here. It is not
an OGRA-regulated price — each oil marketing company sets its own, and
it varies by station — so there is no single official figure on this
page to extract.
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

    # Kerosene (SKO) and LDO sit in the same OGRA-notified table as petrol/diesel,
    # so they can be scraped the same way. Unlike petrol/diesel these are optional:
    # if PSO's labels don't match, we skip them for today rather than failing the run.
    kerosene_match = re.search(r"(?:KEROSENE(?:\s*OIL)?\s*\(?SKO\)?|\bSKO\b)\s*Rs\.?\s*([\d,]+\.?\d*)", page_text, re.IGNORECASE)
    ldo_match = re.search(r"(?:LIGHT DIESEL OIL\s*\(?LDO\)?|\bLDO\b)\s*Rs\.?\s*([\d,]+\.?\d*)", page_text, re.IGNORECASE)
    kerosene = float(kerosene_match.group(1).replace(",", "")) if kerosene_match else None
    ldo = float(ldo_match.group(1).replace(",", "")) if ldo_match else None
    if kerosene is None:
        print("Warning: kerosene (SKO) price not found on page, omitting for today.", file=sys.stderr)
    if ldo is None:
        print("Warning: LDO price not found on page, omitting for today.", file=sys.stderr)

    if not effective_date:
        effective_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return effective_date, petrol, diesel, kerosene, ldo
def load_history():
    if OUTPUT_FILE.exists():
        return json.loads(OUTPUT_FILE.read_text())
    return []
def save_history(history):
    OUTPUT_FILE.write_text(json.dumps(history, indent=2))
def main():
    try:
        effective_date, petrol, diesel, kerosene, ldo = scrape()
    except Exception as exc:
        print(f"Scrape failed: {exc}", file=sys.stderr)
        sys.exit(1)
    history = load_history()
    existing = next((entry for entry in history if entry["date"] == effective_date), None)
    if existing is None:
        entry = {"date": effective_date, "petrol": petrol, "diesel": diesel}
        if kerosene is not None:
            entry["kerosene"] = kerosene
        if ldo is not None:
            entry["ldo"] = ldo
        history.append(entry)
        history.sort(key=lambda e: e["date"])
        save_history(history)
        print(f"Added {effective_date}: petrol={petrol}, diesel={diesel}, kerosene={kerosene}, ldo={ldo}")
    else:
        # Date already recorded (e.g. petrol/diesel added by an earlier run today) —
        # fill in kerosene/ldo if they're missing, otherwise leave it alone.
        changed = False
        if kerosene is not None and "kerosene" not in existing:
            existing["kerosene"] = kerosene
            changed = True
        if ldo is not None and "ldo" not in existing:
            existing["ldo"] = ldo
            changed = True
        if changed:
            save_history(history)
            print(f"{effective_date} already recorded — filled in missing kerosene/ldo: {existing}")
        else:
            print(f"{effective_date} already recorded — no change.")
if __name__ == "__main__":
    main()
