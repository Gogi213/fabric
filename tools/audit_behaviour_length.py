"""Аудит правила длины «пост <300 символов: +17.8 п.п., CI [+13.7,+22.0]» (docs/09 §5, README)
и формата (медиа/ссылки/форвард, §5.2).

1) воспроизведение статистики документа (доли коротких в топ-20 % vs низ-50 %);
2) что это за величина и как её перевести в P(топ | короткий);
3) внутриканальная регрессия (FE канала) с контролями, CI бутстрэпом по каналам;
4) разложение rx/views на rx и views; реакция-микс коротких постов (мемность).
Запуск: python tools/audit_behaviour_length.py
"""
import math, random, re, statistics as st
import numpy as np
from audit_behaviour_common import load, by_channel, top_low_pools

rows = load()
per = by_channel(rows)
CH = sorted(per)
TOPIC = {  # регулярки stats_audit.py — для контроля темы
    "release": r"выпуст|релиз|запуст|нов(ая|ую) модель|анонс",
    "google": r"google|gemini|deepmind|qwen",
    "russia": r"росси|\bрф\b|сбер|яндекс|вконтакте|гос",
    "law": r"суд|регулятор|закон|штраф|\bban\b|запрет",
    "fun": r"прикол|мем|смешн|лол|хаха|🤡|🗿|пхд|аху",
}
LAUGH = {"😁", "🤣", "😂", "🗿", "🤡"}

for r in rows:
    r["short"] = 1.0 if r["len"] < 300 else 0.0
    r["haslink"] = 1.0 if r["links"] > 0 else 0.0
    r["lage"] = math.log(max(r["age"], .05))
    r["fresh"] = 1.0 if r["age"] < 2 else 0.0
    for k, p in TOPIC.items():
        r["t_" + k] = 1.0 if re.search(p, r["text"], re.I) else 0.0
    tot = sum(v for k, v in r["br"].items() if k != "?")
    r["laugh"] = sum(v for k, v in r["br"].items() if k in LAUGH) / tot if tot else 0

# внутриканальные ранги
for ch, ps in per.items():
    for key in ("rxv", "rxv_raw"):
        s = sorted(ps, key=lambda r: r[key])
        for i, r in enumerate(s):
            r["pct_" + key] = (i + .5) / len(s)
    for key in ("rxv", "rx", "views"):
        m = st.mean(math.log(r[key]) for r in ps)
        for r in ps:
            r["dl_" + key] = math.log(r[key]) - m


def pools_stat(chs, key):
    sub = {c: per[c] for c in chs}
    top, low = top_low_pools(sub, key=key)
    a = sum(1 for r in top if r["len"] < 300) / len(top)
    b = sum(1 for r in low if r["len"] < 300) / len(low)
    return (a - b) * 100, a * 100, b * 100, len(top), len(low)


print("=== 1. Статистика документа ===")
for key in ("rxv_raw", "rxv"):
    d, a, b, nt, nl = pools_stat(CH, key)
    rng = random.Random(11)
    bs = sorted(pools_stat([rng.choice(CH) for _ in CH], key)[0] for _ in range(2000))
    print(f"  {key:7s} топ {a:.1f}% vs низ {b:.1f}%  разрыв {d:+.1f} п.п. (n={nt}/{nl}); "
          f"бутстрэп по КАНАЛАМ CI [{bs[50]:+.1f}, {bs[1949]:+.1f}]")
per_ch = []
for c in CH:
    d, a, b, _, _ = pools_stat([c], "rxv")
    per_ch.append((d, c))
print(f"  по каналам разрыв >0 в {sum(1 for d,_ in per_ch if d>0)} из {len(CH)}; "
      f"медиана {st.median(d for d,_ in per_ch):+.1f} п.п.; мин {min(per_ch)[0]:+.1f} ({min(per_ch)[1]}), "
      f"макс {max(per_ch)[0]:+.1f} ({max(per_ch)[1]})")
print(f"  доля коротких по каналам: " +
      ", ".join(f"{c}:{sum(r['short'] for r in per[c])/len(per[c])*100:.0f}%" for c in CH))

print("\n=== 2. Перевод в вероятность: P(топ-20 % канала | короткий) vs | длинный ===")
top, low = top_low_pools(per, key="rxv")
topset = {id(r) for r in top}
s = [r for r in rows if r["short"]]
l = [r for r in rows if not r["short"]]
ps_ = sum(1 for r in s if id(r) in topset) / len(s)
pl_ = sum(1 for r in l if id(r) in topset) / len(l)
print(f"  P(топ|<300)={ps_*100:.1f}%  P(топ|>=300)={pl_*100:.1f}%  разница {(ps_-pl_)*100:+.1f} п.п., "
      f"отношение x{ps_/pl_:.2f}")
print(f"  медиана внутриканального процентиля rx/views: короткие {st.median(r['pct_rxv'] for r in s):.3f}, "
      f"длинные {st.median(r['pct_rxv'] for r in l):.3f}")


# ---------------------------------------------------------- FE-регрессия
def fe_ols(rows_, y, xs):
    """OLS на внутриканально центрированных переменных. Возвращает коэф."""
    byc = {}
    for r in rows_:
        byc.setdefault(r["ch"], []).append(r)
    Y, X = [], []
    for c, ps in byc.items():
        my = st.mean(r[y] for r in ps)
        mx = [st.mean(r[x] for r in ps) for x in xs]
        for r in ps:
            Y.append(r[y] - my)
            X.append([r[x] - m for x, m in zip(xs, mx)])
    b = np.linalg.lstsq(np.array(X), np.array(Y), rcond=None)[0]
    return b


def fe_boot(rows_, y, xs, n=1000, seed=5):
    byc = {}
    for r in rows_:
        byc.setdefault(r["ch"], []).append(r)
    chs = sorted(byc)
    rng = random.Random(seed)
    est = fe_ols(rows_, y, xs)
    bs = []
    for _ in range(n):
        pick = [rng.choice(chs) for _ in chs]
        rr = []
        for j, c in enumerate(pick):
            for r in byc[c]:
                q = dict(r)
                q["ch"] = f"{c}#{j}"
                rr.append(q)
        bs.append(fe_ols(rr, y, xs))
    bs = np.array(bs)
    lo, hi = np.percentile(bs, [2.5, 97.5], axis=0)
    return est, lo, hi


def show(title, rows_, y, xs, transform=None):
    est, lo, hi = fe_boot(rows_, y, xs)
    print(f"  {title} (n={len(rows_)}, каналов={len({r['ch'] for r in rows_})})")
    for i, x in enumerate(xs):
        if transform:
            print(f"     {x:10s} x{math.exp(est[i]):.3f}  [{math.exp(lo[i]):.3f}, {math.exp(hi[i]):.3f}]")
        else:
            print(f"     {x:10s} {est[i]:+.4f}  [{lo[i]:+.4f}, {hi[i]:+.4f}]")


print("\n=== 3. Внутриканальная регрессия, CI бутстрэп по каналам (1000) ===")
show("процентиль rx/views ~ short (без контролей)", rows, "pct_rxv", ["short"])
CTRL = ["short", "media", "fwd", "haslink", "lage", "fresh",
        "t_release", "t_google", "t_russia", "t_law", "t_fun"]
show("процентиль rx/views ~ short + контроли", rows, "pct_rxv", CTRL)
show("log rx/views ~ short + контроли (множитель)", rows, "dl_rxv", CTRL, transform=True)
show("log rx (абсолют) ~ short + контроли", rows, "dl_rx", CTRL, transform=True)
show("log views ~ short + контроли", rows, "dl_views", CTRL, transform=True)
mid = [r for r in rows if 2 <= r["age"] <= 30]
show("процентиль rx/views ~ short, только возраст 2-30 сут", mid, "pct_rxv", ["short", "media", "lage"])
show("с медиа: процентиль ~ short", [r for r in rows if r["media"]], "pct_rxv", ["short", "lage"])
show("без медиа: процентиль ~ short", [r for r in rows if not r["media"]], "pct_rxv", ["short", "lage"])

print("\n=== 4. Механика: короткие посты = мемы/картинки? ===")
for nm, sel in (("<300", s), (">=300", l)):
    print(f"  {nm:5s} n={len(sel):4d} с медиа {sum(r['media'] for r in sel)/len(sel)*100:.1f}%  "
          f"доля смеховых реакций (😁🤣😂🗿🤡) медиана {st.median(r['laugh'] for r in sel)*100:.1f}%  "
          f"с ссылкой {sum(r['haslink'] for r in sel)/len(sel)*100:.1f}%")
low_l = [r for r in rows if r["laugh"] < .25]
show("посты с долей смеховых реакций <25 % (пост-хок фильтр!)", low_l, "pct_rxv", ["short", "media", "lage"])
bins = [(0, 150), (150, 300), (300, 600), (600, 1000), (1000, 1800), (1800, 10 ** 6)]
for lo_, hi_ in bins:
    for r in rows:
        r[f"b{lo_}"] = 1.0 if lo_ <= r["len"] < hi_ else 0.0
show("процентиль ~ бины длины (база 300-600) + media + lage", rows, "pct_rxv",
     ["b0", "b150", "b600", "b1000", "b1800", "media", "lage"])

print("\n=== 5. Формат (§5.2): внутриканальные эффекты медиа/ссылки/форварда ===")
show("процентиль ~ media + haslink + fwd + short + lage", rows, "pct_rxv",
     ["media", "haslink", "fwd", "short", "lage"])
d, a, b, _, _ = pools_stat(CH, "rxv")
top, low = top_low_pools(per, key="rxv")
for nm, f in (("media", lambda r: r["media"]), ("haslink", lambda r: r["haslink"]), ("fwd", lambda r: r["fwd"])):
    pa = sum(1 for r in top if f(r)) / len(top) * 100
    pb = sum(1 for r in low if f(r)) / len(low) * 100
    rng = random.Random(3)
    bs = []
    for _ in range(1000):
        pick = [rng.choice(CH) for _ in CH]
        sub = {}
        for j, c in enumerate(pick):
            sub[f"{c}#{j}"] = per[c]
        t2, l2 = top_low_pools(sub, key="rxv")
        bs.append((sum(1 for r in t2 if f(r)) / len(t2) - sum(1 for r in l2 if f(r)) / len(l2)) * 100)
    bs.sort()
    print(f"  внутриканально топ-20 vs низ-50: {nm:8s} {pa:.1f}% vs {pb:.1f}%  {pa-pb:+.1f} п.п. "
          f"CI каналы [{bs[25]:+.1f}, {bs[974]:+.1f}]")
