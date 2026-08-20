#!/usr/bin/env python3
"""
Scrapes the current OGRA-notified Pakistan fuel prices (petrol, diesel,
kerosene/SKO, LDO and JP-1) from PSO's website into rates.json, plus PSO's
own Octane+ and LPG prices into octane.json and lpg.json.

Runs via GitHub Actions (see .github/workflows/update-fuel-prices.yml).

Why this parser is written the way it is
----------------------------------------
PSO's fuel-prices page carries SEVERAL accordions, each with its own
"Effective From" heading: POL, Octane+, HSFO, LSFO, RLNG and LPG. Some of
those dates are years old (2022) and the Octane+ one uses an abbreviated
month ("Aug 05, 2026"). Searching the whole page for the first
"Effective From" is therefore unsafe: it can pick up a heading that has
nothing to do with the petrol/diesel table.

So instead we locate the POL table by its product label, then take the
"Effective From" heading immediately before it, and read every price from
that same block. Date and prices are guaranteed to come from one table.

HOBC / Octane is deliberately not written to rates.json here. PSO's own
Octane+ price sits in a different table on a different effective date and
varies by city, so it is not part of the OGRA daily notification.
"""
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

PSO_URL = "https://psopk.com/en/fuels/fuel-prices"
OUTPUT_FILE = Path(__file__).parent / "rates.json"
OCTANE_FILE = Path(__file__).parent / "octane.json"
LPG_FILE = Path(__file__).parent / "lpg.json"
PKT = timezone(timedelta(hours=5))          # Pakistan Standard Time, UTC+5
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# Accepts "August 19, 2026", "Aug 05, 2026" and "2026-08-19"
EFFECTIVE_RX = re.compile(
    r"Effective\s+From:?\s*([A-Za-z]{3,9}\s+\d{1,2},\s*\d{4}|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d")


def parse_date(raw):
    """Parse any of PSO's date spellings into YYYY-MM-DD, or None."""
    raw = re.sub(r"\s+", " ", raw).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def find_pol_block(text):
    """
    Return (effective_date, block_text) for the OGRA-notified POL table.

    The product name appears in several places on the page — the navigation menu,
    the summary tiles at the top, and the table itself. So we consider every
    occurrence and accept the first one that is both preceded by an "Effective
    From" heading and sits in a block that also carries the diesel price. That
    combination only holds for the real POL table.
    """
    headings = list(EFFECTIVE_RX.finditer(text))
    if not headings:
        raise RuntimeError(
            "No 'Effective From' heading anywhere on the page — PSO's layout has "
            "changed. Check https://psopk.com/en/fuels/fuel-prices"
        )

    for m in re.finditer(r"PREMIER\s+EURO\s*5", text, re.IGNORECASE):
        if not re.search(r"Rs\.?\s*[\d,]", text[m.end():m.end() + 40], re.IGNORECASE):
            continue                                  # a menu link, not a price row

        heading = None
        for h in headings:
            if h.start() < m.start():
                heading = h
            else:
                break
        if heading is None:
            continue                                  # summary tile above the accordions

        nxt = EFFECTIVE_RX.search(text, heading.end())
        end = nxt.start() if nxt else min(len(text), heading.end() + 2000)
        block = text[heading.start():end]
        if not re.search(r"HI-?CETANE\s+DIESEL\s+EURO\s*5\s*Rs\.?\s*[\d,]", block, re.IGNORECASE):
            continue                                  # petrol without diesel: wrong block

        return parse_date(heading.group(1)), block

    raise RuntimeError(
        "Could not locate the POL price table — PSO's page structure has changed. "
        "Check https://psopk.com/en/fuels/fuel-prices"
    )


def price(block, pattern, label, required=False):
    m = re.search(pattern + r"\s*Rs\.?\s*([\d,]+\.?\d*)", block, re.IGNORECASE)
    if not m:
        if required:
            raise RuntimeError(f"{label} price not found in the POL table.")
        print(f"Warning: {label} not found in the POL table, omitting.", file=sys.stderr)
        return None
    return float(m.group(1).replace(",", ""))


def fetch_page():
    """Return (visible_text, raw_html). Some blocks can only be located in the
    raw HTML, because get_text() discards src/href attributes."""
    resp = requests.get(PSO_URL, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True), resp.text


def scrape(text):
    effective_date, block = find_pol_block(text)

    if not effective_date:
        effective_date = datetime.now(PKT).strftime("%Y-%m-%d")
        print(
            f"Warning: could not parse PSO's effective date, falling back to "
            f"today in Pakistan ({effective_date}).",
            file=sys.stderr,
        )

    # Guard against a date far in the future or absurdly old, which would mean
    # we parsed the wrong heading. Better to fail than to file a bad row.
    today_pkt = datetime.now(PKT).date()
    parsed = datetime.strptime(effective_date, "%Y-%m-%d").date()
    if parsed > today_pkt + timedelta(days=1) or (today_pkt - parsed).days > 60:
        raise RuntimeError(
            f"Effective date {effective_date} is implausible (today in PKT is "
            f"{today_pkt}). Refusing to write it."
        )

    return {
        "date": effective_date,
        "petrol": price(block, r"PREMIER\s+EURO\s*5", "Petrol (Premier Euro 5)", required=True),
        "diesel": price(block, r"HI-?CETANE\s+DIESEL\s+EURO\s*5", "Diesel (Hi-Cetane Euro 5)", required=True),
        "kerosene": price(block, r"(?:KEROSENE(?:\s*OIL)?\s*\(?SKO\)?|\bSKO\b)", "Kerosene (SKO)"),
        "ldo": price(block, r"(?:LIGHT\s+DIESEL\s+OIL\s*\(?LDO\)?|\bLDO\b)", "Light Diesel Oil"),
        "jp1": price(block, r"JP-?1", "Jet fuel (JP-1)"),
    }


def find_block_by(text, needle, search_from=0):
    """Return (effective_date, block_text) for the accordion containing `needle`."""
    m = re.search(needle, text[search_from:], re.IGNORECASE)
    if not m:
        return None, None
    anchor = search_from + m.start()
    heading = None
    for h in EFFECTIVE_RX.finditer(text):
        if h.start() < anchor:
            heading = h
        else:
            break
    if heading is None:
        return None, None
    nxt = EFFECTIVE_RX.search(text, heading.end())
    end = nxt.start() if nxt else min(len(text), heading.end() + 3000)
    return parse_date(heading.group(1)), text[heading.start():end]


def scrape_octane(text):
    """
    PSO's Octane+ Euro 5 price. This is PSO's own retail price, not an OGRA
    notification, and it is quoted per city, so it gets its own file.
    """
    date, block = find_block_by(text, r"Octane\s+Euro\s*5\s*\(")
    if not block:
        raise RuntimeError("Octane+ table not found on the page.")
    prices = {}
    for m in re.finditer(r"Octane\s+Euro\s*5\s*\(([^)]+)\)\s*(?:Rs\.?\s*)?([\d,]+\.?\d*)",
                         block, re.IGNORECASE):
        city = re.sub(r"\s+", " ", m.group(1)).strip()
        prices[city] = float(m.group(2).replace(",", ""))
    if not prices:
        raise RuntimeError("Octane+ table found but no city prices parsed.")
    if not date:
        date = datetime.now(PKT).strftime("%Y-%m-%d")
    return {"date": date, "unit": "PKR/litre", "prices": prices}


def scrape_lpg(text, html):
    """
    PSO's LPG consumer price, quoted per KG rather than per litre.

    The price sits in the product summary, but the effective date lives on an
    accordion whose body is just an image. get_text() strips the image src, so
    the accordion is invisible in the text and has to be found in the raw HTML.
    """
    m = re.search(r"LPG\s*\(LIQUID(?:ED)?\s+PETROLEUM\s+GAS\)\s*Rs\.?\s*([\d,]+\.?\d*)",
                  text, re.IGNORECASE)
    if not m:
        raise RuntimeError("LPG price not found on the page.")
    value = float(m.group(1).replace(",", ""))

    date = None
    anchor = re.search(r"/source/lpg/|/lpg/\d{4}/", html, re.IGNORECASE)
    if anchor:
        heading = None
        for h in EFFECTIVE_RX.finditer(html):
            if h.start() < anchor.start():
                heading = h
            else:
                break
        if heading:
            date = parse_date(heading.group(1))

    if not date:
        raise RuntimeError(
            "LPG price found but its effective date could not be located — "
            "refusing to stamp it with today's date."
        )
    return {"date": date, "unit": "PKR/kg", "price": value}


def upsert(path, entry, describe):
    """Append `entry` to the JSON list at `path`, or update that date in place."""
    history = json.loads(path.read_text()) if path.exists() else []
    existing = next((e for e in history if e["date"] == entry["date"]), None)
    if existing is None:
        history.append(entry)
    elif existing == entry:
        print(f"{describe}: {entry['date']} already recorded — no change.")
        return
    else:
        existing.update(entry)
    history.sort(key=lambda e: e["date"])
    path.write_text(json.dumps(history, indent=2) + "\n")
    print(f"{describe}: wrote {entry['date']}")


def load_history():
    if OUTPUT_FILE.exists():
        return json.loads(OUTPUT_FILE.read_text())
    return []


def save_history(history):
    history.sort(key=lambda e: e["date"])
    OUTPUT_FILE.write_text(json.dumps(history, indent=2) + "\n")


def scrape_extras(text, html):
    """
    Octane+ and LPG are best-effort: a failure here must never stop the
    OGRA-notified POL prices from being recorded. They reuse the page text
    already fetched, so every product comes from one snapshot.
    """
    for label, fn, path in (("Octane+", lambda t=text: scrape_octane(t), OCTANE_FILE),
                            ("LPG", lambda t=text: scrape_lpg(t, html), LPG_FILE)):
        try:
            upsert(path, fn(), label)
        except Exception as exc:
            print(f"{label}: skipped ({exc})", file=sys.stderr)


def main():
    try:
        text, html = fetch_page()
        scraped = scrape(text)
    except Exception as exc:
        print(f"Scrape failed: {exc}", file=sys.stderr)
        sys.exit(1)

    entry = {k: v for k, v in scraped.items() if v is not None}
    history = load_history()
    existing = next((e for e in history if e["date"] == entry["date"]), None)

    if existing is None:
        history.append(entry)
        save_history(history)
        print(f"Added {entry['date']}: {entry}")
        scrape_extras(text, html)
        return

    # Same date already on file. Fill in anything missing, and correct a value
    # if PSO has revised it during the day.
    changed = []
    for key, value in entry.items():
        if key == "date":
            continue
        if key not in existing:
            existing[key] = value
            changed.append(f"+{key}={value}")
        elif existing[key] != value:
            changed.append(f"~{key}: {existing[key]} -> {value}")
            existing[key] = value

    if changed:
        save_history(history)
        print(f"{entry['date']} updated: {', '.join(changed)}")
    else:
        print(f"{entry['date']} already recorded — no change.")

    scrape_extras(text, html)


if __name__ == "__main__":
    main()
