"""Дополнение к audit_behaviour_topics.py: величина эффекта тем в единицах rx/views
(множитель, FE канала + контроль длины/медиа/возраста), неоднородность по слоям,
просмотры (охват) тех же постов и микс реакций тем «РФ/суд».
Запуск: python tools/audit_behaviour_topics2.py
"""
import math, random, re, statistics as st
import numpy as np
from audit_behaviour_common import load, by_channel
import audit_behaviour_topics as T   # переиспользуем регулярки (модуль выполнит свой вывод)

rows, per, CH = T.rows, T.per, T.CH
for ch, ps in per.items():
    for key in ("rxv", "views", "rx"):
        m = st.mean(math.log(r[key]) for r in ps)
        for r in ps:
            r["dl_" + key] = math.log(r[key]) - m
NEG = {"👎", "🤬", "😭", "😢", "💩", "🤮", "😡"}
for r in rows:
    tot = sum(v for k, v in r["br"].items() if k != "?")
    r["neg"] = sum(v for k, v in r["br"].items() if k in NEG) / tot if tot else 0


def boot(y, xs, rows_=None, n=600, seed=9):
    rows_ = rows_ or rows
    chs = sorted({r["ch"] for r in rows_})
    byc = {c: [r for r in rows_ if r["ch"] == c] for c in chs}
    est = T.fe_coef(rows_, y, xs)[0]
    rng = random.Random(seed)
    bs = []
    for _ in range(n):
        rr = []
        for j, c in enumerate(rng.choice(chs) for _ in chs):
            for r in byc[c]:
                q = dict(r); q["ch"] = f"{c}#{j}"; rr.append(q)
        bs.append(T.fe_coef(rr, y, xs)[0])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return est, lo, hi


print("\n\n########## topics2 ##########")
print("=== A. Множитель rx/views (exp коэф. log rxv), FE канала + log длины + медиа + log возраста ===")
KEYS = ["релиз модели", "Google/Gemini", "Россия/локальное", "суд/регулирование",
        "релиз модели (строго)", "Google (строго)", "Россия (строго)", "суд/регулир. (строго)"]
for k in KEYS:
    for y in ("dl_rxv", "dl_views"):
        e, lo, hi = boot(y, ["T:" + k, "llen", "media", "lage"])
        print(f"  {k:24s} {y:8s} x{math.exp(e):.3f} [{math.exp(lo):.3f}, {math.exp(hi):.3f}]")
print("\n=== B. Неоднородность по слою (процентиль, FE) ===")
for k in ("релиз модели (строго)", "Google (строго)", "Россия (строго)", "суд/регулир. (строго)"):
    for lay in ("mass", "exp"):
        sub = [r for r in rows if r["layer"] == lay]
        e, lo, hi = boot("pct", ["T:" + k, "llen", "media", "lage"], sub)
        print(f"  {k:24s} {lay:4s} {e:+.3f} [{lo:+.3f}, {hi:+.3f}]")
print("\n=== C. Доля негативных реакций (👎🤬😭😢💩🤮😡), медиана ===")
for k in ("Россия (строго)", "суд/регулир. (строго)", "релиз модели (строго)"):
    a = [r["neg"] for r in rows if r["T:" + k]]
    b = [r["neg"] for r in rows if not r["T:" + k]]
    print(f"  {k:24s} в теме {st.mean(a)*100:.1f}% (среднее)  вне темы {st.mean(b)*100:.1f}%")
e, lo, hi = boot("pct", ["neg", "llen", "media", "lage"])
print(f"  процентиль rx/views ~ доля негатива (FE): {e:+.3f} [{lo:+.3f}, {hi:+.3f}] (пост-хок, описательно)")
