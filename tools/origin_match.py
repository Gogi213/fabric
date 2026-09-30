"""Откуда приходит новость: сопоставление свежих постов RU-каналов с элементами фидов.

Вход:  data/recent_posts.json (tools/crawl_recent.py), data/feed_items.json (tools/feed_items.py)
Выход: data/origin_match.json

Метод:
  1. Посты-кандидаты: с текстом ≥ 60 символов, без рекламной маркировки.
  2. Сюжеты: посты разных каналов с косинусом ≥ STORY_SIM и разрывом ≤ 48 ч
     объединяются (union-find). Сюжет — единица наблюдения, а не пост.
  3. Для каждого сюжета ищутся элементы фидов с косинусом ≥ MATCH_SIM к любому посту
     сюжета во временном окне [первый пост − 72 ч; первый пост + 24 ч].
  4. Для совпавших: какие категории фидов, кто раньше (фид или Telegram), лаг.
Эмбеддинги: paraphrase-multilingual-MiniLM-L12-v2 (та же модель, что в tools/cross2.py).

Запуск:  python tools/origin_match.py --calibrate   (выгрузка пар по бинам для ручной разметки)
         python tools/origin_match.py [MATCH_SIM]  (основной расчёт)
"""
import json, os, random, re, statistics as st, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import numpy as np
from sentence_transformers import SentenceTransformer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
STORY_SIM = 0.80
args = [a for a in sys.argv[1:] if not a.startswith("--")]
MATCH_SIM = float(args[0]) if args else 0.62   # нижний порог: нужен общий РЕДКИЙ якорь + ещё один общий
HI_SIM = 0.80                                   # выше — принимается без якорей
RARE_DF = 40                                    # «редкий» якорь: встречается не более чем в 40 элементах фидов (1 %)

STOP = set("that this with from have будет было были этот этого которые который также после через "
           "более можно новый новая новые году года теперь уже только всего если когда what your "
           "about into their they will just more than first новости новость".split())


ENT_STOP = set("the and for new with from this that your what how why are was has have its into over "
               "after about more than will just can not you all out now one two use using via app apps model "
               "models update updates release released launch launches launched today first open source video "
               "free best top news report says said year years week day days time based make made get".split())


def entities(text):
    """Языконезависимые якоря: латинские слова ≥3 букв (бренды, модели) и числа/версии ≥2 знаков."""
    out = set()
    for w in re.findall(r"\$?[A-Za-z0-9][A-Za-z0-9.+-]*", text):
        w = w.lower().strip(".-+").replace("'s", "")
        if re.fullmatch(r"\$?\d+(?:[.,]\d+)*", w):
            if len(w.replace("$", "").replace(".", "")) >= 2:
                out.add(w.replace("$", ""))
        elif re.search(r"[a-z]", w) and len(w) >= 3 and w not in ENT_STOP:
            out.add(w)
    return out


def anchors(text):
    """Якоря: числа, латинские слова ≥3 букв, кириллические слова ≥5 букв (обрезка до 5 — грубый стемминг)."""
    out = set()
    for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9$][A-Za-zА-Яа-яЁё0-9.$-]*", text):
        w = w.lower().strip(".-").replace("'s", "")
        if not w or w in STOP:
            continue
        if re.fullmatch(r"\$?\d+(?:[.,]\d+)?", w):
            if len(w.strip("$")) >= 2 or "$" in w:
                out.add(w.strip("$"))
        elif re.fullmatch(r"[a-z][a-z0-9.-]{2,}", w):
            out.add(w[:6])
        elif re.fullmatch(r"[а-яё][а-яё-]{4,}", w):
            out.add(w[:5])
        elif re.search(r"\d", w) and re.search(r"[a-zа-я]", w):
            out.add(w)
    return out

AD = re.compile(r"(\berid\b|#реклама|реклама\.\s*рекламодатель|на правах рекламы)", re.I)
URL = re.compile(r"https?://\S+")
EMO = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


def dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def clean_tg(t):
    t = URL.sub(" ", t)
    t = EMO.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()[:500]


rp = json.load(open(os.path.join(D, "recent_posts.json"), encoding="utf-8"))
fi = json.load(open(os.path.join(D, "feed_items.json"), encoding="utf-8"))
posts = []
skipped = Counter()
for ch, rec in rp.items():
    if ch.startswith("_"):
        continue
    for p in rec["posts"]:
        blob = p["text"] + " " + " ".join(p["links"])
        if not p["has_text"]:
            skipped["без текста"] += 1
        elif AD.search(blob):
            skipped["реклама (маркировка)"] += 1
        elif len(clean_tg(p["text"])) < 60:
            skipped["короче 60 символов"] += 1
        else:
            posts.append({"ch": ch, "id": p["id"], "dt": dt(p["dt"]), "text": clean_tg(p["text"]),
                          "fwd": p["fwd_url"] or p["fwd_name"]})
items = [dict(x, dt=dt(x["dt"])) for x in fi["items"]]
for p in posts:
    p["anc"] = anchors(p["text"])
    p["ent"] = entities(p["text"])
for x in items:
    x["anc"] = anchors(x["title"] + " " + x["summary"][:300])
    x["ent"] = entities(x["title"] + " " + x["summary"][:300])
DF = Counter(a for x in items for a in x["anc"])
print(f"постов в анализе: {len(posts)}; отброшено: {dict(skipped)}")
print(f"элементов фидов: {len(items)} из {sum(1 for v in fi['status'].values() if v['in_window'])} источников")

model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
EP = model.encode([p["text"] for p in posts], batch_size=64, normalize_embeddings=True, show_progress_bar=False)
EF = model.encode([(x["title"] + ". " + x["summary"][:300]).strip() for x in items], batch_size=64,
                  normalize_embeddings=True, show_progress_bar=False)
SIM = EP @ EF.T
tp = np.array([p["dt"].timestamp() for p in posts])
tf = np.array([x["dt"].timestamp() for x in items])
LAG = (tp[:, None] - tf[None, :]) / 60.0          # >0: фид раньше поста, мин
WIN = (LAG <= 72 * 60) & (LAG >= -24 * 60)
S = np.where(WIN, SIM, -1)


def accept(i, j):
    if S[i, j] >= HI_SIM:
        return True
    if S[i, j] < MATCH_SIM:
        return False
    common = posts[i]["anc"] & items[j]["anc"]
    rare = [a for a in common if DF[a] <= RARE_DF]
    return len(rare) >= 1 and len(common) >= 2


STRICT_SIM, STRICT_ENT_SIM = 0.75, 0.68


def strict(i, j):
    """Строгий уровень: ручная точность проверяется аудитом (--audit)."""
    if S[i, j] >= STRICT_SIM:
        return True
    return S[i, j] >= STRICT_ENT_SIM and len(posts[i]["ent"] & items[j]["ent"]) >= 2

if "--calibrate" in sys.argv:
    best = S.argmax(1)
    bs = S[np.arange(len(posts)), best]
    rnd = random.Random(3)
    bins = [(0.45, 0.50), (0.50, 0.55), (0.55, 0.60), (0.60, 0.65), (0.65, 0.70), (0.70, 1.01)]
    out = []
    for lo, hi in bins:
        idx = [i for i in range(len(posts)) if lo <= bs[i] < hi]
        print(f"\n### бин [{lo:.2f}; {hi:.2f}): постов {len(idx)}")
        for i in rnd.sample(idx, min(12, len(idx))):
            j = best[i]
            print(f"  [{bs[i]:.3f}] TG @{posts[i]['ch']} {posts[i]['dt']:%m-%d %H:%M} | {posts[i]['text'][:150]}")
            print(f"          FEED {items[j]['src']} {items[j]['dt']:%m-%d %H:%M} | {items[j]['title'][:150]}")
            out.append({"bin": [lo, hi], "sim": float(bs[i]), "tg": posts[i]["text"][:300],
                        "tg_ch": posts[i]["ch"], "feed": items[j]["title"], "feed_src": items[j]["src"]})
    json.dump(out, open(os.path.join(D, "origin_calibration_sample.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    sys.exit(0)

# ── сюжеты: union-find по постам разных каналов ──────────────────────────────
PP = EP @ EP.T
par = list(range(len(posts)))


def f(x):
    while par[x] != x:
        par[x] = par[par[x]]
        x = par[x]
    return x


for i in range(len(posts)):
    for j in range(i + 1, len(posts)):
        if posts[i]["ch"] != posts[j]["ch"] and PP[i, j] >= STORY_SIM and abs(tp[i] - tp[j]) <= 48 * 3600:
            par[f(i)] = f(j)
stories = defaultdict(list)
for i in range(len(posts)):
    stories[f(i)].append(i)
stories = list(stories.values())
print(f"сюжетов: {len(stories)} (из них в ≥2 каналах: {sum(1 for s in stories if len({posts[i]['ch'] for i in s}) >= 2)})")

rows = []
for s in stories:
    first = min(s, key=lambda i: tp[i])
    t0 = tp[first]
    matched, strict_m = {}, {}
    for i in s:
        for j in np.where(S[i] >= min(MATCH_SIM, STRICT_ENT_SIM))[0]:
            lag0 = (t0 - tf[j]) / 60
            if not (-24 * 60 <= lag0 <= 72 * 60):
                continue
            if accept(i, j):
                matched[j] = max(matched.get(j, 0), float(S[i, j]))
            if strict(i, j):
                strict_m[j] = max(strict_m.get(j, 0), float(S[i, j]))
    loose_n = len(matched)
    matched = strict_m          # всё дальнейшее — по строгому уровню
    cats = Counter(items[j]["cat"] for j in matched)
    srcs = Counter(items[j]["src"] for j in matched)
    earliest = min(matched, key=lambda j: tf[j]) if matched else None
    bestj = max(matched, key=lambda j: matched[j]) if matched else None
    rows.append({
        "channels": sorted({posts[i]["ch"] for i in s}), "n_posts": len(s),
        "first_ch": posts[first]["ch"], "first_dt": posts[first]["dt"].isoformat(),
        "text": posts[first]["text"][:300],
        "matched": len(matched), "loose_matched": loose_n, "cats": dict(cats), "srcs": dict(srcs),
        "earliest_src": items[earliest]["src"] if earliest is not None else None,
        "earliest_cat": items[earliest]["cat"] if earliest is not None else None,
        "earliest_title": items[earliest]["title"][:200] if earliest is not None else None,
        "lag_min": (t0 - tf[earliest]) / 60 if earliest is not None else None,
        "best_sim": max(matched.values()) if matched else None,
        "best_src": items[bestj]["src"] if bestj is not None else None,
        "best_title": items[bestj]["title"][:200] if bestj is not None else None,
        "earliest_sim": matched[earliest] if earliest is not None else None,
    })

N = len(rows)
m = [r for r in rows if r["matched"]]
multi = [r for r in rows if len(r["channels"]) >= 2]
mm = [r for r in multi if r["matched"]]
lo = [r for r in rows if r["loose_matched"]]
print(f"\nМЯГКИЙ уровень (верхняя граница, точность по аудиту ≈ 50 %): {len(lo)} из {len(rows)} сюжетов "
      f"({100 * len(lo) / len(rows):.0f} %)")
print(f"СТРОГИЙ уровень (sim ≥ {STRICT_SIM} или sim ≥ {STRICT_ENT_SIM} и ≥2 общих латинских/числовых якоря):")
print(f"сюжетов с совпадением в фидах: {len(m)} из {N} ({100 * len(m) / N:.0f} %); "
      f"среди сюжетов ≥2 каналов: {len(mm)} из {len(multi)} ({100 * len(mm) / max(len(multi), 1):.0f} %)")
before = [r for r in m if r["lag_min"] > 0]
print(f"фид раньше первого поста: {len(before)} из {len(m)}; медиана лага {st.median([r['lag_min'] for r in before]) if before else float('nan'):.0f} мин")
print("\nКатегория САМОГО РАННЕГО совпавшего элемента (сюжеты, где фид раньше Telegram):")
for k, v in Counter(r["earliest_cat"] for r in before).most_common():
    lags = [r["lag_min"] for r in before if r["earliest_cat"] == k]
    print(f"  {k:10s}{v:5d}   медиана лага {st.median(lags):6.0f} мин")
print("\nИсточники, дающие совпадения (в скольких сюжетах источник вообще встретился):")
cnt = Counter()
for r in m:
    cnt.update(r["srcs"].keys())
for k, v in cnt.most_common(30):
    print(f"  {k:22s}{v:4d}")
print("\nПо каналу, открывшему сюжет: доля сюжетов, найденных в фидах")
byc = defaultdict(lambda: [0, 0])
for r in rows:
    byc[r["first_ch"]][1] += 1
    byc[r["first_ch"]][0] += bool(r["matched"])
for c, (a, b) in sorted(byc.items(), key=lambda x: -x[1][1]):
    print(f"  {c:30s}{a:4d}/{b:<4d} {100 * a / b:5.0f} %")

if "--audit" in sys.argv:
    rnd = random.Random(11)
    print("\n=== АУДИТ: 40 случайных СОВПАВШИХ сюжетов (самый ранний совпавший элемент) ===")
    for r in rnd.sample(m, min(40, len(m))):
        print(f"  [{r['earliest_sim']:.2f}] {r['first_ch']} {r['first_dt'][5:16]} | {r['text'][:120]}")
        print(f"         {r['earliest_src']} лаг {r['lag_min']:+.0f} мин | {r['earliest_title'][:120]}")
    print("\n=== АУДИТ: 30 случайных НЕ совпавших сюжетов ===")
    for r in rnd.sample([r for r in rows if not r["matched"]], 30):
        print(f"  {r['first_ch']} ({len(r['channels'])} кан.) | {r['text'][:150]}")

json.dump({"params": {"MATCH_SIM": MATCH_SIM, "STORY_SIM": STORY_SIM}, "n_posts": len(posts),
           "skipped": skipped, "stories": rows},
          open(os.path.join(D, "origin_match.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1,
          default=str)
