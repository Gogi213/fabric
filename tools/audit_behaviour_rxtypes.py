"""Аудит «типы реакций: кастомные 21.5 % vs 6.7 %, z=+218; 👎 4.2 % vs 0.6 %, z=−143» (docs/09 §7, README).

z в документе посчитан с единицей наблюдения «одна реакция» (1.2 млн «независимых»
наблюдений). Реакции зависимы внутри поста и канала, а набор разрешённых реакций —
настройка канала. Пересчёт: доли на уровне каналов (n=11 vs 9), точная перестановка
меток, бутстрэп; «наличие типа в канале вообще» как прокси настройки.
Запуск: python tools/audit_behaviour_rxtypes.py
"""
import itertools, math, random, statistics as st
from collections import Counter
import numpy as np
from scipy import stats
from audit_behaviour_common import load, by_channel

rows = load()
per = by_channel(rows)
CH = sorted(per)
TYPES = ["custom", "❤", "😁", "🤣", "👍", "🔥", "👎", "😭", "🗿", "🤯", "🤬", "👀"]

print("=== 1. Воспроизведение (единица = реакция, сырые данные) ===")
agg = {"mass": Counter(), "exp": Counter()}
aggf = {"mass": Counter(), "exp": Counter()}
for r in rows:
    for k, v in r["br"].items():
        aggf[r["layer"]][k] += v
import json, os
from audit_behaviour_common import DATA, MASS, NO_RX
R = json.load(open(os.path.join(DATA, "reactions.json"), encoding="utf-8"))
for ch, rec in R.items():
    for p in rec["posts"]:
        if not p.get("dt") or not p["views"]:
            continue
        for k, v in (p.get("rx_break") or {}).items():
            agg["mass" if ch in MASS else "exp"][k] += v
tm, te = sum(agg["mass"].values()), sum(agg["exp"].values())
print(f"  всего {tm+te:,.0f} (масс {tm:,.0f}, эксп {te:,.0f})")
for k in TYPES:
    pm, pe = agg["mass"][k] / tm, agg["exp"][k] / te
    se = math.sqrt(pm * (1 - pm) / tm + pe * (1 - pe) / te)
    print(f"  {k:7s} масс {pm*100:6.2f}% эксп {pe*100:6.2f}% z={(pe-pm)/se:+7.1f}")

print("\n=== 2. Уровень каналов: доля типа в реакциях канала (K-фикс) ===")
share = {}
present = {}
for c in CH:
    cnt = Counter()
    for r in per[c]:
        for k, v in r["br"].items():
            cnt[k] += v
    tot = sum(v for k, v in cnt.items() if k != "?")
    share[c] = {k: cnt[k] / tot for k in TYPES}
    # доля постов канала, где тип встречается хотя бы раз
    present[c] = {k: sum(1 for r in per[c] if r["br"].get(k, 0) > 0) / len(per[c]) for k in TYPES}
lay = {c: per[c][0]["layer"] for c in CH}
E = [c for c in CH if lay[c] == "exp"]
M = [c for c in CH if lay[c] == "mass"]


def exact_perm_p(vals):
    v = np.array([vals[c] for c in CH])
    mask0 = np.array([lay[c] == "exp" for c in CH])
    obs = v[mask0].mean() - v[~mask0].mean()
    cnt = tot = 0
    for comb in itertools.combinations(range(len(CH)), len(E)):
        m = np.zeros(len(CH), bool); m[list(comb)] = True
        d = v[m].mean() - v[~m].mean()
        tot += 1
        cnt += abs(d) >= abs(obs) - 1e-12
    return obs, cnt / tot


def boot_diff(vals, n=4000, seed=2):
    rng = random.Random(seed)
    bs = []
    for _ in range(n):
        e = [vals[rng.choice(E)] for _ in E]
        m = [vals[rng.choice(M)] for _ in M]
        bs.append(st.mean(e) - st.mean(m))
    bs.sort()
    return bs[int(.025 * n)], bs[int(.975 * n) - 1]


print(f"  {'тип':7s} {'масс медиана(мин-макс)':>26s} {'эксп медиана(мин-макс)':>26s} "
      f"{'разн.средних':>12s} {'CI':>18s} {'перест.p':>9s} {'MW p':>7s}")
for k in TYPES:
    vals = {c: share[c][k] for c in CH}
    obs, p = exact_perm_p(vals)
    lo, hi = boot_diff(vals)
    mw = stats.mannwhitneyu([vals[c] for c in E], [vals[c] for c in M]).pvalue
    fm = lambda xs: f"{st.median(xs)*100:5.1f} ({min(xs)*100:4.1f}-{max(xs)*100:4.1f})"
    print(f"  {k:7s} {fm([vals[c] for c in M]):>26s} {fm([vals[c] for c in E]):>26s} "
          f"{obs*100:+10.1f}пп [{lo*100:+5.1f},{hi*100:+5.1f}] {p:9.4f} {mw:7.4f}")

print("\n=== 3. Доступность типа: в скольких каналах тип встречается хотя бы в 1 % постов ===")
for k in ("custom", "👎", "🤬", "😭", "🗿", "👀", "🤯"):
    pm = [c for c in M if present[c][k] >= .01]
    pe = [c for c in E if present[c][k] >= .01]
    none_e = [c for c in E if present[c][k] == 0]
    print(f"  {k:7s} масс {len(pm)}/{len(M)}  эксп {len(pe)}/{len(E)}  эксп-каналы, где тип НИ РАЗУ: {none_e}")
print("\n  число различных ключей реакций по каналу (прокси настроенного набора):")
for c in sorted(CH, key=lambda c: lay[c]):
    keys = set()
    for r in per[c]:
        keys |= set(r["br"])
    print(f"    {c:28s} {lay[c]:4s} типов {len(keys):3d}  custom в {present[c]['custom']*100:5.1f}% постов  "
          f"доля custom {share[c]['custom']*100:5.1f}%  👎 {share[c]['👎']*100:4.1f}%")

print("\n=== 4. Условно на доступность: 👎 только среди каналов, где он встречается ===")
for k in ("👎", "custom"):
    av = [c for c in CH if present[c][k] >= .01]
    e = [share[c][k] for c in av if lay[c] == "exp"]
    m = [share[c][k] for c in av if lay[c] == "mass"]
    if e and m:
        print(f"  {k}: масс n={len(m)} медиана {st.median(m)*100:.1f}%, эксп n={len(e)} медиана {st.median(e)*100:.1f}%, "
              f"MW p={stats.mannwhitneyu(e, m).pvalue:.3f}")
