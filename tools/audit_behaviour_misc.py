"""Прочие утверждения docs/09: ориентиры rx_1k (§8.3), «шум»: эмодзи, час, день недели,
«первый пост после паузы» (§5.3, §1), размеры пулов (§5), окна частоты (docs/10 §4),
и расчёт мощности для экспериментов на собственном канале (что вместо).
Запуск: python tools/audit_behaviour_misc.py
"""
import math, random, re, statistics as st
from collections import defaultdict
import numpy as np
from scipy import stats
from audit_behaviour_common import load, by_channel, top_low_pools, channel_freq

rows = load()
per = by_channel(rows)
CH = sorted(per)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️‍↔️-🫿]")
for ch, ps in per.items():
    s = sorted(ps, key=lambda r: r["rxv"])
    for i, r in enumerate(s):
        r["pct"] = (i + .5) / len(s)
    prev = None
    for r in ps:  # ps отсортирован по времени
        r["gap"] = (r["dt"] - prev).total_seconds() / 3600 if prev else None
        prev = r["dt"]

print("=== 1. Ориентиры §8.3 (p90 rx_1k по постам) ===")
for key in ("rx_1k_raw", "rx_1k"):
    xs = sorted(r[key] for r in rows)
    print(f"  {key:9s} 3690 постов: медиана {st.median(xs):.2f}, p90 {xs[int(.9*len(xs))]:.2f}")
xs = sorted(r["rx_1k"] for r in rows)
p90 = xs[int(.9 * len(xs))]
top = [r for r in rows if r["rx_1k"] >= p90]
print(f"  доля каналов в верхнем дециле: " + ", ".join(
    f"{c}:{sum(1 for r in top if r['ch']==c)}" for c in CH if any(r['ch']==c for r in top)))
print(f"  подписчики каналов верхнего дециля: медиана {st.median(r['subs'] for r in top):,.0f}")

print("\n=== 2. «Шум»: внутриканальные проверки (Краскел по процентилю / FE-наклон) ===")
def fe_slope(xkey, rows_):
    X, Y = [], []
    byc = defaultdict(list)
    for r in rows_:
        byc[r["ch"]].append(r)
    for c, ps in byc.items():
        mx = st.mean(r[xkey] for r in ps); my = st.mean(r["pct"] for r in ps)
        for r in ps:
            X.append(r[xkey] - mx); Y.append(r["pct"] - my)
    X, Y = np.array(X), np.array(Y)
    return float((X * Y).sum() / (X * X).sum())
def boot_slope(xkey, rows_, n=1000):
    byc = defaultdict(list)
    for r in rows_:
        byc[r["ch"]].append(r)
    chs = sorted(byc); rng = random.Random(6); bs = []
    for _ in range(n):
        rr = []
        for j, c in enumerate(rng.choice(chs) for _ in chs):
            rr += [dict(r, ch=f"{c}#{j}") for r in byc[c]]
        bs.append(fe_slope(xkey, rr))
    return fe_slope(xkey, rows_), np.percentile(bs, 2.5), np.percentile(bs, 97.5)
for r in rows:
    r["emo"] = len(EMOJI_RE.findall(r["text"]))
    r["emo12"] = 1.0 if 1 <= r["emo"] <= 2 else 0.0
    r["lgap"] = math.log(max(r["gap"], .05)) if r["gap"] is not None else None
    r["lage"] = math.log(max(r["age"], .05))
e, lo, hi = boot_slope("emo12", rows)
print(f"  1-2 эмодзи (vs прочие): {e:+.3f} [{lo:+.3f}, {hi:+.3f}]")
g = [r for r in rows if r["lgap"] is not None]
e, lo, hi = boot_slope("lgap", g)
print(f"  log(пауза до поста, ч): {e:+.4f} на единицу log [{lo:+.4f}, {hi:+.4f}]  (внутри канала)")
for r in g:
    r["pause6"] = 1.0 if r["gap"] > 6 else 0.0
e, lo, hi = boot_slope("pause6", g)
print(f"  пауза >6 ч (vs <=6 ч), внутри канала: {e:+.3f} [{lo:+.3f}, {hi:+.3f}]")
for nm, key in (("час UTC", lambda r: r["dt"].hour // 3), ("день недели", lambda r: r["dt"].weekday())):
    grp = defaultdict(list)
    for r in rows:
        grp[key(r)].append(r["pct"] - .5)
    H = stats.kruskal(*[v for v in grp.values() if len(v) > 20])
    print(f"  {nm}: Краскел по внутриканальному процентилю H={H.statistic:.1f} p={H.pvalue:.3f}; "
          f"размах средних {min(st.mean(v) for v in grp.values() if len(v)>20)+.5:.3f}–"
          f"{max(st.mean(v) for v in grp.values() if len(v)>20)+.5:.3f}")

print("\n=== 3. Пулы §5 ===")
from audit_behaviour_common import load as L2
allr = L2(include_norx=True)
pa = by_channel(allr)
t22, l22 = top_low_pools(pa, key="rxv_raw")
t20, l20 = top_low_pools(per, key="rxv_raw")
print(f"  22 канала: {len(t22)}/{len(l22)}; 20 каналов: {len(t20)}/{len(l20)} (док: «816/2068 из 20 каналов»)")
print(f"  окна частоты: мин {min(channel_freq(per[c])[1] for c in CH):.1f} сут, макс {max(channel_freq(per[c])[1] for c in CH):.1f} (док: 11–168)")

print("\n=== 4. Мощность для экспериментов на собственном канале ===")
# SD внутриканального log(rx/views) — медиана по каналам
sds = []
for c in CH:
    v = [math.log(r["rxv"]) for r in per[c]]
    sds.append(st.pstdev(v))
sd = st.median(sds)
print(f"  SD log(rx/views) внутри канала: медиана {sd:.3f} (каналы {min(sds):.2f}–{max(sds):.2f})")
for eff in (.10, .15, .20, .30):
    d = math.log(1 + eff) / sd
    n = 2 * ((1.959964 + 0.841621) / d) ** 2
    print(f"  A/B пост-уровня, эффект +{int(eff*100)}% на rx/views: d={d:.2f}, нужно ~{math.ceil(n)} постов на плечо")
# дневной уровень: SD log суммарных реакций дня внутри канала (после тренда) для частоты
dsd = []
for c in CH:
    by = defaultdict(list)
    for r in per[c]:
        by[r["dt"].date()].append(r)
    days = sorted(by)[1:-1]
    if len(days) < 12:
        continue
    y = np.log([sum(r["rx"] for r in by[d]) / len(by[d]) for d in days])
    t = np.arange(len(y))
    res = y - np.polyval(np.polyfit(t, y, 1), t)
    dsd.append(res.std())
sdd = st.median(dsd)
print(f"  SD log(средних rx на пост за день) внутри канала после тренда: медиана {sdd:.3f}")
for eff in (.10, .15, .20):
    d = math.log(1 + eff) / sdd
    n = 2 * ((1.959964 + 0.841621) / d) ** 2
    print(f"  частота (блоки дней A/B), эффект {int(eff*100)}% на rx/пост: ~{math.ceil(n)} дней на режим (без автокорреляции)")
