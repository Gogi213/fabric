"""Аудит §2-§3 docs/09 и строки README «Реакции: 1 245 377 | медиана 209 | 0.64 %».

Запуск: python tools/audit_behaviour_counts.py
"""
import json, os, statistics as st
from collections import Counter
from audit_behaviour_common import load, by_channel, channel_freq, NO_RX, MASS, DATA

allrows = load(include_norx=True)
rows = [r for r in allrows if r["ch"] not in NO_RX]
R = json.load(open(os.path.join(DATA, "reactions.json"), encoding="utf-8"))
raw_posts = sum(len(v["posts"]) for v in R.values())

print("=== 1. Счёт ===")
print(f"постов в файле {raw_posts}, с датой и views>0 {len(allrows)}, каналов {len(R)}")
print(f"из них у каналов без блока реакций {NO_RX}: {len(allrows)-len(rows)}")
print(f"постов с rx>0 среди всех: {sum(1 for r in allrows if r['rx_raw']>0)}; "
      f"среди 20 каналов с реакциями: {sum(1 for r in rows if r['rx_raw']>0)} из {len(rows)}")
print(f"сумма rx как в документе (сырой парсинг): {sum(r['rx_raw'] for r in allrows):,.0f}")
print(f"сумма rx c восстановлением K-фишек:       {sum(r['rx'] for r in allrows):,.0f}")
print(f"  из них фишка '?' (не эмодзи, вероятно звёзды): {sum(r['star'] for r in rows):,.0f}")
nk = Counter()
lost = Counter()
for r in rows:
    if r["nk"]:
        nk[r["ch"]] += r["nk"]
        lost[r["ch"]] += r["rx"] - r["rx_raw"]
print(f"K-фишек (>=1000, распознаны как 1..9): {sum(nk.values())} в "
      f"{sum(1 for r in rows if r['nk'])} постах; потеряно {sum(lost.values()):,.0f} реакций")
for ch, v in nk.most_common():
    n = sum(1 for r in rows if r["ch"] == ch)
    k = sum(1 for r in rows if r["ch"] == ch and r["nk"])
    print(f"   {ch:16s} постов с K-фишкой {k:3d}/{n} ({k/n*100:4.1f} %), потеряно {lost[ch]:9,.0f}")
print(f"постов с усечённой кастомной фишкой (невосстановимо): "
      f"{sum(1 for r in rows if r['trunc_custom'])}")

print("\n=== 2. Медианы (что именно 209 и 0.64 %) ===")
for lab, sel in [("все 4124 (как в docs/09)", allrows), ("20 каналов с реакциями", rows)]:
    for key in ("rx_raw", "rx"):
        xs = sorted(r[key] for r in sel)
        q = lambda p: xs[int(len(xs) * p)]
        print(f"  {lab:26s} {key:7s} p10={q(.1):.0f} p25={q(.25):.0f} med={st.median(xs):.0f} "
              f"p75={q(.75):.0f} p90={q(.9):.0f} p99={q(.99):.0f} max={xs[-1]:.0f} "
              f"доля 0={sum(1 for x in xs if x==0)/len(xs)*100:.1f}%")
    for key in ("rxv_raw", "rxv"):
        xs = sorted(r[key] for r in sel)
        print(f"  {lab:26s} {key:7s} медиана {st.median(xs):.3f} %  p90 {xs[int(len(xs)*.9)]:.3f} %")
tot_rx = sum(r["rx"] for r in rows)
tot_v = sum(r["views"] for r in rows)
print(f"  агрегат rx/views по 20 каналам: {tot_rx/tot_v*100:.3f} %")
# медиана медиан каналов
per = by_channel(rows)
mm = [st.median(r["rxv"] for r in ps) for ps in per.values()]
print(f"  медиана канальных медиан rx/views: {st.median(mm):.3f} % "
      f"(размах {min(mm):.2f}-{max(mm):.2f})")

print("\n=== 3. 12 типов реакций ===")
c12 = sum(1 for r in allrows if r["ntypes_raw"] >= 12)
print(f"постов с >=12 ключами: {c12} ({c12/len(allrows)*100:.1f}% от 4124, "
      f"{c12/len(rows)*100:.1f}% от {len(rows)})")
print(f"  с >=11 ключами {sum(1 for r in rows if r['ntypes_raw']>=11)}; "
      f"кастомные фишки слиты в один ключ -> реальное число фишек не наблюдаемо")
print("  по каналам:", Counter(r["ch"] for r in rows if r["ntypes_raw"] >= 12).most_common())

print("\n=== 4. Глубина окна по каналам ===")
for ch, ps in sorted(per.items(), key=lambda x: x[0] in MASS):
    f, span = channel_freq(ps)
    print(f"  {ch:28s} {'mass' if ch in MASS else 'exp ':4s} n={len(ps):3d} "
          f"окно={span:6.1f} сут  постов/сут={f:5.2f}  медиана возраста={st.median(r['age'] for r in ps):6.1f}")
for lay in ("mass", "exp"):
    sp = [channel_freq(ps)[1] for ch, ps in per.items() if ps[0]["layer"] == lay]
    print(f"  {lay}: медиана окна {st.median(sp):.1f} сут, размах {min(sp):.1f}-{max(sp):.1f}")

print("\n=== 5. Полнота текста ===")
L = [r["len"] for r in allrows]
print(f"  медиана длины {st.median(L):.0f}, макс {max(L)}, >600: {sum(1 for x in L if x>600)/len(L)*100:.1f}%")

print("\n=== 6. Таблица слоёв docs/09 §3 (медианы канальных медиан) ===")
for lay in ("mass", "exp"):
    chs = [ps for ps in per.values() if ps[0]["layer"] == lay]
    for key in ("rx_raw", "rx", "rxv", "rx_1k_raw", "rx_1k"):
        print(f"  {lay:4s} {key:9s} медиана медиан = "
              f"{st.median(st.median(r[key] for r in ps) for ps in chs):.3f}   "
              f"пул постов медиана = {st.median(r[key] for ps in chs for r in ps):.3f}")
