#!/usr/bin/env python3
"""Fetch crypto market data into crypto.json (used by liveratespk.com crypto page).
Stdlib only. If the main market call fails, the old crypto.json is kept (exit 1)."""
import json, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "crypto.json"
CG = "https://api.coingecko.com/api/v3"
UA = "LiveRatesPK-CryptoBot/1.0 (+https://liveratespk.com)"
SPARK_POINTS = 42


def get(url, tries=3, timeout=25):
    last = None
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # 429 etc: wait and retry
            last = e
            time.sleep(4 * (n + 1))
    raise last


def sig(x, n=6):
    if x is None:
        return None
    try:
        return float(f"{float(x):.{n}g}")
    except Exception:
        return None


def down(vals, n=SPARK_POINTS):
    vals = [v for v in (vals or []) if v is not None]
    if len(vals) <= n:
        return [sig(v) for v in vals]
    step = (len(vals) - 1) / (n - 1)
    return [sig(vals[round(i * step)]) for i in range(n)]


def coin(c):
    return {
        "id": c.get("id"), "symbol": (c.get("symbol") or "").upper(), "name": c.get("name"),
        "image": c.get("image"), "rank": c.get("market_cap_rank"),
        "price": sig(c.get("current_price")), "mcap": c.get("market_cap"), "vol": c.get("total_volume"),
        "ch1h": sig(c.get("price_change_percentage_1h_in_currency"), 4),
        "ch24": sig(c.get("price_change_percentage_24h_in_currency", c.get("price_change_percentage_24h")), 4),
        "ch7d": sig(c.get("price_change_percentage_7d_in_currency"), 4),
        "hi24": sig(c.get("high_24h")), "lo24": sig(c.get("low_24h")),
        "ath": sig(c.get("ath")), "athd": sig(c.get("ath_change_percentage"), 4),
        "supply": c.get("circulating_supply"), "max": c.get("max_supply"),
        "spark": down((c.get("sparkline_in_7d") or {}).get("price")),
    }


def main():
    q = urllib.parse.urlencode({"vs_currency": "usd", "order": "market_cap_desc", "per_page": 250, "page": 1,
                                "sparkline": "true", "price_change_percentage": "1h,24h,7d"})
    try:
        raw = get(f"{CG}/coins/markets?{q}")
        coins = [coin(c) for c in raw if c.get("id") and c.get("current_price") is not None]
    except Exception as e:
        print("markets failed:", e)
        sys.exit(1)
    if len(coins) < 20:
        print("too few coins, keeping old file")
        sys.exit(1)
    doc = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "coins": coins}

    try:
        g = get(f"{CG}/global")["data"]
        doc["global"] = {"mcap": g["total_market_cap"]["usd"], "vol": g["total_volume"]["usd"],
                         "btc_dom": g["market_cap_percentage"].get("btc"), "eth_dom": g["market_cap_percentage"].get("eth"),
                         "mcap_ch24": g.get("market_cap_change_percentage_24h_usd"), "active": g.get("active_cryptocurrencies")}
    except Exception as e:
        print("global failed:", e)
    try:
        f = get("https://api.alternative.me/fng/?limit=1")["data"][0]
        doc["fng"] = {"value": int(f["value"]), "label": f["value_classification"]}
    except Exception as e:
        print("fng failed:", e)
    rate = None
    try:
        rate = get("https://open.er-api.com/v6/latest/USD")["rates"]["PKR"]
    except Exception as e:
        print("er-api failed:", e)
    if not rate:
        try:
            rate = get(f"{CG}/simple/price?ids=tether&vs_currencies=pkr")["tether"]["pkr"]
        except Exception as e:
            print("tether pkr failed:", e)
    if rate:
        doc["usd_pkr"] = round(float(rate), 2)
    elif OUT.exists():  # keep the last known rate
        try:
            doc["usd_pkr"] = json.loads(OUT.read_text("utf-8")).get("usd_pkr")
        except Exception:
            pass

    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(OUT)
    print(f"wrote {len(coins)} coins, usd_pkr={doc.get('usd_pkr')}, fng={doc.get('fng')}")


if __name__ == "__main__":
    main()
