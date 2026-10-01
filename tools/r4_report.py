"""R4. Откуда и когда приходят громкие сюжеты — по темам.

Вход: data/r/origins.json (tools/r4_origins.py), data/r/story_topics_raw.json + story_topic_names.json.
Строгое совпадение: косинус заголовка ≥ 0.68 и время публикации не заглушка (не 00:00:00 / 07:00:00 UTC —
Google News так подписывает материалы без времени; таких 40 %).
Лаг = первый пост в Telegram − самая ранняя найденная внешняя публикация (>0 — СМИ раньше).
Найденная публикация — верхняя граница «самой ранней»: индекс Google News неполон.
"""
import json, os, statistics as st, sys
from collections import Counter, defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT  # noqa: E402

D = os.path.join(ROOT, "data", "r")
R = json.load(open(os.path.join(D, "origins.json"), encoding="utf-8"))
T = json.load(open(os.path.join(D, "story_topics_raw.json"), encoding="utf-8"))
names = json.load(open(os.path.join(D, "story_topic_names.json"), encoding="utf-8"))
topic_of = {a: names[str(l)] for a, l in zip(T["anchors"], T["labels"])}

rows = []
for r in R:
    a = f"{r['members'][0]['ch']}/{r['members'][0]['id']}"
    ok = [f for f in r.get("matched") or [] if f["sim"] >= 0.68 and f["t"] % 86400 not in (0, 25200)]
    o = min(ok, key=lambda f: f["t"]) if ok else None
    lag = (datetime.fromisoformat(r["first_t"]).timestamp() - o["t"]) / 60 if o else None
    rows.append({"topic": topic_of.get(a, "(вне типологии)"), "lag": lag, "ed": o["ed"] if o else None,
                 "src": o["src"] if o else None, "n_ch": r["n_ch"]})


def band(x):
    return ("нет внешнего совпадения" if x is None else "Telegram раньше" if x < 0 else "≤1 ч после СМИ" if x <= 60
            else "1–6 ч после" if x <= 360 else ">6 ч после")


print(f"сюжетов {len(rows)}; со строгим внешним совпадением {sum(r['lag'] is not None for r in rows)}")
print("\nПо темам: n | Telegram раньше | ≤1 ч | 1–6 ч | >6 ч | нет совпадения | медиана лага, мин | издание самой ранней")
by = defaultdict(list)
for r in rows:
    by[r["topic"]].append(r)
out = {}
for t, rs in sorted(by.items(), key=lambda x: -len(x[1])):
    c = Counter(band(r["lag"]) for r in rs)
    lags = [r["lag"] for r in rs if r["lag"] is not None]
    ed = Counter(r["ed"] for r in rs if r["ed"])
    print(f"  {t[:44]:44s} {len(rs):3d} | {c['Telegram раньше']:3d} | {c['≤1 ч после СМИ']:3d} | {c['1–6 ч после']:3d} | "
          f"{c['>6 ч после']:3d} | {c['нет внешнего совпадения']:3d} | {st.median(lags) if lags else float('nan'):7.0f} | "
          f"{dict(ed)}")
    out[t] = {"n": len(rs), "bands": dict(c), "median_lag": st.median(lags) if lags else None, "editions": dict(ed)}
json.dump(out, open(os.path.join(D, "r4_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
