"""audit_market.py — офлайн-пересчёт чисел docs/07 §4 и README (рынок).

Только чтение data/*.json; сеть не используется.
Запуск: python tools/audit_market.py  -> печать + audit_parts/audit_market.json
"""
import json, os, re, random, statistics as st
from collections import Counter, defaultdict
from datetime import date

random.seed(20260930)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
OUT = {}


def load(n):
    return json.load(open(os.path.join(D, n), encoding="utf-8"))


def boot_med(v, n=4000):
    b = sorted(st.median([random.choice(v) for _ in v]) for _ in range(n))
    return b[int(.025 * n)], st.median(v), b[int(.975 * n)]


def wilson(k, n, z=1.96):
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** .5) / d
    return (c - h) * 100, (c + h) * 100


BANDS = [("<10K", 0, 10e3), ("10-50K", 10e3, 50e3), ("50-150K", 50e3, 150e3),
         ("150-500K", 150e3, 500e3), ("500K-1.5M", 500e3, 1.5e6), ("1.5M+", 1.5e6, 1e13)]
BANDS5 = [("<10K", 0, 10e3), ("10-50K", 10e3, 50e3), ("50-150K", 50e3, 150e3),
          ("150-500K", 150e3, 500e3), ("500K+", 500e3, 1e13)]


def bands(vals, B=BANDS5):
    n = len(vals)
    r = {}
    for nm, lo, hi in B:
        k = sum(lo <= v < hi for v in vals)
        r[nm] = (k, round(k / n * 100, 1) if n else None,
                 tuple(round(x, 1) for x in wilson(k, n)))
    return r


def is_bot(h):
    return h.lower().endswith("bot")


md = load("market_deep.json")
ms = load("market_size.json")

# ------------------------------------------------------------------ срез B
print("=" * 90)
print("СРЕЗ B: telegram.menu «Технологии, IT»")
menu = md["telegram_menu_tech"]
mv = [x["subs"] for x in menu]
print(f"n={len(menu)} сумма={sum(mv):,.0f} медиана={st.median(mv):,.0f} "
      f"min={min(mv):,.0f} max={max(mv):,.0f}")
print("полосы:", bands(mv, BANDS))
top_sum_wo = sum(sorted(mv)[:-1])
print(f"сумма без @hitvpn_news (VPN, 4.45M): {sum(mv)-4447192:,.0f}")
OUT["menu"] = {"n": len(mv), "sum": sum(mv), "median": st.median(mv),
               "bands": bands(mv, BANDS)}
# чем может быть 43.4M? — подбор
s_sorted = sorted(mv, reverse=True)
cum = 0
for i, v in enumerate(s_sorted, 1):
    cum += v
    if abs(cum - 43.4e6) < 0.6e6:
        print(f"  кумулятивная сумма топ-{i} = {cum:,.0f} (≈43.4M)")

# ------------------------------------------------------------------ срез C
print("=" * 90)
print("СРЕЗ C: tgme.app/search, 9 запросов")
srch = md["tgme_search"]
recs = [(k, x["handle"], x["subs"]) for k, v in srch.items() for x in v]
print("записей:", len(recs), "по запросам:", {k: len(v) for k, v in srch.items()})
allh = {}
for k, h, s in recs:
    allh[h] = max(allh.get(h, 0), s)
print("уникальных (регистр учитывается):", len(allh))
low = defaultdict(list)
for h in allh:
    low[h.lower()].append(h)
dup_case = {k: v for k, v in low.items() if len(v) > 1}
print("уникальных без учёта регистра:", len(low), "дубли по регистру:", dup_case)
allh_ci = {}
for h, s in allh.items():
    allh_ci[h.lower()] = max(allh_ci.get(h.lower(), 0), s)
vals = list(allh_ci.values())
lo, med, hi = boot_med(vals)
print(f"медиана (CI-уник, n={len(vals)}): {med:,.0f} [{lo:,.0f}, {hi:,.0f}]  сумма={sum(vals):,.0f}")
print("полосы:", bands(vals))
OUT["search_all"] = {"records": len(recs), "uniq_cs": len(allh), "uniq_ci": len(vals),
                     "median": [lo, med, hi], "sum": sum(vals), "bands": bands(vals)}

# воспроизведение «103 канала, медиана 69K» (баг: считаются только top-12 каждого запроса)
top12 = {}
for k, v in srch.items():
    for x in v[:12]:
        top12[x["handle"]] = max(top12.get(x["handle"], 0), x["subs"])
t12 = sorted(top12.values())
print(f"\nВОСПРОИЗВЕДЕНИЕ README: top-12 × 9 запросов → {len(t12)} уник., "
      f"медиана(upper) {t12[len(t12)//2]:,.0f}, сумма {sum(t12):,.0f}")
b12 = bands(t12)
print("  полосы top-12:", b12)
OUT["readme_repro"] = {"n": len(t12), "median_upper": t12[len(t12) // 2],
                       "sum": sum(t12), "bands": b12}

# боты
bots = [h for h in allh_ci if is_bot(h)]
nb = [s for h, s in allh_ci.items() if not is_bot(h)]
lo, med, hi = boot_med(nb)
print(f"\nботов по имени (*bot): {len(bots)} ; без ботов n={len(nb)} медиана {med:,.0f} [{lo:,.0f}, {hi:,.0f}]")
print("  полосы без ботов:", bands(nb))
OUT["search_nobots"] = {"n_bots": len(bots), "n": len(nb), "median": [lo, med, hi],
                        "bands": bands(nb)}

# перекрытие запросов
sets = {k: {x["handle"].lower() for x in v} for k, v in srch.items()}
freq = Counter(h for s in sets.values() for h in s)
print("\nв скольких запросах встречается канал:", sorted(Counter(freq.values()).items()))
ks = list(sets)
print("попарные пересечения (Jaccard):")
for i in range(len(ks)):
    for j in range(i + 1, len(ks)):
        a, b = sets[ks[i]], sets[ks[j]]
        if a & b:
            print(f"   {ks[i]:34s} × {ks[j]:34s} ∩={len(a & b):3d}  J={len(a & b)/len(a | b):.2f}")

# минимумы/максимумы по запросу — признак обрезки выдачи
print("\nпо запросу: n, min, медиана, max (признак ранжирования/обрезки):")
for k, v in srch.items():
    s = [x["subs"] for x in v]
    print(f"   {k:34s} n={len(s):3d} min={min(s):>9,.0f} med={st.median(s):>9,.0f} max={max(s):>11,.0f}")

# подозрительные значения подписчиков (год, круглые)
sus = [(h, s) for h, s in allh_ci.items() if 1990 <= s <= 2030 or s == 1000]
print("\nподозрительные subs (≈год/1000 — вероятно число из названия):", sus)

# сверка subs поиска с t.me (market_size) и telegram.menu
msc = {h.lower(): v["subs"] for h, v in ms["channels"].items() if v["subs"]}
mnu = {x["handle"].lower(): x["subs"] for x in menu}
cmp_ = []
for h, s in allh_ci.items():
    ref = msc.get(h) or mnu.get(h)
    if ref:
        cmp_.append((h, s, ref, s / ref))
print("\nсверка subs поиска с t.me/menu:", len(cmp_), "совпадений;",
      "отношения:", sorted(round(c[3], 2) for c in cmp_))
OUT["search_vs_ref"] = cmp_

# ------------------------------------------------------------------ 22 канала выборки в menu
S22 = [k for k in load("subs.json") if not k.startswith("_")]
subs22 = {k: v for k, v in load("subs.json").items() if not k.startswith("_")}
inm = [h for h in S22 if h.lower() in mnu]
ins = [h for h in S22 if h.lower() in allh_ci]
inms = [h for h in S22 if h.lower() in msc]
print("\n22 канала выборки: в menu-58:", len(inm), inm)
print("   доля подписчиков menu-58, приходящаяся на них:",
      round(sum(mnu[h.lower()] for h in inm) / sum(mv) * 100, 1), "%")
print("   в tgme-поиске:", len(ins), ins)
print("   в market_size (TG.ME 18 категорий):", len(inms), inms)
OUT["sample22"] = {"in_menu": inm, "in_search": ins, "in_tgme_cats": inms}

# ------------------------------------------------------------------ market_size: живость
print("=" * 90)
print("МЁРТВЫЕ КАНАЛЫ: market_size.json (снимок 2026-09-29/30)")
ch = ms["channels"]
REF = date(2026, 9, 29)


def age(nw):
    y, m, d_ = map(int, nw.split("-"))
    return (REF - date(y, m, d_)).days


n_all = len(ch)
has_sub = [h for h, v in ch.items() if v["subs"]]
has_dt = [h for h, v in ch.items() if v.get("newest")]
print(f"всего {n_all}, с subs {len(has_sub)}, с датой {len(has_dt)}, без даты {n_all-len(has_dt)}")
nodate = [h for h, v in ch.items() if not v.get("newest")]
nd_sub = [h for h in nodate if ch[h]["subs"]]
print("  без даты, но с subs:", len(nd_sub), nd_sub[:15])
future = [(h, ch[h]["newest"]) for h in has_dt if age(ch[h]["newest"]) < 0]
print("  дата в будущем:", future)
for thr in (30, 90, 180, 365):
    k = sum(age(ch[h]["newest"]) > thr for h in has_dt)
    print(f"  последний пост старше {thr:3d} дн: {k}/{len(has_dt)} = {k/len(has_dt)*100:.1f}% "
          f"CI{tuple(round(x,1) for x in wilson(k, len(has_dt)))}; "
          f"если все без даты мертвы: {(k+n_all-len(has_dt))/n_all*100:.1f}%; если живы: {k/n_all*100:.1f}%")
OUT["dead"] = {}
for cat in ms["by_category"]:
    hs = [h for h in ms["by_category"][cat] if ch[h].get("newest")]
    k = sum(age(ch[h]["newest"]) > 90 for h in hs)
    OUT["dead"][cat] = (k, len(hs), len(ms["by_category"][cat]))
print("  по категориям (>90 дн / с датой / всего):", OUT["dead"])
tech = ms["by_category"]["tech"]
tt = sorted(((ch[h]["subs"] or 0, h, ch[h]["newest"]) for h in tech), reverse=True)
print("\nTG.ME tech (55): топ-20:")
for s, h, nw in tt[:20]:
    print(f"   @{h:28s} {s:>12,.0f} {nw}")
print("  whackdoor в market_size:", ch.get("whackdoor"))
# menu ∩ TG.ME
print("  menu-58 ∩ market_size (все категории):",
      len([h for h in mnu if h in msc]), "; ∩ tech:",
      len([h for h in mnu if h in {x.lower() for x in tech}]))
print("  menu-58 ∩ search:", len([h for h in mnu if h in allh_ci]))
print("  search ∩ market_size:", len([h for h in allh_ci if h in msc]))

# posts_on_page == 0 при наличии subs — пустые/закрытые превью
zero = [h for h, v in ch.items() if v["subs"] and v.get("posts_on_page", 0) == 0]
print("  subs есть, постов на странице 0:", len(zero))

# ------------------------------------------------------------------ portal-tg
print("=" * 90)
pv = md["portal_tg_verticals"]
print("portal-tg:", [(x["name"], x["count"]) for x in pv])
json.dump(OUT, open(os.path.join(ROOT, "audit_parts", "audit_market.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1, default=str)
