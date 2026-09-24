#!/usr/bin/env python3
"""
scrape_shell.py — pulls Shell Pakistan's (Wafi Energy) official Super/Diesel
pump prices and appends today's reading to shell-rates.json, in the exact
same {date, petrol, diesel} shape as rates.json, so the website can load it
with the same code path.

Designed to run daily as a GitHub Action, right alongside whatever already
scrapes rates.json in this repo.

Usage:
    python scrape_shell.py

Writes/updates: shell-rates.json (in the current working directory)
"""

import json
import os
import re
import sys
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

# Shell Pakistan (branded; company is Wafi Energy Pakistan) publishes this
# board directly — no login, no JS rendering needed, it's server-rendered HTML.
SHELL_URL = "https://www.shell.com.pk/shell-stations/shell-station-price-board.html"
OUTPUT_FILE = "shell-rates.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}


def fetch_html() -> str:
    r = requests.get(SHELL_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def parse_prices(html: str):
    """
    Returns (petrol_price, diesel_price, effective_date_str_or_None).
    Tries the price table first (Product / Rs./Litre columns: "Super",
    "Diesel"); falls back to a plain-text regex scan of the whole page if
    Shell changes the table markup, since the row labels and "Rs.xxx.xx"
    figures are stable even when the surrounding HTML isn't.
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    petrol = diesel = None

    # --- Attempt 1: real <table> rows ---
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
            if len(cells) < 2:
                continue
            label, value = cells[0].lower(), cells[-1]
            m = re.search(r"[\d,]+\.\d+", value.replace(",", ""))
            if not m:
                continue
            price = float(m.group(0))
            if "super" in label or label == "petrol" or "ms 92" in label:
                petrol = price
            elif "diesel" in label and "light" not in label:
                # "Diesel" but not "Light Speed Diesel" / LDO variants
                diesel = price

    # --- Attempt 2: regex fallback over the flattened page text ---
    if petrol is None:
        m = re.search(r"Super\D{0,15}?([\d,]+\.\d{2})", text)
        if m:
            petrol = float(m.group(1).replace(",", ""))
    if diesel is None:
        m = re.search(r"\bDiesel\D{0,15}?([\d,]+\.\d{2})", text)
        if m:
            diesel = float(m.group(1).replace(",", ""))

    # --- Effective date, e.g. "updated as at 24 September 2026, 01:00 AM hrs" ---
    eff_date = None
    m = re.search(
        r"updated as at\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text, re.IGNORECASE
    )
    if m:
        try:
            eff_date = datetime.strptime(m.group(1), "%d %B %Y").date().isoformat()
        except ValueError:
            pass

    return petrol, diesel, eff_date


def load_existing(path: str):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def save(path: str, rows: list):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)


def main():
    html = fetch_html()
    petrol, diesel, eff_date = parse_prices(html)

    if petrol is None or diesel is None:
        print(
            "ERROR: could not find both Super and Diesel prices on the Shell "
            "page. Shell likely changed their page layout — open "
            f"{SHELL_URL} in a browser and update the parser in "
            "parse_prices().",
            file=sys.stderr,
        )
        sys.exit(1)

    row_date = eff_date or date.today().isoformat()

    rows = load_existing(OUTPUT_FILE)

    # Same "same date already recorded → overwrite, else append" rule the
    # rates.json feed uses, so a re-run on the same day doesn't duplicate rows.
    rows = [r for r in rows if r.get("date") != row_date]
    rows.append({"date": row_date, "petrol": petrol, "diesel": diesel})
    rows.sort(key=lambda r: r["date"])

    save(OUTPUT_FILE, rows)
    print(f"OK: {row_date} — Shell Super Rs.{petrol}, Diesel Rs.{diesel}")


if __name__ == "__main__":
    main()
