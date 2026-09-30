"""audit_market_size_est.py — оценка числа живых RU IT/AI контент-каналов по полосам.

Вход: audit_parts/audit_market_live.json (перепись telegram.menu/channels/tech, 58 стр.,
живая выборка 40 из tgme-поиска) + ручная разметка ниже (seed 20260930).
Метод: N_band = count_band(перепись) × p_M(доля RU IT/AI контент-каналов, разметка)
        × alive / coverage, где coverage = доля независимого списка (M-каналы из
        tgme-поиска и из сети упоминаний links.json), найденная в переписи
        (Lincoln–Petersen: N = n1·n2/m = n1 / (m/n2)).
Неопределённость — Монте-Карло: Beta(k+1, n-k+1) для p_M, coverage, alive.
Запуск: python tools/audit_market_size_est.py
"""
import json, os, re, random, statistics as st

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = json.load(open(os.path.join(ROOT, "audit_parts", "audit_market_live.json"), encoding="utf-8"))
rx = re.compile(r"Канал\s*•\s*@([A-Za-z0-9_]{3,})\s*•\s*(\d{1,3}(?:\xa0\d{3})*)")
cens = {}
for p, v in R["menu_pages"].items():
    for h, n in rx.findall(v["text"]):
        cens[h.lower()] = int(n.replace("\xa0", ""))
print("перепись telegram.menu tech:", len(cens), "каналов")

BANDS = [("500K+", 5e5, 1e13), ("150-500K", 1.5e5, 5e5), ("50-150K", 5e4, 1.5e5),
         ("10-50K", 1e4, 5e4), ("1-10K", 1e3, 1e4)]
cnt = {nm: sum(lo <= s < hi for s in cens.values()) for nm, lo, hi in BANDS}

# ручная разметка (M = RU контент-канал IT/AI/tech; иначе B/O). k = число M, n = размечено.
# ≥150K размечены сплошь (78 каналов), ниже — случайные выборки (seed 20260930).
LAB = {"500K+": (26, 33), "150-500K": (25, 45), "50-150K": (17, 30),
       "10-50K": (26, 40), "1-10K": (18, 30)}
# покрытие переписью независимых списков (M-каналы, найденные в переписи / все M списка):
#   список 1 — живая выборка 40 из tgme-поиска: 10–150K 7/13, 1–10K 2/4;
#   список 2 — сеть упоминаний/форвардов/t.me-ссылок 22 RU-каналов (links.json, 96 хэндлов,
#             разметка + живая проверка 21 спорного): ≥150K 8/8, 10–150K 13/18, 1–10K 5/11;
#   список 3 — 15 каналов выборки проекта ≥150K: 13/15 (нет trends, tlive).
COV = {"500K+": (21, 23), "150-500K": (21, 23), "50-150K": (20, 31),
       "10-50K": (20, 31), "1-10K": (7, 15)}
ALIVE = (17, 19)                 # живые среди M в живой выборке (2 мёртвых: >90 дн)


def beta(k, n):
    return random.betavariate(k + 1, n - k + 1)


random.seed(20260930)
sims = {nm: [] for nm, _, _ in BANDS}
tot10, tot1 = [], []
for _ in range(20000):
    a = beta(*ALIVE)
    s10 = 0
    s1 = 0
    for nm, _, _ in BANDS:
        k, n = LAB[nm]
        p = k / n if n == cnt[nm] else beta(k, n)   # сплошная разметка — без выборочной ошибки
        cov = beta(*COV[nm])
        v = cnt[nm] * p * a / cov
        sims[nm].append(v)
        if nm != "1-10K":
            s10 += v
        s1 += v
    tot10.append(s10)
    tot1.append(s1)


def q(v):
    v = sorted(v)
    return round(v[int(.025 * len(v))]), round(st.median(v)), round(v[int(.975 * len(v))])


print("\n%-10s %7s %10s %22s" % ("полоса", "в каталоге", "p_M", "N живых RU IT/AI [95%]"))
for nm, _, _ in BANDS:
    k, n = LAB[nm]
    print("%-10s %7d %6d/%-3d %22s" % (nm, cnt[nm], k, n, q(sims[nm])))
print("≥10K итого:", q(tot10))
print("≥1K  итого:", q(tot1))
sh = [sims["10-50K"][i] / tot10[i] for i in range(len(tot10))]
print("доля полосы 10–50K среди ≥10K, %:", tuple(x / 10 for x in q([x * 1000 for x in sh])))
# без поправки на покрытие (нижняя граница: только перепись одного каталога)
lb = sum(cnt[nm] * LAB[nm][0] / LAB[nm][1] for nm in ("500K+", "150-500K", "50-150K", "10-50K"))
print("нижняя граница ≥10K (только перепись, без coverage и живости):", round(lb))
json.dump({"census_counts": cnt, "labels": LAB, "coverage": COV,
           "alive": ALIVE, "bands": {nm: q(sims[nm]) for nm in sims},
           "ge10K": q(tot10), "ge1K": q(tot1), "census_only_ge10K": lb},
          open(os.path.join(ROOT, "audit_parts", "audit_market_size_est.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
