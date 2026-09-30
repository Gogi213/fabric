"""Перепроверка docs/04 (карта источников) и связанных цифр docs/08 (реклама, форварды).

Всё считается заново из data/links.json. Пути относительные от корня репозитория.
Запуск:  python tools/recheck_sources.py            (печатает таблицы)
         python tools/recheck_sources.py --json      (+ пишет data/recheck_sources.json)

Главная идея: прежний анализ считал ссылки «как есть». Здесь каждая ссылка
сначала получает ВИД (своя / реклама / приглашение / бот / сокращатель /
чужой канал / внешний источник), и только внешние источники считаются
«откуда ниша берёт новости».
"""
import json, os, random, re, statistics as st, sys
from collections import Counter, defaultdict
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")

links = json.load(open(os.path.join(D, "links.json"), encoding="utf-8"))

# tehnochat — алиас technomedia (146 идентичных постов): считаем один раз
ALIAS = {"tehnochat": "technomedia"}
MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
EXPERT = ["xor_journal", "neuraldvig", "data_secrets", "seeallochnaya", "denissexy",
          "ai_newz", "cgevent", "NeuralShit", "ai_machinelearning_big_data",
          "tproger", "tlive"]
RU = MASS + EXPERT
EN = ["anthropic", "aipost", "hiaimediaen", "TheHackerNews", "GitHub", "news_crypto",
      "TechDaily", "bleepingcomputer", "perplexity_ai", "machinelearningresearchnews",
      "levelsio", "tldrtech", "AInews_en", "ml_news"]

TG = re.compile(r"(?:^|//)(?:www\.)?(?:t\.me|telegram\.me)/([A-Za-z0-9_+]+)(?:/(\d+))?", re.I)
ERID_PARAM = re.compile(r"[?&]erid=", re.I)
ERID_BARE = re.compile(r"\b2[A-Za-z0-9]{15,25}\b")          # как в tools/production.py
ADTAG = re.compile(r"(#реклама\b|#ad\b|\bреклама\b|\bрекламное сообщение\b|"
                   r"\bsponsored\b|\bpartnership\b)", re.I)
# Явная маркировка (закон о рекламе РФ): «Реклама. Рекламодатель: … erid: …», #реклама,
# либо параметр erid= в ссылке. Реальные erid — короткие (≈11 символов, «2Vtzqu…»),
# поэтому проектный ERID_BARE (16–26 символов, начинается с «2») их не ловит вообще.
ADTAG_STRICT = re.compile(r"(#реклама\b|#ad\b|\berid\b|\bреклама\.\s*рекламодатель|"
                          r"\bна правах рекламы\b|\bрекламное сообщение\b)", re.I)
SHORT = {"bit.ly", "u.to", "clck.ru", "tinyurl.com", "slc.tl", "cutt.ly", "goo.gl",
         "t.co", "vk.cc", "clc.to", "is.gd"}
AD_DOMAINS = re.compile(r"(alfa\.me|alfabank|alfa-|sberbank|sber\.ru|mts\.ru|beeline|"
                        r"tbank|t-bank|setka\.ru|avito|ozon|wildberries|mws\.ru|"
                        r"cloud\.ru|yandex\.cloud|selectel|timeweb)", re.I)


def dom(u):
    h = urlparse(u).netloc.lower()
    h = h[4:] if h.startswith("www.") else h
    return h


def root(h):
    p = h.split(".")
    if len(p) >= 3 and p[-2] in ("co", "com", "org", "net") and len(p[-1]) == 2:
        return ".".join(p[-3:])
    return ".".join(p[-2:]) if len(p) >= 2 else h


def channels(names):
    return {c: links[c] for c in names if c in links}


def pct(a, b):
    return 100.0 * a / b if b else 0.0


def boot_ci(per_ch, stat, n=2000, seed=7):
    """бутстрэп по каналам: per_ch = {канал: (числитель, знаменатель)}"""
    rnd = random.Random(seed)
    keys = list(per_ch)
    vals = []
    for _ in range(n):
        s = [per_ch[rnd.choice(keys)] for _ in keys]
        a, b = sum(x[0] for x in s), sum(x[1] for x in s)
        vals.append(pct(a, b))
    vals.sort()
    return vals[int(.025 * n)], vals[int(.975 * n)]


out = {}

# ─────────────────────────────────────────────────────────────────────────────
print("=" * 100)
print("0. ВХОДНЫЕ ДАННЫЕ")
print("=" * 100)
n_all = sum(len(v) for v in links.values())
l_all = sum(len(p["links"]) for v in links.values() for p in v)
l_dedup = sum(len(p["links"]) for c, v in links.items() if c not in ALIAS for p in v)
print(f"  каналов в links.json: {len(links)} (RU в анализе: {len(RU)}, EN: {len(EN)}, алиасы: {list(ALIAS)})")
print(f"  постов: {n_all}; ссылок: {l_all}; без алиаса tehnochat: {l_dedup} "
      f"(алиас завысил счёт на {l_all - l_dedup} = {pct(l_all - l_dedup, l_dedup):.1f} %)")
same = sum(1 for a, b in zip(links["technomedia"], links["tehnochat"])
           if a["text"] == b["text"])
print(f"  technomedia vs tehnochat: {len(links['technomedia'])} / {len(links['tehnochat'])} постов, "
      f"идентичный текст по позициям: {same}")
out["alias_inflation_links"] = l_all - l_dedup

# ─────────────────────────────────────────────────────────────────────────────
# Свои сайты: домен, >=80 % ссылок на который дал один канал и их >=15
print("\n" + "=" * 100)
print("1. СВОИ САЙТЫ КАНАЛОВ (домен, почти все ссылки на который даёт один канал)")
print("=" * 100)
by_dom = defaultdict(Counter)
for c, v in links.items():
    if c in ALIAS:
        continue
    for p in v:
        for u in p["links"]:
            if not TG.search(u):
                by_dom[root(dom(u))][c] += 1
SELF_SITE = {}
for d_, cnt in by_dom.items():
    tot = sum(cnt.values())
    top, k = cnt.most_common(1)[0]
    if tot >= 15 and k / tot >= 0.80:
        SELF_SITE[d_] = top
for d_, ch in sorted(SELF_SITE.items(), key=lambda x: -sum(by_dom[x[0]].values())):
    print(f"  {d_:32s} {sum(by_dom[d_].values()):4d} ссылок, {by_dom[d_][ch]:4d} из них от @{ch}")
out["self_sites"] = SELF_SITE

# ─────────────────────────────────────────────────────────────────────────────
# Классификация каждой ссылки
def post_is_ad(p, strict=False):
    blob = p["text"] + " " + " ".join(p["links"])
    if any(ERID_PARAM.search(u) for u in p["links"]):
        return True
    if strict:
        return bool(ADTAG_STRICT.search(p["text"]))
    return bool(ERID_BARE.search(blob) or ADTAG.search(p["text"]))


SELF_ALIASES = {"technomedia": {"tehnochat"}}     # @tehnochat — второй адрес того же канала


def kind(ch, p, u):
    m = TG.search(u)
    if m:
        h, pid = m.group(1), m.group(2)
        if h.startswith("+") or h.lower() == "joinchat":
            return "tg:приглашение"
        if h.lower() == ch.lower() or h.lower() in SELF_ALIASES.get(ch, ()):
            return "tg:свой пост" if pid else "tg:свой канал (подпись)"
        if re.search(r"bot$", h, re.I):
            return "tg:бот"
        return "tg:пост чужого канала" if pid else "tg:чужой канал (без поста)"
    d_ = root(dom(u))
    if SELF_SITE.get(d_) == ch:
        return "свой сайт"
    if d_ in SHORT:
        return "сокращатель"
    if post_is_ad(p, strict=True) or AD_DOMAINS.search(dom(u)):
        return "реклама"
    return "внешний источник"


def kinds_for(group, tag):
    cnt, per = Counter(), {}
    rows = []
    for ch in group:
        c = Counter()
        for p in links.get(ch, []):
            for u in p["links"]:
                c[kind(ch, p, u)] += 1
        per[ch] = c
        cnt.update(c)
    tot = sum(cnt.values())
    print(f"\n  {tag}: {len(group)} каналов, {tot} ссылок")
    for k, v in cnt.most_common():
        ci = boot_ci({ch: (per[ch][k], sum(per[ch].values())) for ch in group if per[ch]}, None)
        print(f"    {k:30s}{v:6d}  {pct(v, tot):5.1f} %   95% CI по каналам [{ci[0]:.1f}; {ci[1]:.1f}]")
    return cnt, per


print("\n" + "=" * 100)
print("2. ЧТО НА САМОМ ДЕЛЕ СКРЫВАЕТСЯ ЗА «t.me = 38–48 % ссылок»")
print("=" * 100)
c_ru, per_ru = kinds_for(RU, "RU (22 канала, без алиаса)")
c_en, per_en = kinds_for(EN, "EN (14 каналов)")
out["kinds_ru"] = dict(c_ru)
out["kinds_en"] = dict(c_en)
tg = sum(v for k, v in c_ru.items() if k.startswith("tg:"))
print(f"\n  RU: всего t.me = {tg} ({pct(tg, sum(c_ru.values())):.1f} % всех ссылок); "
      f"из них ссылок на ПОСТ ЧУЖОГО канала = {c_ru['tg:пост чужого канала']} "
      f"({pct(c_ru['tg:пост чужого канала'], sum(c_ru.values())):.2f} % всех ссылок)")

# чужие каналы: кого цитируют
print("\n  Топ чужих t.me-адресатов (RU) — реклама/партнёры или новостные каналы?")
oth = Counter()
oth_ch = defaultdict(set)
for ch in RU:
    for p in links[ch]:
        for u in p["links"]:
            k = kind(ch, p, u)
            if k.startswith("tg:пост чужого") or k.startswith("tg:чужой"):
                h = TG.search(u).group(1)
                oth[h] += 1
                oth_ch[h].add(ch)
for h, n in oth.most_common(25):
    print(f"    @{h:26s}{n:4d}  каналов-цитировщиков: {len(oth_ch[h])} ({', '.join(sorted(oth_ch[h]))[:60]})")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 100)
print("3. ВНЕШНИЕ ИСТОЧНИКИ (без t.me, своих сайтов, рекламы, сокращателей)")
print("=" * 100)


def ext_table(group, tag, top=25):
    links_by_dom, posts_by_dom, ch_by_dom = Counter(), Counter(), defaultdict(set)
    n_posts = 0
    n_with = 0
    for ch in group:
        for p in links.get(ch, []):
            n_posts += 1
            seen = set()
            for u in p["links"]:
                if kind(ch, p, u) != "внешний источник":
                    continue
                d_ = root(dom(u))
                links_by_dom[d_] += 1
                ch_by_dom[d_].add(ch)
                seen.add(d_)
            for d_ in seen:
                posts_by_dom[d_] += 1
            n_with += bool(seen)
    tot = sum(links_by_dom.values())
    print(f"\n  {tag}: постов {n_posts}; с хотя бы одной внешней ссылкой-источником: "
          f"{n_with} ({pct(n_with, n_posts):.1f} %); внешних ссылок {tot}")
    print(f"    {'домен':30s}{'ссылок':>7s}{'постов':>8s}{'каналов':>9s}  (каналов-цитировщиков ≥3 = устойчиво)")
    for d_, n in links_by_dom.most_common(top):
        print(f"    {d_:30s}{n:7d}{posts_by_dom[d_]:8d}{len(ch_by_dom[d_]):9d}")
    return links_by_dom, ch_by_dom, n_with, n_posts


ext_ru, chd_ru, nw, npst = ext_table(RU, "RU")
out["ru_posts_with_external_source_pct"] = pct(nw, npst)
ext_table(EN, "EN", top=15)

# по корзинам, но только для доменов, которые цитируют ≥3 канала (шире, чем один)
print("\n  Домены RU, которые цитируют ≥3 разных канала (устойчивый набор):")
stable = [(d_, n, len(chd_ru[d_])) for d_, n in ext_ru.most_common() if len(chd_ru[d_]) >= 3]
for d_, n, k in stable[:40]:
    print(f"    {d_:30s}{n:5d} ссылок, {k:2d} каналов")
out["stable_domains_ru"] = stable[:60]

# корзины по типу источника — только для внешних ссылок RU-каналов
BUCKETS = [
    ("Лаборатории/вендоры ИИ (блоги, продукты)", {"openai.com", "anthropic.com", "claude.com", "claude.ai",
        "claude.dev", "chatgpt.com", "blog.google", "deepmind.google", "qwen.ai", "mistral.ai", "x.ai",
        "ai.meta.com", "meta.com", "perplexity.ai", "elevenlabs.io", "cursor.com", "nvidia.com",
        "microsoft.com", "google.com", "apple.com", "yandex.ru", "yandex.com", "sber.ru", "gigachat.ru"}),
    ("Код и модели (GitHub, Hugging Face, arXiv)", {"github.com", "huggingface.co", "arxiv.org", "github.io"}),
    ("Соцсети/видео (X, YouTube, Reddit)", {"x.com", "twitter.com", "youtube.com", "youtu.be", "reddit.com",
        "threads.net", "instagram.com", "facebook.com", "linkedin.com"}),
    ("СМИ РФ (агентства, газеты)", {"ria.ru", "rbc.ru", "tass.ru", "iz.ru", "kommersant.ru", "lenta.ru",
        "gazeta.ru", "rg.ru", "vedomosti.ru", "fontanka.ru", "interfax.ru", "forbes.ru", "dzen.ru", "vc.ru",
        "habr.com", "3dnews.ru", "ixbt.com", "cnews.ru", "4pda.to"}),
    ("СМИ мир (англоязычные)", {"reuters.com", "cnn.com", "bbc.com", "nytimes.com", "bloomberg.com",
        "theverge.com", "techcrunch.com", "wired.com", "arstechnica.com", "theguardian.com", "wsj.com",
        "cnbc.com", "404media.co", "ynetnews.com", "semafor.com", "axios.com"}),
    ("Игры (Steam и т. п.)", {"steampowered.com", "steamcommunity.com", "epicgames.com"}),
]
bk, bk_ch = Counter(), defaultdict(set)
for d_, n in ext_ru.items():
    name = "прочее (длинный хвост)"
    for nm, ds in BUCKETS:
        if d_ in ds:
            name = nm
            break
    bk[name] += n
    bk_ch[name] |= chd_ru[d_]
tot_ext = sum(bk.values())
tot_links_ru = sum(c_ru.values())
print("\n  Корзины внешних ссылок RU (домены заданы списком выше; «прочее» — всё остальное):")
print(f"    {'корзина':44s}{'ссылок':>7s}{'% внеш.':>9s}{'% всех':>8s}{'каналов':>9s}")
for nm, n in bk.most_common():
    print(f"    {nm:44s}{n:7d}{pct(n, tot_ext):8.1f}%{pct(n, tot_links_ru):7.1f}%{len(bk_ch[nm]):9d}")
out["ru_external_buckets"] = {k: [v, len(bk_ch[k])] for k, v in bk.items()}

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 100)
print("4. ФОРВАРДЫ: «80–92 % постов — форварды» (docs/04 §5, docs/08 §4)")
print("=" * 100)
tot_p = tot_f = 0
rows = []
for ch in RU:
    v = links[ch]
    f = sum(1 for p in v if p["fwd_name"] or p["fwd_url"])
    rows.append((ch, len(v), f))
    tot_p += len(v)
    tot_f += f
print(f"  RU: постов {tot_p}, форвардов {tot_f} = {pct(tot_f, tot_p):.1f} % всех постов")
pc = [pct(f, n) for _, n, f in rows if n]
print(f"  медиана доли форвардов по каналам: {st.median(pc):.1f} %; максимум {max(pc):.1f} % "
      f"({max(rows, key=lambda r: pct(r[2], r[1]))[0]})")
ml = [pct(f, n) for ch, n, f in rows if ch in MASS]
ex = [pct(f, n) for ch, n, f in rows if ch in EXPERT]
print(f"  медиана по слоям: массовый {st.median(ml):.1f} %, экспертный {st.median(ex):.1f} %")
print("  ⇒ цифры 80.0 / 91.7 в docs/08 — это «% форвардов, не содержащих слов новость/релиз/запуск…»")
print("    (fw/max(f,1) в tools/production.py), то есть ДОЛЯ ФОРВАРДОВ ВНУТРИ форвардов, а не доля постов.")
out["forward_share_posts_pct"] = pct(tot_f, tot_p)

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 100)
print("5. РЕКЛАМА: классификатор docs/08 §4 против строгого (только явная маркировка)")
print("=" * 100)


def proj_is_ad(p):
    blob = p["text"] + " " + " ".join(p["links"])
    if ERID_BARE.search(blob) or ADTAG.search(p["text"]):
        return True
    FWD_OK = re.compile(r"(\bновост\b|\bпресс-релиз\b|\bрелиз\b|\bзапуск\b|\bобъявл)", re.I)
    return bool(p["fwd_name"] and not FWD_OK.search(p["text"]))


def strict_ad(p):
    return post_is_ad(p, strict=True)


def layer_stats(group, fn):
    per = {ch: (sum(fn(p) for p in links[ch]), len(links[ch])) for ch in group}
    med = st.median([pct(a, b) for a, b in per.values() if b])
    return med, per


for name, fn in (("проектный is_ad (erid-regex + слово «реклама» + форвард без маркера)", proj_is_ad),
                 ("явная маркировка (erid= в URL, слово erid, #реклама, #ad, «Реклама. Рекламодатель»)", strict_ad)):
    m1, _ = layer_stats(MASS, fn)
    m2, _ = layer_stats(EXPERT, fn)
    print(f"  {name}\n     медиана по каналам: массовый {m1:.1f} %, экспертный {m2:.1f} %")

digit_only = sum(1 for ch in RU for p in links[ch]
                 if ERID_BARE.findall(p["text"] + " " + " ".join(p["links"]))
                 and all(m.isdigit() for m in ERID_BARE.findall(p["text"] + " " + " ".join(p["links"]))))
any_bare = sum(1 for ch in RU for p in links[ch]
               if ERID_BARE.search(p["text"] + " " + " ".join(p["links"])))
real_erid = sum(1 for ch in RU for p in links[ch]
                if re.search(r"\berid\b", p["text"], re.I) or any(ERID_PARAM.search(u) for u in p["links"]))
print(f"\n  Проектный ERID_BARE сработал в {any_bare} постах; из них {digit_only} — только чисто цифровые строки "
      f"(ID твитов в ссылках x.com), настоящих erid среди них нет.")
print(f"  Постов с реальным erid (слово erid в тексте или erid= в ссылке): {real_erid}")
out["erid_regex_posts"] = any_bare
out["erid_regex_digit_only_posts"] = digit_only
out["real_erid_posts"] = real_erid

# что именно ловит проектный классификатор и строгий не ловит
only_proj = [(ch, p) for ch in RU for p in links[ch] if proj_is_ad(p) and not strict_ad(p)]
c1 = Counter()
for ch, p in only_proj:
    blob = p["text"] + " " + " ".join(p["links"])
    if p["fwd_name"] and not (ERID_BARE.search(blob) or ADTAG.search(p["text"])):
        c1["только из-за форварда"] += 1
    elif ADTAG.search(p["text"]):
        c1["слово «реклама/sponsored/partnership» в тексте"] += 1
    else:
        c1["erid-подобная строка без erid="] += 1
print(f"\n  Постов, которые проектный классификатор считает рекламой, а строгий — нет: {len(only_proj)}")
for k, v in c1.items():
    print(f"    {k}: {v}")
samp = [(ch, p) for ch, p in only_proj if ERID_BARE.search(p["text"] + " " + " ".join(p["links"]))
        and not p["fwd_name"]][:6]
print("  Примеры срабатывания erid-regex без erid= (что именно поймано):")
for ch, p in samp:
    blob = p["text"] + " " + " ".join(p["links"])
    print(f"    @{ch}: {ERID_BARE.search(blob).group(0)}  | {p['text'][:70]!r}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n" + "=" * 100)
print("6. ПРОВЕРКА ЦИФР docs/04 ПО ЕГО ЖЕ ДАННЫМ")
print("=" * 100)
sm = json.load(open(os.path.join(D, "sourcemap.json"), encoding="utf-8"))
b = sm["buckets"]
tot = sum(b.values())
print(f"  sourcemap.json: сумма корзин = {tot} (док: 3813); t.me = {b['Telegram (t.me)']} = {pct(b['Telegram (t.me)'], tot):.1f} %")
print("  Корзины, которые док называет «блогами вендоров», = 'Официальные блоги AI-лабораторий':",
      b["Официальные блоги AI-лабораторий"], f"({pct(b['Официальные блоги AI-лабораторий'], tot):.1f} %)")
dm = sm["domains"]
vendor_dom = ["openai.com", "anthropic.com", "claude.ai", "claude.com", "chatgpt.com", "huggingface.co",
              "blog.google", "qwen.ai", "elevenlabs.io", "perplexity.ai", "x.ai", "mistral.ai", "deepmind.google"]
print("  домены вендоров в sourcemap.json:")
for d_ in vendor_dom:
    if d_ in dm:
        print(f"    {d_:22s}{dm[d_]:5d}")
print("  Сумма по RU-каналам в by_channel (t.me) vs ссылки на СВОЙ канал из links.json:")
selft = sum(c_ru[k] for k in ("tg:свой канал (подпись)", "tg:свой пост"))
print(f"    t.me в sourcemap: {dm['t.me']}; из links.json (RU): свой канал+свой пост = {selft}, всего t.me = {tg}")

if "--json" in sys.argv:
    json.dump(out, open(os.path.join(D, "recheck_sources.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=list)
    print("\nsaved data/recheck_sources.json")
