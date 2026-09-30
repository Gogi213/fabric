import requests, json, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"})

CATS = ["tech", "news", "business", "education", "finance", "gaming", "crypto",
        "jobs", "health", "auto", "lifestyle", "shopping", "travel", "sports",
        "entertainment", "music", "gambling", "bots"]
RXH = re.compile(r'href="/([a-zA-Z0-9_]{3,})"')

cats = {}
allh = {}
for cat in CATS:
    hs = set()
    for u in (f"https://tgme.app/top/{cat}", f"https://tgme.app/c/{cat}"):
        try:
            r = S.get(u, timeout=30)
            if r.status_code != 200:
                continue
            for h in RXH.findall(r.text):
                if h.startswith(("api", "g", "c", "top", "new", "search", "ads",
                                 "wiki", "geo", "ton", "settings", "login", "ads")):
                    continue
                hs.add(h)
        except Exception as e:
            print("  !", cat, u, e, file=sys.stderr)
        time.sleep(0.2)
    cats[cat] = sorted(hs)
    for h in hs:
        allh.setdefault(h, []).append(cat)
    print("%-14s %d каналов (всего уникальных %d)" % (cat, len(hs), len(allh)), file=sys.stderr)

RXS = re.compile(r"([\d.,]+\s*[KM]?)\s*subscribers", re.I)


def snum(s):
    s = s.replace(" ", "").upper()
    m = re.match(r"^([\d.,]+)([KM])?$", s)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return v * {"K": 1e3, "M": 1e6}.get(m.group(2), 1)


def count(h):
    try:
        r = S.get(f"https://t.me/s/{h}", timeout=20)
        if r.status_code != 200:
            return h, None, 0
        s = BeautifulSoup(r.text, "html.parser")
        c = s.select_one(".tgme_channel_info_counter .counter_value")
        n = len(s.select("div.tgme_widget_message[data-post]"))
        dts = [x.get("datetime") for x in s.select("time[datetime]")]
        newest = max(dts)[:10] if dts else None
        return h, (snum(c.get_text(strip=True)) if c else None), n, newest
    except Exception:
        return h, None, 0, None


print("\nзамер подписчиков через t.me для %d каналов ..." % len(allh), file=sys.stderr)
res = {}
with ThreadPoolExecutor(max_workers=10) as ex:
    for h, v, n, newest in ex.map(count, allh):
        res[h] = {"subs": v, "posts_on_page": n, "newest": newest,
                  "cats": allh[h]}

alive = {h: v for h, v in res.items() if v["subs"]}
print("ответили: %d, с численностью: %d" % (len(res), len(alive)), file=sys.stderr)

json.dump({"by_category": cats, "channels": res},
          open("C:/visual projects/parser/data/market_size.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

print("\n" + "=" * 100)
print("РАЗМЕР РЫНКА ПО КАТЕГОРИЯМ")
print("=" * 100)
print("%-14s %8s %16s %14s %16s" % ("категория", "каналов", "сумма подп.", "медиана", "макс"))
for cat in CATS:
    v = [res[h]["subs"] for h in cats[cat] if res[h]["subs"]]
    if not v:
        continue
    v.sort()
    print("%-14s %8d %16s %14s %16s" % (cat, len(v), f"{sum(v):,.0f}",
                                        f"{v[len(v)//2]:,.0f}", f"{max(v):,.0f}"))

tech = sorted(((res[h]["subs"], h, res[h]["newest"]) for h in cats["tech"]
               if res[h]["subs"]), reverse=True)
print("\n" + "=" * 100)
print("TECH: топ-40 по подписчикам (дата последнего поста)")
print("=" * 100)
for i, (s, h, nw) in enumerate(tech[:40], 1):
    print(f"  {i:3d}. @{h:30s} {s:>12,.0f}   {nw}")

print("\n" + "=" * 100)
print("TECH: каналы 10K..300K — 'рабочая середина'")
print("=" * 100)
mid = [(s, h, res[h]["newest"]) for s, h, _ in tech if 10_000 <= s <= 300_000]
print("  количество:", len(mid))
for s, h, nw in mid[:30]:
    print(f"     @{h:30s} {s:>10,.0f}   {nw}")
