#!/usr/bin/env python3
"""Build fx.json for liveratespk.com (dollar-rate and gold-rate pages).

fx.json = today's USD-based rates (open.er-api.com) + about one year of history
for every currency (60 daily points, then weekly), from the free Currency API on
jsDelivr (@fawazahmed0/currency-api). Stdlib only. If the rate source fails the
old fx.json is kept (exit 1). If only the history fails, the old history is kept.
"""
import json, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "fx.json"
ER = "https://open.er-api.com/v6/latest/USD"
CDNS = [
    "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{d}/v1/currencies/usd.min.json",
    "https://{d}.currency-api.pages.dev/v1/currencies/usd.min.json",
]
UA = "LiveRatesPK-FxBot/1.0 (+https://liveratespk.com)"
DAILY, TOTAL_DAYS, WEEK = 60, 365, 7


def get(url, tries=3, timeout=25):
    last = None
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(2 * (n + 1))
    raise last


def sig(x, n=7):
    try:
        return float(f"{float(x):.{n}g}")
    except Exception:
        return None


def day_rates(d):
    for tpl in CDNS:
        try:
            j = get(tpl.format(d=d), tries=2)
            u = j.get("usd")
            if u:
                return {k.upper(): v for k, v in u.items() if isinstance(v, (int, float)) and v > 0}
        except Exception:
            continue
    return None


def main():
    er = get(ER)
    rates = {k: v for k, v in (er.get("rates") or {}).items() if isinstance(v, (int, float)) and v > 0}
    if len(rates) < 50 or "PKR" not in rates:
        print("rate source returned too little data", file=sys.stderr)
        return 1
    today = datetime.now(timezone.utc).date()
    dates = [today - timedelta(days=i) for i in range(1, DAILY + 1)]
    d = DAILY + WEEK
    while d <= TOTAL_DAYS:
        dates.append(today - timedelta(days=d))
        d += WEEK
    dates.sort()
    iso = [x.isoformat() for x in dates]
    with ThreadPoolExecutor(max_workers=8) as ex:
        days = list(ex.map(day_rates, iso))
    ok = sum(1 for x in days if x)
    print(f"history days fetched: {ok}/{len(iso)}")

    old = None
    try:
        old = json.loads(OUT.read_text(encoding="utf-8"))
    except Exception:
        pass
    history = None
    if ok >= len(iso) * 0.6:
        codes = sorted(rates)
        series = {}
        for c in codes:
            row, last = [], None
            for dd in days:
                v = dd.get(c) if dd else None
                if v is None:
                    v = last
                else:
                    last = v
                row.append(v)
            # leading gaps: back-fill from the first known value
            first = next((v for v in row if v is not None), None)
            row = [first if v is None else v for v in row]
            row.append(rates[c])  # today = the same figure the page shows
            if c == "USD" or all(v is None for v in row):
                continue
            series[c] = [sig(v) for v in row]
        history = {"dates": iso + [today.isoformat()], "series": series}
    elif old and old.get("history"):
        history = old["history"]
        print("history failed, keeping old history", file=sys.stderr)

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_updated": er.get("time_last_update_utc"),
        "base": "USD",
        "rates": {k: sig(v) for k, v in sorted(rates.items())},
        "history": history,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print("wrote", OUT, OUT.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
