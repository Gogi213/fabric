"""R1/R9. Сравнение категорий-кандидатов для третьего канала.

Вход: data/r/corpus/*.meta.json.gz (первая страница: ~20 последних постов) по списку
data/r/crawl_list_categories.txt (7 категорий × 20 крупнейших + 20 из полосы 10–50K) и перепись каталога.
Метрики по каналу: постов/сутки (по 20 последним постам), просмотры/подписчики, реакции/просмотр,
доля маркированной рекламы, платные звёзды, доля кириллицы.
"""
import gzip, json, os, re, statistics as st, sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT, is_marked_ad  # noqa: E402

D = os.path.join(ROOT, "data", "r")
cat_of, band_of = {}, {}
for line in open(os.path.join(D, "crawl_list_categories.txt"), encoding="utf-8"):
    if "#" in line and not line.startswith("#"):
        h, rest = line.split("#", 1)
        cat, subs = rest.split()
        cat_of[h.strip()] = cat
        band_of[h.strip()] = "крупные" if int(float(subs)) >= 5e4 else "10–50K"

rows = []
for h, cat in cat_of.items():
    p = os.path.join(D, "corpus", h + ".meta.json.gz")
    if not os.path.exists(p):
        continue
    d = json.load(gzip.open(p, "rt", encoding="utf-8"))
    ps = [x for x in d["posts"] if x.get("dt")]
    subs = ((d.get("meta") or {}).get("counters") or {}).get("subscribers")
    if len(ps) < 5 or not subs:
        continue
    for x in ps:
        x["_ch"] = h
    ts = sorted(datetime.fromisoformat(x["dt"]) for x in ps)
    span = max((ts[-1] - ts[0]).total_seconds() / 86400, 0.05)
    age = (datetime.fromisoformat(d["crawl"]["fetched_at"]) - ts[-1]).total_seconds() / 86400
    views = [x["views"] for x in ps if x.get("views")]
    rx = [x["rx_total"] / x["views"] for x in ps if x.get("views") and x.get("has_rx_block")]
    txt = " ".join(x.get("text") or "" for x in ps)
    let = re.findall(r"[A-Za-zА-Яа-яЁё]", txt)
    rows.append({"h": h, "cat": cat, "band": band_of[h], "subs": subs,
                 "ppd": len(ps) / span, "days_since_last": age,
                 "er": st.median(views) / subs if views else None,
                 "rxv": st.median(rx) if rx else None,
                 "ad": sum(is_marked_ad(x) for x in ps) / len(ps),
                 "stars": sum(x.get("rx_paid_stars") or 0 for x in ps),
                 "cyr": sum(1 for c in let if re.match(r"[А-Яа-яЁё]", c)) / len(let) if let else None})

census = json.load(open(os.path.join(D, "census_menu.json"), encoding="utf-8"))
print(f"каналов с данными: {len(rows)}")
print(f"\n{'категория':10s} {'в каталоге 10–50K':>17s} {'50K+':>6s} | {'полоса':8s} {'n':>3s} {'пост/сут':>8s} "
      f"{'просм/подп':>10s} {'реакц/просм':>11s} {'реклама':>8s} {'со звёздами':>11s} {'кирилл.':>8s}")
out = {}
for cat in ["crypto", "economy", "games", "news", "business", "marketing", "education"]:
    items = {}
    for v in census[cat]["pages"].values():
        for h, s in v:
            if s:
                items[h] = max(items.get(h, 0), s)
    n_mid = sum(1 for s in items.values() if 1e4 <= s < 5e4)
    n_big = sum(1 for s in items.values() if s >= 5e4)
    for b in ["10–50K", "крупные"]:
        sel = [r for r in rows if r["cat"] == cat and r["band"] == b]
        if not sel:
            continue
        med = lambda k: st.median([r[k] for r in sel if r[k] is not None])
        print(f"{cat:10s} {n_mid:17d} {n_big:6d} | {b:8s} {len(sel):3d} {med('ppd'):8.1f} {100*med('er'):9.1f}% "
              f"{100*med('rxv'):10.2f}% {100*st.mean(r['ad'] for r in sel):7.1f}% "
              f"{sum(1 for r in sel if r['stars'] > 0):5d}/{len(sel):<5d} {100*med('cyr'):7.0f}%")
        out[f"{cat}|{b}"] = {"n": len(sel), "ppd": med("ppd"), "er": med("er"), "rxv": med("rxv"),
                             "ad_mean": st.mean(r["ad"] for r in sel), "catalog_mid": n_mid, "catalog_big": n_big}
json.dump({"summary": out, "rows": rows}, open(os.path.join(D, "r1_categories.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
