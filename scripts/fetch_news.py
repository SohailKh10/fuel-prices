#!/usr/bin/env python3
"""LiveRatesPK news fetcher.
Reads public RSS/Atom feeds, classifies items (fuel/gold/crypto/currency/economy),
keeps short snippets + links only, writes news.json at repo root.
"""
import gzip, json, re, sys, time, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "news.json"
MAX_AGE_DAYS = 10
MAX_ITEMS = 900
MAX_PER_CAT = 50   # per category AND region, so global news cannot crowd out Pakistani news
SNIPPET_MAX = 180
CLASSIFY_CHARS = 300

FEEDS = [
    # ---- Pakistan (region "pk") ----
    {"name": "Dawn", "url": "https://www.dawn.com/feeds/business", "region": "pk"},
    {"name": "Dawn", "url": "https://www.dawn.com/feeds/home", "region": "pk", "general": True},
    {"name": "The Express Tribune", "url": "https://tribune.com.pk/feed/business", "region": "pk"},
    {"name": "Business Recorder", "url": "https://www.brecorder.com/feeds/latest-news", "region": "pk"},
    {"name": "ProPakistani", "url": "https://propakistani.pk/feed/", "region": "pk"},
    {"name": "Arab News Pakistan", "url": "https://www.arabnews.pk/rss.xml", "region": "pk", "general": True},
    {"name": "Dawn", "url": "https://www.dawn.com/feeds/sport", "region": "pk"},
    {"name": "The Express Tribune", "url": "https://tribune.com.pk/feed/sports", "region": "pk"},
    # Urdu (all Pakistan)
    {"name": "Express Urdu", "url": "https://www.express.pk/feed/", "lang": "ur", "region": "pk", "general": True},
    {"name": "Express Urdu Sports", "url": "https://www.express.pk/sports/feed/", "lang": "ur", "region": "pk"},
    {"name": "BBC Urdu", "url": "https://feeds.bbci.co.uk/urdu/rss.xml", "lang": "ur", "region": "pk", "general": True},
    {"name": "Independent Urdu", "url": "https://www.independenturdu.com/rss.xml", "lang": "ur", "region": "pk", "general": True},
    {"name": "ARY News Urdu", "url": "https://urdu.arynews.tv/feed/", "lang": "ur", "region": "pk", "general": True},
    {"name": "Dawn News Urdu", "url": "https://www.dawnnews.tv/rss", "lang": "ur", "region": "pk", "general": True},
    # ---- World (region "world"; items that mention Pakistan are promoted to "pk") ----
    {"name": "Dawn", "url": "https://www.dawn.com/feeds/pakistan", "region": "pk", "general": True},
    {"name": "The Express Tribune", "url": "https://tribune.com.pk/feed/pakistan", "region": "pk", "general": True},
    {"name": "Dawn", "url": "https://www.dawn.com/feeds/world", "general": True},
    {"name": "BBC News", "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "general": True},
    {"name": "The Guardian", "url": "https://www.theguardian.com/world/rss", "general": True},
    {"name": "BBC News", "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
    {"name": "The Guardian", "url": "https://www.theguardian.com/business/rss"},
    {"name": "CNBC", "url": "https://www.cnbc.com/id/19836768/device/rss/rss.html", "default_cat": "fuel"},
    {"name": "OilPrice.com", "url": "https://oilprice.com/rss/main", "default_cat": "fuel"},
    {"name": "Mining.com", "url": "https://www.mining.com/feed/"},
    {"name": "FXStreet", "url": "https://www.fxstreet.com/rss/news"},
    {"name": "MarketWatch", "url": "http://feeds.marketwatch.com/marketwatch/topstories/"},
    {"name": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml", "general": True},
    {"name": "Cointelegraph", "url": "https://cointelegraph.com/rss", "default_cat": "crypto"},
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "default_cat": "crypto"},
    {"name": "Decrypt", "url": "https://decrypt.co/feed", "default_cat": "crypto"},
    # Cricket (world)
    {"name": "ESPNcricinfo", "url": "https://www.espncricinfo.com/rss/content/story/feeds/0.xml", "default_cat": "cricket"},
    {"name": "BBC Sport", "url": "https://feeds.bbci.co.uk/sport/cricket/rss.xml", "default_cat": "cricket"},
    {"name": "The Guardian", "url": "https://www.theguardian.com/sport/cricket/rss", "default_cat": "cricket"},
    {"name": "Times of India", "url": "https://timesofindia.indiatimes.com/rssfeeds/4719161.cms", "default_cat": "cricket"},
    {"name": "NDTV Sports", "url": "https://feeds.feedburner.com/ndtvsports-cricket", "default_cat": "cricket"},
    {"name": "Sky Sports", "url": "https://www.skysports.com/rss/12040", "default_cat": "cricket"},
]

CAT_ORDER = ["fuel", "gold", "crypto", "currency", "economy", "cricket", "affairs"]
CAT_RE = {
    "fuel": r"petrol|diesel|hsd|fuel|ogra|lpg|lng|kerosene|petroleum|gasoline|brent|crude|opec|oil|natural gas|gas prices?|omcs?|energy prices?|refiner(?:y|ies)|shale|wti",
    "gold": r"gold|silver|bullion|tola|platinum|palladium|precious metals?|xau",
    "crypto": r"bitcoin|btc|ethereum|ether|crypto\w*|stablecoins?|tether|usdt|blockchain|binance|xrp|solana|altcoins?|defi|virtual assets?|pvara|tokeni[sz]ed?",
    "currency": r"dollar|rupee|pkr|forex|exchange rates?|interbank|remittances?|currency|currencies|yuan|euro|sterling|dirham|riyal|sbp|state bank|yen|dxy|pound sterling|rupees?",
    "cricket": r"cricket\w*|psl|pcb|icc|t20i?s?|odis?|test (?:match|series|cricket)|wickets?|batsman|batters?|bowlers?|innings|asia cup|champions trophy|babar azam|shaheen|rizwan|shadab|naseem|salman agha|ipl|bbl|ashes",
    "affairs": r"politic\w*|parliament|senate|national assembly|election\w*|prime minister|president|cabinet|supreme court|high court|verdict|terror\w*|militants?|suicide (?:attack|bomb\w*)|blasts?|security forces|ispr|army chief|police|tourism|tourists?|travel advisory|floods?|earthquake|monsoon|heatwave|protests?|pti|pml-?n|ppp|imran khan|nawaz sharif|shehbaz|zardari|ceasefire|gaza|ukraine|united nations|summit|visa|diplomat\w*|foreign office|afghanistan|india|iran",
    "economy": r"imf|inflation|kse-?100|psx|stock exchange|policy rate|interest rate|gdp|fbr|budget|world bank|trade deficit|cpi|sensitive price index|spi|federal reserve|the fed|ecb|recession|tariffs?|wall street|nasdaq|dow jones|stock markets?|treasury yields?|central banks?",
}
CAT_UR = {'fuel': 'پیٹرول|ڈیزل|تیل|ایندھن|اوگرا|گیس|ایل پی جی|برینٹ|پیٹرولیم', 'gold': 'سونا|سونے|چاندی|تولہ|پلاٹینم', 'crypto': 'بٹ کوائن|بٹ کوائنز|کرپٹو|ایتھیریم|ڈیجیٹل کرنسی|بائنانس|بلاک چین', 'currency': 'ڈالر|کرنسی|زرمبادلہ|ترسیلات زر|اسٹیٹ بینک|سٹیٹ بینک|شرح تبادلہ|روپے کی قدر|ریال|درہم|انٹربینک', 'cricket': 'کرکٹ|پی ایس ایل|پی سی بی|آئی سی سی|ٹی ٹوئنٹی|ون ڈے|ٹیسٹ میچ|ٹیسٹ سیریز|وکٹ|بلے باز|بولر|بابر اعظم|رضوان', 'affairs': 'سیاست|سیاسی|حکومت|وزیر اعظم|وزیراعظم|صدر|عدالت|سپریم کورٹ|دہشت گرد|دہشتگرد|حملہ|دھماکہ|سیکیورٹی فورسز|آئی ایس پی آر|پولیس|سیاحت|سیاح|سیلاب|زلزلہ|بارش|انتخابات|پارلیمنٹ|قومی اسمبلی|سینیٹ|احتجاج|تحریک انصاف|عمران خان|نواز شریف|شہباز|زرداری|جنگ بندی|غزہ|افغانستان|بھارت|ایران', 'economy': 'آئی ایم ایف|مہنگائی|اسٹاک ایکسچینج|پی ایس ایکس|شرح سود|بجٹ|ایف بی آر|معیشت|معاشی|ٹیکس|جی ڈی پی'}
CAT_RE = {k: re.compile(r"(?:\b(?:%s)\b|%s)" % (v, CAT_UR[k]), re.I) for k, v in CAT_RE.items()}


PK_RE = re.compile(r"(?:\b(?:pakistan\w*|pcb|psl|karachi|lahore|islamabad|peshawar|quetta|rawalpindi|ogra|psx|kse-?100|pkr|state bank of pakistan|sbp)\b|پاکستان|کراچی|لاہور|اسلام آباد)", re.I)

UA = "LiveRatesPK-NewsBot/1.0 (+https://liveratespk.com)"
TRACK = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_src|igshid|cmpid)", re.I)


class _Text(HTMLParser):
    SKIP = {"script", "style", "figure", "blockquote", "iframe"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.depth = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if not self.depth:
            self.parts.append(data)


def plain_text(html):
    if not html:
        return ""
    p = _Text()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass
    t = unescape(" ".join(p.parts))
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^[•·\-–—\*\s]+", "", t)
    t = re.sub(r"^[A-Z][A-Z .,/&'-]{2,40}:\s+", "", t)  # ALL-CAPS dateline
    return t


def make_snippet(text, title=""):
    if not text or text.lower().startswith(title.lower()[:40]) and len(text) < len(title) + 20:
        return ""
    if len(text) <= SNIPPET_MAX:
        return text
    cut = text[:SNIPPET_MAX].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut + "…"


def clean_url(u):
    u = (u or "").strip()
    try:
        p = urllib.parse.urlsplit(u)
    except Exception:
        return ""
    if p.scheme not in ("http", "https") or not p.netloc:
        return ""
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if not TRACK.match(k)]
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, urllib.parse.urlencode(q), ""))


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def classify(title, body, default=None, general=False):
    text = f"{title} {body[:CLASSIFY_CHARS]}"
    cats = [c for c in CAT_ORDER if CAT_RE[c].search(text)]
    # title hits outrank body hits for the primary category
    tcats = [c for c in CAT_ORDER if CAT_RE[c].search(title)]
    if default and default not in cats:
        cats.append(default)
    if not cats:
        if general:
            return "affairs", ["affairs"]
        return None, []
    primary = tcats[0] if tcats else (default if default in cats else cats[0])
    cats = [primary] + [c for c in cats if c != primary]
    return primary, cats


def _local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child_text(el, *names):
    for c in el:
        if _local(c.tag) in names and (c.text or "").strip():
            return c.text.strip()
    return ""


def parse_feed(data, source, default_cat=None, lang="en", region="world", general=False):
    root = ET.fromstring(data)
    out = []
    for el in root.iter():
        n = _local(el.tag)
        if n not in ("item", "entry"):
            continue
        title = plain_text(_child_text(el, "title"))
        link = ""
        if n == "item":
            link = _child_text(el, "link") or _child_text(el, "guid")
        else:
            for c in el:
                if _local(c.tag) == "link":
                    if c.get("rel", "alternate") == "alternate" and c.get("href"):
                        link = c.get("href")
                        break
        url = clean_url(link)
        if not title or not url:
            continue
        raw = _child_text(el, "description", "summary", "encoded", "content")
        body = plain_text(raw)
        dt = parse_date(_child_text(el, "pubDate", "published", "updated", "date"))
        if not dt:
            continue
        cat, cats = classify(title, body, default_cat, general)
        if not cat:
            continue
        out.append({
            "id": url, "title": title[:220], "url": url, "source": source,
            "published": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "summary": make_snippet(body, title), "cat": cat, "cats": cats, "lang": lang,
            "region": "pk" if region == "pk" or PK_RE.search(title) else "world",
        })
    return out


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.5",
        "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=25) as r:
        data = r.read(5 * 1024 * 1024 + 1)
        if len(data) > 5 * 1024 * 1024:
            raise ValueError("feed too large")
        if r.headers.get("Content-Encoding", "").lower() == "gzip" or data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
    return data


def fetch_retry(url):
    try:
        return fetch(url)
    except Exception:
        time.sleep(3)
        return fetch(url)


def load_existing():
    try:
        d = json.loads(OUT.read_text(encoding="utf-8"))
        return d.get("items", [])
    except Exception:
        return []


def merge(old, new, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    by_url = {}
    for it in old + new:  # new overrides old
        by_url[it["url"]] = it
    items = [i for i in by_url.values() if parse_date(i["published"]) and parse_date(i["published"]) >= cutoff]
    items.sort(key=lambda i: i["published"], reverse=True)
    seen, res, per = set(), [], {}
    for i in items:
        k = re.sub(r"\W+", "", i["title"].lower())
        if k in seen:
            continue
        seen.add(k)
        kk = (i["cat"], i.get("region", "world"))
        if per.get(kk, 0) >= MAX_PER_CAT:  # busy topics (cricket) must not crowd out others
            continue
        per[kk] = per.get(kk, 0) + 1
        res.append(i)
    return res[:MAX_ITEMS]



def run_feed(f):
    try:
        items = parse_feed(fetch_retry(f["url"]), f["name"], f.get("default_cat"),
                           f.get("lang", "en"), f.get("region", "world"), f.get("general", False))
        return items, {"name": f["name"], "url": f["url"], "ok": True, "items": len(items), "error": ""}
    except Exception as e:
        return [], {"name": f["name"], "url": f["url"], "ok": False, "items": 0, "error": str(e)[:120]}


def main():
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(run_feed, FEEDS))  # keeps FEEDS order
    new, status = [], []
    for items, st in results:
        new += items
        status.append(st)
        tag = "ok  " if st["ok"] else "FAIL"
        print(f"{tag} {st['name']:<22} {st['items']:>3}  {st['url']}" + ("" if st["ok"] else f"  ({st['error']})"))
    if not any(s["ok"] for s in status):
        print("all feeds failed; keeping old news.json")
        sys.exit(1)
    items = merge(load_existing(), new)
    doc = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "count": len(items), "items": items, "feeds": status}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUT)
    print(f"wrote {len(items)} items")


if __name__ == "__main__":
    main()
