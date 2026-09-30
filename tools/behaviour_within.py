"""ВНУТРИКАНАЛЬНЫЙ анализ: у каждого канала свой топ против своей середины.

Зачем: и rx/1k, и длина, и эмодзи, и возраст сильно зависят от канала.
Сравнивать «каналы между собой» бессмысленно — сравниваем посты
ВНУТРИ одного канала. Тогда все свойства канала (размер, частота,
слой) снимаются, и остаётся только свойство поста.

Метрика: rx/просм — отношение, слабо зависящее от возраста.
"""
import json, re, statistics as st
from collections import defaultdict
from datetime import datetime

D = "C:/visual projects/parser/data/"
R = json.load(open(D + "reactions.json", encoding="utf-8"))
MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️‍↔️-🫿]")
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)

per = defaultdict(list)
for ch, rec in R.items():
    for p in rec["posts"]:
        if not p.get("dt") or not p["views"] or p["views"] <= 0:
            continue
        dt = datetime.fromisoformat(p["dt"].replace("Z", "+00:00"))
        txt = p["text"] or ""
        per[ch].append({
            "dt": dt, "age": (NOW - dt).total_seconds() / 86400,
            "views": p["views"], "rx": p["rx"] or 0,
            "rxv": (p["rx"] or 0) / p["views"] * 100,
            "len": len(txt), "emo": len(EMOJI_RE.findall(txt)),
            "fwd": bool(p["fwd"]), "media": bool(p["media"]),
            "links": p.get("n_links", 0),
            "text": re.sub(r"\s+", " ", txt),
        })

# для каждого канала: топ-20% по rx/просм против нижних 50%
print("=" * 120)
print("ВНУТРИКАНАЛЬНЫЙ ТОП (верхние 20 % по rx/просм) vs НИЗ (нижние 50 %)")
print("=" * 120)
print(f"  {'канал':24s} {'слой':5s} {'n':>5s} {'медиана':>9s} {'низ':>7s} "
      f"{'x':>5s} {'длина':>7s} {'эмодзи':>8s} {'медиа':>8s}")
agg = defaultdict(list)
for ch, ps in per.items():
    if len(ps) < 60:
        continue
    ps = sorted(ps, key=lambda r: -r["rxv"])
    k = max(10, len(ps) // 5)
    top, low = ps[:k], ps[int(len(ps) * .5):]
    mt, ml = st.median(r["rxv"] for r in top), st.median(r["rxv"] for r in low)
    agg["len"].append((st.median(r["len"] for r in top), st.median(r["len"] for r in low)))
    agg["emo"].append((st.median(r["emo"] for r in top), st.median(r["emo"] for r in low)))
    agg["media"].append((sum(1 for r in top if r["media"]) / k * 100,
                         sum(1 for r in low if r["media"]) / len(low) * 100))
    agg["fwd"].append((sum(1 for r in top if r["fwd"]) / k * 100,
                       sum(1 for r in low if r["fwd"]) / len(low) * 100))
    agg["age"].append((st.median(r["age"] for r in top), st.median(r["age"] for r in low)))
    print(f"  {ch:24s} {'масс' if ch in MASS else 'эксп':5s} {len(ps):5d} "
          f"{mt:8.2f}% {ml:6.2f}% {mt/max(ml,.01):5.1f} "
          f"{st.median(r['len'] for r in top):7.0f} "
          f"{st.median(r['emo'] for r in top):8.0f} "
          f"{sum(1 for r in top if r['media'])/k*100:7.0f}%")

print("\n  --- СРЕДНЕЕ ПО ВСЕМ КАНАЛАМ (топ vs низ) ---")
for k, lab in [("len", "длина, симв."), ("emo", "эмодзи"),
               ("media", "доля с медиа, %"), ("fwd", "доля форвардов, %"),
               ("age", "возраст, сут")]:
    a = st.median(x[0] for x in agg[k])
    b = st.median(x[1] for x in agg[k])
    d = (a / b - 1) * 100 if b else 0
    print(f"    {lab:22s} топ {a:8.1f}   низ {b:8.1f}   дельта {d:+7.1f}%")

# ---- пул всех пар «топ-пост vs низ-пост» того же канала: что внутри топа
pool_top, pool_low = [], []
for ch, ps in per.items():
    if len(ps) < 60:
        continue
    ps = sorted(ps, key=lambda r: -r["rxv"])
    k = max(10, len(ps) // 5)
    pool_top += ps[:k]
    pool_low += ps[int(len(ps) * .5):]

print("\n" + "=" * 120)
print("ПУЛ: 1-в-1 сравнение постов (топ-20 % и низ-50 % внутри каждого канала)")
print("=" * 120)
print(f"  в пуле: {len(pool_top)} постов-топов и {len(pool_low)} постов-низов "
      f"из {len(per)} каналов")
BINS = [(0, 150), (150, 300), (300, 600), (600, 1000), (1000, 1800), (1800, 100000)]
print(f"\n  {'признак':26s} {'ТОП':>18s} {'НИЗ':>18s}")
for lo, hi in BINS:
    a = [r for r in pool_top if lo <= r["len"] < hi]
    b = [r for r in pool_low if lo <= r["len"] < hi]
    if a and b:
        sh = lambda s: s / (s + b if False else s) if False else s / (a[0]["len"] or 1) * 0
        pa = len(a) / len(pool_top) * 100
        pb = len(b) / len(pool_low) * 100
        print(f"  длина {lo:5d}-{hi if hi<99999 else 99999:5d}:      "
              f"{pa:7.1f}%  (n={len(a):4d})   {pb:7.1f}%  (n={len(b):4d})   "
              f"{'плюс' if pa>pb else 'МИНУС'}")
for lo, hi in [(0, 1), (1, 3), (3, 6), (6, 100)]:
    a = [r for r in pool_top if lo <= r["emo"] < hi]
    b = [r for r in pool_low if lo <= r["emo"] < hi]
    if a and b:
        pa, pb = len(a) / len(pool_top) * 100, len(b) / len(pool_low) * 100
        print(f"  эмодзи {lo}-{hi-1}:                    "
              f"{pa:7.1f}%  (n={len(a):4d})   {pb:7.1f}%  (n={len(b):4d})   "
              f"{'плюс' if pa>pb else 'МИНУС'}")
for nm, f in [("с медиа", lambda r: r["media"]), ("без медиа", lambda r: not r["media"]),
              ("форвард", lambda r: r["fwd"]), ("без ссылок", lambda r: r["links"] == 0),
              ("с ссылкой", lambda r: r["links"] > 0)]:
    a = sum(1 for r in pool_top if f(r)) / len(pool_top) * 100
    b = sum(1 for r in pool_low if f(r)) / len(pool_low) * 100
    print(f"  {nm:24s}  {a:7.1f}%            {b:7.1f}%            {a-b:+7.1f} п.п.")

# ---- темы, которые систематически в топе
print("\n" + "=" * 120)
print("ТЕМЫ: какие сюжеты попадают в верхний дециль чаще (внутриканальный топ)")
print("=" * 120)
KEYS = {
    "взлом/утечка": r"взлом|утечк|хак|breach|hack|компромет|слив",
    "OpenAI": r"openai|gpt|chatgpt|codex|астра|astra",
    "Anthropic/Claude": r"anthropic|claude|fable|sonnet|opus",
    "Google/Gemini": r"google|gemini|deepmind|qwen",
    "релиз модели": r"выпуст|релиз|запуст|нов(ая|ую) модель|анонс",
    "цены/тарифы": r"цен|подписк|тариф|стоит|стоить|дорог|дешев|\$",
    "суд/регулирование": r"суд|регулятор|закон|штраф|ban|запрет",
    "Россия/локальное": r"росси|рф|сбер|яндекс|вконтакте|гос",
    "Apple": r"apple|iphone|ipad|macbook",
    "SpaceX/космос": r"spacex|starship|илон|маск|орбит",
    "смешно/мем": r"прикол|мем|смешн|лол|хаха|🤡|🗿|пхд|аху",
    "разбор/мнение": r"почему|зачем|что не так|проблем|ошиб|разбор|мнение|по-моему",
    "итоги/цифры": r"итог|цифр|стат|исследован|опрос|дол[яи] ",
}
cnt_t = {k: 0 for k in KEYS}
cnt_l = {k: 0 for k in KEYS}
for r in pool_top:
    for k, pat in KEYS.items():
        if re.search(pat, r["text"], re.I):
            cnt_t[k] += 1
for r in pool_low:
    for k, pat in KEYS.items():
        if re.search(pat, r["text"], re.I):
            cnt_l[k] += 1
print(f"  {'тема':22s} {'в ТОП-20%':>11s} {'в НИЗ-50%':>11s} {'lift':>7s}")
rows_ = []
for k in KEYS:
    a = cnt_t[k] / len(pool_top) * 100
    b = cnt_l[k] / len(pool_low) * 100
    lift = a / b if b else float("inf")
    rows_.append((lift if b else 99, k, a, b))
for lift, k, a, b in sorted(rows_, reverse=True):
    ls = "н/д" if lift == 99 else f"x{lift:.2f}"
    print(f"  {k:22s} {a:10.1f}% {b:10.1f}% {ls:>7s}")

# ---- антипаттерны: чего избегать
print("\n" + "=" * 120)
print("АНТИПАТТЕРНЫ (реже в топе, чем в низе)")
print("=" * 120)
for lift, k, a, b in sorted(rows_)[:5]:
    print(f"  {k:22s} топ {a:5.1f}%  низ {b:5.1f}%  -> переоценена")

# ---- слова, устойчиво связанные с высоким rx/просм ВНУТРИ канала
print("\n" + "=" * 120)
print("СЛОВА с высоким lift (внутриканальный топ-20 % против низ-50 %)")
print("=" * 120)
WORD_RE = re.compile(r"[a-zA-Zа-яА-ЯёЁ][a-zA-Zа-яА-ЯёЁ0-9+.-]{2,}")
STOP = set("""это или для как что по с из на не что то мы вы он она они
этом который которые при без уже ещё все весь может можно нужно так вот его
если когда чтобы там здесь нас вам их тем тебе себя одно такая такое
тоже чем об нас них ней её эту этот эти мне мой моя мои год года""".split())


def words(rs):
    c = defaultdict(int)
    for r in rs:
        t = re.sub(r"https?://\S+|t\.me/\S+|@\w+", " ", r["text"].lower())
        for w in WORD_RE.findall(t):
            if len(w) > 3 and w not in STOP:
                c[w] += 1
    return c


ct, cl = words(pool_top), words(pool_low)
nt, nl = sum(ct.values()), sum(cl.values())
rt = {k: v / nt for k, v in ct.items()}
rl = {k: v / nl for k, v in cl.items()}
out = []
for k, v in rt.items():
    if v * nt < 40:
        continue
    b = rl.get(k, 0)
    if b <= 0:
        continue
    out.append((v / b, k, v * nt / (b * nl) * 100, v * nt))
for lift, k, pct, c in sorted(out, reverse=True)[:25]:
    print(f"  {k:24s} {pct:5.2f}% в топе   lift x{lift:.2f}   (упоминаний {c:.0f})")
