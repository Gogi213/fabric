"""R3. Отчёт по скорости и копированию среди НОВОСТНЫХ МЕДИА (типы каналов из data/r/channels.json).

Считает:
  * волна: через сколько минут после первого канала сюжет выходит во 2-м, 5-м, 10-м канале;
  * рейтинг скорости: доля «первым» и медианный ранг (0 — первый, 1 — последний) по сюжетам в ≥3 медиа;
  * доноры: кто чаще всех оказывается «родителем» более поздних постов с высокой дословностью (J ≥ 0.5);
  * синхронные группы: пары каналов, публикующие один сюжет с разницей ≤ 3 мин многократно (одна редакция/сеть).
Выход: data/r/r3_report.json + печать.
"""
import json, os, statistics as st, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT  # noqa: E402

D = os.path.join(ROOT, "data", "r")
MEDIA = {"Медиа: AI и тех-новости", "Медиа: массовые тех-развлекательные", "Медиа: гаджеты и железо",
         "Apple и смартфоны (медиа и магазины)", "Медиа: кибербез и мошенничество"}
CH = {c["handle"]: c for c in json.load(open(os.path.join(D, "channels.json"), encoding="utf-8"))}
media = {h for h, c in CH.items() if c["kind"] in MEDIA and (c.get("deal_share") or 0) < 0.3}
S = json.load(open(os.path.join(D, "stories.json"), encoding="utf-8"))
E = json.load(open(os.path.join(D, "copy_edges.json"), encoding="utf-8"))
out = {"n_media": len(media)}

# сюжеты только по медиа: первый пост каждого канала
ms = []
for s in S:
    first = {}
    for m in s["members"]:
        if m["ch"] in media and m["ch"] not in first:
            first[m["ch"]] = m
    if len(first) >= 2:
        t0 = min(x["lag_min"] for x in first.values())
        order = sorted(((ch, x["lag_min"] - t0) for ch, x in first.items()), key=lambda z: z[1])
        ms.append({"order": order, "text": s["text"], "first_t": s["first_t"]})
print(f"новостных медиа: {len(media)}; сюжетов в ≥2 медиа: {len(ms)}, ≥3: {sum(len(x['order']) >= 3 for x in ms)}, "
      f"≥10: {sum(len(x['order']) >= 10 for x in ms)}")

print("\nВолна: лаг k-го канала от первого (сюжеты, где каналов ≥ k), минуты")
wave = {}
for k in (2, 3, 5, 10, 20):
    v = [x["order"][k - 1][1] for x in ms if len(x["order"]) >= k]
    if v:
        q = sorted(v)
        wave[k] = {"n": len(v), "p25": q[len(q) // 4], "median": st.median(v), "p75": q[3 * len(q) // 4]}
        print(f"  {k:2d}-й канал: n={len(v):4d}  медиана {st.median(v):6.0f}  [p25 {q[len(q)//4]:.0f}; p75 {q[3*len(q)//4]:.0f}]")
out["wave"] = wave

part, first, ranks = Counter(), Counter(), defaultdict(list)
for x in ms:
    o = x["order"]
    if len(o) < 3:
        continue
    for r, (ch, lag) in enumerate(o):
        part[ch] += 1
        ranks[ch].append(r / (len(o) - 1))
    first[o[0][0]] += 1
rows = []
for ch, n in part.items():
    if n < 8:
        continue
    rows.append({"ch": ch, "kind": CH[ch]["kind"], "subs": CH[ch]["subs"], "posts_per_day": CH[ch]["posts_per_day"],
                 "stories": n, "first": first[ch], "first_share": round(first[ch] / n, 3),
                 "median_rank": round(st.median(ranks[ch]), 3)})
rows.sort(key=lambda r: (r["median_rank"], -r["first_share"]))
print("\nСамые быстрые медиа (сюжеты в ≥3 медиа, участие ≥8): медианный ранг 0 = всегда первый")
for r in rows[:30]:
    print(f"  @{r['ch']:24s} {r['kind'][:28]:28s} {str(r['subs']):>8s} {r['posts_per_day']:5.1f}/д  "
          f"сюжетов {r['stories']:3d} первым {r['first']:3d} ({100*r['first_share']:3.0f} %) ранг {r['median_rank']:.2f}")
out["speed"] = rows

# доноры среди медиа: родитель с J≥0.5 (почти дословно) и лаг ≤ 24 ч
don, rec, pairs = Counter(), Counter(), Counter()
for e in E:
    if e["from"] in media and e["to"] in media and e["J"] >= 0.5 and e["lag_min"] <= 1440 and not e["fwd"]:
        don[e["from"]] += 1
        rec[e["to"]] += 1
        pairs[(e["from"], e["to"])] += 1
print(f"\nПочти дословные повторы между медиа (J ≥ 0.5, без форвардов): {sum(don.values())}")
print("  чаще всего «оригинал»:", ", ".join(f"@{h}×{n}" for h, n in don.most_common(12)))
print("  чаще всего «повтор»:  ", ", ".join(f"@{h}×{n}" for h, n in rec.most_common(12)))
print("  пары:", ", ".join(f"@{a}→@{b}×{n}" for (a, b), n in pairs.most_common(12)))
out["verbatim_donors"] = don.most_common(30)
out["verbatim_pairs"] = [[a, b, n] for (a, b), n in pairs.most_common(50)]

# синхронные группы: один сюжет в двух медиа с разницей ≤ 3 мин
sync = Counter()
for x in ms:
    o = x["order"]
    for i in range(len(o)):
        for j in range(i + 1, len(o)):
            if abs(o[j][1] - o[i][1]) <= 3:
                sync[tuple(sorted((o[i][0], o[j][0])))] += 1
print("\nСинхронные пары (один сюжет с разницей ≤3 мин, ≥4 раз за 14 дней):")
print("  " + ", ".join(f"{a}+{b}×{n}" for (a, b), n in sync.most_common(20) if n >= 4))
out["sync_pairs"] = [[a, b, n] for (a, b), n in sync.most_common(60) if n >= 3]
json.dump(out, open(os.path.join(D, "r3_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
