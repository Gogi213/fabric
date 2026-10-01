"""R11 §5. Разбор теневого прогона: насколько машина могла опередить первый русский канал.

Вход: data/r/shadow/items.jsonl и tg.jsonl (несколько прогонов дописываются в те же файлы;
для каждого элемента берётся самая ранняя запись).

1. Задержка лент: момент, когда элемент впервые появился в нашем опросе, минус время публикации
   в самой ленте (только элементы, появившиеся во время прогона, у лент с точным временем).
2. Сюжеты каналов: новые посты (не форварды, ≥40 знаков) склеиваются к первому посту сюжета (окно 48 ч)
   при косинусе ≥ 0.80, как в R3, или ≥ 0.65 с общим конкретным якорем: короткие посты разных каналов
   об одном событии редко дают 0.80. В сюжет входят и посты, опубликованные до старта прогона.
   Берутся сюжеты, первый пост которых вышел во время прогона.
3. Источник сюжета: элемент ленты, замеченный не позже чем через 30 мин после первого поста, с косинусом
   ≥ HIGH_SIM и любым общим якорем или ≥ MATCH_SIM при общем конкретном якоре (версия, модель, имя; не просто
   бренд вроде Apple/OpenAI, не страна и не год). Без якоря короткие посты дают ложные совпадения.
   Порог подобран по 25 размеченным парам (14 из 15 принятых верны). Итоговые пары проверены вручную:
   data/r/r11_verdicts.json, ключ «канал|время первого поста» → {"ok": bool, "note": "..."}; пара с ok=false
   отбрасывается; у сюжета без источника note объясняет, откуда он (местная новость, вирусное и т.п.).
   Запас машины = первый пост в Telegram минус момент, когда машина увидела источник.
   Если элемент был в ленте уже при старте, момент — время публикации из ленты (помечается).

Выход: data/r/r11_shadow_report.json. Запуск: python tools/r11_shadow_report.py [--all]
  --all — проверка метода: берутся и сюжеты, начатые до старта (запас считается по времени из ленты).
"""
import json, os, re, statistics as st, sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT  # noqa: E402

D = os.path.join(ROOT, "data", "r")
SH = os.path.join(D, "shadow")
MATCH_SIM, HIGH_SIM, STORY_SIM, STORY_SIM_ANCHOR, STORY_H = 0.60, 0.75, 0.80, 0.65, 48
ALL = "--all" in sys.argv
RU_FEEDS = {"3dnews", "ixbt", "4pda", "cnews", "habr_news", "securitylab", "vcru", "overclockers", "opennet", "rb_ru",
            "kommersant", "lenta", "rbc", "ria", "tass", "interfax"}
IMPRECISE = {"openai", "anthropic_sitemap", "reddit_localllama", "reddit_openai"}  # время ленты неточное или его нет
STOP = set("the and for new with from this that your what how are was has have its into over after about more than "
           "will just can not you all out now one two use app apps model update release today first open video free "
           "best top news pro max ultra plus mini https http www com".split())
STOP_CYR = set("Это Как Что Теперь Также Если Когда После Сегодня Новый Новая Новые Для При Вот Все Всё Уже Там "
               "Однако Кроме Вместе Пока Ранее".split())
CYR_GENERIC = {"росси", "сша", "китай", "китая", "трамп", "путин", "европ", "москв", "украи"}
BRANDS = set("apple iphone ipad mac macbook google android openai chatgpt gpt anthropic claude gemini microsoft windows "
             "samsung galaxy xiaomi huawei sony meta amazon nvidia intel amd tesla spacex musk telegram youtube "
             "ios reuters".split())


def first_records(name, key):
    out = {}
    for line in open(os.path.join(SH, name), encoding="utf-8"):
        r = json.loads(line)
        k = key(r)
        if k not in out or r["seen_t"] < out[k]["seen_t"]:
            out[k] = r
    return list(out.values())


def anchors(t):
    lat = {w.lower() for w in re.findall(r"\b[A-Za-z][A-Za-z0-9.+-]{2,}\b", t) if w.lower() not in STOP}
    num = set(re.findall(r"\b\d+(?:[.,]\d+)?\b", t)) - {str(i) for i in range(32)}
    cyr = {w[:5].lower() for w in re.findall(r"(?<=[^.!?\n]\s)([А-ЯЁ][а-яё]{3,})", t) if w not in STOP_CYR}
    cyr -= CYR_GENERIC
    return lat | num | cyr


def ts(iso):
    from datetime import datetime
    return datetime.fromisoformat(iso).timestamp()


items = first_records("items.jsonl", lambda r: (r["src"], r["id"]))
tg = first_records("tg.jsonl", lambda r: (r["ch"], r["id"]))
t_start = min(r["seen_t"] for r in tg)
t_end = max(max(r["seen_t"] for r in tg), max(r["seen_t"] for r in items))
print(f"прогон: {(t_end - t_start) / 3600:.1f} ч; элементов лент {len(items)} "
      f"(новых {sum(not r['baseline'] for r in items)}); постов каналов {len(tg)} "
      f"(новых {sum(not r['baseline'] for r in tg)})")

# 1. задержка лент
lat = defaultdict(list)
for r in items:
    if not r["baseline"] and r.get("pub_t") and r["src"] not in IMPRECISE:
        lat[r["src"]].append(r["seen_t"] - r["pub_t"])
# элемент с временем публикации старше 6 ч — старая статья, заново попавшая в ленту; считается отдельно
feed_lat = {s: {"n": len(v), "old_resurfaced": sum(x > 6 * 3600 for x in v),
                "median_min": st.median([x for x in v if x <= 6 * 3600] or [float("nan")]) / 60,
                "p90_min": float(np.percentile([x for x in v if x <= 6 * 3600] or [float("nan")], 90)) / 60}
            for s, v in lat.items() if len(v) >= 3}
print("\nзадержка лент, мин (медиана / p90, n, из них старых статей):")
for s, v in sorted(feed_lat.items(), key=lambda x: x[1]["median_min"]):
    print(f"  {s:20s} {v['median_min']:7.1f} {v['p90_min']:8.1f}  {v['n']}  {v['old_resurfaced']}")

# 2. сюжеты каналов
posts = [r for r in tg if r.get("dt") and not r.get("fwd") and len(r.get("text") or "") >= 40]
for p in posts:
    p["t"] = ts(p["dt"])
posts.sort(key=lambda p: p["t"])
from sentence_transformers import SentenceTransformer  # noqa: E402
model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
enc = lambda xs: model.encode(xs, normalize_embeddings=True, show_progress_bar=False, batch_size=64)
P = enc([p["text"][:400] for p in posts])
specific = lambda xs: {x for x in xs if x not in BRANDS and not re.fullmatch(r"20[12]\d", x)}
PA = [anchors(p["text"]) for p in posts]
members = {}
for j in range(len(posts)):
    best, bs = None, 0.0
    for a in members:
        if posts[j]["t"] - posts[a]["t"] <= STORY_H * 3600:
            s = float(P[j] @ P[a])
            ok = s >= STORY_SIM or (s >= STORY_SIM_ANCHOR and specific(PA[j] & PA[a]))
            if ok and s > bs:
                best, bs = a, s
    if best is None:
        members[j] = [j]
    else:
        members[best].append(j)
stories = [m for a, m in members.items() if ALL or (not posts[a]["baseline"] and posts[a]["t"] >= t_start)]
print(f"\nсюжетов{'' if ALL else ', начатых во время прогона'}: {len(stories)} (постов в них {sum(len(m) for m in stories)})")

# 3. источники
for r in items:
    r["detect_t"] = r["seen_t"] if not r["baseline"] else (r.get("pub_t") if r["src"] not in IMPRECISE else None)
cand = [r for r in items if r["detect_t"]]
I = enc([(r["title"] + ". " + (r.get("summary") or ""))[:400] for r in cand])
IA = [anchors(r["title"] + " " + (r.get("summary") or "")) for r in cand]
IT = np.array([r["detect_t"] for r in cand])
VP = os.path.join(D, "r11_verdicts.json")
VERD = json.load(open(VP, encoding="utf-8")) if os.path.exists(VP) else {}
rows = []
for m in stories:
    a = posts[m[0]]
    win = (IT >= a["t"] - 48 * 3600) & (IT <= a["t"] + 1800)
    sims = I @ P[m[0]]
    aa = anchors(a["text"])
    hits = [k for k in np.where(win & (sims >= MATCH_SIM))[0]
            if (sims[k] >= HIGH_SIM and IA[k] & aa) or specific(IA[k] & aa)]
    v = VERD.get(f'{a["ch"]}|{a["dt"]}')
    row = {"first_ch": a["ch"], "first_dt": a["dt"], "n_posts": len(m), "n_ch": len({posts[j]["ch"] for j in m}),
           "chs": [posts[j]["ch"] for j in m], "text": a["text"][:200], "sources": []}
    if v:
        row["verdict"] = v
    if hits and not (v and v.get("ok") is False):
        hits.sort(key=lambda k: IT[k])
        e = cand[hits[0]]
        row.update({"src": e["src"], "src_title": e["title"], "src_link": e["link"], "sim": float(sims[hits[0]]),
                    "lead_min": (a["t"] - e["detect_t"]) / 60, "lead_by": "pub_t" if e["baseline"] else "seen_t"})
        row["sources"] = sorted({cand[k]["src"] for k in hits})
    rows.append(row)

found = [r for r in rows if "lead_min" in r]
print(f"с найденным источником: {len(found)} из {len(rows)}; проверено вручную: "
      f"{sum('verdict' in r for r in rows)}, отброшено: {sum(r.get('verdict', {}).get('ok') is False for r in rows)}")
bands = [(-1e9, 0, "Telegram раньше ленты"), (0, 5, "0–5 мин"), (5, 30, "5–30 мин"), (30, 120, "30 мин – 2 ч"),
         (120, 360, "2–6 ч"), (360, 1e9, "> 6 ч")]
dist = {name: sum(lo <= r["lead_min"] < hi for r in found) for lo, hi, name in bands}
for k, v in dist.items():
    print(f"  {k:22s} {v}")
if found:
    print(f"  медиана запаса {st.median(r['lead_min'] for r in found):.0f} мин; "
          f"по seen_t: {sum(r['lead_by'] == 'seen_t' for r in found)}")
for lang in ("ru", "en"):
    xs = [r["lead_min"] for r in found if (r["src"] in RU_FEEDS) == (lang == "ru")]
    if xs:
        print(f"  источник {lang}: n={len(xs)}, медиана запаса {st.median(xs):.0f} мин")
first_src = Counter(r["src"] for r in found)
print("лента, давшая сюжет первой:", first_src.most_common(15))
print("канал, вышедший первым:", Counter(r["first_ch"] for r in rows).most_common(10))

json.dump({"run_hours": (t_end - t_start) / 3600, "t_start": t_start, "t_end": t_end,
           "n_items": len(items), "n_items_new": sum(not r["baseline"] for r in items),
           "n_tg": len(tg), "n_tg_new": sum(not r["baseline"] for r in tg),
           "feed_latency": feed_lat, "n_stories": len(rows), "n_found": len(found), "lead_bands": dist,
           "lead_median_min": st.median(r["lead_min"] for r in found) if found else None,
           "first_source": first_src.most_common(), "stories": rows},
          open(os.path.join(D, "r11_shadow_report_all.json" if ALL else "r11_shadow_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
