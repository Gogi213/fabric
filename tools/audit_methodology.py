"""Аудит фактических и методических утверждений docs/01-methodology.md.

Запуск (из корня репозитория):
  python tools/audit_methodology.py            офлайн-проверки по data/*.json и коду tools/
  python tools/audit_methodology.py --emb      + эмбеддинги RU<->EN (модель из локального кэша HF)
  python tools/audit_methodology.py --live     + 5–6 запросов к t.me/s (строго последовательно, пауза 3.5 с)
Существующие файлы не меняет.
"""
import json, math, os, re, statistics as st, sys, time
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
T = os.path.join(ROOT, "tools")
J = lambda n: json.load(open(os.path.join(D, n), encoding="utf-8"))
dt = datetime.fromisoformat

links, posts, posts_en, react = J("links.json"), J("posts.json"), J("posts_en.json"), J("reactions.json")
MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
EXP = ["xor_journal", "neuraldvig", "data_secrets", "seeallochnaya", "denissexy",
       "ai_newz", "cgevent", "NeuralShit", "ai_machinelearning_big_data", "tproger", "tlive"]
RU = MASS + EXP
EN = list(posts_en)
RNG = np.random.default_rng(20260930)


def hr(t):
    print("\n" + "=" * 100 + "\n" + t + "\n" + "=" * 100)


def src(name):
    return open(os.path.join(T, name), encoding="utf-8").read()


# ============================================================ 1.2 порядок постов, страницы
hr("M 1.2. ПОРЯДОК ПОСТОВ НА СТРАНИЦЕ И РАЗМЕР СТРАНИЦЫ (по порядку записи в файлах)")
for fname, data in (("links.json", links), ("posts.json", posts)):
    pages, inv_in_page, pairs_in_page, inv_global, pairs_global = [], 0, 0, 0, 0
    for c, ps in data.items():
        cur = [ps[0]] if ps else []
        for a, b in zip(ps, ps[1:]):
            if int(b["id"]) > int(a["id"]):
                cur.append(b)
                pairs_in_page += 1
                inv_in_page += dt(b["dt"]) < dt(a["dt"])
            else:
                pages.append(len(cur))
                cur = [b]
        if cur:
            pages.append(len(cur))
        srt = sorted(ps, key=lambda p: int(p["id"]))
        for a, b in zip(srt, srt[1:]):
            pairs_global += 1
            inv_global += dt(b["dt"]) < dt(a["dt"])
    print(f"  {fname}: страниц (серий возрастающих id) {len(pages)}, постов с текстом на странице: "
          f"медиана {st.median(pages)}, макс {max(pages)}; внутри страницы id растёт, а дата падает: "
          f"{inv_in_page} из {pairs_in_page} пар; по всем постам канала (сорт. по id): {inv_global} из {pairs_global}")
print("  Пример из doc («page 1 dates: 22, 22, 23, 24, 24») — это возрастание, т.е. хронологический порядок "
      "(старые сверху), а страницы идут назад по времени.")
FWD_BAD = 'a.tgme_widget_message_forwarded_from"'
for f in ("crawl.py", "crawl_links.py"):
    s = src(f)
    mp = re.search(r"max_pages=(\d+)", s)
    since = re.search(r"SINCE = (.*)", s).group(1).strip()
    print(f"  {f}: max_pages={mp.group(1) if mp else '?'}; SINCE={since}; "
          f"пропускает посты без текста: {'if not txt' in s}; класс a.tgme_widget_message_forwarded_from в коде: "
          f"{FWD_BAD in s}")
print(f"  posts.json: постов с непустым fwd_url: {sum(1 for v in posts.values() for p in v if p['fwd_url'])}, "
      f"с fwd_name: {sum(1 for v in posts.values() for p in v if p['fwd_name'])} "
      f"(crawl.py берёт fwd_url из несуществующего a.tgme_widget_message_forwarded_from)")
cap = {c: len(v) for c, v in links.items() if len(v) >= 700}
print(f"  links.json: каналы, упёршиеся в max_pages=40 (~800 постов): {cap}; "
      f"их окно начинается с {min(p['dt'] for c in cap for p in links[c])[:16]}, а не с 2026-09-15")
bc = src("behave_crawl.py")
ppc = re.search(r"PAGES_PER_CH = (\d+)", bc).group(1)
print(f"  «12 страниц на канал»: PAGES_PER_CH есть только в behave_crawl.py "
      f"({ppc}), т.е. относится к reactions.json, а не к links/posts")

# ============================================================ 1.3 окна
hr("M 1.3/1.10. ОКНА И ОБЪЁМЫ")
for fname, data in (("posts.json", posts), ("posts_en.json", posts_en), ("links.json", links)):
    allp = [p for v in data.values() for p in v]
    notxt = sum(1 for p in allp if not p["text"].strip())
    d = sorted(dt(p["dt"]) for p in allp)
    print(f"  {fname}: ключей {len(data)}, постов {len(allp)}, без текста {notxt}, окно {d[0]:%Y-%m-%d %H:%M} … "
          f"{d[-1]:%Y-%m-%d %H:%M} UTC ({(d[-1]-d[0]).total_seconds()/86400:.2f} сут)")
ru_posts = sum(len(posts[c]) for c in RU)
same_alias = sum(1 for a, b in zip(posts["technomedia"], posts["tehnochat"]) if a["text"] == b["text"])
same_alias_l = sum(1 for a, b in zip(links["technomedia"], links["tehnochat"]) if a["text"] == b["text"])
print(f"  алиас: posts.json technomedia/tehnochat {len(posts['technomedia'])}/{len(posts['tehnochat'])}, идентичных "
      f"по позиции {same_alias}; links.json {len(links['technomedia'])}/{len(links['tehnochat'])}, идентичных {same_alias_l}")


def norm(t):
    t = t.lower()
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[^0-9a-zа-яё]+", " ", t)
    return " ".join(t.split())


def clean(t):
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"@\w+", " ", t)
    return " ".join(t.split())[:900]


n_an2 = sum(1 for v in posts.values() for p in v if len(norm(p["text"])) >= 20)
n_an2_na = sum(1 for c in RU for p in posts[c] if len(norm(p["text"])) >= 20)
n_en40 = sum(1 for v in posts_en.values() for p in v if len(clean(p["text"])) >= 40)
print(f"  analyze2.py берёт постов (norm>=20): {n_an2} (с алиасом), {n_an2_na} без алиаса; RU-каналов без алиаса: {len(RU)}")
print(f"  cross2.py EN-постов (clean>=40): {n_en40} (в доке «936 с текстом»)")
ru_links = sum(len(links[c]) for c in RU)
uniq = set()
for data, chans in ((posts, RU), (links, RU), (posts_en, EN), (links, EN)):
    for c in chans:
        for p in data.get(c, []):
            uniq.add((c, str(p["id"])))
print(f"  таблица 1.10: RU в карте источников = {ru_links} (док «~3900»); итого уникальных постов (канал,id) по "
      f"posts+posts_en+links без алиаса = {len(uniq)} (док «~6400» — сумма с двойным счётом пересекающихся окон)")
ms = J("market_size.json")
print(f"  каркас market_size.json: {len(ms['channels'])} каналов, с подписчиками "
      f"{sum(1 for v in ms['channels'].values() if v.get('subs'))}")

# ============================================================ 1.4–1.5 параметры кода
hr("M 1.4–1.5. ПАРАМЕТРЫ В КОДЕ analyze2.py")
a2 = src("analyze2.py")
jac_thr = re.findall(r">= (0\.\d+)", a2)
ball = re.search(r"len\(idxs\) > (\d+)", a2).group(1)
ngr = re.search(r"ngram_range=\((\d, \d)\)", a2).group(1)
edge = re.search(r"if v >= (0\.\d+)", a2).group(1)
print(f"  Jaccard/порог в коде: {jac_thr}; отсечка «шаров»: len(idxs) > {ball} (в доке «> 60»)")
print(f"  n-грамм TF-IDF: {ngr}; порог ребра {edge}; фильтр коротких: len(n) < 20")

# TF-IDF RU↔RU: распределение пар по корзинам (как в analyze2: кросс-канальные пары, алиас склеен)
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize as sknorm
P = []
for ch, ps in posts.items():
    for p in ps:
        n = norm(p["text"])
        if len(n) >= 20:
            P.append(("technomedia" if ch == "tehnochat" else ch, n))
X = sknorm(TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True,
                           max_features=200000).fit_transform([n for _, n in P]))
S = (X @ X.T).toarray()
chs = np.array([c for c, _ in P])
iu = np.triu_indices(len(P), 1)
cross = chs[iu[0]] != chs[iu[1]]
v = S[iu][cross]
edges = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]
hist = np.histogram(v, bins=edges)[0]
print("  TF-IDF RU↔RU, кросс-канальные пары (posts.json, алиас склеен — копии tehnochat дают cos≈1 внутри "
      "«одного» канала и обнулены):")
for lo_, hi_, k in zip(edges, edges[1:], hist):
    print(f"    {lo_:.1f}–{min(hi_,1):.1f}: {k}")
print(f"    >=0.42: {int((v >= .42).sum())}; >=0.55: {int((v >= .55).sum())}")
# вариант с алиасом как отдельным каналом (как было бы без canon)
P2 = [(ch, norm(p["text"])) for ch, ps in posts.items() for p in ps if len(norm(p["text"])) >= 20]
chs2 = np.array([c for c, _ in P2])
cross2 = chs2[iu[0]] != chs2[iu[1]]
v2 = S[iu][cross2]
print(f"    (если алиас не склеивать: 0.9–1.0 = {int(((v2>=.9)).sum())})")

# ============================================================ 1.8 алиасы
hr("M 1.8. АЛИАСЫ")
print(f"  aipost в данных: posts_en {len(posts_en.get('aipost', []))}, links {len(links.get('aipost', []))}; "
      f"artificial_intelligence_neural в любых data/*.json: "
      f"{any('artificial_intelligence_neural' in open(os.path.join(D, f), encoding='utf-8').read() for f in os.listdir(D) if f.endswith('.json'))}")
cr = src("crawl.py")
cm = re.search(r'"aipost",\s*#(.*)', cr).group(1).strip()
print(f"  crawl.py комментарий к aipost: {cm}")

# ============================================================ 1.9 форварды
hr("M 1.9. ФОРВАРДЫ (sources3.py)")
AD = re.compile(r"(альфа|alfabank| alfa|alfa_|vygodno|aaaa_|avito|немалы|beeline|mts|burger|ozon|setka|"
                r"mediyca|alfabank\.sale|Only)", re.I)
TG = re.compile(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{3,})", re.I)
sources3_ru = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet", "trends", "tlive", "technomotel",
               "hiaimedia", "xor_journal", "ai_newz", "data_secrets", "seeallochnaya", "denissexy", "neuraldvig",
               "gptpublic", "rozetked", "d_code", "cgevent", "NeuralShit", "tproger", "ai_machinelearning_big_data"]
fw_url = [(c, p) for c in sources3_ru for p in links[c] if p["fwd_url"]]
fw_any = [(c, p) for c in sources3_ru for p in links[c] if p["fwd_url"] or p["fwd_name"]]
print(f"  форвардов с fwd_url (как считает sources3.py): {len(fw_url)}; с fwd_url или fwd_name: {len(fw_any)} "
      f"(10 форвардов без ссылки на источник — скрытые/приватные — sources3.py не видит)")
cls = Counter()
srcs = defaultdict(lambda: [0, ""])
for c, p in fw_url:
    m = TG.search(p["fwd_url"])
    h = m.group(1) if m else p["fwd_name"]
    isad = bool(AD.search(h + " " + p["fwd_name"]))
    cls[isad] += 1
    srcs[(h, p["fwd_name"], isad)][0] += 1
    srcs[(h, p["fwd_name"], isad)][1] = p["text"][:70]
print(f"  классификация regex AD: рекламных {cls[True]}, новостных {cls[False]}")
ERID_ANY = re.compile(r"erid", re.I)
news_erid = [(c, p["fwd_name"]) for c, p in fw_url
             if not AD.search((TG.search(p["fwd_url"]).group(1) if TG.search(p["fwd_url"]) else p["fwd_name"]) + " " + p["fwd_name"])
             and (ERID_ANY.search(p["text"]) or any(ERID_ANY.search(u) for u in p["links"]))]
print(f"  «новостные» форварды, содержащие erid (т.е. маркированная реклама): {len(news_erid)} {Counter(n for _, n in news_erid)}")
for (h, n, isad), (k, t) in sorted(srcs.items(), key=lambda x: -x[1][0]):
    print(f"    {'AD ' if isad else 'NEW'} x{k:2d} @{h:24s} «{n[:28]}» | {t}")

# ============================================================ 1.10.2 возраст и rx
hr("M 1.10.2–1.10.4. РЕАКЦИИ: ВОЗРАСТ, ГЛУБИНА, ПРЕДЕЛ ТИПОВ")
t_end = max(dt(p["dt"]) for c in RU for p in react[c]["posts"])
pos, rr, rv, depth, npc = 0, [], [], {}, {}
er_age = []
for c in RU:
    ps = [p for p in react[c]["posts"] if p.get("views")]
    npc[c] = len(react[c]["posts"])
    d = [dt(p["dt"]) for p in react[c]["posts"]]
    depth[c] = (max(d) - min(d)).total_seconds() / 86400
    if not any(p.get("rx") for p in ps):
        continue
    age = [(t_end - dt(p["dt"])).total_seconds() / 86400 for p in ps]
    r1 = stats.spearmanr(age, [p["rx"] or 0 for p in ps]).statistic
    r2 = stats.spearmanr(age, [(p["rx"] or 0) / p["views"] for p in ps]).statistic
    r3 = stats.spearmanr(age, [p["views"] for p in ps]).statistic
    rr.append((c, r1)); rv.append(r2); er_age.append((c, r3))
    pos += r1 > 0
print(f"  каналов с реакциями: {len(rr)}; rho(возраст, rx_1k)>0 у {pos}; медиана rho {st.median(r for _, r in rr):+.2f}")
print(f"  rho(возраст, rx/просм): от {min(rv):+.2f} до {max(rv):+.2f}, медиана {st.median(rv):+.2f}")
print(f"  rho(возраст, просмотры) внутри канала: медиана {st.median(r for _, r in er_age):+.2f}, "
      f"положительных {sum(r > 0 for _, r in er_age)}/{len(er_age)}")
print("  Знак: rho>0 значит, что СТАРЫЕ посты имеют БОЛЬШЕ реакций на текущего подписчика -> метрика у медленных "
      "каналов (старые посты) ЗАВЫШЕНА, а не занижена, как пишет docs/08 §8.1")
print(f"  reactions.json: постов на канал медиана {st.median(npc.values())}, min {min(npc.values())}, max {max(npc.values())}")
for g, names in (("массовый", MASS), ("экспертный", EXP)):
    print(f"    глубина {g}: " + ", ".join(f"{c}:{depth[c]:.0f}" for c in names))
nt = Counter(len(p.get("rx_break") or {}) for c in RU for p in react[c]["posts"])
print(f"  число ключей rx_break на пост: {dict(sorted(nt.items()))}; все кастомные эмодзи слиты в один ключ 'custom' "
      f"-> «предел 12 типов» по этим данным не считается")
dl = re.search(r"DELAY = ([\d.]+)", bc).group(1)
mw_ = re.search(r"MAX_WORKERS = (\d+)", bc).group(1)
print(f"  behave_crawl.py: DELAY={dl}, MAX_WORKERS={mw_}")

# ============================================================ 1.11 протокол в docs/08
hr("M 1.11. СОБЛЮДЕНИЕ ПРОТОКОЛА В docs/08 И НУМЕРАЦИЯ")
d08 = open(os.path.join(ROOT, "docs", "08-production.md"), encoding="utf-8").read()
d01 = open(os.path.join(ROOT, "docs", "01-methodology.md"), encoding="utf-8").read()
checks = {
    "95 % CI": len(re.findall(r"95 ?% ?CI|\[\d", d08)),
    "p-значения": len(re.findall(r"\bp ?[=<]", d08)),
    "TOST": d08.count("TOST"),
    "FDR": d08.count("FDR"),
    "«не контролировалось»": len(re.findall(r"не контролир", d08)),
    "частичная корреляция/Симпсон": len(re.findall(r"Симпсон|частичн", d08)),
    "«связи нет» (запрещено 1.11.5)": len(re.findall(r"связи нет|СВЯЗИ НЕТ|Связи нет", d08)),
    "«confidence: высокий»": d08.count("confidence: высокий"),
}
print("  docs/08: " + "; ".join(f"{k}: {v}" for k, v in checks.items()))
n111 = len(re.findall(r"^## 1\.11\.", d01, re.M))
print(f"  docs/01: заголовков «## 1.11.»: {n111}")
rd = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
print(f"  README: «связи нет»: {rd.count('связи нет')}")
pr = src("production.py")
print(f"  production.py пишет data/subs.json из сети при кэше старше суток: {'json.dump(got, open(SUBS_PATH' in pr}")
print(f"  «cd parser» в docs/01 §1.12: {'cd parser' in d01}; каталога parser/ в репозитории: "
      f"{os.path.isdir(os.path.join(ROOT, 'parser'))}")

# ============================================================ эмбеддинги
if "--emb" in sys.argv:
    hr("M 1.5–1.6. ЭМБЕДДИНГИ RU↔EN (paraphrase-multilingual-MiniLM-L12-v2, локальный кэш)")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from sentence_transformers import SentenceTransformer
    PP = []
    for lang, srcd in (("RU", posts), ("EN", posts_en)):
        for ch, ps in srcd.items():
            for p in ps:
                if len(clean(p["text"])) >= 40:
                    PP.append((lang, ch, dt(p["dt"]), clean(p["text"])))
    m = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    E = np.asarray(m.encode([p[3] for p in PP], batch_size=64, normalize_embeddings=True, show_progress_bar=False))
    R_ = [i for i, p in enumerate(PP) if p[0] == "RU"]
    N_ = [i for i, p in enumerate(PP) if p[0] == "EN"]
    Sm = E[N_] @ E[R_].T
    lag = np.array([[(PP[r][2] - PP[e][2]).total_seconds() / 3600 for r in R_] for e in N_])
    alias = np.array([PP[r][1] == "tehnochat" for r in R_])
    win = np.abs(lag) <= 72
    for nm, mask in (("все пары", np.ones_like(win)), ("|лаг|<=72 ч", win),
                     ("|лаг|<=72 ч, без tehnochat", win & ~alias[None, :])):
        vv = Sm[mask.astype(bool)]
        h = np.histogram(vv, bins=edges)[0]
        print(f"  {nm}: " + ", ".join(f"{a:.1f}–{min(b,1):.1f}:{k}" for a, b, k in zip(edges, edges[1:], h)) +
              f" | >=0.55: {int((vv >= .55).sum())} | >=0.80: {int((vv >= .80).sum())}")
    tl = [j for j, e in enumerate(N_) if PP[e][1] == "tldrtech"]
    if tl:
        sub = Sm[tl][:, :]
        hit = (sub >= .55) & win[tl]
        rus = hit.any(axis=0)
        print(f"  tldrtech: постов {len(tl)}; RU-постов с cos>=0.55 (|лаг|<=72ч) хоть с одним его постом: {int(rus.sum())}; "
              f"средний cos этих пар {sub[hit].mean():.3f}")
        hit2 = sub >= .55
        print(f"  tldrtech без окна лага: RU-постов с cos>=0.55: {int(hit2.any(axis=0).sum())}; пар {int(hit2.sum())}; "
              f"средний cos пар {sub[hit2].mean():.3f}; средний по RU-посту max-cos {sub[:, hit2.any(axis=0)].max(axis=0).mean():.3f}")
    # «RU↔EN не пересекается по TF-IDF»: TF-IDF на общем словаре для пар эмбеддингов >=0.80 против случайных
    Xt = sknorm(TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True)
                .fit_transform([norm(p[3]) for p in PP]))
    XN, XR = Xt[N_], Xt[R_]
    tp = np.argwhere((Sm >= .80) & win)
    tf_true = np.array([(XN[e] @ XR[r].T).toarray()[0, 0] for e, r in tp])
    rp = np.column_stack([RNG.integers(0, len(N_), 5000), RNG.integers(0, len(R_), 5000)])
    tf_rand = np.array([(XN[e] @ XR[r].T).toarray()[0, 0] for e, r in rp])
    auc = stats.mannwhitneyu(tf_true, tf_rand).statistic / (len(tf_true) * len(tf_rand))
    print(f"  TF-IDF RU↔EN (общий словарь): у пар эмбеддингов >=0.80 медиана cos {np.median(tf_true):.3f}, "
          f"доля >=0.10: {(tf_true >= .10).mean()*100:.0f} %; у случайных пар медиана {np.median(tf_rand):.3f}, "
          f"доля >=0.10: {(tf_rand >= .10).mean()*100:.1f} %; AUC {auc:.3f}")
    # калибровка на двух парах из doc
    a = m.encode(["Релиз GPT-6.1 Sol: новая модель OpenAI для кодинга, в 5 раз дешевле",
                  "OpenAI released GPT-6.1 Sol, a new coding model that is 5x cheaper",
                  "Кулинария: рецепт борща"], normalize_embeddings=True)
    print(f"  калибровка doc: перевод {a[0]@a[1]:.3f}, нерелевантное {a[0]@a[2]:.3f}")
    # что даёт порог в «серой зоне»: случайные пары одной темы (RU↔EN) в 0.55–0.80
    mid = np.argwhere((Sm >= .55) & (Sm < .8) & win)
    print(f"  пар в серой зоне 0.55–0.80 (|лаг|<=72ч): {len(mid)}; примеры (5 случайных):")
    for k in RNG.choice(len(mid), min(5, len(mid)), replace=False):
        e, r = mid[k]
        print(f"    {Sm[e, r]:.2f} EN @{PP[N_[e]][1]}: {PP[N_[e]][3][:70]!r}")
        print(f"         RU @{PP[R_[r]][1]}: {PP[R_[r]][3][:70]!r}")

# ============================================================ живая проверка
if "--live" in sys.argv:
    hr("LIVE. t.me/s (последовательно, пауза 3.5 с)")
    import requests
    from bs4 import BeautifulSoup
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/124.0 Safari/537.36")
    s = requests.Session()
    s.headers["User-Agent"] = UA

    def get(u):
        r = s.get(u, timeout=30)
        time.sleep(3.5)
        return r

    for ch in ("tlive", "neuraldvig", "xor_journal"):
        r = get(f"https://t.me/s/{ch}")
        soup = BeautifulSoup(r.text, "html.parser")
        wr = soup.select("div.tgme_widget_message[data-post]")
        ids = [int(w["data-post"].split("/")[-1]) for w in wr]
        ts = [w.select_one("time[datetime]")["datetime"] for w in wr if w.select_one("time[datetime]")]
        more = soup.select_one("a.tme_messages_more[data-before]")
        print(f"  @{ch}: HTTP {r.status_code}; виджетов {len(wr)}; id возрастают: {ids == sorted(ids)}; "
              f"время возрастает: {ts == sorted(ts)}; пример datetime {ts[0] if ts else None}; "
              f"a.tme_messages_more[data-before]: {more.get('data-before') if more else None}; "
              f"a.tgme_widget_message_forwarded_from: {len(soup.select('a.tgme_widget_message_forwarded_from'))}, "
              f"div.tgme_widget_message_forwarded_from: {len(soup.select('div.tgme_widget_message_forwarded_from'))}, "
              f"a..._forwarded_from_name: {len(soup.select('a.tgme_widget_message_forwarded_from_name'))}; "
              f"с текстом: {sum(1 for w in wr if w.select_one('div.js-message_text'))}")
    for ch in ("aipost", "artificial_intelligence_neural"):
        r = get(f"https://t.me/s/{ch}")
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.select_one(".tgme_channel_info_header_title")
        cnt = soup.select_one(".tgme_channel_info_counter .counter_value")
        wr = soup.select("div.tgme_widget_message[data-post]")
        last = [(w["data-post"], (w.select_one("div.js-message_text").get_text(" ", strip=True)[:50]
                                  if w.select_one("div.js-message_text") else "")) for w in wr[-2:]]
        can = soup.select_one("meta[property='og:url']") or soup.select_one("link[rel=canonical]")
        print(f"  @{ch}: HTTP {r.status_code}, final {r.url}; title {title.get_text(strip=True) if title else None!r}; "
              f"подписчиков {cnt.get_text(strip=True) if cnt else None}; последние посты {last}")
print("\nГотово.")
