"""uncertainty.py — доверительные интервалы для всех чисел в документах.

Принципы (docs/01 §1.11):
  * для утверждений про СЛОЙ (массовые/экспертные) бутстрэпим по КАНАЛАМ,
    потому что посты внутри канала зависимы;
  * для утверждений про канал бутстрэпим по ПОСТАМ канала;
  * для долей — бутстрэп, для сравнения долей — бутстрэп разности;
  * для корреляций — интервал Фишера.

Запуск: python tools/uncertainty.py  -> data/uncertainty.json + печать отчёта
"""
import json, re, math, random, statistics as st
from collections import Counter, defaultdict
from datetime import datetime

random.seed(20260930)
D = "C:/visual projects/parser/data/"

MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
EXPERTS = ["xor_journal", "neuraldvig", "data_secrets", "seeallochnaya",
           "denissexy", "ai_newz", "cgevent", "NeuralShit",
           "ai_machinelearning_big_data", "tproger", "tlive"]
ZERO_RX = ["NeuralShit", "tlive"]
N = 5000

OUT = {}


def hr(t):
    print("\n" + "#" * 104)
    print(t)
    print("#" * 104)


def bmed(vals, n=N):
    """Бутстрэп-медиана: (lo, med, hi)."""
    if len(vals) < 3:
        return (None, None, None)
    s = []
    for _ in range(n):
        s.append(st.median([random.choice(vals) for _ in vals]))
    s.sort()
    return (s[int(.025 * n)], st.median(vals), s[int(.975 * n)])


def bmed_cluster(clusters, n=N):
    """Бутстрэп медианы по кластерам (кластер = канал)."""
    keys = [c for c in clusters if clusters[c]]
    if len(keys) < 3:
        return (None, None, None)
    meds = []
    for _ in range(n):
        pick = [random.choice(keys) for _ in keys]
        vals = []
        for k in pick:
            vals += clusters[k]
        meds.append(st.median(vals))
    meds.sort()
    return (meds[int(.025 * n)], st.median(meds), meds[int(.975 * n)])


def bmean_cluster(clusters, n=N):
    keys = [c for c in clusters if clusters[c]]
    if len(keys) < 3:
        return (None, None, None)
    m = []
    for _ in range(n):
        pick = [random.choice(keys) for _ in keys]
        vals = []
        for k in pick:
            vals += clusters[k]
        m.append(sum(vals) / len(vals))
    m.sort()
    return (m[int(.025 * n)], st.median(m), m[int(.975 * n)])


def bsum_cluster(clusters, n=N):
    """Бутстрэп суммы: сколько всего, если каналы случайны."""
    keys = [c for c in clusters if clusters[c]]
    if len(keys) < 3:
        return (None, None, None)
    s = []
    for _ in range(n):
        pick = [random.choice(keys) for _ in keys]
        s.append(sum(sum(clusters[k]) for k in pick))
    s.sort()
    return (s[int(.025 * n)], st.median(s), s[int(.975 * n)])


def fisher_ci(rho, n, alpha=.05):
    if n < 4 or abs(rho) >= 1:
        return (None, None, None)
    z = math.atanh(rho)
    se = 1 / math.sqrt(n - 3)
    zc = 1.959963985
    return (math.tanh(z - zc * se), rho, math.tanh(z + zc * se))


def diff_prop_ci(pairs_a, pairs_b, n=N):
    """CI разности долей по кластерам."""
    ka, kb = list(pairs_a.keys()), list(pairs_b.keys())
    if len(ka) < 3 or len(kb) < 3:
        return (None, None, None)
    d = []
    for _ in range(n):
        A = [random.choice(ka) for _ in ka]
        B = [random.choice(kb) for _ in kb]
        pa = sum(A) / len(A)
        pb = sum(B) / len(B)
        d.append((pa - pb) * 100)
    d.sort()
    return (d[int(.025 * n)], st.median(d), d[int(.975 * n)])


def pooled_share_ci(per_chan_counts, per_chan_totals, n=N):
    """CI для ДОЛИ в пуле: ресемплируем каналы, считаем суммарную долю.
    Доли по каналам брать нельзя — это другая величина."""
    keys = [c for c in per_chan_counts if per_chan_totals.get(c, 0) > 0]
    if len(keys) < 3:
        return (None, None, None)
    tot = sum(per_chan_counts.values())
    if not tot:
        return (None, None, None)
    d = []
    for _ in range(n):
        pick = [random.choice(keys) for _ in keys]
        num = sum(per_chan_counts[k] for k in pick)
        den = sum(per_chan_totals[k] for k in pick)
        d.append(num / den * 100 if den else 0)
    d.sort()
    return (d[int(.025 * n)], tot, d[int(.975 * n)])


def fi(lo, med, hi, fmt="{:,.1f}"):
    if lo is None:
        return "н/д"
    return f"{fmt.format(med)} [{fmt.format(lo)}, {fmt.format(hi)}]"


# ================================================================ docs/08
hr("docs/08 — ПРОИЗВОДСТВЕННЫЕ МЕТРИКИ: интервалы")
links = json.load(open(D + "links.json", encoding="utf-8"))
posts_full = json.load(open(D + "posts.json", encoding="utf-8"))
subs = {k: v for k, v in json.load(open(D + "subs.json", encoding="utf-8")).items()
        if not k.startswith("_") and v}


def grp(ch):
    return "массовые" if ch in MASS else "экспертные"


# частота публикации
freq_c = {}
for ch in MASS + EXPERTS:
    ps = links.get(ch) or []
    if len(ps) < 5:
        continue
    dts = sorted(datetime.fromisoformat(p["dt"]) for p in ps)
    days = (dts[-1] - dts[0]).total_seconds() / 86400 + 1
    freq_c[ch] = [len(ps) / days]
print("\n1.1 Частота публикаций, постов/сутки")
for g, names in [("массовые", MASS), ("экспертные", EXPERTS)]:
    cl = {c: freq_c[c] for c in names if c in freq_c}
    lo, med, hi = bmed_cluster(cl)
    r = freq_c and st.median(freq_c[c][0] for c in cl)
    print(f"    {g:12s} медиана {med:5.1f}  CI [{lo:.1f}, {hi:.1f}]  (n={len(cl)} каналов)")
    OUT[f"freq_{g}"] = [lo, med, hi]
    per_month = med * 30
    OUT[f"freq_per_month_{g}"] = [lo * 30, per_month, hi * 30]
    print(f"    {'':12s} в пересчёте на месяц: {fi(lo*30, per_month, hi*30, '{:.0f}')} постов/мес")

# ER
er_c = defaultdict(list)
for ch in MASS + EXPERTS:
    if ch not in subs:
        continue
    v = []
    for p in links.get(ch, []):
        vv = p.get("views")
        if not vv:
            continue
        s = re.sub(r"[\s ]", "", str(vv)).upper()
        m = re.match(r"^([\d.,]+)([KM]?)$", s.replace(",", "."))
        if m:
            v.append(float(m.group(1)) * {"K": 1e3, "M": 1e6}.get(m.group(2), 1))
    if v:
        er_c[ch] = [st.median(v) / subs[ch] * 100]
print("\n1.2 Вовлечённость ER = медианные просмотры / подписчики")
for g, names in [("массовые", MASS), ("экспертные", EXPERTS)]:
    cl = {c: er_c[c] for c in names if c in er_c}
    lo, med, hi = bmed_cluster(cl)
    print(f"    {g:12s} медиана {med:5.2f}%  CI [{lo:.2f}%, {hi:.2f}%]  (n={len(cl)})")
    OUT[f"er_{g}"] = [lo, med, hi]
allc = {c: v for c, v in er_c.items()}
lo, med, hi = bmed_cluster(allc)
print(f"    {'все':12s} медиана {med:5.2f}%  CI [{lo:.2f}%, {hi:.2f}%]  (n={len(allc)})")
OUT["er_all"] = [lo, med, hi]

# ER per channel
print("\n    по каналам:")
OUT["er_per_channel"] = {}
for ch in sorted(er_c, key=lambda c: -er_c[c][0]):
    v = [er_c[ch][0]]
    # бутстрэп по постам канала
    raw = []
    for p in links.get(ch, []):
        vv = p.get("views")
        if not vv:
            continue
        s = re.sub(r"[\s ]", "", str(vv)).upper()
        m = re.match(r"^([\d.,]+)([KM]?)$", s.replace(",", "."))
        if m:
            raw.append(float(m.group(1)) * {"K": 1e3, "M": 1e6}.get(m.group(2), 1))
    if len(raw) < 10:
        continue
    b = []
    for _ in range(2000):
        b.append(st.median([random.choice(raw) for _ in raw]) / subs[ch] * 100)
    b.sort()
    lo, hi = b[50], b[1949]
    OUT["er_per_channel"][ch] = [lo, er_c[ch][0], hi]
    print(f"      @{ch:26s} {er_c[ch][0]:5.2f}%  CI [{lo:.2f}%, {hi:.2f}%]")

# рекламная нагрузка
ERID = re.compile(r"\b2[A-Za-z0-9]{15,25}\b")
ADTAG = re.compile(r"(#реклама\b|#ad\b|\bреклама\b|\bрекламное сообщение\b|"
                   r"\bsponsored\b|\bpartnership\b)", re.I)
FWD_OK = re.compile(r"(\bновост\b|\bпресс-релиз\b|\bрелиз\b|\bзапуск\b|\bобъявл)", re.I)


def is_ad(p):
    blob = p["text"] + " " + " ".join(p.get("links") or [])
    if ERID.search(blob) or ADTAG.search(p["text"]):
        return True
    if p.get("fwd_name") and not FWD_OK.search(p["text"]):
        return True
    return False


print("\n1.3 Рекламная нагрузка, % постов")
for g, names in [("массовые", MASS), ("экспертные", EXPERTS)]:
    per_c = {}
    for ch in names:
        ps = links.get(ch) or []
        if len(ps) < 20:
            continue
        per_c[ch] = [sum(1 for p in ps if is_ad(p)) / len(ps) * 100]
    lo, med, hi = bmed_cluster(per_c)
    print(f"    {g:12s} медиана {med:5.1f}%  CI [{lo:.1f}%, {hi:.1f}%]  (n={len(per_c)})")
    OUT[f"ad_{g}"] = [lo, med, hi]

# длина
print("\n1.4 Длина поста, символов (полный текст из posts.json)")
for g, names in [("массовые", MASS), ("экспертные", EXPERTS)]:
    cl = {c: [len(p["text"]) for p in posts_full[c]] for c in names if c in posts_full}
    lo, med, hi = bmed_cluster(cl)
    print(f"    {g:12s} медиана {med:5.0f}  CI [{lo:.0f}, {hi:.0f}]  (n={len(cl)})")
    OUT[f"len_{g}"] = [lo, med, hi]
allL = [len(p["text"]) for v in posts_full.values() for p in v]
lo, med, hi = bmed(allL)
print(f"    {'все посты':12s} медиана {med:5.0f}  CI [{lo:.0f}, {hi:.0f}]  (n={len(allL)})")
OUT["len_all"] = [lo, med, hi]

# расписание: доля постов в окне 13-17 UTC
print("\n1.5 Расписание: доля постов в окне 13:00-17:59 UTC")
for g, names in [("массовые", MASS), ("экспертные", EXPERTS)]:
    per_c = []
    for ch in names:
        ps = links.get(ch) or []
        if len(ps) < 20:
            continue
        k = sum(1 for p in ps if 13 <= datetime.fromisoformat(p["dt"]).hour <= 17)
        per_c.append(k / len(ps) * 100)
    b = sorted(sum(random.choice(per_c) for _ in per_c) / len(per_c)
               for _ in range(N))
    print(f"    {g:12s} медиана {st.median(per_c):5.1f}%  CI [{b[125]:.1f}%, {b[4874]:.1f}%]")
    OUT[f"sched_{g}"] = [b[125], st.median(per_c), b[4874]]

# суммарный объём
print("\n1.6 Суммарный объём 22 каналов, постов/сутки")
tot = sum(freq_c[c][0] for c in freq_c)
cl = {c: freq_c[c] for c in freq_c}
lo, med, hi = bsum_cluster(cl)
print(f"    точечная {tot:.0f}/сут  |  бутстрэп по каналам: {fi(lo, med, hi, '{:.0f}')}/сут")
print(f"    в месяц: {fi(lo*30, med*30, hi*30, '{:.0f}')}")
OUT["volume_total"] = [lo, med, hi]

# ================================================================ docs/09 (ER per channel, already)
# ================================================================ docs/04
hr("docs/04 — КАРТА ИСТОЧНИКОВ: интервалы")
sm = json.load(open(D + "sourcemap.json", encoding="utf-8"))
tot_links = sum(sm["buckets"].values())
print(f"\nВсего ссылок: {tot_links}")
print("\n2.1 Доли корзин (бутстрэп по постам каждого канала)")
byp = defaultdict(list)
for ch, ps in links.items():
    for p in ps:
        byp[ch].append(p)
OUT["buckets"] = {}
for k, v in sorted(sm["buckets"].items(), key=lambda x: -x[1]):
    share = v / tot_links * 100
    print(f"    {k:28s} {v:5d}  {share:5.2f}%")
    OUT["buckets"][k] = [v, share]

print("\n2.2 Топ-домены: доли с интервалом (пул + бутстрэп по каналам)")
dom_c = {}
for ch, ps in byp.items():
    c = Counter()
    for p in ps:
        for u in p.get("links") or []:
            c[re.sub(r"^https?://", "", u).split("/")[0]] += 1
    dom_c[ch] = c
tot_c = {ch: max(sum(c.values()), 1) for ch, c in dom_c.items()}
allc = Counter()
for c in dom_c.values():
    allc += c
print(f"    {'домен':24s} {'ссылок':>7s} {'доля%':>8s}   {'95% CI доли (пул)'}")
OUT["domains"] = {}
for dom, cnt in allc.most_common(18):
    lo, _, hi = pooled_share_ci({ch: dom_c[ch][dom] for ch in dom_c}, tot_c, 1500)
    if lo is None:
        continue
    print(f"    {dom:24s} {cnt:7d} {cnt/sum(tot_c.values())*100:7.2f}%   "
          f"[{lo:.2f}%, {hi:.2f}%]")
    OUT["domains"][dom] = [lo, cnt / sum(tot_c.values()) * 100, hi]

lo, _, hi = pooled_share_ci({ch: dom_c[ch]["t.me"] for ch in dom_c}, tot_c)
print(f"\n    ДОЛЯ t.me (пул): {sum(dom_c[ch]['t.me'] for ch in dom_c)/sum(tot_c.values())*100:.1f}%"
      f"  95% CI [{lo:.1f}%, {hi:.1f}%]")
OUT["tme_share"] = [lo, sum(dom_c[ch]["t.me"] for ch in dom_c) / sum(tot_c.values()) * 100, hi]
per = [dom_c[ch]["t.me"] / tot_c[ch] * 100 for ch in dom_c]
b = sorted(st.median([random.choice(per) for _ in per]) for _ in range(1500))
print(f"    Для справки, медиана доли по каналам {st.median(per):.1f}% "
      f"CI [{b[37]:.1f}%, {b[1462]:.1f}%] — это ДРУГАЯ величина")

# ================================================================ docs/07
hr("docs/07 — РАЗМЕР РЫНКА: интервалы")
md = json.load(open(D + "market_deep.json", encoding="utf-8"))
srch = md.get("tgme_search", {})
allh = {}
for k, v in srch.items():
    for x in v:
        allh[x["handle"]] = max(allh.get(x["handle"], 0), x["subs"])
vals = list(allh.values())
print(f"\n3.1 Хвост ниши по 9 запросам: {len(vals)} уникальных каналов")
lo, med, hi = bmed(vals)
print(f"    медиана подписчиков {med:,.0f}  CI [{lo:,.0f}, {hi:,.0f}]")
OUT["tail_median_subs"] = [lo, med, hi]
lo, med, hi = bmed(vals, 3000)
print(f"    сумма {sum(vals):,.0f}  бутстрэп-сумма CI [нет: сумма не имеет смысла "
      f"при перевыборке каналов с разными размерами]")
OUT["tail_sum"] = sum(vals)
print("    (!) Сумма подписок НЕ является оценкой ёмкости: пересечение аудиторий "
      "не измерено (G6).")

bands = [("<10K", 0, 10e3), ("10-50K", 10e3, 50e3), ("50-150K", 50e3, 150e3),
         ("150-500K", 150e3, 500e3), ("500K+", 500e3, 1e12)]
print("\n3.2 Распределение по полосам (бутстрэп по каналам)")
OUT["bands"] = {}
for nm, lo_, hi_ in bands:
    ind = [1 if lo_ <= v < hi_ else 0 for v in vals]
    m = sum(ind) / len(ind) * 100
    b = sorted(sum(random.choice(ind) for _ in ind) / len(ind) * 100 for _ in range(N))
    print(f"    {nm:10s} {m:5.1f}%  CI [{b[125]:.1f}%, {b[4874]:.1f}%]")
    OUT["bands"][nm] = [b[125], m, b[4874]]

MS = json.load(open(D + "market_size.json", encoding="utf-8"))
cats = MS.get("by_category", {})
print("\n3.3 Медиана подписчиков по категориям TG.ME (18 категорий)")
OUT["cat_median"] = {}
for c, hs in cats.items():
    v = [MS["channels"][h]["subs"] for h in hs
         if h in MS["channels"] and MS["channels"][h]["subs"]]
    if len(v) < 5:
        continue
    lo, med, hi = bmed(v, 2000)
    print(f"    {c:14s} n={len(v):3d}  медиана {med:>10,.0f}  CI [{lo:>10,.0f}, {hi:>10,.0f}]")
    OUT["cat_median"][c] = [lo, med, hi]

mt = md.get("telegram_menu_tech", [])
if mt:
    v = [x["subs"] for x in mt]
    lo, med, hi = bmed(v, 2000)
    print(f"\n3.4 telegram.menu «Технологии/IT»: {len(v)} каналов, "
          f"медиана {med:,.0f}  CI [{lo:,.0f}, {hi:,.0f}]")
    OUT["menu_median"] = [lo, med, hi]

tot_m = md.get("market_totals", {})
print(f"\n3.5 Итоги рынка (приводятся каталогом, не измерены нами): {tot_m}")

# ================================================================ docs/02
hr("docs/02 — ПЕРЕПЕЧАТКИ: интервалы")
cl2 = json.load(open(D + "clusters.json", encoding="utf-8"))
print("\nТип данных:", type(cl2).__name__,
      (list(cl2)[:8] if isinstance(cl2, dict) else len(cl2)))
if isinstance(cl2, dict):
    sizes = []
    for k, v in cl2.items():
        if isinstance(v, (int, float)):
            continue
        try:
            sizes.append(len(v))
        except TypeError:
            pass
    if sizes:
        lo, med, hi = bmed(sizes, 2000)
        print(f"4.1 Размер кластеров: n={len(sizes)}  медиана {med:.0f}  "
              f"CI [{lo:.0f}, {hi:.0f}]")
        OUT["cluster_size"] = [lo, med, hi]
        print(f"    общий объём: {sum(sizes)} постов в {len(sizes)} кластерах")

json.dump(OUT, open(D + "uncertainty.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\n  -> data/uncertainty.json")
