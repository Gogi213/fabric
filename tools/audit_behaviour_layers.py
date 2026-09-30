"""Аудит «разрыв слоёв x5.7 (x5.07 по votes)» — docs/09 §1,§3; docs/10 #18; README.

Проверки: воспроизведение; разложение rx_1k = (views/subs) x (rx/views);
перестановка меток слоя (точная, все C(20,9)); исключение по одному каналу;
слой по данным (размер, частота); только посты возраста 2-7 сут; размер канала.
Запуск: python tools/audit_behaviour_layers.py
"""
import itertools, math, random, statistics as st
import numpy as np
from scipy import stats
from audit_behaviour_common import load, by_channel, channel_freq

rows = load()
per = by_channel(rows)
CH = sorted(per)


def chstats(sel_rows_by_ch):
    out = {}
    for ch, ps in sel_rows_by_ch.items():
        if not ps:
            continue
        out[ch] = {k: st.median(r[k] for r in ps) for k in
                   ("rx_1k", "rx_1k_raw", "votes_1k", "rxv", "vps", "rx")}
        out[ch]["subs"] = ps[0]["subs"]
        out[ch]["layer"] = ps[0]["layer"]
        out[ch]["freq"] = channel_freq(per[ch])[0]
        out[ch]["rx_per_vote"] = st.median(r["rx"] / r["votes"] for r in ps if r["votes"])
        out[ch]["n"] = len(ps)
    return out


def gap(cs, key, labels=None):
    lab = labels or {c: cs[c]["layer"] for c in cs}
    e = [cs[c][key] for c in cs if lab[c] == "exp"]
    m = [cs[c][key] for c in cs if lab[c] == "mass"]
    if not e or not m:
        return float("nan")
    return st.median(e) / st.median(m)


cs = chstats(per)
print("=== 1. Воспроизведение (медиана канальных медиан, эксп/масс) ===")
for key in ("rx_1k_raw", "rx_1k", "votes_1k", "rxv", "vps", "rx", "rx_per_vote"):
    print(f"  {key:12s} разрыв x{gap(cs, key):.2f}")
print("  -> rx_1k = vps * rxv: разрыв по rx_1k почти целиком = разрыв по views/subs (ER)")

print("\n=== 2. Точная перестановка меток (все C(20,9)) и бутстрэп по каналам ===")
n_exp = sum(1 for c in cs if cs[c]["layer"] == "exp")
for key in ("rx_1k", "rxv", "vps"):
    obs = gap(cs, key)
    vals = np.array([cs[c][key] for c in CH])
    cnt = tot = 0
    for comb in itertools.combinations(range(len(CH)), n_exp):
        mask = np.zeros(len(CH), bool)
        mask[list(comb)] = True
        g = np.median(vals[mask]) / np.median(vals[~mask])
        tot += 1
        if abs(math.log(g)) >= abs(math.log(obs)) - 1e-12:
            cnt += 1
    rng = random.Random(7)
    E = [c for c in CH if cs[c]["layer"] == "exp"]
    M = [c for c in CH if cs[c]["layer"] == "mass"]
    bs = []
    for _ in range(4000):
        e = [cs[rng.choice(E)][key] for _ in E]
        m = [cs[rng.choice(M)][key] for _ in M]
        bs.append(st.median(e) / st.median(m))
    bs.sort()
    print(f"  {key:6s} x{obs:.2f}  перест. p={cnt/tot:.4f} (из {tot})  "
          f"бутстрэп CI [{bs[100]:.2f}, {bs[3899]:.2f}]")
    mw = stats.mannwhitneyu([cs[c][key] for c in E], [cs[c][key] for c in M])
    print(f"         Манн-Уитни p={mw.pvalue:.4f}")

print("\n=== 3. Исключение по одному каналу (rx_1k) ===")
loo = []
for c in CH:
    sub = {k: v for k, v in cs.items() if k != c}
    loo.append((gap(sub, "rx_1k"), c))
loo.sort()
print(f"  диапазон x{loo[0][0]:.2f} (без {loo[0][1]}) … x{loo[-1][0]:.2f} (без {loo[-1][1]})")

print("\n=== 4. Слой по данным ===")
subs_med = st.median(cs[c]["subs"] for c in CH)
for name, lab in [
    ("размер: subs >= 500K = 'mass'", {c: "mass" if cs[c]["subs"] >= 5e5 else "exp" for c in CH}),
    (f"размер: subs >= медианы {subs_med:,.0f}", {c: "mass" if cs[c]["subs"] >= subs_med else "exp" for c in CH}),
    ("частота >= 6 постов/сут", {c: "mass" if cs[c]["freq"] >= 6 else "exp" for c in CH}),
]:
    ne = sum(1 for v in lab.values() if v == "exp")
    diff = [c for c in CH if lab[c] != cs[c]["layer"]]
    print(f"  {name:32s} n_exp={ne:2d}  rx_1k x{gap(cs,'rx_1k',lab):.2f}  "
          f"rxv x{gap(cs,'rxv',lab):.2f}  vps x{gap(cs,'vps',lab):.2f}  "
          f"не совпадает с авторской меткой: {diff}")

print("\n=== 5. Только посты возраста 2-7 сут (снимает накопление/состав возраста) ===")
sel = {c: [r for r in ps if 2 <= r["age"] <= 7] for c, ps in per.items()}
sel = {c: v for c, v in sel.items() if len(v) >= 8}
cs2 = chstats(sel)
print(f"  каналов с >=8 такими постами: {len(cs2)}; "
      f"mass {sum(1 for c in cs2 if cs2[c]['layer']=='mass')}, exp {sum(1 for c in cs2 if cs2[c]['layer']=='exp')}")
print(f"  нет: {[c for c in CH if c not in cs2]}")
for key in ("rx_1k", "rxv", "vps"):
    print(f"  {key:6s} x{gap(cs2, key):.2f}")

print("\n=== 6. Размер канала ===")
ls = [math.log10(cs[c]["subs"]) for c in CH]
for key in ("rx_1k", "rxv", "vps"):
    y = [cs[c][key] for c in CH]
    r = stats.spearmanr(ls, y).statistic
    print(f"  Спирмен(log subs, {key:6s}) по 20 каналам = {r:+.3f}")
    for lay in ("mass", "exp"):
        xs = [math.log10(cs[c]["subs"]) for c in CH if cs[c]["layer"] == lay]
        ys = [cs[c][key] for c in CH if cs[c]["layer"] == lay]
        print(f"      внутри {lay}: {stats.spearmanr(xs, ys).statistic:+.3f} (n={len(xs)})")
# OLS: log rx_1k ~ log subs + layer ; бутстрэп по каналам
X = np.array([[1, math.log10(cs[c]["subs"]), 1.0 if cs[c]["layer"] == "exp" else 0.0] for c in CH])
for key in ("rx_1k", "rxv"):
    y = np.array([math.log(cs[c][key]) for c in CH])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    rng = np.random.default_rng(3)
    bb = []
    for _ in range(4000):
        idx = rng.integers(0, len(CH), len(CH))
        if len(set(X[idx, 2])) < 2:
            continue
        bb.append(np.linalg.lstsq(X[idx], y[idx], rcond=None)[0])
    bb = np.array(bb)
    lo, hi = np.percentile(bb[:, 2], [2.5, 97.5])
    los, his = np.percentile(bb[:, 1], [2.5, 97.5])
    print(f"  OLS log({key}) ~ log10(subs) + exp: коэф. размера {b[1]:+.2f} [{los:+.2f},{his:+.2f}] "
          f"(на x10 подписчиков -> x{math.exp(b[1]):.2f}); "
          f"слой exp: x{math.exp(b[2]):.2f} [{math.exp(lo):.2f}, {math.exp(hi):.2f}]")
# сравнение в зоне перекрытия размеров
ov = [c for c in CH if 1.5e5 <= cs[c]["subs"] <= 7e5]
print(f"  зона перекрытия 150K-700K: {[(c, cs[c]['layer'], round(cs[c]['rx_1k'],2), round(cs[c]['rxv'],2)) for c in ov]}")

print("\n=== 7. 'Гигиена реакций': реакций на 'голосующего' (rx/max chip) ===")
for lay in ("mass", "exp"):
    v = [cs[c]["rx_per_vote"] for c in CH if cs[c]["layer"] == lay]
    print(f"  {lay}: медиана rx/votes = {st.median(v):.2f} (каналы {min(v):.2f}-{max(v):.2f})")
print("\n=== Канальная таблица ===")
for c in sorted(CH, key=lambda c: -cs[c]["subs"]):
    v = cs[c]
    print(f"  {c:28s} {v['layer']:4s} subs={v['subs']:>9,.0f} f={v['freq']:5.1f} "
          f"rx_1k={v['rx_1k']:6.3f} vps={v['vps']:6.3f} rxv={v['rxv']:5.2f}% rx/vote={v['rx_per_vote']:4.2f}")
