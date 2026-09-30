"""R6. Рекламодатели и реклама в корпусе.

Реклама определяется только по явной маркировке (закон о рекламе РФ): «Реклама. Рекламодатель …»,
erid в тексте, erid= в ссылке (кроме ссылки на собственный канал), #реклама / #ad.
Немаркированная реклама этим не ловится — её доля оценивается ручной разметкой выборки (R2).

Выход: data/r/ads.json + печать сводок.
"""
import json, os, re, statistics as st, sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT, advertiser, is_marked_ad, load  # noqa: E402

C = load()
rows, per_ch = [], {}
for ch, d in C.items():
    ps = d["posts"]
    subs = (d["meta"] or {}).get("counters", {}).get("subscribers")
    ads = [p for p in ps if is_marked_ad(p)]
    per_ch[ch] = {"subs": subs, "posts": len(ps), "ads": len(ads)}
    for p in ads:
        name, inn = advertiser(p)
        doms = [urlparse(u).netloc.lower().removeprefix("www.") for u, _ in p.get("links") or []]
        rows.append({"ch": ch, "id": p["id"], "dt": p["dt"], "views": p.get("views"), "advertiser": name,
                     "inn": inn, "domains": sorted(set(d for d in doms if d and "t.me" not in d)),
                     "tg": sorted({re.search(r"t\.me/([A-Za-z0-9_]+)", u).group(1) for u, _ in p.get("links") or []
                                   if re.search(r"t\.me/([A-Za-z0-9_]+)", u)} - {ch}),
                     "text": (p.get("text") or "")[:300]})

band = lambda s: "?" if not s else "<10K" if s < 1e4 else "10–50K" if s < 5e4 else "50–200K" if s < 2e5 else "200K–1M" if s < 1e6 else "1M+"
print(f"каналов {len(C)}, постов {sum(v['posts'] for v in per_ch.values())}, маркированной рекламы {len(rows)}")
print("\nДоля маркированной рекламы по полосам (медиана по каналам; каналов с ≥1 рекламой):")
for b in ["10–50K", "50–200K", "200K–1M", "1M+"]:
    sel = [v for v in per_ch.values() if band(v["subs"]) == b and v["posts"] >= 10]
    if sel:
        print(f"  {b:8s} каналов {len(sel):4d}  медиана {100 * st.median(v['ads'] / v['posts'] for v in sel):4.1f} %  "
              f"с рекламой {sum(1 for v in sel if v['ads'])}")

key = lambda r: r["inn"] or (r["advertiser"] or "").lower() or None
adv = defaultdict(lambda: {"posts": 0, "channels": set(), "names": Counter(), "domains": Counter(), "tg": Counter()})
for r in rows:
    k = key(r) or ("dom:" + r["domains"][0] if r["domains"] else "tg:" + r["tg"][0] if r["tg"] else "?")
    a = adv[k]
    a["posts"] += 1
    a["channels"].add(r["ch"])
    if r["advertiser"]:
        a["names"][r["advertiser"]] += 1
    a["domains"].update(r["domains"])
    a["tg"].update(r["tg"])
print(f"\nРекламодателей (по ИНН / названию / домену): {len(adv)}")
top = sorted(adv.items(), key=lambda x: (-len(x[1]["channels"]), -x[1]["posts"]))
for k, a in top[:40]:
    nm = a["names"].most_common(1)[0][0] if a["names"] else k
    print(f"  {nm[:45]:45s} постов {a['posts']:3d} каналов {len(a['channels']):3d}  "
          f"{', '.join(d for d, _ in a['domains'].most_common(2))} {', '.join('@' + t for t, _ in a['tg'].most_common(2))}")
json.dump({"per_channel": per_ch, "ads": rows,
           "advertisers": [{"key": k, "name": (a["names"].most_common(1)[0][0] if a["names"] else None),
                            "posts": a["posts"], "channels": sorted(a["channels"]),
                            "domains": a["domains"].most_common(5), "tg": a["tg"].most_common(5)} for k, a in top]},
          open(os.path.join(ROOT, "data", "r", "ads.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
