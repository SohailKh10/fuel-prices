#!/usr/bin/env python3
"""
scrape_shell.py — pulls Shell Pakistan's (Wafi Energy) official Super/Diesel
pump prices and appends today's reading to shell-rates.json, in the exact
same {date, petrol, diesel} shape as rates.json.

Shell's price board renders its table with client-side JavaScript, so a plain
requests+BeautifulSoup fetch only ever sees an empty shell (no pun intended) —
the numbers simply aren't in the HTML the server sends. This version uses
Playwright to load the page in a real (headless) browser, wait for the table
to render, then read the numbers out of the finished page — the same way a
person's browser would show them.

Usage:
    pip install playwright beautifulsoup4
    playwright install --with-deps chromium
    python scrape_shell.py

Writes/updates: shell-rates.json (in the current working directory)
"""

import json
import os
import re
import sys
from datetime import date, datetime

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SHELL_URL = "https://www.shell.com.pk/shell-stations/shell-station-price-board.html"
OUTPUT_FILE = "shell-rates.json"


def fetch_rendered_html() -> str:
    """Loads the page in headless Chromium and waits for the price table
    to actually appear before grabbing the HTML — a plain page-load wait
    isn't enough, since the table is filled in slightly after the rest
    of the page."""
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )
        page.goto(SHELL_URL, wait_until="networkidle", timeout=45000)

        # Wait for a table row that actually contains a price-shaped number,
        # rather than a fixed sleep — more robust if Shell's load time varies.
        try:
            page.wait_for_selector("text=/Rs\\.?\\s*\\d/", timeout=20000)
        except Exception:
            pass  # fall through — parse_prices() will report clearly if nothing showed up

        html = page.content()
        browser.close()
        return html


def parse_prices(html: str):
    """
    Returns (petrol_price, diesel_price, effective_date_str_or_None).
    Tries the rendered price table first (rows like "Super" / "Diesel" next
    to "Rs.xxx.xx/Ltr"); falls back to a plain-text regex scan of the whole
    page if the table markup changes, since the row labels and "Rs.xxx.xx"
    figures are far more stable than the surrounding HTML.
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
    html = fetch_rendered_html()
    petrol, diesel, eff_date = parse_prices(html)

    if petrol is None or diesel is None:
        # Dump the rendered HTML for debugging when this fails in CI — the
        # workflow can pick this up as a build artifact so we can see exactly
        # what Playwright actually got back.
        with open("shell-debug.html", "w", encoding="utf-8") as f:
            f.write(html)
        print(
            "ERROR: could not find both Super and Diesel prices even after "
            "rendering the page with a real browser. Shell likely changed "
            "their page layout or component — the rendered HTML has been "
            "saved to shell-debug.html for inspection.",
            file=sys.stderr,
        )
        sys.exit(1)

    row_date = eff_date or date.today().isoformat()

    rows = load_existing(OUTPUT_FILE)
    rows = [r for r in rows if r.get("date") != row_date]
    rows.append({"date": row_date, "petrol": petrol, "diesel": diesel})
    rows.sort(key=lambda r: r["date"])

    save(OUTPUT_FILE, rows)
    print(f"OK: {row_date} — Shell Super Rs.{petrol}, Diesel Rs.{diesel}")


if __name__ == "__main__":
    main()
