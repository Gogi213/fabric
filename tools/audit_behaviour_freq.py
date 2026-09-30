"""Аудит «частота -> отклик»: rho −0.662/−0.72 (между каналами), −0.159 CI [−0.230,−0.086]
(«внутри канала по дням»), −0.378 (22 канала), rho(частота, суммарный отклик) = −0.009,
«высокочастотные 4.12 vs 2.91», предел обнаружимости, TOST (docs/09 §4, §8; docs/10 §3; README).
Запуск: python tools/audit_behaviour_freq.py
"""
import math, random, statistics as st
from collections import defaultdict
from datetime import timedelta
import numpy as np
from scipy import stats
from audit_behaviour_common import load, by_channel, channel_freq, fisher_ci, T_REF

rows_all = load(include_norx=True)
rows = [r for r in rows_all if r["ch"] not in ("tlive", "NeuralShit")]
per = by_channel(rows)
per_all = by_channel(rows_all)
CH = sorted(per)


def sp(a, b):
    return float(stats.spearmanr(a, b).statistic)


print("=== 1. Между каналами ===")
cs = {}
for c, ps in per_all.items():
    f, span = channel_freq(ps)
    cs[c] = {"f": f, "layer": ps[0]["layer"], "subs": ps[0]["subs"],
             "rx_1k_raw": st.median(r["rx_1k_raw"] for r in ps),
             "rx_1k": st.median(r["rx_1k"] for r in ps),
             "rxv": st.median(r["rxv"] for r in ps),
             "rx": st.median(r["rx"] for r in ps)}
    fr = [r for r in ps if 2 <= r["age"] <= 7]
    cs[c]["rx_1k_27"] = st.median(r["rx_1k"] for r in fr) if len(fr) >= 8 else None
for key in ("rx_1k_raw", "rx_1k", "rxv", "rx"):
    x = [cs[c]["f"] for c in CH]; y = [cs[c][key] for c in CH]
    r = sp(x, y); lo, hi = fisher_ci(r, len(x))
    print(f"  частота ~ {key:9s} n=20 rho={r:+.3f} Fisher CI [{lo:+.3f}, {hi:+.3f}]")
c22 = sorted(per_all)
r = sp([cs[c]["f"] for c in c22], [cs[c]["rx_1k_raw"] for c in c22]); lo, hi = fisher_ci(r, 22)
print(f"  22 канала (2 без блока реакций как 0): rho={r:+.3f} [{lo:+.3f}, {hi:+.3f}]  <- некорректно: это пропуск, не 0")
sel = [c for c in CH if cs[c]["rx_1k_27"] is not None]
r = sp([cs[c]["f"] for c in sel], [cs[c]["rx_1k_27"] for c in sel]); lo, hi = fisher_ci(r, len(sel))
print(f"  только посты 2-7 сут (n={len(sel)}): частота ~ rx_1k rho={r:+.3f} [{lo:+.3f}, {hi:+.3f}]")
# контроль размера: частичная Спирмен частота~rx_1k | log subs
def partial_sp(x, y, z):
    rx_, ry, rz = (stats.rankdata(v) for v in (x, y, z))
    def res(a, b):
        b1 = np.polyfit(b, a, 1)
        return a - np.polyval(b1, b)
    return float(np.corrcoef(res(rx_, rz), res(ry, rz))[0, 1])
x = [cs[c]["f"] for c in CH]; y = [cs[c]["rx_1k"] for c in CH]; z = [math.log(cs[c]["subs"]) for c in CH]
print(f"  частичная частота~rx_1k | log subs: {partial_sp(x, y, z):+.3f};  "
      f"| слой: {partial_sp(x, y, [1 if cs[c]['layer']=='exp' else 0 for c in CH]):+.3f}")
print(f"  Спирмен(частота, log subs) = {sp(x, z):+.3f}")

print("\n=== 2. Предел обнаружимости (80 % мощности, alpha=.05, Fisher; для Спирмена SE x1.03) ===")
for n in (9, 10, 11, 12, 16, 20, 100):
    zc, zp = 1.959964, 0.841621
    r1 = math.tanh((zc + zp) / math.sqrt(n - 3))
    r2 = math.tanh((zc + zp) * math.sqrt(1.06) / math.sqrt(n - 3))
    print(f"  n={n:3d}: |rho|>={r1:.3f} (Пирсон-Фишер), {r2:.3f} (Спирмен, var 1.06/(n-3))")


print("\n=== 3. «Внутри канала по дням» ===")
def daily(ps, drop_first=False, last_day=None):
    by = defaultdict(list)
    for r in ps:
        by[r["dt"].date()].append(r)
    days = sorted(by)
    if drop_first:
        days = days[1:]
    if last_day:
        days = [d for d in days if d <= last_day]
    return [(d, by[d]) for d in days]


def chan_rho(ps, ykey, drop_first, detrend, last_day):
    dd = daily(ps, drop_first, last_day)
    if len(dd) < 12:
        return None
    n = [len(v) for _, v in dd]
    y = [st.mean(r[ykey] for r in v) for _, v in dd]
    if len(set(y)) < 2:
        return None
    if not detrend:
        return sp(n, y), len(dd)
    t = [(d - dd[0][0]).days for d, _ in dd]
    wd = [d.weekday() for d, _ in dd]
    rn, ry, rt = (stats.rankdata(v) for v in (n, y, t))
    X = np.column_stack([np.ones(len(t)), rt] + [[1.0 if w == k else 0.0 for w in wd] for k in range(1, 7)])
    res = lambda a: a - X @ np.linalg.lstsq(X, a, rcond=None)[0]
    return float(np.corrcoef(res(rn), res(ry))[0, 1]), len(dd)


def pool(est, spearman_var=False, re_=False):
    zs = np.array([math.atanh(max(min(r, .999), -.999)) for r, n in est])
    v = np.array([(1.06 if spearman_var else 1.0) / (n - 3) for r, n in est])
    w = 1 / v
    zf = (w * zs).sum() / w.sum()
    if not re_:
        se = math.sqrt(1 / w.sum())
        return math.tanh(zf), math.tanh(zf - 1.96 * se), math.tanh(zf + 1.96 * se), None
    Q = (w * (zs - zf) ** 2).sum()
    k = len(zs)
    tau2 = max(0.0, (Q - (k - 1)) / (w.sum() - (w ** 2).sum() / w.sum()))
    wr = 1 / (v + tau2)
    zr = (wr * zs).sum() / wr.sum()
    se = math.sqrt(1 / wr.sum())
    I2 = max(0.0, (Q - (k - 1)) / Q) if Q > 0 else 0
    return math.tanh(zr), math.tanh(zr - 1.96 * se), math.tanh(zr + 1.96 * se), (Q, I2, tau2)


LAST = (T_REF - timedelta(days=1)).date()
variants = [
    ("как в stats_audit: rx_1k(raw), все дни", "rx_1k_raw", False, False),
    ("rx_1k(fix)", "rx_1k", False, False),
    ("rx_1k(fix), без первого (неполного) дня", "rx_1k", True, False),
    ("rx_1k(fix), без 1-го дня, тренд+день недели", "rx_1k", True, True),
    ("rx/views, все дни", "rxv", False, False),
    ("rx/views, без 1-го дня, тренд+день недели", "rxv", True, True),
]
per_ch_out = {}
for name, yk, df, dt in variants:
    est = {}
    for c in sorted(per_all):
        r_ = chan_rho(per_all[c], yk, df, dt, LAST)
        if r_ is not None and r_[0] == r_[0]:
            est[c] = r_
    e = list(est.values())
    fe = pool(e)
    rev = pool(e, spearman_var=True, re_=True)
    rng = random.Random(1)
    keys = sorted(est)
    bs = sorted(pool([est[rng.choice(keys)] for _ in keys])[0] for _ in range(4000))
    Q, I2, tau2 = rev[3]
    print(f"  {name:44s} k={len(e):2d} FE {fe[0]:+.3f} [{fe[1]:+.3f},{fe[2]:+.3f}] | "
          f"RE {rev[0]:+.3f} [{rev[1]:+.3f},{rev[2]:+.3f}] I2={I2*100:.0f}% | "
          f"бутстрэп каналов [{bs[100]:+.3f},{bs[3899]:+.3f}] | <0 в {sum(1 for r,_ in e if r<0)}/{len(e)}")
    per_ch_out[name] = est
print("  каналы (вариант 1 -> вариант с rx/views, тренд):")
for c in sorted(per_ch_out[variants[0][0]]):
    a = per_ch_out[variants[0][0]][c]
    b = per_ch_out[variants[-1][0]].get(c)
    print(f"    {c:28s} дней {a[1]:3d} rho {a[0]:+.3f} -> {('%+.3f' % b[0]) if b else '  н/д'}")
excluded = [c for c in CH if c not in per_ch_out[variants[0][0]]]
print(f"  исключены (<12 дней): {excluded}")

print("\n=== 4. Эластичность суммарных реакций дня по числу постов дня (внутри канала) ===")
print("    log(сумма rx за день) ~ log(n постов) + тренд + день недели; 1 = без каннибализации")
sl = {}
for c in CH:
    dd = daily(per[c], True, LAST)
    if len(dd) < 12:
        continue
    n = np.array([len(v) for _, v in dd], float)
    if len(set(n)) < 2:
        continue
    y = np.log([sum(r["rx"] for r in v) for _, v in dd])
    t = np.array([(d - dd[0][0]).days for d, _ in dd], float)
    wd = [d.weekday() for d, _ in dd]
    X = np.column_stack([np.ones(len(t)), np.log(n), t] + [[1.0 if w == k else 0.0 for w in wd] for k in range(1, 7)])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    sl[c] = b[1]
keys = sorted(sl)
rng = random.Random(2)
bs = sorted(st.median(sl[rng.choice(keys)] for _ in keys) for _ in range(4000))
print(f"  каналов {len(sl)}; медиана эластичности {st.median(sl.values()):.2f} "
      f"[бутстрэп каналов {bs[100]:.2f}, {bs[3899]:.2f}]; по каналам: "
      + ", ".join(f"{c}:{v:.2f}" for c, v in sorted(sl.items(), key=lambda x: x[1])))

print("\n=== 5. «Суммарный отклик» M2 = медиана rx_1k x постов/сут ===")
for key in ("rx_1k_raw", "rx_1k"):
    m2 = {c: cs[c][key] * cs[c]["f"] for c in CH}
    x = [cs[c]["f"] for c in CH]; y = [m2[c] for c in CH]
    r = sp(x, y); lo, hi = fisher_ci(r, 20)
    lo90, hi90 = fisher_ci(r, 20, z=1.644854)
    lo_ = [m2[c] for c in CH if cs[c]["f"] < 6]; hi_ = [m2[c] for c in CH if cs[c]["f"] >= 6]
    rng = random.Random(3)
    L = [c for c in CH if cs[c]["f"] < 6]; H = [c for c in CH if cs[c]["f"] >= 6]
    bs = sorted(st.median(m2[rng.choice(H)] for _ in H) / st.median(m2[rng.choice(L)] for _ in L) for _ in range(4000))
    print(f"  {key:9s} rho={r:+.3f} 95% [{lo:+.3f},{hi:+.3f}] 90% [{lo90:+.3f},{hi90:+.3f}] "
          f"(TOST ±0.3 {'пройден' if lo90>-.3 and hi90<.3 else 'НЕ пройден'}); "
          f"медианы низк/высок {st.median(lo_):.2f}/{st.median(hi_):.2f}, "
          f"отношение CI [{bs[100]:.2f}, {bs[3899]:.2f}], MW p={stats.mannwhitneyu(hi_, lo_).pvalue:.2f}")
# корректнее: реакций в сутки на 1k подписчиков = сумма rx / окно / subs
m3 = {}
for c in CH:
    f, span = channel_freq(per[c])
    m3[c] = sum(r["rx"] for r in per[c]) / (span + 1) / cs[c]["subs"] * 1000
x = [cs[c]["f"] for c in CH]
r = sp(x, [m3[c] for c in CH]); lo, hi = fisher_ci(r, 20)
print(f"  сумма rx/сутки/1k подп. (прямо): rho={r:+.3f} [{lo:+.3f},{hi:+.3f}]; "
      f"| log subs: {partial_sp(x, [m3[c] for c in CH], [math.log(cs[c]['subs']) for c in CH]):+.3f}")

print("\n=== 6. Дрейф rx_1k с возрастом (docs/10 §3.3) ===")
pos = []
for c in CH:
    ps = per[c]
    r1 = sp([r["age"] for r in ps], [r["rx_1k"] for r in ps])
    r2 = sp([r["age"] for r in ps], [r["rx"] for r in ps])
    r3 = sp([r["age"] for r in ps], [r["rx_1k_raw"] for r in ps])
    pos.append((c, r3, r1, r2))
print(f"  rho(возраст, rx_1k raw) > 0 в {sum(1 for x in pos if x[1] > 0)}/20; "
      f"совпадает ли с rho(возраст, rx) внутри канала: "
      f"{all(abs(x[2]-x[3])<1e-9 for x in pos)} (подписчики — константа канала)")
print("  " + ", ".join(f"{c}:{a:+.2f}" for c, a, _, _ in sorted(pos, key=lambda x: x[1])))
# накопление: медиана rx по возрасту (пул, внутри-канальный процентиль)
bins = [(0, 1), (1, 2), (2, 4), (4, 7), (7, 14), (14, 30), (30, 200)]
for lo_, hi_ in bins:
    sel = [r for r in rows if lo_ <= r["age"] < hi_]
    if sel:
        print(f"    возраст {lo_:3d}-{hi_:3d} сут: n={len(sel):4d} медиана rx {st.median(r['rx'] for r in sel):6.0f} "
              f"views {st.median(r['views'] for r in sel):8.0f} rx/views {st.median(r['rxv'] for r in sel):.2f}%")
