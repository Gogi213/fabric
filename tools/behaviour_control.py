"""Контроль возраста поста и концентрация реакций.

Проблема: views и реакции накапливаются со временем. Старый пост
покажет и просмотры, и реакции выше просто из-за возраста. Любой вывод
«какие посты лучше» без контроля возраста будет ложным.

Что делаем:
  1. измеряем связь возраст -> rx и возраст -> rx/1k
  2. пересчитываем топ-дециль ТОЛЬКО на свежих постах (<= 7 суток)
  3. смотрим концентрацию: сколько каналов/событий держат топ
  4. проверяем «эффект очереди»: первый пост пачки против следующих
"""
import json, re, statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timedelta

D = "C:/visual projects/parser/data/"
R = json.load(open(D + "reactions.json", encoding="utf-8"))

MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️‍↔️-🫿]")


def grp(ch):
    return "массовые" if ch in MASS else "экспертные"


rows = []
for ch, rec in R.items():
    subs = rec["subs"] or 0
    for p in rec["posts"]:
        if not p.get("dt") or not p["views"] or p["views"] <= 0:
            continue
        dt = datetime.fromisoformat(p["dt"].replace("Z", "+00:00"))
        rows.append({
            "ch": ch, "grp": grp(ch), "subs": subs, "dt": dt,
            "age": (NOW - dt).total_seconds() / 86400,
            "views": p["views"], "rx": p["rx"] or 0,
            "rx_views": (p["rx"] or 0) / p["views"] * 100,
            "rx_1k": (p["rx"] or 0) * 1000 / subs if subs else 0,
            "len": len(p["text"] or ""),
            "fwd": bool(p["fwd"]), "media": bool(p["media"]),
            "n_links": p.get("n_links", 0),
            "emo": len(EMOJI_RE.findall(p["text"] or "")),
            "text": re.sub(r"\s+", " ", p["text"] or "")[:200],
        })

rows.sort(key=lambda r: r["dt"])
for ch in R:
    ps = sorted([r for r in rows if r["ch"] == ch], key=lambda r: r["dt"])
    # «очередь»: расстояние от предыдущего поста того же канала
    prev = None
    for r in ps:
        r["gap_h"] = (r["dt"] - prev).total_seconds() / 3600 if prev else 999
        prev = r["dt"]

print("=" * 118)
print("1. ВОЗРАСТ ПОСТА: насколько он искажает выводы")
print("=" * 118)
ages = sorted(r["age"] for r in rows)
qa = lambda p: ages[int(len(ages) * p)]
print(f"  возраст (сут): p10={qa(.10):.1f}  p25={qa(.25):.1f}  медиана={qa(.50):.1f}  "
      f"p75={qa(.75):.1f}  p90={qa(.90):.1f}  макс={ages[-1]:.1f}")
print()
print("  бины возраста -> медиана просмотров / реакций / rx/1k")
abins = [(0, 3), (3, 7), (7, 14), (14, 30), (30, 60), (60, 10000)]
for lo, hi in abins:
    sel = [r for r in rows if lo <= r["age"] < hi]
    if not sel:
        continue
    print(f"    {lo:3d}-{hi if hi < 9999 else 999:4d} сут: n={len(sel):5d}  "
          f"просм={st.median(r['views'] for r in sel):9,.0f}  "
          f"реакц={st.median(r['rx'] for r in sel):7,.0f}  "
          f"rx/1k={st.median(r['rx_1k'] for r in sel):5.2f}  "
          f"rx/просм={st.median(r['rx_views'] for r in sel):5.2f}%")


def spearman(a, b):
    n = len(a)
    if n < 3:
        return None
    def ranks(xs):
        idx = sorted(range(len(xs)), key=lambda i: xs[i])
        rk = [0.0] * len(xs)
        i = 0
        while i < len(idx):
            j = i
            while j + 1 < len(idx) and xs[idx[j + 1]] == xs[idx[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                rk[idx[k]] = avg
            i = j + 1
        return rk
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    nu = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    de = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** .5
    return nu / de if de else 0.0


A = [r["age"] for r in rows]
for m in ("views", "rx", "rx_1k", "rx_views"):
    print(f"  возраст vs {m:9s} rho = {spearman(A, [r[m] for r in rows]):+.3f}")

print("\n" + "=" * 118)
print("2. ТОП-ДЕЦИЛЬ С КОНТРОЛЕМ ВОЗРАСТА (только посты <= 7 суток)")
print("=" * 118)
fresh = [r for r in rows if r["age"] <= 7]
print(f"  свежих постов: {len(fresh)} из {len(rows)} "
      f"({len(fresh)/len(rows)*100:.0f} %), по {len(set(r['ch'] for r in fresh))} каналам")
fs = sorted(r["rx_1k"] for r in fresh)
thr = fs[int(len(fs) * .90)]
print(f"  порог rx/1k в свежей выборке: p90 = {thr:.2f}")
top = [r for r in fresh if r["rx_1k"] >= thr]
rest = [r for r in fresh if r["rx_1k"] < thr]
print(f"  топ: {len(top)} постов из {len(fresh)}")
print()
FEATS = [("длина текста", lambda r: r["len"]),
         ("эмодзи", lambda r: r["emo"]),
         ("ссылок", lambda r: r["n_links"]),
         ("подписчиков", lambda r: r["subs"] / 1000),
         ("возраст, сут", lambda r: r["age"])]
print(f"  {'признак':20s} {'ТОП':>20s} {'ОСТАЛЬНЫЕ':>20s}   дельта")
for name, f in FEATS:
    a = sorted(f(r) for r in top)
    b = sorted(f(r) for r in rest)
    ma, mb = st.median(a), st.median(b)
    d = (ma / mb - 1) * 100 if mb else 0
    print(f"  {name:20s} {ma:10,.1f} (IQR {a[len(a)//4]:,.0f}-{a[3*len(a)//4]:,.0f})  "
          f"{mb:10,.1f} (IQR {b[len(b)//4]:,.0f}-{b[3*len(b)//4]:,.0f})  {d:+7.1f}%")
for nm, f in [("форвард", lambda r: r["fwd"]), ("с медиа", lambda r: r["media"]),
              ("без ссылок", lambda r: r["n_links"] == 0),
              ("без эмодзи", lambda r: r["emo"] == 0)]:
    print(f"  доля '{nm:10s}': топ {sum(1 for r in top if f(r))/len(top)*100:5.1f}%  "
          f"остальные {sum(1 for r in rest if f(r))/len(rest)*100:5.1f}%")

print("\n  --- rx/1k по бинам длины (только свежие) ---")
for lo, hi in abins[:0] or [(0, 150), (150, 300), (300, 600), (600, 1000),
                            (1000, 1800), (1800, 100000)]:
    sel = [r["rx_1k"] for r in fresh if lo <= r["len"] < hi]
    if sel:
        print(f"    {lo:5d}-{hi if hi<99999 else 99999:5d} симв.: n={len(sel):4d}  "
              f"медиана {st.median(sel):5.2f}  "
              f"p90 {sorted(sel)[int(len(sel)*.9)]:5.2f}")

print("\n" + "=" * 118)
print("3. КОНЦЕНТРАЦИЯ: кто держит топ")
print("=" * 118)
cc = Counter(r["ch"] for r in top)
print(f"  топ-дециль ({len(top)} постов) распределён по {len(cc)} каналам:")
for ch, n in cc.most_common():
    ch_rows = [r for r in fresh if r["ch"] == ch]
    share = n / len(cc)
    print(f"    {ch:30s} {n:4d} постов  ({n/len(top)*100:5.1f}% топа)  "
          f"в выборке {len(ch_rows):4d} ({n/len(ch_rows)*100:5.1f}% своих)  "
          f"слой={'масс' if ch in MASS else 'эксп'}")
print(f"\n  ТОП-3 канала держат {sum(n for _, n in cc.most_common(3))/len(top)*100:.0f}% "
      f"верхнего дециля.")

print("\n" + "=" * 118)
print("4. ЭФФЕКТ ОЧЕРЕДИ: первый пост пачки против следующих (свежие)")
print("=" * 118)
first = [r for r in fresh if r["gap_h"] > 6]
follow = [r for r in fresh if 0.5 <= r["gap_h"] <= 6]
bursty = [r for r in fresh if r["gap_h"] <= 0.5]
for nm, sel in [("первый в пачке (пауза >6ч)", first),
                ("в пределах пачки (0.5-6ч)", follow),
                ("частая очередь (<0.5ч)", bursty)]:
    if sel:
        print(f"  {nm:30s} n={len(sel):4d}  rx/1k медиана={st.median(r['rx_1k'] for r in sel):5.2f}  "
              f"rx/просм={st.median(r['rx_views'] for r in sel):5.2f}%  "
              f"просм={st.median(r['views'] for r in sel):8,.0f}")

print("\n" + "=" * 118)
print("5. ЧАСТОТА vs РЕАКЦИИ, С КОНТРОЛЕМ ВОЗРАСТА (только свежие, >=40 постов)")
print("=" * 118)
per = defaultdict(list)
for r in fresh:
    per[r["ch"]].append(r)
print(f"  {'канал':22s} {'слой':5s} {'свежих':>7s} {'пост/сут':>9s} {'rx/1k медиана':>14s}")
xs, ys = [], []
for ch, rs in sorted(per.items(), key=lambda x: -len(x[1])):
    if len(rs) < 40:
        continue
    days = max(1.0, (max(r["dt"] for r in rs) - min(r["dt"] for r in rs)).total_seconds() / 86400)
    pd_ = len(rs) / days
    med = st.median(r["rx_1k"] for r in rs)
    xs.append(pd_)
    ys.append(med)
    print(f"  {ch:22s} {'масс' if ch in MASS else 'эксп':5s} {len(rs):7d} {pd_:9.1f} {med:14.2f}")
print(f"\n  rho(пост/сут, rx/1k) по свежим = {spearman(xs, ys):+.3f}  (n={len(xs)} каналов)")

print("\n" + "=" * 118)
print("6. ПРАВИЛО: СКОЛЬКО РЕАКЦИЙ НУЖНО НА ПОСТ (по возрасту, не по размеру канала)")
print("=" * 118)
for lo, hi in [(0, 1), (1, 3), (3, 7), (7, 14), (14, 30), (30, 10000)]:
    sel = [r for r in rows if lo <= r["age"] < hi]
    if not sel:
        continue
    s = sorted(r["rx_1k"] for r in sel)
    m = len(s)
    print(f"  возраст {lo:2d}-{hi if hi<9999 else 999:3d} сут: n={m:4d}  "
          f"rx/1k p50={s[m//2]:5.2f}  p90={s[int(m*.9)]:5.2f}  "
          f"-> на 10k подписчиков: {s[m//2]*10:6.1f} / {s[int(m*.9)]*10:6.1f} реакций")

json.dump({
    "age_effect": {m: spearman(A, [r[m] for r in rows]) for m in
                   ("views", "rx", "rx_1k", "rx_views")},
    "fresh_threshold_rx_1k_p90": thr,
    "fresh_top_channels": dict(cc),
    "volume_vs_rx_fresh_rho": spearman(xs, ys),
}, open(D + "behaviour_control.json", "w", encoding="utf-8"),
    ensure_ascii=False, indent=1)
print("\n  -> data/behaviour_control.json")
