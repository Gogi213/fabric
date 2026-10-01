"""R5. Что набирает просмотры и реакции — внутри канала.

Единица — пост. Мера — ОТНОСИТЕЛЬНЫЕ просмотры: просмотры поста / медиана просмотров постов того же канала
(только посты старше 48 ч на момент сбора, чтобы счётчик почти устоялся). Аналогично — реакции на просмотр.
Так размер канала, его частота и аудитория снимаются, остаётся свойство поста.

Сравнения (медиана относительных просмотров; 95 % CI — бутстрэп по каналам):
  1. скорость: пост вышел первым среди медиа в сюжете / 2–3-м / 4-м и позже / сюжет только у этого канала;
  2. ширина сюжета: сколько медиа его подхватили (1, 2–3, 4–9, ≥10);
  3. вид поста (фото, видео, альбом, текст, форвард…);
  4. длина текста, капс, эмодзи;
  5. час публикации (МСК).
Выход: data/r/r5.json + печать.
"""
import json, os, random, re, statistics as st, sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT, is_marked_ad, load, post_format  # noqa: E402

D = os.path.join(ROOT, "data", "r")
MEDIA = {"Медиа: AI и тех-новости", "Медиа: массовые тех-развлекательные", "Медиа: гаджеты и железо",
         "Apple и смартфоны (медиа и магазины)", "Медиа: кибербез и мошенничество"}
CHS = {c["handle"]: c for c in json.load(open(os.path.join(D, "channels.json"), encoding="utf-8"))}
media = {h for h, c in CHS.items() if c["kind"] in MEDIA and (c.get("deal_share") or 0) < 0.3}
C = load()
S = json.load(open(os.path.join(D, "stories.json"), encoding="utf-8"))
CAPS = re.compile(r"\b[А-ЯЁA-Z]{4,}\b")
EMO = re.compile("[\U0001F300-\U0001FAFF☀-➿]")

# позиция поста в сюжете среди медиа
pos, breadth = {}, {}
for s in S:
    first = {}
    for m in s["members"]:
        if m["ch"] in media and m["ch"] not in first:
            first[m["ch"]] = m
    order = sorted(first.values(), key=lambda m: m["lag_min"])
    for r, m in enumerate(order):
        pos[(m["ch"], m["id"])] = r + 1
        breadth[(m["ch"], m["id"])] = len(order)

rows = []
for ch in media:
    if ch not in C:
        continue
    d = C[ch]
    fetched = datetime.fromisoformat(d["crawl"]["fetched_at"])
    ps = [p for p in d["posts"] if p.get("views") and p["_t"] and fetched - p["_t"] >= timedelta(hours=48)
          and not is_marked_ad(p)]
    if len(ps) < 10:
        continue
    medv = st.median(p["views"] for p in ps)
    rxs = [p["rx_total"] / p["views"] for p in ps if p.get("has_rx_block")]
    medrx = st.median(rxs) if rxs else None
    for p in ps:
        k = (ch, p["id"])
        t = p.get("text") or ""
        b = breadth.get(k, 1)
        rows.append({
            "ch": ch, "rv": p["views"] / medv, "brk": 1.0 if p["views"] / medv >= 1.5 else 0.0,
            "rrx": (p["rx_total"] / p["views"]) / medrx if medrx and p.get("has_rx_block") else None,
            "speed": ("только у канала" if b == 1 else "первым" if pos[k] == 1 else "2–3-м" if pos[k] <= 3 else "4-м и позже"),
            "breadth": "1" if b == 1 else "2–3" if b <= 3 else "4–9" if b <= 9 else "≥10",
            "fmt": post_format(p),
            "len": "<150" if len(t) < 150 else "150–300" if len(t) < 300 else "300–600" if len(t) < 600 else "600+",
            "caps": "есть КАПС" if CAPS.search(t) else "нет капса",
            "emoji": "0" if not EMO.search(t) else "1–3" if len(EMO.findall(t)) <= 3 else "4+",
            "hour": ((p["_t"] + timedelta(hours=3)).hour // 3) * 3,
        })
print(f"медиа-каналов в анализе: {len({r['ch'] for r in rows})}, постов: {len(rows)}")
q = sorted(r["rv"] for r in rows)
cvs = []
for c in {r["ch"] for r in rows}:
    v = [r["rv"] for r in rows if r["ch"] == c]
    if len(v) >= 20:
        cvs.append(st.pstdev(v) / st.mean(v))
print(f"разброс просмотров внутри канала: p10 {q[len(q)//10]:.2f}, p50 {q[len(q)//2]:.2f}, p90 {q[9*len(q)//10]:.2f}, "
      f"p99 {q[99*len(q)//100]:.2f} от медианы канала; медианный коэффициент вариации {st.median(cvs):.2f}; "
      f"«выстрелов» ≥1.5× — {100*sum(r['brk'] for r in rows)/len(rows):.1f} %")


def summarize(field, metric="rv", order=None, min_n=60):
    agg = (lambda v: sum(v) / len(v)) if metric == "brk" else st.median
    rnd = random.Random(0)
    by = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if r[metric] is not None:
            by[r[field]][r["ch"]].append(r[metric])
    res = []
    for g, chs in by.items():
        allv = [x for v in chs.values() for x in v]
        if len(allv) < min_n:
            continue
        keys = list(chs)
        boots = []
        for _ in range(500):
            sm = [x for k in (rnd.choice(keys) for _ in keys) for x in chs[k]]
            boots.append(agg(sm))
        boots.sort()
        res.append((g, len(allv), len(chs), agg(allv), boots[12], boots[487]))
    res.sort(key=lambda x: (order.index(x[0]) if order and x[0] in order else 99, -x[3]))
    return res


OUT = {}
for field, title, order in [
    ("speed", "Скорость: позиция канала в сюжете", ["первым", "2–3-м", "4-м и позже", "только у канала"]),
    ("breadth", "Ширина сюжета (сколько медиа подхватили)", ["1", "2–3", "4–9", "≥10"]),
    ("fmt", "Вид поста", None),
    ("len", "Длина текста", ["<150", "150–300", "300–600", "600+"]),
    ("caps", "КАПС в тексте", None),
    ("emoji", "Эмодзи", ["0", "1–3", "4+"]),
    ("hour", "Час публикации (МСК, 3-часовые окна)", [0, 3, 6, 9, 12, 15, 18, 21]),
]:
    for metric, mname in (("rv", "просмотры"), ("rrx", "реакции/просмотр"), ("brk", "доля «выстрелов» ≥1.5×")):
        res = summarize(field, metric, order)
        OUT[f"{field}|{metric}"] = res
        print(f"\n{title} — относительные {mname} (1.00 = медиана канала):")
        for g, n, nc, med, lo, hi in res:
            print(f"  {str(g):18s} постов {n:6d} каналов {nc:4d}   {med:5.2f}  [{lo:.2f}; {hi:.2f}]")
json.dump(OUT, open(os.path.join(D, "r5.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
