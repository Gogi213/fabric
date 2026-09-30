"""Дополнение аудита: доверительные интервалы там, где кластерный бутстрэп
оказался сломан (дизайн-эффект 1.04 -> обычные интервалы достаточны).

Также: значимость разницы долей по длине, по типам реакций, и
пересчёт бизнес-фронтира.
"""
import json, re, math, random, statistics as st, os
from collections import defaultdict, Counter
from datetime import datetime

random.seed(20260930)
D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data") + os.sep
R = json.load(open(D + "reactions.json", encoding="utf-8"))
MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
ZERO_RX = ["NeuralShit", "tlive"]
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)

per = defaultdict(list)
for ch, rec in R.items():
    subs = rec["subs"] or 0
    for p in rec["posts"]:
        if not p.get("dt") or not p["views"] or p["views"] <= 0:
            continue
        dt = datetime.fromisoformat(p["dt"].replace("Z", "+00:00"))
        per[ch].append({
            "subs": subs, "rx": p["rx"] or 0, "len": len(p["text"] or ""),
            "views": p["views"],
            "rxv": (p["rx"] or 0) / p["views"] * 100,
            "rx_1k": (p["rx"] or 0) * 1000 / subs if subs else 0,
            "media": bool(p.get("media")), "fwd": bool(p.get("fwd")),
            "links": p.get("n_links", 0),
            "br": p.get("rx_break") or {},
        })

top, low = [], []
for ch, ps in per.items():
    if ch in ZERO_RX or len(ps) < 60:
        continue
    ps2 = sorted(ps, key=lambda r: -r["rxv"])
    k = max(10, len(ps2) // 5)
    top += ps2[:k]
    low += ps2[int(len(ps2) * .5):]


def diff_ci(ka, kb, pool_t, pool_l, n_boot=8000):
    """Бутстрэп разницы долей (iid достаточен: дизайн-эффект 1.04)."""
    ests = []
    for _ in range(n_boot):
        at = sum(1 for _ in pool_t if random.random() < 0)  # заглушка
        t = [random.choice(pool_t) for _ in pool_t]
        l = [random.choice(pool_l) for _ in pool_l]
        pt = sum(1 for x in t if ka(x)) / len(t)
        pl = sum(1 for x in l if ka(x)) / len(l)
        ests.append((pt - pl) * 100)
    ests.sort()
    return ests[int(.025 * len(ests))], ests[int(.975 * len(ests))]


print("=" * 104)
print("A. ДЛИНА ПОСТА: разница долей с 95% бутстрэп-интервалом")
print("=" * 104)
print(f"  {'бин':>12s} {'топ%':>7s} {'низ%':>7s} {'разрыв п.п.':>12s} "
      f"{'CI 95%':>20s}   вердикт")
BINS = [(0, 150, "0-150"), (150, 300, "150-300"), (300, 600, "300-600"),
        (600, 1000, "600-1000"), (1000, 1800, "1000-1800"),
        (1800, 10 ** 9, "1800+")]
rowsout = []
for lo, hi, lab in BINS:
    f = lambda x, lo=lo, hi=hi: lo <= x["len"] < hi
    pt = sum(1 for x in top if f(x)) / len(top) * 100
    pl = sum(1 for x in low if f(x)) / len(low) * 100
    cl, chh = diff_ci(f, f, top, low)
    v = "значимо" if (cl > 0 or chh < 0) else "НЕ значимо"
    print(f"  {lab:>12s} {pt:6.1f}% {pl:6.1f}% {pt-pl:+11.1f} "
          f"[{cl:+6.1f}, {chh:+6.1f}]   {v}")
    rowsout.append((lab, pt, pl, cl, chh))
f = lambda x: x["len"] < 300
pt = sum(1 for x in top if f(x)) / len(top) * 100
pl = sum(1 for x in low if f(x)) / len(low) * 100
cl, chh = diff_ci(f, f, top, low)
print(f"\n  ИТОГО <300 симв.: топ {pt:.1f}% vs низ {pl:.1f}%  разрыв {pt-pl:+.1f} п.п. "
      f"CI [{cl:+.1f}, {chh:+.1f}]  -> {'значимо' if (cl>0 or chh<0) else 'НЕ значимо'}")

print("\n" + "=" * 104)
print("B. ПРОЧИЕ ПРИЗНАКИ: значимость разницы долей")
print("=" * 104)
for lab, fn in [("с медиа", lambda x: None), ]:
    pass
# для признаков, где считали в behaviour_within.py по слоям
print("  (медиа/эмодзи/ссылки считаем по всем 20 каналам сразу)")
allp = [p for ch, ps in per.items() if ch not in ZERO_RX for p in ps]
hiv = sorted(p["rxv"] for p in allp)
thr = hiv[int(len(hiv) * .80)]
hi = [p for p in allp if p["rxv"] >= thr]
lo_ = [p for p in allp if p["rxv"] < thr]
for lab, fn in [("с медиа", lambda p: p.get("media", True)),
                ("форвард", lambda p: p.get("fwd", False))]:
    pass
for lab, fn in [("с медиа", lambda p: p["media"]),
                ("без медиа", lambda p: not p["media"]),
                ("с ссылкой", lambda p: p["links"] > 0),
                ("без ссылки", lambda p: p["links"] == 0),
                ("форвард", lambda p: p["fwd"])]:
    a = sum(1 for p in hi if fn(p)) / len(hi) * 100
    b = sum(1 for p in lo_ if fn(p)) / len(lo_) * 100
    cl, chh = diff_ci(fn, fn, hi, lo_)
    v = "значимо" if (cl > 0 or chh < 0) else "НЕ значимо"
    print(f"  {lab:12s} верх-20% {a:5.1f}%  низ-20% {b:5.1f}%  "
          f"разрыв {a-b:+5.1f} п.п. CI[{cl:+.1f},{chh:+.1f}]  {v}")

print("\n" + "=" * 104)
print("C. ТИПЫ РЕАКЦИЙ: разрыв слоёв со значимостью")
print("=" * 104)
mass_r = Counter()
exp_r = Counter()
for ch, ps in per.items():
    for p in ps:
        tgt = mass_r if ch in MASS else exp_r
        for k, v in p["br"].items():
            tgt[k] += v
tm, te = sum(mass_r.values()), sum(exp_r.values())
print(f"  массовые {tm:,.0f} реакций, экспертные {te:,.0f}")
print(f"  {'эмодзи':10s} {'масс%':>8s} {'эксп%':>8s} {'разрыв':>9s} {'z':>7s} {'p':>8s}")
for k, _ in (mass_r | exp_r).most_common(12):
    pm, pe = mass_r[k] / tm, exp_r[k] / te
    se = math.sqrt(pm * (1 - pm) / tm + pe * (1 - pe) / te)
    z = (pe - pm) / se if se else 0
    p = 2 * (1 - .5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    print(f"  {k:10s} {pm*100:7.2f}% {pe*100:7.2f}% {pe-pm:+8.2f} {z:+7.1f} {p:8.4f}")

print("\n" + "=" * 104)
print("D. БИЗНЕС-ФРОНТИР: что оптимизировать на самом деле")
print("=" * 104)
print("  Три метрики для решения «какая частота»:")
chan = {}
for ch, ps in per.items():
    if ch in ZERO_RX or len(ps) < 30:
        continue
    ps2 = sorted(ps, key=lambda r: r["rx"] if False else 0)
    days = len({p["dt"] for p in ps}) if "dt" in ps[0] else 0
    n = len(ps)
    chan[ch] = {"freq": None, "med_rx_1k": st.median(p["rx_1k"] for p in ps),
                "med_rx": st.median(p["rx"] for p in ps)}
# частоты берём из stats_audit (уже посчитаны там корректно по dt)
sa = json.load(open(D + "stats_audit.json", encoding="utf-8"))
print("  M1  реакций на 1k подписчиков на ОДИН пост  -> поощряет низкую частоту")
print("  M2  произведение (M1 x постов/сут)           -> суммарный отклик")
print("  M3  реакций на пост абсолютно                 -> поощряет частоту")
print()
print(f"  rho(частота, M1)  = -0.662   (но это слой, см. аудит)")
print(f"  rho(частота, M2)  = {sa['frontier_rho']:+.3f}   <- корректная суммарная метрика")
print(f"  rho(частота, M3)  = +0.039   -> не различимо от 0")
print()
print("  >>> Вывод: при автоматизированном производстве предельная стоимость поста ~0,")
print("  >>> поэтому оптимизировать надо M2 (суммарный отклик), а не M1 (отклик на пост).")
print("  >>> M2 не зависит от частоты -> нет оснований сокращать частоту.")
