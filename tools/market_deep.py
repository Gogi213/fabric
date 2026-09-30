import os
import requests, re, json, sys, time
from concurrent.futures import ThreadPoolExecutor
from bs4 import BeautifulSoup

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"})
OUT = {}


def snum(s):
    s = re.sub(r"[\s\u00a0\u2009]", "", str(s)).upper().replace(",", ".")
    m = re.match(r"^([\d.]+)([KMB])?$", s)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return v * {"K": 1e3, "M": 1e6, "B": 1e9}.get(m.group(2), 1)


# ---------- 1. telegram.menu — реальные медиа-каналы ниши ----------
RX_MENU = re.compile(r"@([A-Za-z0-9_]{3,})\s*•\s*([\d\s\u00a0]+)")
try:
    r = S.get("https://telegram.menu/channels/tech", timeout=30)
    s = BeautifulSoup(r.text, "html.parser")
    t = re.sub(r"<!--.*?-->", " ", s.get_text("\n", strip=True))
    items = []
    for m in RX_MENU.finditer(t):
        v = snum(m.group(2))
        if v:
            items.append({"handle": m.group(1), "subs": v})
    seen, uniq = set(), []
    for it in items:
        if it["handle"] not in seen:
            seen.add(it["handle"])
            uniq.append(it)
    uniq.sort(key=lambda z: -z["subs"])
    OUT["telegram_menu_tech"] = uniq
    print("telegram.menu/channels/tech: %d каналов" % len(uniq), file=sys.stderr)
except Exception as e:
    print("menu err", e, file=sys.stderr)

# ---------- 2. tgme keyword search — середина рынка ----------
KEYS = ["нейросети", "искусственный интеллект", "ChatGPT", "IT новости",
        "технологии", "программирование", "нейросети для бизнеса",
        "искусственный интеллект новости", "промпты"]
RX_SEARCH = re.compile(r"@\s*([A-Za-z0-9_]{3,})[^@]{0,40}?([\d.,]+\s*[KM]?)\b", re.I)
search = {}
for k in KEYS:
    try:
        r = S.get("https://tgme.app/search?q=" + requests.utils.quote(k), timeout=30)
        t = re.sub(r"<!--.*?-->", " ", BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True))
        got = []
        for m in RX_SEARCH.finditer(t):
            v = snum(m.group(2))
            if v and v >= 1000:
                got.append({"handle": m.group(1), "subs": v})
        seen, uniq = set(), []
        for g in got:
            if g["handle"] not in seen:
                seen.add(g["handle"])
                uniq.append(g)
        uniq.sort(key=lambda z: -z["subs"])
        search[k] = uniq
        print("search %-28s %d каналов" % ('"%s"' % k, len(uniq)), file=sys.stderr)
    except Exception as e:
        print("search err", k, e, file=sys.stderr)
    time.sleep(0.4)
OUT["tgme_search"] = search

# ---------- 3. portal-tg: размеры вертикалей ----------
try:
    r = S.get("https://portal-tg.online/", timeout=30)
    t = re.sub(r"<!--.*?-->", " ", BeautifulSoup(r.text, "html.parser").get_text("\n", strip=True))
    m = re.findall(r"([А-ЯЁ][^\n]{2,40})\n(\d{1,4})", t)
    vs, seenv = [], set()
    for a, b in m:
        a, b = a.strip(), int(b)
        if a not in seenv:
            seenv.add(a)
            vs.append({"name": a, "count": b})
    OUT["portal_tg_verticals"] = vs
    print("portal-tg вертикалей (уник.): %d" % len(vs), file=sys.stderr)
except Exception as e:
    print("portal err", e, file=sys.stderr)

# ---------- 4. рекламная экономика ниши: креативы и просмотры ----------
RX_AD = re.compile(r"@([A-Za-z0-9_]{3,})[^@]{0,40}?([\d\s\u00a0.,]+)\s*creatives?", re.I)
ads = {}
for cat in ["tech", "news", "business", "education", "finance", "jobs", "health"]:
    try:
        r = S.get(f"https://tgme.app/c/{cat}", timeout=30)
        t = re.sub(r"<!--.*?-->", " ", BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True))
        i = t.find("Niche advertisers")
        blk = t[i:i + 1600] if i > 0 else ""
        rows, seen = [], set()
        for m in RX_AD.finditer(blk):
            h = m.group(1)
            if h in seen:
                continue
            seen.add(h)
            cr = snum(m.group(2)) or 0
            tail = blk[m.end():m.end() + 40]
            mv = re.match(r"\s*([\d\s\u00a0.,]+?)\s*(views|impressions)", tail, re.I)
            rows.append({"advertiser": h, "creatives": cr,
                         "views": snum(mv.group(1)) if mv else None})
        ads[cat] = rows
        print("ads %-12s %d рекламодателей" % (cat, len(rows)), file=sys.stderr)
    except Exception as e:
        print("ads err", cat, e, file=sys.stderr)
    time.sleep(0.3)
OUT["niche_ads"] = ads

# ---------- 5. рынок в целом ----------
try:
    r = S.get("https://tgme.app/ads", timeout=30)
    t = re.sub(r"<!--.*?-->", " ", BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True))
    OUT["market_totals"] = {}
    for key, pat in [("channels", r"([\d.,]+[KMB]?)\s*Channels in the catalogue"),
                     ("subs", r"([\d.,]+[KMB]?)\s*Subscriptions in total"),
                     ("views_per_day", r"([\d.,]+[KMB]?)\s*Views per day")]:
        m = re.search(pat, t, re.I)
        OUT["market_totals"][key] = snum(m.group(1)) if m else None
    print("итоги рынка:", OUT["market_totals"], file=sys.stderr)
except Exception as e:
    print("totals err", e, file=sys.stderr)

json.dump(OUT, open(os.path.join(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"), "market_deep.json"), "w",
                    encoding="utf-8"), ensure_ascii=False, indent=1)

# ================= ВЫВОД =================
print("\n" + "=" * 104)
print("A. РЕАЛЬНЫЕ МЕДИА-КАНАЛЫ НИШИ (telegram.menu, Технологии/IT)")
print("=" * 104)
for i, x in enumerate(OUT.get("telegram_menu_tech", [])[:35], 1):
    print(f"  {i:3d}. @{x['handle']:28s} {x['subs']:>11,.0f}")
mm = OUT.get("telegram_menu_tech", [])
if mm:
    s = [x["subs"] for x in mm]
    bands = [("10K–50K", 10e3, 50e3), ("50K–150K", 50e3, 150e3),
             ("150K–500K", 150e3, 500e3), ("500K–1.5M", 500e3, 1.5e6),
             ("1.5M+", 1.5e6, 1e12)]
    print("\n  распределение по размеру:")
    for nm, lo, hi in bands:
        n = len([v for v in s if lo <= v < hi])
        print(f"    {nm:12s} {n:4d} каналов")

print("\n" + "=" * 104)
print("B. СЕРЕДИНА РЫНКА ПО КЛЮЧЕВЫМ ЗАПРОСАМ (tgme search)")
print("=" * 104)
allh = {}
for k, v in search.items():
    print(f"\n  «{k}» — {len(v)} каналов")
    for x in v[:12]:
        print(f"     @{x['handle']:28s} {x['subs']:>10,.0f}")
        allh[x["handle"]] = max(allh.get(x["handle"], 0), x["subs"])
print(f"\n  уникальных каналов во всех запросах: {len(allh)}")
s = sorted(allh.values())
if s:
    print(f"  медиана {s[len(s)//2]:,.0f}   сумма {sum(s):,.0f}")
    print("  bands: " + ", ".join(
        f"{nm}={len([v for v in s if lo<=v<hi])}"
        for nm, lo, hi in [("<10K",0,10e3),("10-50K",10e3,50e3),("50-150K",50e3,150e3),
                           ("150-500K",150e3,500e3),("500K+",500e3,1e12)]))

print("\n" + "=" * 104)
print("C. РАЗМЕРЫ ВЕРТИКАЛЕЙ (portal-tg, число каналов в каталоге)")
print("=" * 104)
for v in sorted(OUT.get("portal_tg_verticals", []), key=lambda z: -z["count"])[:22]:
    print(f"  {v['name'][:40]:42s} {v['count']:5d}")

print("\n" + "=" * 104)
print("D. РЕКЛАМНАЯ ЭКОНОМИКА: кто рекламируется в нише")
print("=" * 104)
for cat, rows in ads.items():
    if not rows:
        continue
    print(f"\n  ниша {cat}:")
    for r_ in sorted(rows, key=lambda z: -(z["creatives"] or 0))[:8]:
        vps = (r_["views"] / r_["creatives"]) if r_["creatives"] and r_["views"] else None
        print(f"     @{r_['advertiser']:28s} креативов={r_['creatives']:>7,.0f} "
              f"просмотров={str(round(r_['views'])) if r_['views'] else '-':>12s}"
              + (f"  {vps:,.0f} просм./креатив" if vps else ""))
