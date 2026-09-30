"""Поведенческий анализ: какие посты вызывают реакции, и как объём канала
связан с реакциями.

Метрики:
  rx            — сумма всех реакций (может >100% от просмотров: один
                  пользователь ставит несколько разных эмодзи)
  rx/views      — реакций на просмотр (вовлечённость охвата)
  rx_1k_subs    — реакций на 1000 подписчиков (размер канала снят)

Вход:  data/reactions.json
Выход: data/behaviour.json
"""
import json, re, statistics as st, os
from collections import Counter, defaultdict
from datetime import datetime

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data") + os.sep
R = json.load(open(D + "reactions.json", encoding="utf-8"))

MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
EXPERTS = ["xor_journal", "neuraldvig", "data_secrets", "seeallochnaya",
           "denissexy", "ai_newz", "cgevent", "NeuralShit",
           "ai_machinelearning_big_data", "tproger", "tlive"]

EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️‍↔️-🫿]")
WORD_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ][a-zA-Zа-яА-ЯёЁ0-9+#.-]{2,}")


def grp(ch):
    return "массовые" if ch in MASS else "экспертные"


def safe_div(a, b):
    return a / b if b else 0.0


def rank_pct(xs, x):
    """процентиль x в выборке xs"""
    return sum(1 for v in xs if v < x) / len(xs) * 100 if xs else 0.0


rows = []
for ch, rec in R.items():
    subs = rec["subs"] or 0
    for p in rec["posts"]:
        if not p.get("dt") or not p["views"] or p["views"] <= 0:
            continue
        dt = datetime.fromisoformat(p["dt"].replace("Z", "+00:00"))
        txt = p["text"] or ""
        rows.append({
            "ch": ch, "grp": grp(ch), "subs": subs,
            "id": p["id"], "dt": dt, "views": p["views"], "rx": p["rx"] or 0,
            "rx_views": safe_div(p["rx"] or 0, p["views"]) * 100,
            "rx_1k": safe_div((p["rx"] or 0) * 1000, subs),
            "len": len(txt), "fwd": bool(p["fwd"]), "media": bool(p["media"]),
            "n_links": p.get("n_links", 0),
            "emo": len(EMOJI_RE.findall(txt)),
            "hour": dt.hour, "dow": dt.weekday(),
            "text": txt[:600],
            "rx_break": p.get("rx_break") or {},
        })

print("=" * 122)
print(f"БАЗА: {len(rows)} постов с валидными views и датой, "
      f"{len(R)} каналов, {sum(1 for r in rows if r['rx'])} с реакциями>0")
print("=" * 122)

# ---------------------------------------------------------------- 1. каналы
print("\n" + "=" * 122)
print("1. ОБЪЁМ КАНАЛА vs РЕАКЦИИ  (ключевой вопрос исследования)")
print("=" * 122)
print(f"  {'канал':22s} {'слой':5s} {'подп.':>10s} {'пост/сут':>9s} "
      f"{'медиана':>8s} {'rx/просм':>9s} {'rx/1ksub':>9s}")
chan = {}
for ch, rec in R.items():
    rs = [r for r in rows if r["ch"] == ch]
    if len(rs) < 30:
        continue
    dts = sorted(r["dt"] for r in rs)
    days = (dts[-1] - dts[0]).total_seconds() / 86400 + 1
    per_day = len(rs) / days
    med_rx = st.median(r["rx"] for r in rs)
    rxv = st.median(r["rx_views"] for r in rs)
    rxk = st.median(r["rx_1k"] for r in rs)
    chan[ch] = {"grp": grp(ch), "subs": rec["subs"], "per_day": per_day,
                "med_rx": med_rx, "rx_views": rxv, "rx_1k": rxk, "n": len(rs)}
for ch, v in sorted(chan.items(), key=lambda x: -x[1]["per_day"]):
    print(f"  {ch:22s} {'масс' if v['grp']=='массовые' else 'эксп':5s} "
          f"{v['subs']:10,.0f} {v['per_day']:9.1f} {v['med_rx']:8,.0f} "
          f"{v['rx_views']:8.2f}% {v['rx_1k']:9.1f}")

act = [v for v in chan.values() if v["rx_1k"] > 0]
print()
print("  --- корреляции (Спирмен, ранги) ---")


def spearman(a, b):
    n = len(a)
    if n < 3:
        return None
    ra = {v: i for i, v in enumerate(sorted(a))}
    rb = {v: i for i, v in enumerate(sorted(b))}
    # ранги с допуском равных значений
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
    num_ = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = (sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb)) ** 0.5
    return num_ / den if den else 0.0


pd_ = [v["per_day"] for v in act]
for metric in ("rx_1k", "rx_views", "med_rx"):
    m = [v[metric] for v in act]
    s = spearman(pd_, m)
    print(f"    постов/сут  vs  {metric:9s}  rho = {s:+.3f}")

for g in ("массовые", "экспертные"):
    sel = [v for v in act if v["grp"] == g]
    if len(sel) > 2:
        print(f"    внутри '{g}' (n={len(sel)}):  rho = "
              f"{spearman([v['per_day'] for v in sel], [v['rx_1k'] for v in sel]):+.3f}")

for g in ("массовые", "экспертные"):
    sel = [v["med_rx"] for v in act if v["grp"] == g]
    sel2 = [v["per_day"] for v in act if v["grp"] == g]
    sel3 = [v["rx_1k"] for v in act if v["grp"] == g]
    sel4 = [v["rx_views"] for v in act if v["grp"] == g]
    if sel:
        print(f"    {g:12s} медиана постов/сут={st.median(sel2):5.1f}  "
              f"реакций/пост={st.median(sel):7,.0f}  rx/1k={st.median(sel3):6.1f}  "
              f"rx/просм={st.median(sel4):5.2f}%")

# ------------------------------------------------------- 2. распределения
print("\n" + "=" * 122)
print("2. РАСПРЕДЕЛЕНИЕ РЕАКЦИЙ ПО ПОСТАМ")
print("=" * 122)
allrx = sorted(r["rx"] for r in rows)
n = len(allrx)
q = lambda p: allrx[int(n * p)]
print(f"  реакций на пост: p10={q(.10):.0f}  p25={q(.25):.0f}  медиана={q(.50):.0f}  "
      f"p75={q(.75):.0f}  p90={q(.90):.0f}  p99={q(.99):.0f}  макс={max(allrx):,.0f}")
print(f"  доля постов с 0 реакций: {sum(1 for x in allrx if x==0)/n*100:.1f}%")
rxv = sorted(r["rx_views"] for r in rows)
qv = lambda p: rxv[int(n * p)]
print(f"  rx/просм (%):        p25={qv(.25):.2f}  медиана={qv(.50):.2f}  "
      f"p75={qv(.75):.2f}  p90={qv(.90):.2f}  макс={max(rxv):.1f}")
rxk = sorted(r["rx_1k"] for r in rows)
qk = lambda p: rxk[int(n * p)]
print(f"  rx/1k подписчиков:   p25={qk(.25):.1f}  медиана={qk(.50):.1f}  "
      f"p75={qk(.75):.1f}  p90={qk(.90):.1f}  макс={max(rxk):.1f}")

# --------------------------------------------------- 3. что отличает топ
print("\n" + "=" * 122)
print("3. ЧТО ОТЛИЧАЕТ ТОП-ПОСТЫ (верхние 10 % по rx/просм) ОТ ОСТАЛЬНЫХ")
print("=" * 122)
thr = qv(.90)
top = [r for r in rows if r["rx_views"] >= thr]
rest = [r for r in rows if r["rx_views"] < thr]
print(f"  порог: rx/просм >= {thr:.2f}%  ->  топ {len(top)} постов ({len(top)/n*100:.0f} %)")

FEATS = [("длина текста", lambda r: r["len"]),
         ("эмодзи в тексте", lambda r: r["emo"]),
         ("внешних ссылок", lambda r: r["n_links"]),
         ("форвард", lambda r: int(r["fwd"])),
         ("медиа", lambda r: int(r["media"])),
         ("подписчиков (тыс)", lambda r: r["subs"] / 1000)]
print(f"\n  {'признак':22s} {'ТОП-10%':>26s} {'ОСТАЛЬНЫЕ':>26s}   дельта")
for name, f in FEATS:
    a = [f(r) for r in top]
    b = [f(r) for r in rest]
    ma, mb = st.median(a), st.median(b)
    d = (ma / mb - 1) * 100 if mb else 0
    print(f"  {name:22s} {ma:12,.1f} (IQR {sorted(a)[len(a)//4]:,.0f}-"
          f"{sorted(a)[3*len(a)//4]:,.0f})  {mb:12,.1f} (IQR {sorted(b)[len(b)//4]:,.0f}-"
          f"{sorted(b)[3*len(b)//4]:,.0f})  {d:+7.1f}%")

print(f"\n  доля форвардов:  топ {sum(1 for r in top if r['fwd'])/len(top)*100:5.1f}%  "
      f"остальные {sum(1 for r in rest if r['fwd'])/len(rest)*100:5.1f}%")
print(f"  доля с медиа:    топ {sum(1 for r in top if r['media'])/len(top)*100:5.1f}%  "
      f"остальные {sum(1 for r in rest if r['media'])/len(rest)*100:5.1f}%")
print(f"  доля без ссылок: топ {sum(1 for r in top if r['n_links']==0)/len(top)*100:5.1f}%  "
      f"остальные {sum(1 for r in rest if r['n_links']==0)/len(rest)*100:5.1f}%")

# --- разрез 2: топ по rx/1k подписчиков (размер канала снят полностью)
thr1 = qk(.90)
top1 = [r for r in rows if r["rx_1k"] >= thr1]
rest1 = [r for r in rows if r["rx_1k"] < thr1]
bins = [(0, 150), (150, 300), (300, 600), (600, 1000), (1000, 1800), (1800, 100000)]
print(f"\n  [разрез 2] порог rx/1k >= {thr1:.2f} реакций на 1000 подписчиков"
      f" -> топ {len(top1)} постов ({len(top1)/len(rows)*100:.0f} %)")
print(f"  {'признак':22s} {'ТОП-10%':>26s} {'ОСТАЛЬНЫЕ':>26s}   дельта")
for name, f in FEATS:
    a = [f(r) for r in top1]
    b = [f(r) for r in rest1]
    ma, mb = st.median(a), st.median(b)
    d = (ma / mb - 1) * 100 if mb else 0
    print(f"  {name:22s} {ma:12,.1f} (IQR {sorted(a)[len(a)//4]:,.0f}-"
          f"{sorted(a)[3*len(a)//4]:,.0f})  {mb:12,.1f} (IQR {sorted(b)[len(b)//4]:,.0f}-"
          f"{sorted(b)[3*len(b)//4]:,.0f})  {d:+7.1f}%")
for nm, f in [("форвард", lambda r: r["fwd"]), ("с медиа", lambda r: r["media"]),
              ("без ссылок", lambda r: r["n_links"] == 0)]:
    print(f"  доля '{nm}': топ {sum(1 for r in top1 if f(r))/len(top1)*100:5.1f}%  "
          f"остальные {sum(1 for r in rest1 if f(r))/len(rest1)*100:5.1f}%")
print("  --- rx/1k по бинам длины ---")
for lo, hi in bins:
    sel = [r["rx_1k"] for r in rows if lo <= r["len"] < hi]
    if sel:
        print(f"    {lo:5d}-{hi if hi<99999 else 99999:5d} симв.: n={len(sel):5d}  "
              f"медиана {st.median(sel):6.2f} реакций/1k подп.")

# бины по длине
print("\n  --- rx/просм по бинам длины ---")
for lo, hi in bins:
    sel = [r["rx_views"] for r in rows if lo <= r["len"] < hi]
    if sel:
        print(f"    {lo:5d}-{hi if hi<99999 else 99999:5d} симв.: n={len(sel):5d}  "
              f"медиана {st.median(sel):6.2f}%")

print("\n  --- rx/просм по бинам эмодзи ---")
for lo, hi in [(0, 1), (1, 3), (3, 6), (6, 100)]:
    sel = [r["rx_views"] for r in rows if lo <= r["emo"] < hi]
    if sel:
        print(f"    {lo}-{hi-1} эмодзи: n={len(sel):5d}  медиана {st.median(sel):6.2f}%")

print("\n  --- по типу поста ---")
for name, f in [("форвард", lambda r: r["fwd"]), ("свой текст", lambda r: not r["fwd"]),
                ("с медиа", lambda r: r["media"]), ("без медиа", lambda r: not r["media"])]:
    sel = [r["rx_views"] for r in rows if f(r)]
    if sel:
        print(f"    {name:14s} n={len(sel):5d}  медиана {st.median(sel):6.2f}%  "
              f"среднее {sum(sel)/len(sel):6.2f}%")

# ------------------------------------------------- 4. время и день недели
print("\n" + "=" * 122)
print("4. ВРЕМЯ ПУБЛИКАЦИИ")
print("=" * 122)
for label, keyf, lo, hi in [("час UTC", lambda r: r["hour"], 0, 24),
                            ("день недели (0=Пн)", lambda r: r["dow"], 0, 7)]:
    print(f"  --- {label} ---")
    buckets = defaultdict(list)
    for r in rows:
        buckets[keyf(r)].append(r["rx_views"])
    for k in sorted(buckets):
        v = buckets[k]
        bar = "#" * int(st.median(v) * 1.6)
        name = k if label.startswith("час") else ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"][k]
        print(f"    {str(name):>4s} n={len(v):5d}  медиана {st.median(v):6.2f}%  {bar}")

# ------------------------------------------------------- 5. типы реакций
print("\n" + "=" * 122)
print("5. ТИПЫ РЕАКЦИЙ: ЧТО НАЖИМАЮТ")
print("=" * 122)
for g in ("массовые", "экспертные", "ВСЕ"):
    sel = [r for r in rows if g == "ВСЕ" or r["grp"] == g]
    tot = Counter()
    for r in sel:
        for k, v in r["rx_break"].items():
            tot[k] += v
    s = sum(tot.values())
    if not s:
        continue
    print(f"\n  {g} (всего {s:,.0f} реакций):")
    for k, v in tot.most_common(12):
        print(f"    {k:9s} {v:9,.0f}  {v/s*100:5.1f}%  {'#'*int(v/s*220)}")

# --------------------------------------------------------- 6. топ-посты
print("\n" + "=" * 122)
print("6. ТОП-20 ПОСТОВ ПО rx/1k подписчиков (нормализовано по размеру канала)")
print("=" * 122)
topk = sorted(rows, key=lambda r: -r["rx_1k"])[:20]
for i, r in enumerate(topk, 1):
    t = re.sub(r"\s+", " ", r["text"])[:105]
    print(f"  {i:2d}. {r['ch']:22s} подп={r['subs']:>9,.0f} просм={r['views']:>8,.0f} "
          f"реакц={r['rx']:>6,.0f}  rx/1k={r['rx_1k']:7.1f}  {t}")

print("\n" + "=" * 122)
print("7. ТОП-15 САМЫХ РЕАГИРУЕМЫХ ПОСТОВ ПО АБСОЛЮТНОМУ ЧИСЛУ РЕАКЦИЙ")
print("=" * 122)
for i, r in enumerate(sorted(rows, key=lambda x: -x["rx"])[:15], 1):
    t = re.sub(r"\s+", " ", r["text"])[:100]
    print(f"  {i:2d}. {r['ch']:22s} подп={r['subs']:>9,.0f} просм={r['views']:>8,.0f} "
          f"реакц={r['rx']:>6,.0f}  rx/1k={r['rx_1k']:6.1f}  {t}")

# --------------------------------------- 8. словарь самых реакционных постов
print("\n" + "=" * 122)
print("8. ЛЕКСИКА ТОП-ПОСТОВ vs ОСТАЛЬНЫЕ (слова, +3 раза чаще в топе)")
print("=" * 122)
STOP = set("""это или для как что по с из на не что то мы вы он она они
этом который которые при без уже ещё все весь может можно нужно так вот его
если когда чтобы там здесь нас вам их тем тебе себя себя одно такая такое
тоже чем об этом нас них ней её эту этот эти мне мой моя мои год года""".split())


def words(rs):
    c = Counter()
    for r in rs:
        # выкидываем URL: иначе в лексику попадают токены доменов и t.me/xxx
        t = re.sub(r"https?://\S+|t\.me/\S+|@\w+", " ", r["text"].lower())
        for w in WORD_RE.findall(t):
            if len(w) > 3 and w not in STOP:
                c[w] += 1
    return c


ct, cr = words(top), words(rest)
nt, nr = sum(ct.values()), sum(cr.values())
rt = {k: v / nt for k, v in ct.items()}
rr = {k: v / nr for k, v in cr.items()}
lift = []
for k, v in rt.items():
    if v * nt < 25:
        continue
    base = rr.get(k, 0)
    if base <= 0:
        continue
    lift.append((v / base, k, v * nt, v * nt / (base * nr) * 100))
for l, k, c, pct in sorted(lift, reverse=True)[:30]:
    print(f"    {k:22s} частота в топе {pct:5.2f}%  lift x{l:.2f}  (упоминаний {c:.0f})")

# ------------------------------------------------- 9. порог входа
print("\n" + "=" * 122)
print("9. С КАКОГО УРОВНЯ РЕАКЦИЙ СТАРТОВАТЬ (для нового канала)")
print("=" * 122)
for band, sel in [("все посты", rows)] + [(g, [r for r in rows if r["grp"] == g])
                                         for g in ("массовые", "экспертные")]:
    if not sel:
        continue
    s1k = sorted(r["rx_1k"] for r in sel)
    m = len(s1k)
    print(f"  {band:12s} p25={s1k[m//4]:6.2f}  медиана={s1k[m//2]:6.2f}  "
          f"p75={s1k[3*m//4]:6.2f}  p90={s1k[int(m*.9)]:6.2f}  "
          f"p99={s1k[int(m*.99)]:6.2f}  макс={s1k[-1]:6.2f}")
print("\n  Бенчмарк: сколько реакций на пост нужно при разном размере канала,")
print("  чтобы попасть в верхний дециль ниши по rx/1k (порог p90):")
tgt = qk(.90)
for subs in (3_000, 10_000, 30_000, 100_000, 300_000, 1_000_000):
    print(f"    {subs:9,d} подписчиков -> {tgt*subs/1000:8,.1f} реакций/пост")

json.dump({
    "channels": chan,
    "quantiles": {"rx": {"p10": q(.10), "p25": q(.25), "p50": q(.50),
                         "p75": q(.75), "p90": q(.90), "p99": q(.99),
                         "max": max(allrx)},
                  "rx_views_p90": thr},
    "top20_rx1k": [{"ch": r["ch"], "subs": r["subs"], "views": r["views"],
                    "rx": r["rx"], "rx_1k": r["rx_1k"],
                    "text": re.sub(r"\s+", " ", r["text"])[:300]} for r in topk],
}, open(D + "behaviour.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n  -> data/behaviour.json")
