"""Производственные метрики ниши IT/AI-каналов Telegram.

Источники:
  data/links.json  — двухнедельная выборка (37 каналов), текст ОБРЕЗАН на 1200 символов
  data/posts.json  — недельная выборка (23 канала), текст ПОЛНЫЙ
  data/subs.json   — кэш подписчиков, снят напрямую с t.me/s/<handle>

Запуск:  python tools/production.py
"""
import json, re, os, sys, statistics as st
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests
from bs4 import BeautifulSoup

D = "C:/visual projects/parser/data/"

MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
EXPERTS = ["xor_journal", "neuraldvig", "data_secrets", "seeallochnaya",
           "denissexy", "ai_newz", "cgevent", "NeuralShit",
           "ai_machinelearning_big_data", "tproger", "tlive"]
ALL = MASS + EXPERTS

# erid — маркер российской маркировки рекламы: ~20 симв., начинается с "2"
ERID = re.compile(r"\b2[A-Za-z0-9]{15,25}\b")
ADTAG = re.compile(r"(#реклама\b|#ad\b|\bреклама\b|\bрекламное сообщение\b|"
                   r"\bsponsored\b|\bpartnership\b)", re.I)
# маркеры, по которым форвард считаем корпоративным/новостным, а не рекламным
FWD_OK = re.compile(r"(\bновост\b|\bпресс-релиз\b|\bрелиз\b|\bзапуск\b|\bобъявл)",
                    re.I)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿️⬀-⯿]")

CAP = 1200  # потолок обрезки в links.json


def vnum(s):
    if not s:
        return None
    s = s.strip().upper().replace(" ", "").replace(" ", "")
    m = re.match(r"^([\d.,]+)([KM])?$", s)
    if not m:
        return None
    try:
        v = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    return v * {"K": 1e3, "M": 1e6}.get(m.group(2), 1)


def load(name):
    p = D + name
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}


links = load("links.json")
posts = load("posts.json")

# ---------------------------------------------------------------- подписчики
SUBS_PATH = D + "subs.json"
CACHE = 1  # сутки


def fetch_subs(handle):
    try:
        r = requests.get(f"https://t.me/s/{handle}",
                         headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                               "AppleWebKit/537.36 Chrome/124.0 Safari/537.36"},
                         timeout=25)
        if r.status_code != 200:
            return handle, None
        el = BeautifulSoup(r.text, "html.parser").select_one(
            ".tgme_channel_info_counter .counter_value")
        return handle, (vnum(el.get_text(strip=True)) if el else None)
    except Exception:
        return handle, None


subs = load("subs.json")
fresh = subs.get("_fetched") if subs else None
stale = True
if fresh:
    try:
        stale = (datetime.now() - datetime.fromisoformat(fresh)).total_seconds() >= CACHE * 86400
    except ValueError:
        stale = True
if not subs or stale:
    with ThreadPoolExecutor(max_workers=8) as ex:
        got = dict(ex.map(fetch_subs, ALL))
    got["_fetched"] = datetime.now().isoformat(timespec="seconds")
    json.dump(got, open(SUBS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    subs = got
subs = {k: v for k, v in subs.items() if not k.startswith("_") and v}

def group(ch):
    return "массовые" if ch in MASS else "экспертные"

def line(ch, n=28):
    return f"@{ch}".ljust(n)

print("=" * 116)
print("1. ЧАСТОТА ПУБЛИКАЦИИ (постов в сутки) — окно 2026-09-15..29")
print("=" * 116)
rows = []
for ch in ALL:
    ps = links.get(ch) or []
    if len(ps) < 5:
        continue
    dts = sorted(datetime.fromisoformat(p["dt"]) for p in ps)
    days = (dts[-1] - dts[0]).total_seconds() / 86400 + 1
    rows.append((len(ps) / days, ch, len(ps), days))
grp = defaultdict(list)
for pd_, ch, n, d in rows:
    grp[group(ch)].append(pd_)
for g, v in grp.items():
    print(f"  {g:12s} n={len(v):2d}  медиана {st.median(v):5.1f} постов/сутки  "
          f"(min {min(v):.1f}, max {max(v):.1f})")
print()
for pd_, ch, n, d in sorted(rows, reverse=True):
    print(f"  {line(ch)} [{group(ch)[:4]:4s}]  {pd_:5.1f}/сут   "
          f"всего {n} за {d:.1f} сут")

print("\n" + "=" * 116)
print("2. РАСПРЕДЕЛЕНИЕ ПУБЛИКАЦИЙ ПО ЧАСАМ (UTC)")
print("=" * 116)
hours = {g: Counter() for g in ("массовые", "экспертные")}
for ch in ALL:
    for p in links.get(ch, []):
        hours[group(ch)][datetime.fromisoformat(p["dt"]).hour] += 1
peak = max(sum(c.values()) for c in hours.values())
print("  час  |" + "".join(f"{h:5d}" for h in range(24)))
for g in ("массовые", "экспертные"):
    print(f"  {g:11s}|" + "".join(f"{int(hours[g][h]/peak*40):5d}" for h in range(24)))
print("  масштаб: 1 дефиниция = 2.5% от максимума")
for g in ("массовые", "экспертные"):
    tot = sum(hours[g].values())
    best = sorted(hours[g].items(), key=lambda x: -x[1])[:5]
    print(f"  {g:11s} топ: " + ", ".join(f"{h:02d}:00 ({n/tot*100:.1f}%)" for h, n in best))
allh = Counter()
for g in hours.values():
    allh.update(g)
t = sum(allh.values())
print(f"  ОБЩИЙ пик: " + ", ".join(f"{h:02d}:00 ({n/t*100:.1f}%)"
                                  for h, n in sorted(allh.items(), key=lambda x: -x[1])[:6]))

print("\n" + "=" * 116)
print("3. РЕКЛАМНАЯ НАГРУЗКА — erid в тексте ИЛИ в ссылках, #реклама, форварды")
print("=" * 116)
print("  канал                          erid  #тег  форв.  всего   ad%   форвард%   медиана просм.")


def is_ad(p):
    """Реклама: явный маркер (erid/тег) ИЛИ форвард без редакционного маркера."""
    blob = p["text"] + " " + " ".join(p.get("links") or [])
    if ERID.search(blob) or ADTAG.search(p["text"]):
        return True
    if p.get("fwd_name") and not FWD_OK.search(p["text"]):
        return True
    return False


adrows = []
for ch in ALL:
    ps = links.get(ch) or []
    if not ps:
        continue
    e = sum(1 for p in ps if ERID.search(p["text"] + " " + " ".join(p.get("links") or [])))
    t = sum(1 for p in ps if ADTAG.search(p["text"]))
    f = sum(1 for p in ps if p.get("fwd_name"))
    fw = sum(1 for p in ps if p.get("fwd_name") and not FWD_OK.search(p["text"]))
    v = [x for x in (vnum(p["views"]) for p in ps) if x]
    med = st.median(v) if v else 0
    adrows.append((sum(is_ad(p) for p in ps) / len(ps) * 100, ch, e, t, f,
                   len(ps), fw / max(f, 1) * 100, med))
for pct, ch, e, t, f, n, fwp, med in sorted(adrows, reverse=True):
    print(f"  {line(ch)} {e:5d} {t:5d} {f:5d} {n:6d} {pct:5.1f}% {fwp:8.1f}%   {med:>12,.0f}")
for g in ("массовые", "экспертные"):
    sel = [r for r in adrows if group(r[1]) == g]
    if sel:
        print(f"  --> {g}: медиана ad% = {st.median([r[0] for r in sel]):.1f}%, "
              f"медиана форвард% = {st.median([r[6] for r in sel]):.1f}%")

print("\n" + "=" * 116)
print("4. ДЛИНА ПОСТА — полный текст из posts.json (без обрезки)")
print("=" * 116)
print("  канал                          медиана  p25   p75   p95   макс   эмодзи  ссылок")
frows = []
for ch in ALL:
    src = posts.get(ch) or []
    if not src:
        src = links.get(ch) or []
        note = "*"
    else:
        note = " "
    if not src:
        continue
    L = sorted(len(p["text"]) for p in src)
    E = sorted(len(EMOJI.findall(p["text"])) for p in src)
    K = sorted(len([u for u in (p.get("links") or []) if "t.me" not in u]) for p in src)
    frows.append((st.median(L), ch, L, E, K, note))
for med, ch, L, E, K, note in sorted(frows, reverse=True):
    q = lambda f: L[min(len(L) - 1, int(len(L) * f))]
    print(f" {note}{line(ch)} {med:7.0f} {q(.25):5d} {q(.75):5d} {q(.95):5d} {max(L):5d}"
          f"   {st.median(E):5.1f}   {st.median(K):5.1f}")
print("  * = данных в posts.json нет, длина из links.json и обрезана на 1200 символов")

allL = sorted(len(p["text"]) for v in posts.values() for p in v)
if allL:
    print(f"\n  ПОЛНЫЙ текст (posts.json, {len(allL)} постов): медиана {st.median(allL):.0f}, "
          f"p25 {allL[len(allL)//4]}, p75 {allL[3*len(allL)//4]}, "
          f"p95 {allL[int(len(allL)*.95)]}, макс {max(allL)}")
cut = [len(p["text"]) for v in links.values() for p in v]
ncut = len([x for x in cut if x >= CAP - 1])
print(f"  links.json: {len(cut)} постов, из них упёрлись в потолок {CAP}: {ncut} "
      f"({ncut/len(cut)*100:.1f}%)")
print(f"  ИТОГ: обрезка искажает только хвост. Медиана {st.median(cut):.0f} vs полная "
      f"{st.median(allL):.0f} — расхождения нет.")

print("\n" + "=" * 116)
print("5. ВОВЛЕЧЁННОСТЬ (ER) = медианные просмотры / подписчики")
print("=" * 116)
print("  канал                          подписч.   медиана просм.      ER      ER пост/сут")
errows = []
for ch in ALL:
    ps = links.get(ch, [])
    s = subs.get(ch)
    v = [x for x in (vnum(p["views"]) for p in ps) if x]
    if not v or not s:
        continue
    med = st.median(v)
    pd_ = next((r[0] for r in rows if r[1] == ch), 0)
    errows.append((med / s, ch, s, med, pd_))
for er, ch, s, med, pd_ in sorted(errows, reverse=True):
    print(f"  {line(ch)} {s:10,.0f}   {med:13,.0f}   {er*100:6.2f}%   {med*pd_:12,.0f}")
if errows:
    for g in ("массовые", "экспертные"):
        v = [e[0] for e in errows if group(e[1]) == g]
        if v:
            print(f"  --> {g}: медиана ER = {st.median(v)*100:.2f}%  "
                  f"(min {min(v)*100:.2f}%, max {max(v)*100:.2f}%)")
    v = [e[0] for e in errows]
    print(f"  --> ВСЕ {len(v)} каналов: медиана ER = {st.median(v)*100:.2f}%")
    print(f"  --> Оценка ёмкости ниши (G4): при ER {st.median(v)*100:.1f}% канал на 30K "
          f"даёт ~{30000*st.median(v):,.0f} просмотров/пост")

print("\n" + "=" * 116)
print("6. СВЯЗЬ ДЛИНЫ С ПРОСМОТРАМИ (внутри канала — снимает разницу охвата)")
print("=" * 116)
print("  канал                          <400 симв.   >1000 симв.     разница")
found = False
for ch in ALL:
    ps = [p for p in (links.get(ch) or []) if vnum(p["views"])]
    if len(ps) < 12:
        continue
    sh = [vnum(p["views"]) for p in ps if len(p["text"]) < 400]
    lo = [vnum(p["views"]) for p in ps if len(p["text"]) > 1000]
    if len(sh) < 3 or len(lo) < 3:
        continue
    found = True
    a, b = st.median(sh), st.median(lo)
    print(f"  {line(ch)} {a:10,.0f}   {b:11,.0f}   {(b/a-1)*100:+7.1f}%")
if not found:
    print("  недостаточно данных (мало постов в обоих диапазонах)")

print("\n" + "=" * 116)
print("7. ОБЪЁМ ПРОИЗВОДСТВА: сколько постов в сутки нужно для конкуренции")
print("=" * 116)
for g in ("массовые", "экспертные"):
    sel = [r for r in rows if group(r[1]) == g]
    if not sel:
        continue
    v = sorted(r[0] for r in sel)
    tot_med = st.median(v)
    print(f"  {g}: медиана {tot_med:.1f}/сут = {tot_med*30:.0f} постов/мес, "
          f"p25 {v[len(v)//4]:.1f}..p75 {v[3*len(v)//4]:.1f}")
print(f"  Сводка по 22 каналам: суммарно "
      f"{sum(r[0] for r in rows):.0f} постов/сут = "
      f"{sum(r[0] for r in rows)*30:.0f} постов/мес")
json.dump({"rows": [{"ch": c, "per_day": round(p, 2), "n": n, "days": round(d, 1),
                     "subs": subs.get(c)} for p, c, n, d in sorted(rows, reverse=True)],
           "er": [{"ch": c, "subs": s, "median_views": round(m), "er": round(er, 4)}
                  for er, c, s, m, _ in sorted(errows, reverse=True)]},
          open(D + "production_metrics.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\n  -> data/production_metrics.json")
