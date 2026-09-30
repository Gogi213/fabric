"""Аудит ПОЛНОТЫ всего количественного: каналы, дни, посты, реакции, домены.

Вопросы, на которые отвечает скрипт:
  1. Сколько каналов в каждом наборе и какую часть «ниши» они покрывают?
  2. Какие даты реально покрыты, есть ли дыры, дубли, посты «из будущего»?
  3. Сколько постов собрано из того, что было опубликовано (по диапазону id)?
  4. Реакции: сколько постов с данными, какие каналы пустые, какая глубина?
  5. Совпадают ли числа из README/docs с тем, что лежит в data/?

Запуск:  python tools/recheck_coverage.py [--json]
"""
import json, os, re, statistics as st, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")


def J(name):
    return json.load(open(os.path.join(D, name), encoding="utf-8"))


ALIAS = {"tehnochat": "technomedia"}
MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet", "trends",
        "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
EXPERT = ["xor_journal", "neuraldvig", "data_secrets", "seeallochnaya", "denissexy", "ai_newz",
          "cgevent", "NeuralShit", "ai_machinelearning_big_data", "tproger", "tlive"]
RU = MASS + EXPERT


def dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def vnum(s):
    if isinstance(s, (int, float)):
        return float(s)
    if not s:
        return None
    s = s.strip().upper().replace(" ", "")
    m = re.match(r"^([\d.,]+)([KM])?$", s)
    if not m:
        return None
    return float(m.group(1).replace(",", ".")) * {"K": 1e3, "M": 1e6}.get(m.group(2), 1)


out = {}
print("=" * 104)
print("1. НАБОРЫ ДАННЫХ: сколько чего и за какие даты")
print("=" * 104)
datasets = {"posts.json": J("posts.json"), "posts_en.json": J("posts_en.json"), "links.json": J("links.json")}
R = J("reactions.json")
print(f"  {'набор':18s}{'каналов':>8s}{'постов':>8s}  {'с':10s}  {'по':10s}{'дней':>6s}  дублей(id)  «будущих»  без views")
now_ref = datetime(2026, 9, 30, 23, 59, tzinfo=timezone.utc)   # сбор закончен 30.09
for name, ds in list(datasets.items()) + [("reactions.json", {c: v["posts"] for c, v in R.items()})]:
    allp = [(c, p) for c, v in ds.items() for p in v]
    ts = [dt(p["dt"]) for c, p in allp if p.get("dt")]
    ids = Counter((c, str(p["id"])) for c, p in allp)
    dup = sum(v - 1 for v in ids.values() if v > 1)
    fut = sum(1 for t in ts if t > now_ref + timedelta(hours=1))
    nov = sum(1 for c, p in allp if not vnum(p.get("views")))
    print(f"  {name:18s}{len(ds):8d}{len(allp):8d}  {min(ts):%Y-%m-%d}  {max(ts):%Y-%m-%d}"
          f"{(max(ts) - min(ts)).days:6d}  {dup:8d}  {fut:9d}  {nov:9d}")
    out[name] = dict(channels=len(ds), posts=len(allp), first=f"{min(ts):%F}", last=f"{max(ts):%F}", dup=dup, future=fut, no_views=nov)
print("  (в каждом наборе technomedia и tehnochat — один канал; каналов с учётом алиаса на 1 меньше)")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 104)
print("2. ГЛУБИНА ПО КАНАЛАМ: сколько суток реально покрыто (а не сколько заявлено)")
print("=" * 104)
print("  Заявлено: posts.json — 7 сут (22–29.09), links.json — 14 сут (15–29.09), reactions.json — «12 страниц»")
print(f"  {'канал':28s}{'слой':5s}{'posts.json':>11s}{'links.json':>11s}{'reactions':>11s}  сут(react)  пост/сут  макс.пауза,ч")
rows = []
for c in RU:
    row = [c]
    for ds in (datasets["posts.json"], datasets["links.json"], {c: R[c]["posts"]}):
        row.append(len(ds.get(c, [])))
    rp = R[c]["posts"]
    ts = sorted(dt(p["dt"]) for p in rp if p.get("dt"))
    span = (ts[-1] - ts[0]).total_seconds() / 86400 if len(ts) > 1 else 0
    gaps = [(b - a).total_seconds() / 3600 for a, b in zip(ts, ts[1:])]
    row += [span, len(ts) / span if span else 0, max(gaps) if gaps else 0]
    rows.append(row)
    print(f"  {c:28s}{'масс' if c in MASS else 'эксп':5s}{row[1]:11d}{row[2]:11d}{row[3]:11d}  {span:9.1f}  {row[5]:8.1f}  {row[6]:12.1f}")
spans = [r[4] for r in rows]
print(f"\n  Глубина reactions.json: от {min(spans):.0f} до {max(spans):.0f} сут, медиана {st.median(spans):.0f}. "
      f"Массовые: {st.median([r[4] for r in rows if r[0] in MASS]):.0f} сут, экспертные: {st.median([r[4] for r in rows if r[0] in EXPERT]):.0f} сут.")
print("  ⇒ сравнение «массовый vs экспертный» по реакциям идёт на РАЗНЫХ периодах (docs/01 §1.10.3 это признаёт).")
out["reaction_depth_days"] = {r[0]: round(r[4], 1) for r in rows}

# покрытие календарных суток в links.json (окно 15–29.09 UTC)
print("\n  Календарные сутки с ≥1 собранным постом (links.json, окно 15.09–29.09 = 15 суток, последние неполные):")
Lk = datasets["links.json"]
dcov = {}
for c in RU:
    days = {dt(p["dt"]).date() for p in Lk[c]}
    dcov[c] = len(days)
print("   " + ", ".join(f"{c}:{n}" for c, n in dcov.items()))
full_ch = [c for c, n in dcov.items() if n >= 14]
print(f"  каналов с постами ≥14 суток из 15: {len(full_ch)} из {len(RU)}; остальные — редкие каналы "
      f"({', '.join(c for c in RU if dcov[c] < 14)}): пустые сутки там — реальные паузы или потери, отличить нельзя")
out["days_covered_links"] = dcov

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 104)
print("3. ПОЛНОТА ПОСТОВ: собрано / опубликовано (по диапазону id в окне)")
print("=" * 104)
print("  Ожидание: id в Telegram непрерывны; каждое сообщение альбома — отдельный id, текст только у одного.")
print("  Собираются только посты С ТЕКСТОМ (crawl*.py: `if not txt: continue`), поэтому доля < 100 % ожидаема;")
print("  важно, одинакова ли она у разных каналов (иначе «постов/сутки» несравнимы).")
print(f"  {'канал':28s}{'id-диапазон':>12s}{'собрано':>9s}{'доля':>8s}{'с медиа':>9s}  (links.json, 14 сут)")
cov = {}
L = datasets["links.json"]
for c in RU:
    ps = L[c]
    ids = sorted(int(p["id"]) for p in ps)
    rng = ids[-1] - ids[0] + 1
    cov[c] = len(ids) / rng
    mediaR = sum(1 for p in R[c]["posts"] if p.get("media"))
    print(f"  {c:28s}{rng:12d}{len(ids):9d}{100 * cov[c]:7.1f}%{100 * mediaR / max(len(R[c]['posts']), 1):8.0f}%")
idrate = {}
for c in RU:
    ids = sorted(int(p["id"]) for p in L[c])
    ts = sorted(dt(p["dt"]) for p in L[c])
    span = (ts[-1] - ts[0]).total_seconds() / 86400
    idrate[c] = ((ids[-1] - ids[0] + 1) / span, len(ids) / span)
for nm, grp in (("массовые", MASS), ("экспертные", EXPERT)):
    a = st.median(idrate[c][0] for c in grp)
    b = st.median(idrate[c][1] for c in grp)
    print(f"  {nm}: медиана id/сутки (все сообщения канала, включая медиа-элементы альбомов) = {a:.1f}; "
          f"постов с текстом/сутки = {b:.1f}")
print("  ⇒ «13.0 и 2.7 поста/сутки» из docs/08 — это ПОСТЫ С ТЕКСТОМ; общее число сообщений канала выше.")
out["id_rate"] = {c: [round(a, 1), round(b, 1)] for c, (a, b) in idrate.items()}
print(f"\n  доля собранных id: медиана {100 * st.median(cov.values()):.0f} %, min {100 * min(cov.values()):.0f} % "
      f"({min(cov, key=cov.get)}), max {100 * max(cov.values()):.0f} % ({max(cov, key=cov.get)})")
out["post_id_coverage_median"] = st.median(cov.values())

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 104)
print("4. РЕАКЦИИ: что реально собрано")
print("=" * 104)
tot_posts = tot_rx = 0
zero = []
rows = []
for c, v in R.items():
    ps = v["posts"]
    rx = [p.get("rx") or 0 for p in ps]
    with_rx = sum(1 for x in rx if x > 0)
    tot_posts += len(ps)
    tot_rx += sum(rx)
    if with_rx == 0:
        zero.append(c)
    rows.append((c, len(ps), with_rx, sum(rx)))
print(f"  каналов в файле: {len(R)}; с реакциями >0 хотя бы у одного поста: {len(R) - len(zero)}; пустые: {zero}")
print(f"  постов: {tot_posts}; сумма реакций: {tot_rx:,.0f}")
has = sum(r[2] for r in rows)
print(f"  постов с rx>0: {has} ({100 * has / tot_posts:.1f} %)")
capped = sum(1 for v in R.values() for p in v["posts"] if len(p.get("rx_break") or {}) >= 12)
print(f"  постов на пределе ~12 типов реакций (rx — нижняя оценка): {capped} ({100 * capped / tot_posts:.1f} %)")
valid = [r for r in rows if r[2] > 0]
print(f"  ⇒ реально доступно для анализа реакций: {len(valid)} каналов и {sum(r[1] for r in valid)} постов "
      f"(в README: «22 канала», «4124 поста»)")
out["reactions"] = dict(channels_file=len(R), channels_with_data=len(valid), posts_file=tot_posts,
                        posts_with_rx=has, total_rx=tot_rx, capped_posts=capped, empty_channels=zero)

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 104)
print("5. КАНАЛЫ: выборка против каркаса")
print("=" * 104)
ms = J("market_size.json")["channels"]
deep = J("market_deep.json")
menu = deep["telegram_menu_tech"]
search = deep["tgme_search"]
search_all = {}
for q, v in search.items():
    for c in v:
        search_all[c["handle"]] = c["subs"]
BOT = re.compile(r"bot$|_bot$|bot_", re.I)
print(f"  каркас A: telegram.menu «Технологии/IT»: {len(menu)} каналов, сумма {sum(c['subs'] for c in menu) / 1e6:.1f} млн")
print(f"  каркас B: tgme.app поиск (9 запросов): {len(search_all)} уникальных, из них по имени ботов {sum(1 for h in search_all if BOT.search(h))}")
print(f"  каркас C: market_size.json: {len(ms)} каналов; с числом подписчиков: {sum(1 for v in ms.values() if v.get('subs'))}")
sample = {c.lower() for c in RU}
inA = [c for c in menu if c["handle"].lower() in sample]
print(f"\n  Из 22 каналов выборки в каркасе A (топ-58): {len(inA)}; доля подписчиков каркаса A в выборке: "
      f"{100 * sum(c['subs'] for c in inA) / sum(c['subs'] for c in menu):.0f} %")
inB = [h for h in search_all if h.lower() in sample]
print(f"  Из 22 каналов выборки в каркасе B: {len(inB)} {inB}")
print("  Каналы каркаса A, НЕ вошедшие в выборку (по убыванию подписчиков):")
miss = [c for c in menu if c["handle"].lower() not in sample]
for c in miss[:25]:
    nm = ms.get(c["handle"], {})
    print(f"    @{c['handle']:26s}{c['subs'] / 1e6:6.2f}M  последний пост: {nm.get('newest', '?')}")
out["frame_A"] = len(menu)
out["sample_in_frame_A"] = [c["handle"] for c in inA]

print("\n  Активность каркаса C (market_size.json): последний пост по месяцам")
newest = Counter((v.get("newest") or "?")[:7] for v in ms.values())
for k, n in sorted(newest.items(), reverse=True)[:8]:
    print(f"    {k}: {n}")
alive = sum(1 for v in ms.values() if (v.get("newest") or "") >= "2026-09-16")
print(f"  активны (пост за последние 14 сут): {alive} из {len(ms)}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 104)
print("6. ИСТОЧНИКИ: полнота карты доменов")
print("=" * 104)
from urllib.parse import urlparse
L = datasets["links.json"]
dom_ch = defaultdict(set)
dom_n = Counter()
for c, v in L.items():
    if c in ALIAS:
        continue
    for p in v:
        for u in p["links"]:
            h = urlparse(u).netloc.lower()
            h = h[4:] if h.startswith("www.") else h
            dom_n[h] += 1
            dom_ch[h].add(c)
print(f"  уникальных хостов: {len(dom_n)}; встретились 1 раз: {sum(1 for n in dom_n.values() if n == 1)} "
      f"({100 * sum(1 for n in dom_n.values() if n == 1) / len(dom_n):.0f} %)")
print(f"  хостов, которые цитируют ≥3 каналов: {sum(1 for h in dom_ch if len(dom_ch[h]) >= 3)}; ≥5 каналов: {sum(1 for h in dom_ch if len(dom_ch[h]) >= 5)}")
sm = J("sourcemap.json")
print(f"  sourcemap.json: {len(sm['domains'])} доменов (док 04 §3: «1087 уникальных доменов» по links.json)")
print(f"  (пересчёт по links.json без алиаса: {len(dom_n)} хостов — доменов второго уровня меньше)")
out["hosts"] = len(dom_n)

# насыщение: растёт ли число доменов с добавлением каналов/суток?  (RU, без t.me)
import random
rnd = random.Random(1)
ext = defaultdict(list)          # канал -> [(дата, корневой домен)]
for c in RU:
    for p in L[c]:
        for u in p["links"]:
            h = urlparse(u).netloc.lower()
            h = h[4:] if h.startswith("www.") else h
            if not h or h.startswith("t.me") or h.startswith("telegram.me"):
                continue
            pp = h.split(".")
            ext[c].append((dt(p["dt"]).date(), ".".join(pp[-2:]) if len(pp) >= 2 else h))
allext = [x for c in RU for x in ext[c]]
cnt = Counter(d_ for _, d_ in allext)
single = sum(1 for n in cnt.values() if n == 1)
print(f"\n  Внешних ссылок RU: {len(allext)}, уникальных корневых доменов: {len(cnt)}, из них встретились ровно 1 раз: {single}")
print(f"  Оценка Гуда–Тьюринга доли ссылок на ещё не виденные домены: {100 * single / len(allext):.1f} % "
      f"(каждая седьмая новая ссылка ведёт на домен, которого нет в карте)")
curve = []
for k in (1, 2, 4, 6, 8, 11, 14, 17, 22):
    v = []
    for _ in range(200):
        chs = rnd.sample(RU, k)
        v.append(len({d_ for c in chs for _, d_ in ext[c]}))
    curve.append((k, sum(v) / len(v)))
print("  Кривая насыщения по КАНАЛАМ (среднее число уникальных доменов при k случайных каналах):")
print("    " + "  ".join(f"k={k}:{m:.0f}" for k, m in curve))
days = sorted({d for c in RU for d, _ in ext[c]})
dc = []
for i in (1, 3, 5, 7, 10, 13, len(days)):
    sel = set(days[:i])
    dc.append((i, len({d_ for c in RU for d, d_ in ext[c] if d in sel})))
print("  Кривая насыщения по СУТКАМ (накопительно от 15.09):")
print("    " + "  ".join(f"{i} сут:{n}" for i, n in dc))
g = (curve[-1][1] - curve[-2][1]) / (22 - 17)
print(f"  Прирост на последних каналах: ≈{g:.0f} новых доменов на канал. Кривая не выходит на плато ⇒ карта доменов неполна; "
      f"устойчивы только домены, которые цитируют много каналов.")
out["domain_singletons_pct"] = 100 * single / len(allext)

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 104)
print("7. ЧИСЛА ИЗ README/docs ПРОТИВ data/")
print("=" * 104)
sub = J("subs.json")
checks = [
    ("README: posts.json «1600 RU-постов»", 1600, sum(len(v) for v in datasets["posts.json"].values())),
    ("README: posts_en.json «936 EN-постов» (в файле 957, все с текстом; фильтр 936 не задокументирован)", 936, sum(len(v) for v in datasets["posts_en.json"].values())),
    ("README: links.json «4464 поста»", 4464, sum(len(v) for v in L.values())),
    ("README: reactions.json «4124 поста» (с views)", 4124, sum(1 for v in R.values() for p in v["posts"] if vnum(p.get("views")))),
    ("README: «1 245 377 реакций»", 1245377, int(tot_rx)),
    ("README: market_size «921 канал»", 921, len(ms)),
    ("README: subs.json «22 канала» (без алиаса)", 22, len([k for k in sub if k not in ALIAS and not k.startswith("_")])),
    ("docs/01 §1.10: «22 RU + 14 EN = 36 каналов»", 36, len(RU) + len(datasets["posts_en.json"])),
    ("docs/04: links.json «37 каналов»", 37, len(L)),
    ("docs/07 §4.1: «58 каналов» telegram.menu", 58, len(menu)),
    ("docs/07 §4.1: «321 уникальный канал» поиск", 321, len(search_all)),
]
for nm, doc, real in checks:
    mark = "✓" if doc == real else "✗"
    print(f"  {mark} {nm:54s} документ {doc:>10,}   данные {real:>10,}")
print("  Независимых каналов в 'links.json' (37) на самом деле 36: technomedia и tehnochat — один канал.")

if "--json" in sys.argv:
    json.dump(out, open(os.path.join(D, "recheck_coverage.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    print("\nsaved data/recheck_coverage.json")
