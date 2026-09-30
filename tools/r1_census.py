"""R1. Перепись каналов по каталогу telegram.menu (все страницы выбранных категорий).

Запуск:  python tools/r1_census.py [cat ...]   ->  data/r/census_menu.json (дописывается, можно прерывать)
По умолчанию: ai tech crypto economy business games marketing news education.
"""
import json, os, re, sys, time
import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "r", "census_menu.json")
CATS = sys.argv[1:] or ["ai", "tech", "crypto", "economy", "business", "games", "marketing", "news", "education"]
S = requests.Session()
S.headers["User-Agent"] = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
DELAY = 1.5


def snum(s):
    s = re.sub(r"[\s  ]", "", s)
    return int(s) if s.isdigit() else None


def page(cat, p):
    u = f"https://telegram.menu/channels/{cat}" + ("" if p == 1 else f"/page/{p}")
    for attempt in range(3):
        try:
            r = S.get(u, timeout=30)
            if r.status_code == 200:
                break
        except Exception:
            r = None
        time.sleep(5 * (attempt + 1))
    time.sleep(DELAY)
    if r is None or r.status_code != 200:
        return None, None
    soup = BeautifulSoup(r.text, "html.parser")
    t = soup.get_text(" ", strip=True)
    items = [(h, snum(v)) for h, v in re.findall(r"@([A-Za-z0-9_]{3,})\s*•\s*([\d\s  ]+)", t)]
    last = max([int(x) for x in re.findall(rf"/channels/{cat}/page/(\d+)", r.text)] or [1])
    return items, last


res = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
for cat in CATS:
    c = res.setdefault(cat, {"pages": {}, "last": None})
    p = 1
    while True:
        if str(p) in c["pages"]:
            p += 1
            if c["last"] and p > c["last"]:
                break
            continue
        items, last = page(cat, p)
        if items is None:
            print(f"  ! {cat} p{p} failed", file=sys.stderr)
            break
        c["pages"][str(p)] = items
        c["last"] = max(c["last"] or 1, last)
        json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  {cat} p{p}/{c['last']}: {len(items)} каналов, {items[:1]} … {items[-1:]}", file=sys.stderr)
        p += 1
        if p > c["last"] or not items:
            break
tot = {k: sum(len(v) for v in c["pages"].values()) for k, c in res.items()}
print("итого:", tot, file=sys.stderr)
