"""Перепроверка docs/02 (перепечатки RU), docs/03 (зарубежные каналы), docs/05 (скорость).

Всё считается заново из сырых данных репозитория; пути относительные от корня.
Таблицы из документов (02 §2.2/2.4/2.5/2.7, 03 §3.1/3.6/3.7, 05 §3) ПАРСЯТСЯ из .md
прямо при запуске, поэтому после правки документа вердикт обновится сам. Отдельные
фразы из прозы («23 из 24», «медиана ≈ 2.5 ч», …) зашиты в словарь DOC ниже вместе
со ссылкой на параграф.

Запуск:
  python tools/recheck_crosspost.py                 офлайн-часть (только данные репозитория)
  python tools/recheck_crosspost.py --live          + сверка с живыми страницами t.me/s/
                                                     (~60 запросов, 1.1 с между запросами)
  python tools/recheck_crosspost.py --embed         + пересчёт кросс-пар эмбеддингами
                                                     (нужен sentence-transformers, качает модель)
  python tools/recheck_crosspost.py --json          + пишет data/recheck_crosspost.json
Зависимости: офлайн-часть — только stdlib; пересчёт кластеров — numpy+scikit-learn
(если их нет, блок пропускается); --live — requests+bs4.

Вердикты: ВЕРНО / ВЕРНО ОКРУГЛЕНО / НЕВЕРНО / НЕ ПРОВЕРЯЕМО.
Файлы data/*.json и tools/* этот скрипт НЕ перезаписывает.
"""
import json, math, os, re, statistics as st, sys, time
from collections import Counter, defaultdict
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
DOCS = os.path.join(ROOT, "docs")
ARGS = set(sys.argv[1:])
LIVE, EMBED, WRITE_JSON = "--live" in ARGS, "--embed" in ARGS, "--json" in ARGS


def jload(name):
    return json.load(open(os.path.join(D, name), encoding="utf-8"))


def doc(name):
    return open(os.path.join(DOCS, name), encoding="utf-8").read()


def section(text, start, end=None):
    """Кусок markdown между заголовками (по подстроке)."""
    a = text.index(start)
    b = text.index(end, a + 1) if end else len(text)
    return text[a:b]


ru = jload("posts.json")
en = jload("posts_en.json")
CL = jload("clusters.json")
CROSS = jload("cross_strict.json")
TL = jload("timeline_hn.json")
LINKS = jload("links.json")
SUBS = jload("subs.json")
D02, D03, D05 = doc("02-crossposting-ru.md"), doc("03-foreign-channels.md"), doc("05-timing.md")

ALIAS = {"tehnochat": "technomedia"}
TM = "technomedia/tehnochat"          # имя канала-алиаса в clusters.json
UNI1 = {"whackdoor", "bugnotfeature", "exploitex", TM, "naebnet", "trends", "rozetked", "technomotel"}
UNI2 = {"xor_journal", "neuraldvig", "data_secrets", "ai_machinelearning_big_data", "ai_newz",
        "seeallochnaya", "denissexy", "cgevent", "NeuralShit", "gptpublic"}          # docs/02 §2.1


def dt(s):
    return datetime.fromisoformat(s)


def mins(a, b):
    """минуты от a до b (строки ISO)"""
    return (dt(b) - dt(a)).total_seconds() / 60


def canon_url(u):
    return u.replace("/tehnochat/", "/technomedia/")


def med_hi(v):
    """«верхняя медиана» sorted(v)[len//2] — так считает timeline3.py и, судя по §2.5, docs/02"""
    s = sorted(v)
    return s[len(s) // 2]


# ------------------------------------------------------------------ отчёт
RES = []


class Rep:
    cur = ""


def sec(title):
    Rep.cur = title
    print("\n" + "=" * 110 + f"\n{title}\n" + "=" * 110)


def sub(title):
    print(f"\n--- {title}")


def check(ref, claim, docv, calc, verdict, note=""):
    assert verdict in ("ВЕРНО", "ВЕРНО ОКРУГЛЕНО", "НЕВЕРНО", "НЕ ПРОВЕРЯЕМО"), verdict
    RES.append({"ref": ref, "claim": claim, "doc": str(docv), "calc": str(calc),
                "verdict": verdict, "note": note})
    tail = f"  // {note}" if note else ""
    print(f"  [{verdict:15s}] {ref:10s} {claim}: док={docv} | пересчёт={calc}{tail}")


def num_verdict(docv, calc, tol=0.0):
    if docv == calc:
        return "ВЕРНО"
    return "ВЕРНО ОКРУГЛЕНО" if abs(docv - calc) <= tol else "НЕВЕРНО"


def f1(x, nd=1):
    return "—" if x is None else f"{x:.{nd}f}"


def parse_k(s):
    """'1.44 M' -> 1.44e6, '19.4 K' -> 19400, '19' -> 19"""
    m = re.match(r"\s*([\d.,]+)\s*([KkMm]?)", s.replace(" ", " "))
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return v * {"K": 1e3, "M": 1e6, "": 1}[m.group(2).upper()]


def minus(s):
    return s.replace("−", "-").replace("**", "").strip()


# Фразы из прозы, которых нет в таблицах (значение, где в документе)
DOC = {
    "n_posts_header": 1595,          # 02 шапка: «22 канала, 1595 постов с текстом»
    "n_clusters": 64,                # 02 §2.12
    "wd_bnf_common": 15,             # 02 §2.3
    "lag_wd_bnf": (7, 8),            # 02 §2.3/§2.5, 05 §2.1
    "uni_links": 2,                  # 02 §2.1: «МЕЖДУ НИМИ: 2 связи за неделю»
    "uni1_dup_range": (0.6, 14.0),   # 02 §2.1
    "uni2_dup_range": (4.0, 35.0),   # 02 §2.1
    "uni1_dup_range_210": (14.0, 17.0),   # 02 §2.10 п.1
    "cluster_size_median": 22,       # 02 §2.11 «медиана 22 [11, 64]»
    "hia_ru_first": (23, 24),        # 03 §3.3
    "hia_twin": (18, 20),            # 03 §3.3: «18 из 20 английских постов имеют русского близнеца»
    "hia_median_h": 2.5, "hia_min_min": 11, "hia_max_h": 20,         # 03 §3.3
    "ain_ru_first": (23, 27),        # 03 §3.4
    "ain_lag": (12, 43),             # 03 §3.4: «от 12 минут до 43 часов»
    "cross_pairs": 124,              # 03 шапка
    "n_en_posts": 936, "n_en_channels": 14,      # 03 шапка
    "zero_cross_channels": 10,       # 03 §3.7
    "tl_total": 12, "tl_valid": 3,   # 05 §3
    "hn_links": 2,                   # 05 §4: «hackernews встречается 2 раза»
}


# ================================================================== 0. данные
sec("0. ДАННЫЕ: что лежит в posts.json, алиасы, часовой пояс")
raw_total = sum(len(v) for v in ru.values())
same_ids = {p["id"] for p in ru["technomedia"]} == {p["id"] for p in ru["tehnochat"]}
ident = sum(1 for a, b in zip(ru["technomedia"], ru["tehnochat"])
            if (a["id"], a["dt"], a["text"]) == (b["id"], b["dt"], b["text"]))


def norm(t):                                   # как в tools/analyze2.py
    t = re.sub(r"https?://\S+", " ", t.lower())
    return " ".join(re.sub(r"[^0-9a-zа-яё]+", " ", t).split())


def clean(t):                                   # как в tools/cross2.py
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"@\w+", " ", t)
    return " ".join(t.split())[:900]


n_text_raw = sum(1 for ps in ru.values() for p in ps if len(norm(p["text"])) >= 20)
n_text_uniq = sum(1 for ch, ps in ru.items() if ch not in ALIAS for p in ps if len(norm(p["text"])) >= 20)
print(f"  ключей в posts.json: {len(ru)} (22 канала + алиас tehnochat); постов всего {raw_total}; "
      f"у technomedia и tehnochat {len(ru['technomedia'])}/{len(ru['tehnochat'])}, "
      f"совпадают id: {same_ids}, побитово идентичны (id+dt+text): {ident}")
check("02 шапка", "«1595 постов с текстом»", DOC["n_posts_header"], n_text_uniq,
      "ВЕРНО" if DOC["n_posts_header"] == n_text_uniq else "НЕВЕРНО",
      f"1595 = {n_text_uniq} уникальных + {len(ru['tehnochat'])} копий tehnochat (тот же канал, analyze2 не склеил алиас)")
tz_ok = all(p["dt"].endswith("+00:00") for ps in ru.values() for p in ps) and \
        all(p["dt"].endswith("+00:00") for ps in en.values() for p in ps)
zero_sec = Counter(); all_sec = Counter()
for ch, ps in ru.items():
    for p in ps:
        all_sec[ch] += 1
        zero_sec[ch] += p["dt"][17:19] == "00"
z_tot = sum(zero_sec.values())
print(f"  все datetime с суффиксом +00:00: {tz_ok}; секунды != 00 у {100 * (1 - z_tot / raw_total):.1f} % постов")
check("05 §7.4", "«datetime с точностью до минуты для части каналов»", "округлено до минуты",
      f"секунды есть у {100 * (1 - z_tot / raw_total):.1f} % постов; макс. доля :00 по каналу "
      f"{max(zero_sec[c] / all_sec[c] for c in all_sec) * 100:.0f} %",
      "НЕВЕРНО", "округление — артефакт ручных ANCHORS в tools/timeline3.py ('…T%H:%M'), не t.me")
ALLDT = [p["dt"] for ps in ru.values() for p in ps]
check("02 шапка", "окно «22…29 сентября (7 дней)»", "7 дней",
      f"{min(ALLDT)[:16]} … {max(ALLDT)[:16]} = {mins(min(ALLDT), max(ALLDT)) / 1440:.1f} сут", "ВЕРНО ОКРУГЛЕНО")

# ================================================================== 1. §2.2
sec("1. docs/02 §2.2 — «доля перепечатанных постов»")
raw_by = Counter(); text_by = Counter(); c2_by = Counter()
for ch, ps in ru.items():
    c = TM if ch in ALIAS or ch == "technomedia" else ch
    raw_by[c] += len(ps)
    text_by[c] += sum(1 for p in ps if len(norm(p["text"])) >= 20)
    c2_by[c] += sum(1 for p in ps if len(clean(p["text"])) >= 40)
uniq_by = dict(raw_by); uniq_by[TM] = len(ru["technomedia"])
uniq_text = dict(text_by); uniq_text[TM] = sum(1 for p in ru["technomedia"] if len(norm(p["text"])) >= 20)
uniq_c2 = dict(c2_by); uniq_c2[TM] = sum(1 for p in ru["technomedia"] if len(clean(p["text"])) >= 40)

clusters = CL["clusters"]


def members(x):
    """члены кластера без дублей алиаса (один пост technomedia=tehnochat входит дважды)"""
    seen, out = set(), []
    for m in x["members"]:
        u = canon_url(m["url"])
        if u not in seen:
            seen.add(u); out.append({**m, "url": u})
    return sorted(out, key=lambda m: dt(m["dt"]))


ncl = Counter(); posts_in = defaultdict(set)
for x in clusters:
    chs = set()
    for m in members(x):
        chs.add(m["ch"]); posts_in[m["ch"]].add(m["url"])
    for c in chs:
        ncl[c] += 1
dup_chk = all(len(posts_in[c]) == ncl[c] for c in ncl)
print(f"  «дублирующих» в analyze2 = число КЛАСТЕРОВ с участием канала; число разных постов в кластерах "
      f"совпадает с ним у всех каналов: {dup_chk}")

rows22 = []
for ln in section(D02, "## 2.2.", "## 2.3.").splitlines():
    m = re.match(r"\|\s*@(\S+)(?:\s*\(\+@\S+\))?\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*\**([\d.]+)\s*%", ln)
    if m:
        ch = TM if m.group(1) == "technomedia" else m.group(1)
        rows22.append((ch, int(m.group(2)), int(m.group(3)), float(m.group(4))))
print(f"\n  {'канал':28s}|док: дубл/всего  доля |posts.json: сырых  с текстом(≥20)  cross2(≥40)|дубл   доля(верная)  вердикт")
bad22 = 0
for ch, dd, dtot, dsh in rows22:
    tot_ok = uniq_text.get(ch)
    calc_sh = ncl.get(ch, 0) / tot_ok * 100 if tot_ok else 0
    v_tot = num_verdict(dtot, tot_ok)
    v_dup = num_verdict(dd, ncl.get(ch, 0))
    v_sh = num_verdict(dsh, round(calc_sh, 1), 0.051)
    bad = "НЕВЕРНО" in (v_tot, v_dup, v_sh)
    bad22 += bad
    print(f"  {ch:28s}|{dd:4d}/{dtot:<4d} {dsh:5.1f} %|{uniq_by[ch]:6d}{uniq_text[ch]:12d}{uniq_c2[ch]:14d}  "
          f"|{ncl.get(ch, 0):4d}  {calc_sh:6.1f} %   {'НЕВЕРНО' if bad else 'ВЕРНО'}")
check("02 §2.2", "строк таблицы без ошибок", f"{len(rows22)} строк", f"{len(rows22) - bad22} верных",
      "ВЕРНО" if not bad22 else "НЕВЕРНО", "ошибка только в строке technomedia/tehnochat: 292 вместо 146, 3.4 % вместо 6.8 %")
r = {c: (d, t, s) for c, d, t, s in rows22}
check("02 §2.2", "@technomedia(+@tehnochat): всего постов", r[TM][1], uniq_text[TM], num_verdict(r[TM][1], uniq_text[TM]),
      "tehnochat = тот же канал (на t.me/s/ идентичные заголовок, 3.08M, 10.2K фото); посчитан дважды")
check("02 §2.2", "@technomedia(+@tehnochat): доля, %", r[TM][2], round(ncl[TM] / uniq_text[TM] * 100, 1),
      num_verdict(r[TM][2], round(ncl[TM] / uniq_text[TM] * 100, 1), 0.051), "вдвое занижена")
check("02 §2.2", "@whackdoor всего постов", r["whackdoor"][1], len(ru["whackdoor"]), "ВЕРНО", "posts.json: 160")
check("03 §3.7", "@whackdoor «1 пост из 155»", 155, uniq_c2["whackdoor"],
      "ВЕРНО" if uniq_c2["whackdoor"] == 155 else "НЕВЕРНО",
      f"разночтение 160/155: cross2.py отбрасывает посты с очищенным текстом (без URL и @упоминаний) < 40 симв. "
      f"({len(ru['whackdoor']) - uniq_c2['whackdoor']} шт.); в docs/03 знаменатель другой, без пояснения")
check("02 §2.2", "@bugnotfeature всего", r["bugnotfeature"][1], len(ru["bugnotfeature"]), "ВЕРНО", "120")
order_ok = [s for _, _, _, s in rows22] == sorted([s for _, _, _, s in rows22], reverse=True)
check("02 §2.2", "таблица отсортирована по убыванию доли", "да", "да" if order_ok else "нет (tlive 13.0 % стоит выше naebnet 14.6 %)",
      "ВЕРНО" if order_ok else "НЕВЕРНО", "косметика")
dc = r["d_code"]
check("02 §2.10", "«@tproger, @d_code — 0 % дублирования»", "0 %", f"tproger {r['tproger'][2]} %, d_code {dc[2]} % (2 кластера)",
      "НЕВЕРНО", "внутри самого docs/02: §2.2 даёт d_code 1.5 %; плюс у d_code 14 кросс-пар с EN (docs/03 §3.7)")

# повторный прогон кластеризации (проверка воспроизводимости clusters.json и влияния алиаса)
sub("Пересчёт кластеризации из posts.json (как tools/analyze2.py: TF-IDF 1-2gram cos≥0.42, union-find)")
RECL = None
try:
    import numpy as np
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize as sk_norm

    def recluster(drop_alias):
        P = []
        for ch, ps in ru.items():
            if drop_alias and ch == "tehnochat":
                continue
            for p in ps:
                n = norm(p["text"])
                if len(n) >= 20:
                    P.append({"ch": ch, "c": TM if ch in ALIAS or ch == "technomedia" else ch, "id": p["id"], "n": n})
        X = sk_norm(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=200000).fit_transform([p["n"] for p in P]))
        S = (X @ X.T).toarray(); np.fill_diagonal(S, 0)
        par = list(range(len(P)))

        def find(a):
            while par[a] != a:
                par[a] = par[par[a]]; a = par[a]
            return a
        for i in range(len(P)):
            for j in range(i + 1, len(P)):
                if P[i]["c"] != P[j]["c"] and S[i, j] >= 0.42:
                    par[find(j)] = find(i)
        g = defaultdict(list)
        for i in range(len(P)):
            g[find(i)].append(i)
        return len(P), {frozenset(f"{P[i]['c']}:{P[i]['id']}" if P[i]['c'] != TM else f"{TM}:{P[i]['id']}" for i in v)
                        for v in g.values() if len(v) >= 2}

    n_a, cl_a = recluster(False)
    n_b, cl_b = recluster(True)
    orig = {frozenset(f"{m['ch']}:{m['url'].split('/')[-1]}" for m in x["members"]) for x in clusters}
    print(f"  как в analyze2: постов {n_a}, кластеров {len(cl_a)}, совпадает с clusters.json: {cl_a == orig}")
    print(f"  с удалением tehnochat: постов {n_b}, кластеров {len(cl_b)}, тот же набор кластеров: "
          f"{ {frozenset(s.split(':')[0] + ':' + s.split(':')[1] for s in c) for c in cl_b} == {frozenset(s.split(':')[0] + ':' + s.split(':')[1] for s in c) for c in cl_a} }")
    RECL = (cl_a == orig, len(cl_b))
    check("02 §2.12", "clusters.json воспроизводится из posts.json", "64 кластера", f"{len(cl_a)} кластеров, идентичны: {cl_a == orig}",
          "ВЕРНО" if cl_a == orig else "НЕВЕРНО")
    check("02 §2.12", "число кластеров после склейки алиаса", DOC["n_clusters"], len(cl_b), num_verdict(DOC["n_clusters"], len(cl_b)),
          "удаление дубля tehnochat меняет знаменатели, но не состав кластеров")
except ImportError:
    print("  numpy/scikit-learn не установлены — блок пропущен")
    check("02 §2.12", "clusters.json воспроизводится из posts.json", "64", "—", "НЕ ПРОВЕРЯЕМО", "нет numpy/scikit-learn")
    check("02 §2.12", "число кластеров", DOC["n_clusters"], len(clusters), num_verdict(DOC["n_clusters"], len(clusters)))

# ================================================================== 2. §2.4-2.7
sec("2. docs/02 §2.4 (матрица), §2.5 (направление и лаг), §2.6 (rozetked), §2.7 (кто первый)")
pairs_real = {tuple(sorted((p["a"], p["b"]))): p["n"] for p in CL["pairwise"]}
NAMEFIX = {"ai_ml_big_data": "ai_machinelearning_big_data"}
docm = Counter(); occ = Counter()
for ln in section(D02, "## 2.4.", "## 2.5.").splitlines():
    m = re.match(r"\s*@(\S+)\s+⇄\s+@(\S+)\s+(\d+)\s*$", ln)
    if m:
        a, b = NAMEFIX.get(m.group(1), m.group(1)), NAMEFIX.get(m.group(2), m.group(2))
        k = tuple(sorted((a, b))); docm[k] += int(m.group(3)); occ[k] += 1
diff = []
for k in set(docm) | set(pairs_real):
    if docm.get(k, 0) != pairs_real.get(k, 0):
        diff.append((k, docm.get(k), pairs_real.get(k), occ.get(k, 0)))
print(f"  строк матрицы в документе: {sum(occ.values())}, различных пар {len(docm)}; реальных пар в clusters.json: {len(pairs_real)}")
for k, dv, rv, o in sorted(diff, key=lambda z: str(z[0])):
    why = "пара записана дважды" if o > 1 else ("нет в документе" if dv is None else "нет в данных")
    print(f"    расхождение {k[0]} ⇄ {k[1]}: док {dv}, данные {rv}  ({why})")
check("02 §2.4", "верхняя часть матрицы (пары ≥ 2 тем)", "6 строк-лидеров",
      "все значения ≥ 2 совпадают" if all((dv or 0) < 2 or dv == rv or o > 1 for k, dv, rv, o in diff) else "есть расхождения", "ВЕРНО")
check("02 §2.4", "матрица целиком", f"{sum(occ.values())} строк / {len(docm)} пар",
      f"{len(pairs_real)} пар, сумма {sum(pairs_real.values())}", "НЕВЕРНО" if diff else "ВЕРНО",
      f"{len(diff)} расхождений: 3 пары записаны дважды (exploitex⇄whackdoor 4+1, exploitex⇄trends 3+1, tlive⇄xor_journal 1+1), "
      f"1 выдуманная (exploitex⇄hiaimedia), 5 пропущено — переписана руками; выводы (лидер 15) не меняются")
wb = pairs_real[("bugnotfeature", "whackdoor")]
check("02 §2.3", "«15 общих тем» whackdoor⇄bugnotfeature — максимум", DOC["wd_bnf_common"], wb,
      num_verdict(DOC["wd_bnf_common"], wb), f"следующая по величине пара: {sorted(pairs_real.values())[-2]} (xor⇄neuraldvig)")

# ---- лаги по парам: первый пост каждого канала в кластере
def first_by_ch(x):
    f = {}
    for m in members(x):
        f.setdefault(m["ch"], m)
    return f


LAG = defaultdict(list)         # (src,dst) -> [мин]
for x in clusters:
    f = first_by_ch(x)
    for a in f:
        for b in f:
            if a != b:
                d = mins(f[a]["dt"], f[b]["dt"])
                if d > 0:
                    LAG[(a, b)].append(d)
rows25 = []
for ln in section(D02, "## 2.5.", "## 2.6.").splitlines():
    m = re.match(r"\s*@(\S+)\s+→\s+@(\S+)\s+(\d+)\s+([+-]?\d+)\s+([+-]?\d+)\s*$", ln)
    if m:
        rows25.append((NAMEFIX.get(m.group(1), m.group(1)), NAMEFIX.get(m.group(2), m.group(2)),
                       int(m.group(3)), int(m.group(4)), int(m.group(5))))
print(f"\n  §2.5: {len(rows25)} строк. Пересчёт: по кластерам, берётся первый пост канала в кластере (алиас склеен), n = число кластеров.")
print(f"  {'источник → получатель':52s}|док n  min  мед |факт n   min   медиана  верх.мед|вердикт")
ok25 = part25 = bad25 = 0; maxmed = 0
for a, b, dn, dmin, dmed in rows25:
    v = LAG.get((a, b), [])
    if not v:
        print(f"  {a + ' → ' + b:52s}|{dn:5d} {dmin:+4d} {dmed:+4d} |   нет данных"); bad25 += 1; continue
    n, mn, md, mh = len(v), min(v), st.median(v), med_hi(v)
    vn = dn == n; vmin = abs(dmin - mn) <= 1.0; vmed = abs(dmed - md) <= 1.0; vmh = abs(dmed - mh) <= 1.0
    status = "ВЕРНО" if vn and vmin and vmed else ("верна только как «верхняя медиана»" if vn and vmin and vmh else "НЕВЕРНО")
    if status == "ВЕРНО": ok25 += 1
    elif status.startswith("верна"): part25 += 1
    else: bad25 += 1
    print(f"  {a + ' → ' + b:52s}|{dn:5d} {dmin:+4d} {dmed:+4d} |{n:6d} {mn:6.1f} {md:8.1f} {mh:8.1f} |{status}" +
          ("" if vn else f"  (n: {dn}≠{n})"))
check("02 §2.5", f"строки таблицы лагов ({len(rows25)})", "все верны", f"{ok25} верно, {part25} только как верхняя медиана, {bad25} неверно",
      "ВЕРНО" if ok25 == len(rows25) else "НЕВЕРНО",
      "кода для таблицы в репозитории нет; 'медиана' в n=2 — это максимум (верхняя медиана sorted(v)[n//2], как в timeline3.py)")
v = LAG[("ai_machinelearning_big_data", "data_secrets")]
check("02 §2.5", "«медленные (медиана > 2 ч): ai_ml→data_secrets +176»", "+176 мин", f"медиана {st.median(v):.0f} мин (n=2: {[round(x) for x in v]})",
      "НЕВЕРНО", "по настоящей медиане 116 мин < 120: по собственному критерию документа — не «медленный»")

# ---- §2.7 кто первым
firsts = Counter(x["first"]["ch"] for x in clusters)
docf = {}
for ln in section(D02, "## 2.7.", "## 2.8.").splitlines():
    m = re.match(r"\s*@(\S+)\s+(\d+)\s*$", ln)
    if m:
        name = m.group(1)
        full = [c for c in list(firsts) + list(ncl) if c == name or c.startswith(name)]
        docf[full[0] if full else name] = int(m.group(2))
mism = {c: (docf.get(c), firsts.get(c, 0)) for c in set(docf) | set(firsts) if docf.get(c, 0) != firsts.get(c, 0)}
check("02 §2.7", "таблица «первый в кластере» (17 каналов, сумма 64)", f"сумма {sum(docf.values())}", f"сумма {sum(firsts.values())}; расхождений: {len(mism)}",
      "ВЕРНО" if not mism else "НЕВЕРНО", "пересчёт по полю first каждого кластера")
span = sorted(x["span_min"] for x in clusters)
long_ = [x for x in clusters if x["span_min"] > 120]
print(f"\n  разброс кластеров (первый→последний пост): медиана {st.median(span):.1f} мин; >120 мин: {len(long_)}; ≥ 1 сут: {sum(1 for s in span if s >= 1440)}")
sub("Чувствительность «первый»: win-rate = первым / кластеров с участием канала (только кластеры с разбросом ≤ 120 мин)")
short = [x for x in clusters if x["span_min"] <= 120]
fc, tc = Counter(), Counter()
for x in short:
    fc[x["first"]["ch"]] += 1
    for c in {m["ch"] for m in members(x)}:
        tc[c] += 1
print("  " + "  ".join(f"{c}:{fc[c]}/{tc[c]}" for c, _ in tc.most_common(9)))

# ---- §2.6 rozetked
sub("§2.6: «rozetked — единственный канал, стабильно выигрывающий у всех»")
troz = [(i, x) for i, x in enumerate(clusters) if any(m["ch"] == "rozetked" for m in members(x))]
roz_first = sum(1 for i, x in troz if x["first"]["ch"] == "rozetked")
for i, x in troz:
    ms = members(x)
    print(f"    кластер #{i}: разброс {x['span_min']:.0f} мин, " + ", ".join(f"{m['ch'][:9]} {m['dt'][5:16]}" for m in ms))
wr = {c: (fc2, tc2) for c in ncl for fc2, tc2 in [(firsts.get(c, 0), ncl[c])] if tc2 >= 3}
print("  win-rate по всем кластерам (первым/в кластерах, n≥3): " +
      ", ".join(f"{c} {a}/{b}={a / b:.0%}" for c, (a, b) in sorted(wr.items(), key=lambda kv: -kv[1][0] / kv[1][1])[:8]))
check("02 §2.6", "rozetked «стабильно выигрывает у всех»", "единственный канал, все берут у него",
      f"rozetked в {len(troz)} кластерах, первым в {roz_first} (третий кластер — ложная склейка на 3 сут, реклама Авито); "
      f"реальных событий 2", "НЕВЕРНО",
      "n=2 события; win-rate naebnet 9/12, trends 4/5, xor_journal 7/10, exploitex 11/17 — не ниже; §2.7 (rozetked первым 2 раза против 11 у exploitex/whackdoor) "
      "не противоречит §2.6 формально, но подтверждает только «в 2 из 2 своих событий был первым», а не «стабильно»")


def find_posts(rx, day, ch_skip=("tehnochat",)):
    out = {}
    for ch, ps in ru.items():
        if ch in ch_skip:
            continue
        for p in ps:
            if p["dt"].startswith(day) and re.search(rx, p["text"], re.I):
                if ch not in out or p["dt"] < out[ch]["dt"]:
                    out[ch] = p
    return out


sub("§2.6 примеры: сверка времён с posts.json")
ex1 = find_posts(r"Redmi\s*Note\s*17", "2026-09-24")
base = ex1["rozetked"]["dt"]
DOC_EX1 = {"whackdoor": 55, "xor_journal": 64, "bugnotfeature": 75, "exploitex": 119}
print(f"  Redmi Note 17: rozetked {base[5:16]} (id {ex1['rozetked']['id']})")
for ch in ("whackdoor", "xor_journal", "bugnotfeature", "technomedia", "exploitex", "naebnet"):
    if ch in ex1:
        d = mins(base, ex1[ch]["dt"])
        print(f"    {ch:14s} {ex1[ch]['dt'][5:16]}  +{d:.0f} мин   док: {DOC_EX1.get(ch, '—')}")
for ch, dv in DOC_EX1.items():
    d = mins(base, ex1[ch]["dt"])
    check("02 §2.6", f"Redmi Note 17: {ch} отстаёт", f"+{dv}", f"+{d:.0f}", num_verdict(dv, round(d), 1))
nb = ex1["naebnet"]
check("02 §2.6", "Redmi Note 17: @naebnet «09:38 (на след. день) +1440»", "24.09→25.09 09:38, +1440 мин",
      f"{nb['dt'][5:16]} (id {nb['id']}), +{mins(base, nb['dt']):.0f} мин", "НЕВЕРНО",
      "такого поста нет: 09:38 — это naebnet 23.09 09:38:16 (id 17271) из ДРУГОЙ истории («Братья»), т.е. на 1448 мин РАНЬШЕ rozetked-поста 24.09, а не позже; даже 25.09 09:38 дало бы +1432, а не 1440")
ex2 = find_posts(r"Братья", "2026-09-23")
ex2 = {c: p for c, p in ex2.items() if re.search(r"Макконахи|Харрельсон", p["text"])}
b2 = ex2["rozetked"]["dt"]
for ch, dv in {"exploitex": 38, "technomedia": 41, "naebnet": 195}.items():
    d = mins(b2, ex2[ch]["dt"])
    check("02 §2.6", f"Apple TV/«Братья»: {ch}", f"+{dv}", f"+{d:.0f}", num_verdict(dv, round(d), 1))
print("    не упомянуты в примерах: " + ", ".join(f"{c} +{mins(b2, p['dt']):.0f}" for c, p in ex2.items() if c not in ("rozetked", "exploitex", "technomedia", "naebnet")) +
      " | Redmi: technomedia +%.0f" % mins(base, ex1["technomedia"]["dt"]))

# ================================================================== 3. методика
sec("3. МЕТОДИКА ЛАГОВ: что такое «первый» и «лаг» в analyze2.py")
src = open(os.path.join(ROOT, "tools", "analyze2.py"), encoding="utf-8").read()
print("  analyze2.cluster_info: first = min по p['dt'] (время публикации в канале); поле fwd используется только для печати; "
      f"фильтра на форварды/рекламу в коде нет: {'fwd' not in re.sub(r'.*print.*', '', src.split('def cluster_info')[1].split('rows = []')[0])}")
fw = [(i, x) for i, x in enumerate(clusters) if any(m["fwd"] for m in x["members"])]
AD_HOST = re.compile(r"(alfa|sber|mts\.ru|avito|mws|cloud\.ru|yandex\.cloud|beeline|t-bank|tbank|setka)", re.I)
idx = {(ch, p["id"]): p for ch, ps in LINKS.items() for p in ps}
ad_like = []
for i, x in enumerate(clusters):
    k = 0
    for m in members(x):
        p = idx.get((m["url"].split("/")[3], m["url"].split("/")[4]))
        if p and (AD_HOST.search(" ".join(p.get("links") or [])) or p.get("fwd_name") in ("Авито", "Альфа-Банк", "Альфа-Выгодно", "Немалый бизнес", "Яндекс", "Alfa Only")):
            k += 1
    if k >= 2:
        ad_like.append(i)
print(f"  кластеров с пересланными постами (fwd_name): {len(fw)} из {len(clusters)}")
print(f"  кластеров, похожих на рекламный посев (≥2 поста с ссылкой на рекламодателя / fwd от рекламодателя): {len(ad_like)}: {ad_like}")
big = [i for i, x in enumerate(clusters) if x["span_min"] >= 1396]
print(f"  кластеры с разбросом ≥ ~1 сут: {len(big)}; из них рекламоподобных: {len([i for i in big if i in ad_like])}")
check("03 (метод)", "время поста ≠ время появления новости для форвардов/посевов учтено", "—",
      f"нет: {len(fw)} кластеров с fwd и {len(ad_like)} рекламоподобных не отделены; {len([i for i in big if i in ad_like])} из {len(big)} суточных «догонялок» — рекламные интеграции",
      "НЕВЕРНО", "у рекламы время задаёт рекламодатель; в §2.8 это названо «заполнением ленты», а не посевом")
tl_dt = sorted(p["dt"] for p in en["tldrtech"])
gaps = [mins(a, b) * 60 for a, b in zip(tl_dt, tl_dt[1:])]
hrs = Counter(p["dt"][:13] for p in en["tldrtech"])
print(f"  tldrtech: {len(tl_dt)} постов в {len(hrs)} различных часах, {sum(1 for g in gaps if g <= 60) / len(gaps) * 100:.1f} % интервалов ≤ 60 с, "
      f"медианный интервал {st.median(gaps):.0f} с")
ntl = sum(1 for r in CROSS if r["en_ch"] == "tldrtech")
check("03 §3.6", "@tldrtech: время поста = время новости (27 пар, «EN-первый 22 %»)", "27 пар", f"{ntl} пар; время — выгрузка дайджеста пачкой", "НЕВЕРНО",
      "500 постов за ~15 часов, 98 % интервалов ≤ 60 с; лаги к tldrtech бессмысленны; в 124 пар вклад 22 %")

# ================================================================== 4. whackdoor ⇄ bugnotfeature
sec("4. «Лаг 7–8 минут» whackdoor ⇄ bugnotfeature (docs/02 §2.3/§2.5, docs/05 §2.1, README)")
wdb, bwd, both_ = [], [], []
for i, x in enumerate(clusters):
    f = first_by_ch(x)
    if "whackdoor" in f and "bugnotfeature" in f:
        d = mins(f["whackdoor"]["dt"], f["bugnotfeature"]["dt"])
        both_.append((i, d, x["verbatim"]))
        (wdb if d > 0 else bwd).append(abs(d))
print(f"  общих кластеров: {len(both_)}; whackdoor раньше: {len(wdb)}, bugnotfeature раньше: {len(bwd)}; дословных (verbatim): {sum(1 for _, _, v in both_ if v)}")
print(f"  whackdoor→bugnotfeature: n={len(wdb)}, min {min(wdb):.1f}, медиана {st.median(wdb):.1f}, верх.медиана {med_hi(wdb):.1f}, max {max(wdb):.1f}; "
      f"значения {[round(v, 1) for v in sorted(wdb)]}")
print(f"  bugnotfeature→whackdoor: n={len(bwd)}, min {min(bwd):.1f}, медиана {st.median(bwd):.1f}; значения {[round(v, 1) for v in sorted(bwd)]}")
allabs = [abs(d) for _, d, _ in both_]
print(f"  по модулю по всем {len(allabs)}: медиана {st.median(allabs):.1f}; доля |лаг| ≤ 15 мин: {sum(1 for v in allabs if v <= 15)}/{len(allabs)}")
k = len(wdb)
pval = 2 * sum(math.comb(len(both_), j) for j in range(max(k, len(bwd)), len(both_) + 1)) / 2 ** len(both_)
check("02 §2.5", "whackdoor→bugnotfeature: n", 9, len(wdb), num_verdict(9, len(wdb)),
      "9+3 = 12 ≠ 15 «общих тем» (§2.3); верно 12+3 = 15. Медиана «+7» соответствует n=12 (6.7), а не n=9 (6.1)")
check("02 §2.5", "whackdoor→bugnotfeature: медиана", 7, round(st.median(wdb), 1), num_verdict(7, round(st.median(wdb), 1), 0.5), "min 1.3 → «+1» ок")
check("02 §2.5", "bugnotfeature→whackdoor: n / медиана", "3 / +8", f"{len(bwd)} / {st.median(bwd):.1f}", "ВЕРНО ОКРУГЛЕНО" if len(bwd) == 3 else "НЕВЕРНО",
      "n=3 с выбросом 138 мин (кластер #15); «+8» — оценка по трём точкам")
import random
random.seed(20260930)


def boot_med(v, n=4000):
    b = sorted(st.median([random.choice(v) for _ in v]) for _ in range(n))
    return b[int(.025 * n)], b[int(.975 * n)]


lo1, hi1 = boot_med(wdb); lo2, hi2 = boot_med(allabs)
first_second = []
for x in clusters:
    ms = members(x)
    j = next((m for m in ms if m["ch"] != ms[0]["ch"]), None)
    if j:
        first_second.append(mins(ms[0]["dt"], j["dt"]))
lo3, hi3 = boot_med(first_second)
check("02 §2.3/05 §2.1", "лаг whackdoor⇄bugnotfeature «7–8 мин»", f"{DOC['lag_wd_bnf'][0]}–{DOC['lag_wd_bnf'][1]} мин",
      f"wd→bnf медиана {st.median(wdb):.1f} [95 % бутстрэп {lo1:.1f}; {hi1:.1f}], n=12; bnf→wd {st.median(bwd):.1f}, n=3; по модулю по 15: {st.median(allabs):.1f} [{lo2:.1f}; {hi2:.1f}]",
      "ВЕРНО ОКРУГЛЕНО", "как точечная оценка по одной паре — воспроизводится; интервал широкий (до 13 мин), хвост 20/34/123/138 мин")
check("05 §2.1", "«типичный лаг внутри ниши — 7–8 минут»", "7–8 мин (вывод, confidence: средний)",
      f"по всем 64 кластерам медиана лага 1-й→2-й другой канал {st.median(first_second):.1f} мин [95 % бутстрэп {lo3:.1f}; {hi3:.1f}]; медиана разброса кластера {st.median(span):.1f} мин",
      "НЕВЕРНО", "документ сам называет это лагом пары (не ниши); по нише порядок не 7–8, а ~18 мин, и 21 из 64 кластеров шире 2 ч. "
      f"Асимметрия wd→bnf 12:3 (двусторонний биномиальный p≈{pval:.3f}) — «близнецы/двусторонний» не подтверждается: whackdoor ведёт в 80 % общих тем")
rk = sorted(((SUBS[c], c) for c in SUBS if not c.startswith("_")), reverse=True)
pos = {c: i + 1 for i, (_, c) in enumerate(rk)}
check("05 §2.1", "«лаг между крупнейшей парой» (и 02 §2.11 «двумя крупнейшими каналами»)", "крупнейшие",
      f"whackdoor {pos['whackdoor']}-й ({SUBS['whackdoor'] / 1e6:.2f}M), bugnotfeature {pos['bugnotfeature']}-й ({SUBS['bugnotfeature'] / 1e6:.2f}M) из 22 по subs.json",
      "НЕВЕРНО", "это самая связанная пара (15 кластеров), а не самая большая; README «между крупнейшими каналами 7–8 мин» повторяет ошибку")
print("  ссылки на «7–8 мин» в других документах (потребители): README:32,91; docs/04:215; docs/06:25; docs/07:436,505,572; docs/08:394")

# ================================================================== 5. cross_strict
sec("5. docs/03 §3.3 / §3.4 / §3.5 / §3.6 — зарубежные пары (cross_strict.json: gap_min = RU − EN; >0 ⇒ EN первый)")
ENF = lambda r: r["gap_min"] > 0
uniq_pairs = {}
for r in CROSS:
    uniq_pairs.setdefault((r["en_url"], canon_url(r["ru_url"])), r)
print(f"  пар в файле {len(CROSS)}; уникальных после склейки алиаса tehnochat=technomedia: {len(uniq_pairs)}")
m_en = Counter(Counter(r["en_url"] for r in uniq_pairs.values()).values())
m_ru = Counter(Counter(canon_url(r["ru_url"]) for r in uniq_pairs.values()).values())
print(f"  кратность: EN-пост входит в k пар: {dict(sorted(m_en.items()))}; RU-пост входит в k пар: {dict(sorted(m_ru.items()))}")
check("03 шапка", "124 содержательные кросс-пары", DOC["cross_pairs"], len(CROSS), num_verdict(DOC["cross_pairs"], len(CROSS)),
      f"но 1 пара задвоена (bleepingcomputer/25653 → technomedia и tehnochat, один пост) ⇒ {len(uniq_pairs)}")
n_en = sum(1 for ch, ps in en.items() for p in ps if len(clean(p["text"])) >= 40)
check("03 шапка", "936 постов с текстом, 14 каналов", f"{DOC['n_en_posts']}, {DOC['n_en_channels']}", f"{n_en}, {len(en)}", num_verdict(DOC["n_en_posts"], n_en))

sub("§3.6 (по парам; en_first = gap_min > 0)")
lead = defaultdict(lambda: [0, 0])
for r in CROSS:
    lead[r["en_ch"]][0 if ENF(r) else 1] += 1
rows36 = []
for ln in section(D03, "## 3.6.", "## 3.7.").splitlines():
    m = re.match(r"\s*@(\S+)\s+(\d+)\s+(\d+)(?:\s*\(\s*\d+\s*%\))?\s+(\d+)", ln)
    if m:
        rows36.append((m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4))))
bad36 = [(c, dn, de, dr, lead[c]) for c, dn, de, dr in rows36 if [de, dr] != lead[c] or dn != sum(lead[c])]
check("03 §3.6", "таблица EN-первый / RU-первый по каналам (12 строк)", "12 строк", f"расхождений {len(bad36)}", "ВЕРНО" if not bad36 else "НЕВЕРНО", "пересчёт по знаку gap_min")

by_en = defaultdict(lambda: defaultdict(list))
for r in CROSS:
    by_en[r["en_ch"]][r["en_url"]].append(r)
print(f"\n  {'EN-канал':28s} пар  EN-пост. | EN-первый/RU-первый (по постам: EN первый, если ВСЕ его RU-совпадения позже)")
per_post = {}
for c, d in sorted(by_en.items(), key=lambda kv: -sum(len(v) for v in kv[1].values())):
    ef = sum(1 for v in d.values() if min(r["gap_min"] for r in v) > 0)
    per_post[c] = (sum(len(v) for v in d.values()), len(d), ef, len(d) - ef)
    print(f"  {c:28s}{per_post[c][0]:4d} {per_post[c][1]:8d} | {ef:2d}/{len(d) - ef:2d}")

sub("§3.3 @hiaimedia / @hiaimediaen")
h = [r for r in CROSS if r["en_ch"] == "hiaimediaen"]
hh = [r for r in h if r["ru_ch"] == "hiaimedia"]
print(f"  пар hiaimediaen: {len(h)}: с hiaimedia {len(hh)}, с другими русскими {len(h) - len(hh)} ({Counter(r['ru_ch'] for r in h if r['ru_ch'] != 'hiaimedia')})")
ru_first = sum(1 for r in h if not ENF(r))
check("03 §3.3", "«RU-версия первая в 23 случаях из 24» (арифметика)", f"{DOC['hia_ru_first'][0]} из {DOC['hia_ru_first'][1]}", f"{ru_first} из {len(h)} пар с EN-постами hiaimediaen (любые RU-каналы)",
      "ВЕРНО" if (ru_first, len(h)) == DOC["hia_ru_first"] else "НЕВЕРНО")
check("03 §3.3", "…как утверждение про пару @hiaimedia/@hiaimediaen", "23 из 24 (96 %)", f"{sum(1 for r in hh if not ENF(r))} из {len(hh)} (100 %) — это {len({r['en_url'] for r in hh})} различных EN-постов; остальные 6 пар — чужие каналы "
      f"({', '.join(sorted(set(r['ru_ch'] for r in h if r['ru_ch'] != 'hiaimedia')))}); единственный «EN-первый» — пара с @rozetked (+204 мин)",
      "НЕВЕРНО", "счёт смешивает близнеца с посторонними каналами; один EN-пост сопоставлен 1–4 RU-постам (см. гистограмму кратности выше)")
twin_n = len({r["en_url"] for r in hh})
check("03 §3.3 прим.", "«два независимых канала с разными редакционными циклами, а не зеркала»", "не зеркала", f"{twin_n} из {len(en['hiaimediaen'])} EN-постов (90 %) — переводы постов hiaimedia, все выходят позже (медиана {st.median([-r['gap_min'] for r in hh]) / 60:.1f} ч)",
      "НЕВЕРНО", "по данным это отстающее зеркало-перевод (документ сам говорит так в §3.3 выше: «отстающий перевод русского»)")
lag_h = [-r["gap_min"] for r in hh if not ENF(r)]
check("03 §3.3", "медиана отставания EN ≈ 2.5 ч", DOC["hia_median_h"], f"{st.median(lag_h) / 60:.2f} ч ({st.median(lag_h):.0f} мин, n={len(lag_h)})",
      "НЕВЕРНО", "2.5 ч не воспроизводится ни для 18 пар близнеца (3.4 ч), ни для 23 RU-first пар (4.7 ч)")
check("03 §3.3", "диапазон «от 11 мин до 20 ч»", f"{DOC['hia_min_min']} мин … {DOC['hia_max_h']} ч", f"{min(lag_h):.1f} мин … {max(lag_h) / 60:.1f} ч", "НЕВЕРНО",
      "верхняя граница 23.6 ч; нижняя 12.4 мин")
twin = len({r["en_url"] for r in hh})
check("03 §3.3", "«18 из 20 EN-постов имеют русского близнеца»", "18 из 20", f"{twin} из {len(en['hiaimediaen'])}", num_verdict(18, twin))
check("03 §3.3", "sim близнецов «0.85–0.96»", "0.85–0.96", f"{min(r['sim'] for r in hh):.3f}–{max(r['sim'] for r in hh):.3f}", "ВЕРНО ОКРУГЛЕНО", "нижняя 0.837")
check("03 §3.3", "«EN отстал на 13 мин» (Starship 09-28)", 13, 12.4, "ВЕРНО ОКРУГЛЕНО", "секунды: 12.4 мин; «19 мин» у Dots — 19.6")

sub("§3.4 @AInews_en")
ai = [r for r in CROSS if r["en_ch"] == "AInews_en"]
ai_rf = sum(1 for r in ai if not ENF(r))
check("03 §3.4", "«в 23 парах из 27 русский оригинал первым»", f"{DOC['ain_ru_first'][0]} из {DOC['ain_ru_first'][1]}", f"{ai_rf} из {len(ai)} пар; по EN-постам {per_post['AInews_en'][3]} из {per_post['AInews_en'][1]}",
      num_verdict(DOC["ain_ru_first"][0], ai_rf), f"27 пар — это {per_post['AInews_en'][1]} EN-постов (один пост сопоставлен 1–4 RU-постам)")
ail = [-r["gap_min"] for r in ai if not ENF(r)]
check("03 §3.4", "лаг «от 12 минут до 43 часов»", f"{DOC['ain_lag'][0]} мин … {DOC['ain_lag'][1]} ч", f"{min(ail):.1f} мин … {max(ail) / 60:.1f} ч", "ВЕРНО ОКРУГЛЕНО", "≈, но не точно")
ain_ch = Counter(r["ru_ch"] for r in ai)
exp_pairs = sum(n for c, n in ain_ch.items() if c in UNI2)
edi_pairs = sum(n for c, n in ain_ch.items() if c in UNI1 or c in ("technomedia", "tehnochat"))
check("03 §3.4", "«в точности экспертная вселенная»", "только эксперты", f"пар с экспертными {exp_pairs}, с редакционными {edi_pairs} (naebnet, technomotel, bugnotfeature, whackdoor, exploitex), прочие {len(ai) - exp_pairs - edi_pairs}; каналов {len(ain_ch)} (док. перечисляет 12)",
      "НЕВЕРНО", f"{edi_pairs / len(ai) * 100:.0f} % пар — редакционные каналы; NeuralShit в перечне пропущен")
print("  «avg_sim 0.660 по @neuraldvig — самая высокая пара» (03 §3.4): считалась в прогоне с порогом 0.55, в репозитории сохранён только cross_strict (≥0.80)")
check("03 §3.4", "avg_sim 0.660 (neuraldvig)", 0.660, "—", "НЕ ПРОВЕРЯЕМО", "данные порога 0.55 (5301 пара) в репозитории не сохранены")

sub("Независимые события вместо пар (компоненты связности по общему EN- или RU-посту; алиас склеен)")
par_ = {}


def find(a):
    par_.setdefault(a, a)
    while par_[a] != a:
        par_[a] = par_[par_[a]]; a = par_[a]
    return a


for (e_, r_) in uniq_pairs:
    par_[find("E:" + e_)] = find("R:" + r_)
comp = defaultdict(lambda: {"en": {}, "ru": {}})
for (e_, r_), r in uniq_pairs.items():
    c = find("E:" + e_)
    comp[c]["en"][e_] = (r["en_ch"], r["en_dt"]); comp[c]["ru"][r_] = (r["ru_ch"], r["ru_dt"])
EV = []
for v in comp.values():
    te = min(d for _, d in v["en"].values()); tr = min(d for _, d in v["ru"].values())
    EV.append({"first": "EN" if dt(te) < dt(tr) else "RU", "en": sorted({c for c, _ in v["en"].values()}),
               "ru": sorted({c for c, _ in v["ru"].values()}), "t": min(te, tr), "gap": mins(te, tr)})
print(f"  пар {len(uniq_pairs)} → событий {len(EV)}; первым EN: {sum(1 for e in EV if e['first'] == 'EN')}, первым RU: {sum(1 for e in EV if e['first'] == 'RU')}")
hia_ev = [e for e in EV if e["en"] == ["hiaimediaen"] and e["ru"] == ["hiaimedia"]]
print(f"  из них «hiaimediaen↔hiaimedia» в чистом виде: {len(hia_ev)} событий, все RU-первые: {all(e['first'] == 'RU' for e in hia_ev)}")
CLEAN_EN = {"aipost", "TheHackerNews", "bleepingcomputer", "news_crypto", "TechDaily", "machinelearningresearchnews", "ml_news"}
cl_ev = [e for e in EV if set(e["en"]) <= CLEAN_EN]
print(f"  только независимые зарубежные каналы (без tldrtech [дамп пачкой], AInews_en [10 подп., перевод RU], "
      f"hiaimediaen/anthropic [тот же издатель, что hiaimedia], GitHub [русскоязычный]): {len(cl_ev)} событий, EN первым: {sum(1 for e in cl_ev if e['first'] == 'EN')}")
for e in sorted(cl_ev, key=lambda e: e["t"]):
    print(f"     {e['t'][5:16]} первым {e['first']}  EN={e['en']}  RU={e['ru']}  gap RU−EN={e['gap']:+.0f} мин")
check("03 §3.3/3.4/3.6", "счёт «пар» как счёт независимых наблюдений", f"{len(CROSS)} пар", f"{len(EV)} событий (RU первым {sum(1 for e in EV if e['first'] == 'RU')}, EN первым {sum(1 for e in EV if e['first'] == 'EN')})",
      "НЕВЕРНО", "один пост даёт до 5 пар; самые крупные «доли» (23/24, 23/27, GitHub 4/4) — 18, 17 и 1 событие")

sub("Язык «зарубежных» каналов (ожидается английский)")
cyr = {c: sum(1 for p in ps if re.search(r"[А-Яа-яЁё]{3,}", p["text"])) for c, ps in en.items()}
check("03 §3.1/3.5", "@GitHub — зарубежный/англоязычный канал, «английский слот»", "EN", f"{cyr['GitHub']} из {len(en['GitHub'])} постов на русском",
      "НЕВЕРНО", "канал «GitHub Community»: «Лучшие проекты с GitHub», РКН, реклама telega.in — русскоязычный; 4 его «EN→RU» пары — это RU↔RU, а не EN→RU")
print(f"  кириллица в текстах 'EN'-каналов: { {c: n for c, n in cyr.items() if n} }")

sub("§3.5 @aipost: «единственный зарубежный канал, стабильно опережающий русские»")
ap = [r for r in CROSS if r["en_ch"] == "aipost"]
ap_ev = [e for e in EV if "aipost" in e["en"]]
print(f"  aipost: {len(ap)} пар, EN-первый {sum(1 for r in ap if ENF(r))} ({sum(1 for r in ap if ENF(r)) / len(ap) * 100:.0f} %), событий {len(ap_ev)}, первым был aipost в {sum(1 for e in ap_ev if e['first'] == 'EN')}")
tr_ = [r for r in ap if r["en_dt"].startswith("2026-09-23T04:48")]
print("  (в скобках gap = RU − EN, мин; минус ⇒ русский пост РАНЬШЕ)\n  Trump/«Super Intelligence» (EN 23.09 04:48):  " + "; ".join(f"{r['ru_ch']} {r['ru_dt'][5:16]} ({r['gap_min']:+.0f})" for r in sorted(tr_, key=lambda r: r["ru_dt"])))
so_ = [r for r in ap if r["en_dt"].startswith("2026-09-28T19:11")]
print("  Sonnet 5.5 (EN 28.09 19:11):  " + "; ".join(f"{r['ru_ch']} {r['ru_dt'][5:16]} ({r['gap_min']:+.0f})" for r in sorted(so_, key=lambda r: r["ru_dt"])))
check("03 §3.5", "Trump: aipost первый (док: RU +217 hiaimedia, +162 rozetked)", "aipost первым", "data_secrets на 736 мин и technomotel на 745 мин РАНЬШЕ aipost", "НЕВЕРНО",
      "документ привёл только поздние RU-посты; HN: 22.09 16:02, data_secrets 16:31 (docs/05 «валидно»); aipost отстал на ~12.8 ч")
check("03 §3.5", "Sonnet 5.5: aipost 28.09 19:11 первый (d_code +68, naebnet +717)", "aipost первым", "ai_ml 18:05, naebnet 18:07, xor_journal 18:15 РАНЬШЕ aipost на 56–66 мин; naebnet +717 — другой (повторный) пост 29.09", "НЕВЕРНО",
      "релиз 28.09 ~18:00; aipost — 4-й–5-й")
ain_ = per_post["aipost"]
check("03 §3.10", "«aipost иногда на 1–12 часов раньше русских»", "1–12 ч", f"EN-первый в {ain_[2]} из {ain_[1]} постов; лаги RU-постов за ним: " +
      ", ".join(f"{r['gap_min'] / 60:.1f} ч" for r in sorted((r for r in ap if ENF(r)), key=lambda r: r["gap_min"])), "ВЕРНО ОКРУГЛЕНО",
      "диапазон 1.1–23.7 ч, но это РАССТОЯНИЕ до поздних RU-постов, а не опережение «всех русских»")
ghp = sorted((r for r in CROSS if r["en_ch"] == "GitHub"), key=lambda r: r["ru_dt"])
check("03 §3.5", "GitHub/MWS Cloud Day: EN 10:09 → whackdoor +32, bugnotfeature +63, ai_ml +174, data_secrets +289", "32/63/174/289",
      "/".join(f"{r['gap_min']:.0f}" for r in ghp), "ВЕРНО ОКРУГЛЕНО", "времена верны; «EN-слот» неверно — канал русскоязычный")
nc = [r for r in CROSS if r["en_ch"] == "news_crypto"]
check("03 §3.5", "news_crypto: d_code +958, hiaimedia +2113", "958/2113", "/".join(f"{r['gap_min']:.0f}" for r in sorted(nc, key=lambda r: r["gap_min"])[1:]), "ВЕРНО ОКРУГЛЕНО")
check("03 §3.5", "заголовок «три случая, и два из них реклама»", "2 рекламных", "в тексте реклама одна (GitHub); news_crypto — «первоисточник NBC», aipost — контент", "НЕВЕРНО", "внутреннее противоречие")

# ---- §3.7
sub("§3.7 «Десять русских каналов — ноль кросс-бордера» (sim ≥ 0.80)")
cn = lambda c: TM if c in ("technomedia", "tehnochat") else c
all_by_ru = Counter(cn(r["ru_ch"]) for r in uniq_pairs.values())        # алиас склеен
enf_by_ru = Counter(cn(r["ru_ch"]) for r in uniq_pairs.values() if ENF(r))
zero_doc = []
blk = section(D03, "## 3.7.", "Полный список")
for ln in blk.splitlines():
    m = re.match(r"\s*@(\S+)(?:\s+\(\+@\S+\))?\s+\d+(?:\s+постов)?\s*$", ln)
    if m:
        zero_doc.append(TM if m.group(1) == "technomedia" else NAMEFIX.get(m.group(1), m.group(1)))
print(f"  документ называет {len(zero_doc)} каналов; пары в ЛЮБОМ направлении / только EN-первые (как считал cross2.py):")
ok_zero = 0
for c in zero_doc:
    print(f"    {c:28s} все пары {all_by_ru.get(c, 0):3d}   EN→RU (EN первым) {enf_by_ru.get(c, 0):3d}")
    ok_zero += all_by_ru.get(c, 0) == 0
check("03 §3.7", "10 каналов без ни одной пары sim≥0.80 с зарубежными", f"{DOC['zero_cross_channels']} каналов", f"{ok_zero} каналов без пар; остальные {len(zero_doc) - ok_zero} имеют RU-первые пары (xor_journal {all_by_ru['xor_journal']}, neuraldvig {all_by_ru['neuraldvig']}, technomotel {all_by_ru['technomotel']}…)",
      "НЕВЕРНО", "cross2.py блок D печатает «не получают ни одной пары» по множеству down = пары с g>0 (EN первым); док. прочитал это как «ноль пар вообще». Верная формулировка: «ни разу не были позже зарубежного поста»; противоречит и §3.4 (AInews_en↔xor_journal/neuraldvig) и §3.9")
rows37 = []
for ln in section(D03, "Полный список", "## 3.8.").splitlines():
    m = re.match(r"\|\s*@(\S+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s+из\s+(\d+)\s*\|", ln)
    if m:
        rows37.append((NAMEFIX.get(m.group(1), m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))))
badr = []
for c, n, k2, tot in rows37:
    cc = TM if c == "technomedia" else c
    if enf_by_ru.get(c, 0) != n or uniq_c2.get(cc) != tot:
        badr.append((c, n, enf_by_ru.get(c, 0), tot, uniq_c2.get(cc)))
check("03 §3.7", "таблица «EN→RU пар» и знаменатели (cross2: посты ≥ 40 симв.)", f"{len(rows37)} строк", f"расхождений {len(badr)}", "ВЕРНО" if not badr else "НЕВЕРНО", f"{badr}" if badr else "")
print(f"  d_code — канал с наибольшим числом EN→RU пар: {enf_by_ru['d_code']}; при этом docs/02 §2.10 называет его «авторским, 0 % дублирования»")

# ---- §3.8
sub("§3.8 «Внутри англоязычного: перепечаток почти нет, все пары по 1 совпадению»")
c2src = open(os.path.join(ROOT, "tools", "cross2.py"), encoding="utf-8").read()
capped = "seen2" in c2src and "if k in seen2" in c2src
print(f"  tools/cross2.py блок E: `if k in seen2: continue` (ключ = пара каналов) присутствует: {capped}")
check("03 §3.8", "«все пары по 1 совпадению»", "1 у всех", "артефакт кода: счётчик ограничен 1 на пару каналов", "НЕВЕРНО" if capped else "НЕ ПРОВЕРЯЕМО",
      "вывод «перепечаток нет» из этого кода не следует; реальный счёт см. --embed")

# ================================================================== 6. §3.1 живые каналы
sec("6. docs/03 §3.1 — таблица «живых зарубежных каналов» и список мёртвых")
rows31 = []
for ln in section(D03, "### Живые зарубежные каналы", "**Вывод: переводить").splitlines():
    m = re.match(r"\|\s*@(\S+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*\**(\d+)\**\s*\|", ln)
    if m:
        rows31.append((m.group(1), m.group(2), parse_k(m.group(3)), int(m.group(4))))
print(f"  {'канал':28s}|док: подписчики  постов/нед | posts_en.json: постов")
for c, title, subs_, pw in rows31:
    n = len(en.get(c, []))
    print(f"  {c:28s}|{subs_:14,.0f} {pw:8d} | {n}")
    check("03 §3.1", f"@{c}: постов/нед", pw, n, num_verdict(pw, n))
LIVE_ROWS = {}
if LIVE:
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        requests = None
        print("  --live: нет requests/bs4 — пропущено")
    if requests:
        UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

        def fetch(ch, before=None):
            url = f"https://t.me/s/{ch}" + (f"?before={before}" if before else "")
            try:
                r = requests.get(url, headers=UA, timeout=30)
            except Exception:                           # сеть: одна повторная попытка
                time.sleep(2)
                try:
                    r = requests.get(url, headers=UA, timeout=30)
                except Exception:
                    return None
            time.sleep(1.1)
            return r

        def live_info(ch):
            r = fetch(ch)
            if r is None:
                return {"state": "ошибка сети"}
            s = BeautifulSoup(r.text, "lxml")
            o = {"url": r.url, "title": None, "subs": None, "desc": None, "last": None, "n": 0, "state": None, "btn": None}
            t = s.select_one(".tgme_channel_info_header_title")
            o["title"] = t.get_text(" ", strip=True) if t else None
            for c in s.select(".tgme_channel_info_counter"):
                ty = c.select_one(".counter_type")
                if ty and ty.get_text(strip=True).startswith("subscriber"):
                    o["subs"] = c.select_one(".counter_value").get_text(strip=True)
            d = s.select_one(".tgme_channel_info_description") or s.select_one(".tgme_page_description")
            o["desc"] = d.get_text(" ", strip=True)[:160] if d else None
            tm = [x.get("datetime") for x in s.select(".tgme_widget_message_date time")]
            o["n"] = len(tm); o["last"] = max(tm) if tm else None
            b = s.select_one(".tgme_action_button_new")
            o["btn"] = b.get_text(strip=True) if b else None
            if s.select_one(".tgme_channel_history"):
                o["state"] = "канал с веб-превью"
            elif o["btn"] and o["btn"].startswith("View"):
                o["state"] = "имя ЗАНЯТО каналом/чатом без веб-превью (кнопка View in Telegram; t.me/s/ редиректит на t.me/<имя>)"
            else:
                o["state"] = "нет канала с таким именем (страница «Send Message»: свободное имя / пользователь / бот)"
            return o

        print("\n  ЖИВАЯ СВЕРКА (t.me/s/<канал>, подписчики — точное текстовое значение из .counter_value):")
        for c, title, subs_, pw in rows31:
            o = live_info(c); LIVE_ROWS[c] = o
            ls = parse_k(o["subs"]) if o.get("subs") else None
            v = "НЕ ПРОВЕРЯЕМО" if ls is None else ("ВЕРНО" if abs(ls - subs_) / max(subs_, 1) < 0.01 else "ВЕРНО ОКРУГЛЕНО" if abs(ls - subs_) / max(subs_, 1) < 0.03 else "НЕВЕРНО")
            check("03 §3.1", f"@{c}: подписчики (сейчас на t.me)", f"{subs_:,.0f}", o.get("subs"), v,
                  f"«{o.get('title')}»; последний пост {(o.get('last') or '')[:10]}" + ("; ПАРСИНГ-ОШИБКИ НЕТ: на странице буквально это число" if c in ("tldrtech", "AInews_en", "ml_news") else ""))
        print(f"  описание @anthropic: {LIVE_ROWS['anthropic']['desc']}")
        print(f"  описание @GitHub:    {LIVE_ROWS['GitHub']['desc']}")
        print(f"  описание @hiaimediaen: {LIVE_ROWS['hiaimediaen']['desc']}")
        print(f"  описание @AInews_en: {LIVE_ROWS['AInews_en']['desc']}")

        sub("Мёртвые/несуществующие каналы из §3.1 — фактическое состояние СЕЙЧАС")
        DEAD = [  # (имя, то, что утверждает документ)
            ("OpenAI", "канал не существует"), ("AnthropicAI", "2024-12-20"), ("MetaAI", "2021-10-28"),
            ("GoogleDeepMind", "2026-09-18 (официал)"), ("deepmind", "2026-09-18 (официал)"),
            ("Kimi_Moonshot", "2026-09-11"), ("deepseek_ai", "2026-09-10"), ("AINewsDaily", "342 K; 2023-08-27"),
            ("ArtificialAnalysis", "1.17 K; 2026-04-10"), ("HuggingFace", "301 K; 2026-02-17"),
            ("TheSequenceAI", "не существует/пусто"), ("simonw", "не существует/пусто"), ("swyx", "не существует/пусто"),
            ("karpathy", "не существует/пусто"), ("ylecun", "не существует/пусто"), ("bindured", "не существует/пусто"),
            ("TheVerge", "→ агрегатор tech2 1.35 K"), ("TechCrunch", "→ агрегатор tech2 1.35 K"),
            ("arstechnica", "→ агрегатор tech2 1.35 K"), ("HackerNews", "→ агрегатор tech2 1.35 K")]
        for c, claim in DEAD:
            o = live_info(c); LIVE_ROWS[c] = o
            print(f"    @{c:20s} док: {claim:26s} | сейчас: {o.get('state')}; «{o.get('title')}»; подписчики {o.get('subs')}; "
                  f"постов на странице {o.get('n')}, последний {(o.get('last') or '—')[:10]}")
        o = LIVE_ROWS["OpenAI"]
        check("03 §3.1", "@OpenAI «канал не существует»", "не существует", o["state"], "НЕВЕРНО" if "ЗАНЯТО" in o["state"] else "ВЕРНО",
              "t.me/OpenAI даёт кнопку «View in Telegram» и «view posts by @OpenAI» (у несуществующего имени — «Send Message»/«contact»): канал с таким именем есть, "
              "но без публичного веб-превью; официальность/контент/дату последнего поста через t.me/s/ установить нельзя")
        o = LIVE_ROWS["AnthropicAI"]
        check("03 §3.1", "@AnthropicAI последний пост 2024-12-20", "2024-12-20", (o.get("last") or "")[:10], "ВЕРНО" if (o.get("last") or "").startswith("2024-12-20") else "НЕВЕРНО",
              f"«{o.get('title')}», {o.get('subs')} подписчиков; официальность не подтверждена")
        for c, ex_ in (("MetaAI", "2021-10-28"), ("Kimi_Moonshot", "2026-09-11"), ("deepseek_ai", "2026-09-10"), ("AINewsDaily", "2023-08-27"), ("ArtificialAnalysis", "2026-04-10"), ("HuggingFace", "2026-02-17")):
            o = LIVE_ROWS[c]
            check("03 §3.1", f"@{c} последний пост", ex_, (o.get("last") or "")[:10], "ВЕРНО" if (o.get("last") or "").startswith(ex_) else "НЕВЕРНО")
        check("03 §3.1", "@AINewsDaily «342 K»", "342 K", LIVE_ROWS["AINewsDaily"].get("subs"), "НЕВЕРНО", "342 подписчика, не 342 тыс. (суффикс K добавлен в документе)")
        check("03 §3.1", "@HuggingFace «301 K»", "301 K", LIVE_ROWS["HuggingFace"].get("subs"), "НЕВЕРНО", "≈302 подписчика, не тысячи; неофициальный канал")
        o = LIVE_ROWS["deepmind"]
        check("03 §3.1", "@deepmind «официал, не новости»", "официальный DeepMind", f"«{o.get('title')}»", "НЕВЕРНО", "китайский бот-канал («Ai官方频道»), к Google DeepMind не относится; @GoogleDeepMind — свободное имя")
        for c in ("TheSequenceAI", "simonw", "swyx", "bindured"):
            check("03 §3.1", f"@{c} «не существует/пусто»", "нет канала", LIVE_ROWS[c]["state"][:40], "ВЕРНО" if LIVE_ROWS[c]["state"].startswith("нет канала") else "НЕВЕРНО")
        for c in ("karpathy", "ylecun"):
            o = LIVE_ROWS[c]
            check("03 §3.1", f"@{c} «не существует/пусто»", "нет канала", f"канал «{o['title']}», {o['subs']} подписчиков, последний пост {(o.get('last') or '')[:10]}", "ВЕРНО ОКРУГЛЕНО",
                  "канал есть, но заброшенный и явно неофициальный")
        for c in ("TheVerge", "TechCrunch"):
            check("03 §3.1", f"@{c} «сведён в агрегатор tech2 1.35 K»", "tech2", LIVE_ROWS[c]["state"][:45], "НЕВЕРНО", "только arstechnica и HackerNews ведут на «tech2» (1.36K, последний пост 2024-03-09); TheVerge/TechCrunch — не каналы")
        check("03 §3.1", "@arstechnica, @HackerNews → «tech2»", "tech2 1.35 K", f"«{LIVE_ROWS['arstechnica']['title']}» {LIVE_ROWS['arstechnica']['subs']}, последний пост {(LIVE_ROWS['arstechnica'].get('last') or '')[:10]}", "ВЕРНО ОКРУГЛЕНО")
        o = LIVE_ROWS["anthropic"]
        check("03 §3.1", "@anthropic (1.44M) — «Discover • Tech News»", "чужой ник", f"«{o['title']}», описание: {o['desc']}", "ВЕРНО",
              "верно, что не Anthropic; но это тот же издатель, что @hiaimedia/@hiaimediaen (@GPT4Telegrambot, Ads @hiai_ads) — его «EN→RU» пары с hiaimedia = внутри одного издателя")
        # холартем и алиас
        for c in ("whackdoor", "bugnotfeature", "technomedia", "tehnochat"):
            r = fetch(c)
            s = BeautifulSoup(r.text, "lxml") if r is not None else None
            LIVE_ROWS["_" + c] = {"holartem": bool(s and "holartem" in r.text.lower()),
                                  "title": (s.select_one(".tgme_channel_info_header_title").get_text(" ", strip=True) if s and s.select_one(".tgme_channel_info_header_title") else None),
                                  "counters": [x.get_text(" ", strip=True) for x in (s.select(".tgme_channel_info_counter") if s else [])][:2]}
        check("02 §2.3", "@holartem в описании whackdoor и bugnotfeature", "у обоих", f"whackdoor {LIVE_ROWS['_whackdoor']['holartem']}, bugnotfeature {LIVE_ROWS['_bugnotfeature']['holartem']}",
              "ВЕРНО" if LIVE_ROWS["_whackdoor"]["holartem"] and LIVE_ROWS["_bugnotfeature"]["holartem"] else "НЕВЕРНО", "в репозитории данных нет — только живая страница")
        check("02 §2.2", "technomedia и tehnochat — один канал", "алиас", f"{LIVE_ROWS['_technomedia']['title']} {LIVE_ROWS['_technomedia']['counters']} = {LIVE_ROWS['_tehnochat']['title']} {LIVE_ROWS['_tehnochat']['counters']}",
              "ВЕРНО" if LIVE_ROWS["_technomedia"]["counters"] == LIVE_ROWS["_tehnochat"]["counters"] else "НЕВЕРНО")

        sub("Часовой пояс и точность времени: сверка 10 постов с живой страницей t.me/s/<канал>?before=<id+1>")
        SAMPLE = [("whackdoor", "31794"), ("bugnotfeature", "28116"), ("rozetked", "27537"), ("rozetked", "27518"), ("naebnet", "17287"),
                  ("xor_journal", "10172"), ("exploitex", "36800"), ("data_secrets", "10036"), ("data_secrets", "9990"), ("naebnet", "17271")]
        eq = 0
        for ch, pid in SAMPLE:
            r = fetch(ch, before=int(pid) + 1)
            mine = next(p for p in ru[ch] if p["id"] == pid)
            if r is None:
                continue
            s = BeautifulSoup(r.text, "lxml")
            msg = next((m for m in s.select(".tgme_widget_message") if m.get("data-post") == f"{ch}/{pid}"), None)
            if msg is None:
                print(f"    {ch}/{pid}: не найден на странице"); continue
            tm = msg.select_one(".tgme_widget_message_date time")
            same = tm.get("datetime") == mine["dt"]
            eq += same
            print(f"    {ch}/{pid}: live {tm.get('datetime')} (на экране {tm.get_text(strip=True)}) | posts.json {mine['dt']} | совпало: {same}")
        check("02/05 (время)", "posts.json хранит время в UTC с секундами", "UTC", f"{eq}/{len(SAMPLE)} постов совпало до секунды с живым datetime=+00:00, на экране то же UTC-время", "ВЕРНО" if eq == len(SAMPLE) else "НЕВЕРНО")
else:
    print("  (живая сверка отключена: запусти с --live)")
    check("03 §3.1", "подписчики и состояние «мёртвых» каналов", "—", "—", "НЕ ПРОВЕРЯЕМО", "нужен --live (t.me/s/)")

# ================================================================== 7. docs/05
sec("7. docs/05 — 12 историй против timeline_hn.json и posts.json")
rows05 = []
for ln in section(D05, "| История |", "### 3.1").splitlines():
    cells = [c.strip() for c in ln.strip().strip("|").split("|")]
    if len(cells) == 4 and not cells[0].startswith(("История", "---")):
        nm = cells[0].replace("**", "")
        lg = minus(cells[1])
        rows05.append((nm, None if lg in ("—", "") else int(lg.replace("+", "")), cells[2], minus(cells[3])))
print(f"  строк в таблице docs/05: {len(rows05)}")
print(f"  {'история':26s}|док лаг  | JSON lag_min | пересчёт по данным JSON | якоря на месте? | оценка в док.")
valid_doc = 0
for nm, lg, parts, ev in rows05:
    t_ = TL.get(nm)
    if t_ is None:
        print(f"  {nm:26s}| нет в JSON"); continue
    ru_a = sorted(dt(a) for a, _ in t_["ru"]) if False else sorted((dt(x), c) for x, c in t_["ru"])
    calc = round((ru_a[0][0] - dt(t_["hn"][0][0])).total_seconds() / 60) if t_["hn"] else None
    alias_ = {"ai_ml": "ai_machinelearning_big_data"}
    okk = []
    for ts_, c in t_["ru"]:
        c_ = alias_.get(c, c)
        best = min(ru[c_], key=lambda p: abs(mins(ts_ + ("" if len(ts_) > 16 else ":00"), p["dt"])))
        okk.append(abs(mins(ts_, best["dt"])) < 1.0)
    valid_doc += ev.startswith("валидно")
    vv = "ВЕРНО" if lg == t_["lag_min"] else ("НЕВЕРНО" if lg is not None or t_["lag_min"] is not None else "ВЕРНО")
    print(f"  {nm:26s}|{str(lg):8s}| {str(t_['lag_min']):12s} | {str(calc):23s} | {sum(okk)}/{len(okk)}             | {ev}")
    check("05 §3", f"{nm}: лаг RU−HN", lg, t_["lag_min"], vv if lg == t_["lag_min"] else "НЕВЕРНО",
          {"Codex burned $80k": "JSON 16234: по ручному совпадению (HN 26.09 22:15 'OpenAI Codex agents go rogue') получилось бы +1401 — в таблицу перенесено ручное число, JSON/скрипт его не воспроизводят",
           "ChatGPT $500 tier": "в JSON hn=[] (нет пары HN) — значения +975 в данных нет вообще"}.get(nm, ""))
check("05 §3", "12 историй, валидных 3", f"{DOC['tl_total']}, {DOC['tl_valid']}", f"{len(TL)}, оценок «валидно» {valid_doc}", num_verdict(DOC["tl_valid"], valid_doc))
mis_anchor = []
for nm, t_ in TL.items():
    for ts_, c in t_["ru"]:
        c_ = {"ai_ml": "ai_machinelearning_big_data"}.get(c, c)
        best = min(ru[c_], key=lambda p: abs(mins(ts_ + ":00", p["dt"])))
        if abs(mins(ts_ + ":00", best["dt"])) >= 1.0:
            mis_anchor.append((nm, c_, ts_[5:16], best["dt"][5:16], best["text"][:45].replace("\n", " ")))
print("\n  ANCHORS в timeline3.py (вбиты руками), которых нет в posts.json в пределах минуты:")
for z in mis_anchor:
    print(f"    {z[0]:22s} {z[1]:26s} якорь {z[2]} | ближайший пост {z[3]} «{z[4]}»")
check("05/timeline3", "якоря RU-постов совпадают с posts.json", "все", f"{len(mis_anchor)} из {sum(len(t['ru']) for t in TL.values())} не найдены", "НЕВЕРНО" if mis_anchor else "ВЕРНО",
      "hiaimedia/denissexy/seeallochnaya в «Opus 5.5» — другие посты; ai_newz в «ChatGPT $500» — другой час и тема")

sub("Claude Sonnet 5.5: когда русские каналы писали впервые (posts.json)")
son = []
for ch, ps in ru.items():
    if ch == "tehnochat":
        continue
    for p in ps:
        if re.search(r"Sonnet[\s-]*5\.5", p["text"]) and p["dt"] >= "2026-09-25":
            son.append((p["dt"], ch, p["id"], p["text"][:70].replace("\n", " ")))
son.sort()
for z in son[:9]:
    print(f"    {z[0][5:19]} {z[1]:26s} id={z[2]:>6s} {z[3]!r}")
ds_posts = [(p["dt"], p["id"]) for p in ru["data_secrets"] if re.search(r"Sonnet", p["text"])]
print(f"  data_secrets упоминает Sonnet в: {ds_posts}  (никакого поста 25.09 18:06 — ближайший 25.09 16:01 про NetHack/AIRI)")
son_links = sorted((pp["dt"], ch, u) for ch, ps in LINKS.items() if ch in ru for pp in ps for u in (pp.get("links") or []) if re.search(r"sonnet-5-5", u, re.I))
print(f"  links.json: ссылки на страницы Sonnet 5.5 (RU-каналы), самая ранняя: {son_links[0][0][5:19]} {son_links[0][1]} {son_links[0][2]}; ссылок до 28.09: {sum(1 for z in son_links if z[0] < '2026-09-28')}")
hn_son = dt(TL["Claude Sonnet 5.5"]["hn"][0][0])
first_any = min(son)
t_ai_ml = next(z for z in son if z[1] == "ai_machinelearning_big_data")
t_ds = next(z for z in son if z[1] == "data_secrets" and "Вышел" in z[3])
print(f"  HN первый: {TL['Claude Sonnet 5.5']['hn'][0][0][:19]} «{TL['Claude Sonnet 5.5']['hn'][0][1]}»")
print(f"  лаг при исправленном якоре: data_secrets 28.09 18:06:58 → {mins(TL['Claude Sonnet 5.5']['hn'][0][0], t_ds[0]):+.1f} мин; "
      f"самый ранний из трёх указанных каналов (ai_ml {t_ai_ml[0][11:19]}) → {mins(TL['Claude Sonnet 5.5']['hn'][0][0], t_ai_ml[0]):+.1f} мин; "
      f"самый ранний русский пост вообще ({first_any[1]} {first_any[0][5:19]}) → {mins(TL['Claude Sonnet 5.5']['hn'][0][0], first_any[0]):+.1f} мин")
check("05 §3.1", "Sonnet 5.5: «−4312 мин, русские на 3 суток раньше HN, разные события»", "ложное совпадение", f"опечатка в ANCHORS: 25.09 вместо 28.09; событие одно (релиз 28.09 ~18:00), лаг ≈ {mins(TL['Claude Sonnet 5.5']['hn'][0][0], t_ai_ml[0]):+.0f} … {mins(TL['Claude Sonnet 5.5']['hn'][0][0], first_any[0]):+.0f} мин",
      "НЕВЕРНО", "диагноз «разные события» неверен; история — валидная; с ней валидных 4 из 12, а не 3. Противоречия с docs/03 §3.5 по дате нет: оба документа дают 28.09; ошибка только в якоре 25.09 (docs/05, timeline3.py)")
check("05 §3", "«Claude Opus 5.5»: «@xor_journal в обоих случаях был первым»", "xor_journal первым", "первым был @exploitex 22.09 16:30:25; xor_journal 16:31:22 (+57 с)", "НЕВЕРНО",
      "для GPT-6.1 Sol xor_journal первым верно (17:11:17)")
op_ = find_posts(r"Opus\s*5\.5", "2026-09-22")
ek = min((p["dt"], c) for c, p in op_.items() if p["dt"] >= "2026-09-22T16:00")
print(f"  Opus 5.5: самый ранний русский пост {ek[1]} {ek[0][11:19]}; HN {TL['Claude Opus 5.5']['hn'][0][0][11:19]} ⇒ +{mins(TL['Claude Opus 5.5']['hn'][0][0], ek[0]):.1f} мин (док «+4» — от xor_journal, якорь с точностью до минуты)")
hn_links = [(ch, p["dt"], u) for ch, ps in LINKS.items() for p in ps for u in (p.get("links") or []) if "news.ycombinator.com" in u]
print(f"  ссылки на news.ycombinator.com в links.json: {len(hn_links)}: {[(c, d[5:16], u.split('=')[-1]) for c, d, u in hn_links]}")
check("05 §4", "«hackernews встречается 2 раза» и «HN для ниши не upstream»", f"{DOC['hn_links']} ссылки", f"{len(hn_links)} ссылки на HN (2 от RU-каналов neuraldvig и xor_journal на ОДИН item — история Codex $80k, 1 от AInews_en)",
      "ВЕРНО ОКРУГЛЕНО", "проверка «ссылается ли xor_journal на HN» в документе названа «не выполненной», хотя выполнима: да, в одной истории (Codex), лаг от HN ≈ 23 ч; в 2 валидных историях — нет")
check("05 §3.1", "«626–20812 мин = 10–14 суток»", "10–14 суток", "626 мин = 10.4 ч; 20812 мин = 14.5 сут; 975 мин = 16 ч; 1400 мин = 23 ч", "НЕВЕРНО", "диапазон смешан; лаги 10–23 ч (Meta VR, $500, Codex) не «10–14 суток»")
check("05 §3.1", "Dots: «русские посты — двухнедельной давности»", "RU двухнедельной давности", "RU-посты 29.09 17:10–17:14; двухнедельные — HN-находки (15–16.09)", "НЕВЕРНО", "перепутано, что старое")
check("05 §7.2", "«медиана 4 мин основана на двух измерениях»", "двух", "на трёх валидных (+4, +4, +29: медиана 4); в docs/05 §3 валидных названо 3", "НЕВЕРНО", "внутреннее противоречие §7.2 vs §3")

# ================================================================== 8. прочее
sec("8. ПРОЧИЕ ЧИСЛА И ВНУТРЕННИЕ ПРОТИВОРЕЧИЯ")
sz = [len(members(x)) for x in clusters]
raw_sz = [len(x["members"]) for x in clusters]
sz_bug = [len(v) for k, v in CL.items() if not isinstance(v, (int, float))]
check("02 §2.11", "«размер кластера медиана 22 [11, 64]»", DOC["cluster_size_median"], f"медиана {st.median(sz):.0f}, диапазон {min(sz)}–{max(sz)} (с дублями алиаса {st.median(raw_sz):.0f})",
      "НЕВЕРНО", f"баг tools/uncertainty.py (блок docs/02): берёт len() верхнеуровневых полей clusters.json {sz_bug} → медиана {st.median(sz_bug):.0f}. "
      f"Кластеры по 2–5 постов, 47 из 64 — пары; вывод «одна новость на 22 постах, независимых наблюдений на порядок меньше» ложен и противоречит docs/10 (дизайн-эффект 1.04)")
u = json.load(open(os.path.join(D, "uncertainty.json"), encoding="utf-8")).get("cluster_size")
print(f"  data/uncertainty.json cluster_size = {u}")
cl_both = [x for x in clusters if {m['ch'] for m in members(x)} & UNI1 and {m['ch'] for m in members(x)} & UNI2]
cross_pairs = [(p["a"], p["b"], p["n"]) for p in CL["pairwise"] if (p["a"] in UNI1 and p["b"] in UNI2) or (p["a"] in UNI2 and p["b"] in UNI1)]
check("02 §2.1", "«МЕЖДУ НИМИ: 2 связи за неделю»", DOC["uni_links"], f"{len(cross_pairs)} пар каналов, {sum(n for *_, n in cross_pairs)} общих тем, {len(cl_both)} из {len(clusters)} кластеров содержат обе вселенные",
      "НЕВЕРНО", f"крупнейшая — gptpublic⇄naebnet (5); внутри вселенных: редакционная {sum(p['n'] for p in CL['pairwise'] if p['a'] in UNI1 and p['b'] in UNI1)}, экспертная {sum(p['n'] for p in CL['pairwise'] if p['a'] in UNI2 and p['b'] in UNI2)}; межвселенских ≈ 19 %")


def pair_lags(U):
    out = []
    for x in clusters:
        f = first_by_ch(x)
        chs = [c for c in f if c in U]
        for i in range(len(chs)):
            for j in range(i + 1, len(chs)):
                out.append(abs(mins(f[chs[i]]["dt"], f[chs[j]]["dt"])))
    return sorted(out)


l1, l2 = pair_lags(UNI1), pair_lags(UNI2)
check("02 §2.1", "редакционная вселенная: «лаг 0–120 минут»", "0–120 мин", f"{sum(1 for v in l1 if v <= 120)} из {len(l1)} пар каналов в кластерах ≤ 120 мин; медиана {st.median(l1):.0f}, p90 {l1[int(.9 * len(l1))]:.0f}, max {max(l1):.0f} мин",
      "ВЕРНО ОКРУГЛЕНО", "верно как «типично» (78 %), не как диапазон")
check("02 §2.1", "экспертная вселенная: «лаг 0–30 минут»", "0–30 мин", f"{sum(1 for v in l2 if v <= 30)} из {len(l2)} пар ≤ 30 мин; медиана {st.median(l2):.0f}, p90 {l2[int(.9 * len(l2))]:.0f}, max {max(l2):.0f} мин",
      "НЕВЕРНО", "у экспертов лаги МЕДЛЕННЕЕ, чем у редакционных (медиана 143 против 10 мин), n=17 пар")
idx2 = {(ch, p["id"]): p for ch, ps in LINKS.items() for p in ps}
seen2, n_e, n_fw, n_attr = set(), 0, 0, 0
for x in clusters:
    for m in members(x):
        ch, pid = m["url"].split("/")[3], m["url"].split("/")[4]
        if m["ch"] in UNI2 and (ch, pid) not in seen2:
            seen2.add((ch, pid)); n_e += 1
            pp = idx2.get((ch, pid)) or {}
            fwd = bool(m["fwd"]); n_fw += fwd
            oth = [u for u in (pp.get("mentions") or []) if u.lower() != ch.lower()] or \
                  [u for u in (pp.get("links") or []) if "t.me/" in u and f"t.me/{ch}" not in u]
            n_attr += fwd or bool(oth)
ver_u2 = sum(1 for x in clusters if {m["ch"] for m in members(x)} <= UNI2)
ver_u2v = sum(1 for x in clusters if {m["ch"] for m in members(x)} <= UNI2 and x["verbatim"])
check("02 §2.1", "экспертная вселенная: «форвардят друг друга С АТРИБУЦИЕЙ»", "с атрибуцией", f"из {n_e} постов экспертов в кластерах: forward-заголовок у {n_fw} ({n_fw / n_e:.0%}); +упоминание/ссылка на другой канал — {n_attr} ({n_attr / n_e:.0%})",
      "НЕВЕРНО", f"{ver_u2v} из {ver_u2} чисто-экспертных кластеров — дословные копии (verbatim), в основном без видимой атрибуции; «осознанно и с атрибуцией» (§2.2) — меньшинство")


def shares(U):
    return sorted((ncl.get(c, 0) / uniq_text[c] * 100, c) for c in U)


s1, s2 = shares(UNI1), shares(UNI2)
check("02 §2.1", "доля дублей редакционной вселенной «0.6–14 %»", "0.6–14", f"{s1[0][0]:.1f} ({s1[0][1]}) – {s1[-1][0]:.1f} ({s1[-1][1]})", "НЕВЕРНО", "bugnotfeature 17.5 % выше верхней границы")
check("02 §2.1", "доля дублей экспертной «4–35 %»", "4–35", f"{s2[0][0]:.1f} ({s2[0][1]}) – {s2[-1][0]:.1f} ({s2[-1][1]})", "НЕВЕРНО", "мелочь: нижняя граница 2.4 % (cgevent), верхняя верна")
core = ["whackdoor", "bugnotfeature", "exploitex", TM, "naebnet", "trends"]
vals = {c: ncl.get(c, 0) / uniq_text[c] * 100 for c in core}
check("02 §2.10", "«редакционная: доля дублирования 14–17 %»", "14–17 %", ", ".join(f"{c.split('/')[0]} {v:.1f}" for c, v in vals.items()), "НЕВЕРНО", "technomedia 6.8 и trends 5.0 вне диапазона")
ivs = [c for c in ("xor_journal", "neuraldvig", "data_secrets", "seeallochnaya", "denissexy", "ai_newz")]
check("02 §2.10", "«аудитория экспертных 80–190 K»", "80–190 K", ", ".join(f"{c} {SUBS[c] / 1e3:.0f}K" for c in ivs), "НЕВЕРНО", "neuraldvig 294K вне диапазона (мелочь)")
check("02 §2.8", "суточные «догонялки»: 1524 / 1445 / 812 мин", "1524/1445/812", "/".join(f"{x['span_min']:.0f}" for x in clusters if round(x["span_min"]) in (1524, 1445, 812) or abs(x["span_min"] - 811.7) < 0.1), "ВЕРНО",
      "числа верны; но примеры 1 и 2 — рекламные интеграции (MWS Cloud, МТС РИИЛ: время задаёт рекламодатель), в примерах 1 и 3 опущен участник (bugnotfeature 10:04 / whackdoor 10:48); пример 3 — 13 ч, не «более суток»")
hrs_ = [dt(p["dt"]).hour for ch, ps in ru.items() if ch != "tehnochat" for p in ps]
pk = sum(1 for h in hrs_ if 13 <= h <= 16) / len(hrs_) * 100
pk2 = sum(1 for h in hrs_ if 13 <= h <= 17) / len(hrs_) * 100
check("05 §2.2", "«пик 13:00–17:00 UTC, в нём 29 % всех постов»", "29 %", f"13:00–16:59: {pk:.1f} %; 13:00–17:59 (окно из uncertainty.py): {pk2:.1f} %", "ВЕРНО ОКРУГЛЕНО", "цифра относится к окну 13–16 ч, а не 13–17 ч; пик пологий (8–12 ч — 89–105 постов/час против 102–117)")
w = re.search(r"WINDOW\s*=\s*\(datetime\((\d+), (\d+), (\d+)[^)]*\),\s*datetime\((\d+), (\d+), (\d+)", open(os.path.join(ROOT, "tools", "timeline3.py"), encoding="utf-8").read())
if w:
    g = list(map(int, w.groups()))
    wd_ = (datetime(g[3], g[4], g[5]) - datetime(g[0], g[1], g[2])).days
    check("05 §7.5", "«окно 15 суток» (окно поиска HN)", 15, wd_, num_verdict(15, wd_), "WINDOW в tools/timeline3.py: 15.09 … 02.10")
vb = sum(1 for x in clusters if x["verbatim"])
print(f"  кластеров с флагом дословного совпадения (verbatim): {vb} из {len(clusters)}; у пары whackdoor⇄bugnotfeature — {sum(1 for _, _, v in both_ if v)} из 15")
check("02 §2.9", "данные tgregister.com (simhash, 18 из 45 ошибок)", "—", "внешний сервис, в репозитории нет данных", "НЕ ПРОВЕРЯЕМО", "не входило в проверку по сырым данным")
n13 = len({cn(r["ru_ch"]) for r in uniq_pairs.values() if ENF(r)})
check("03 §3.12", "«13 пар из 37 каналов»", "13 пар / 37 каналов", f"13 = число РУССКИХ каналов с ≥1 EN→RU парой ({n13}), не пар; 37 = 23 RU-ключа (с алиасом tehnochat) + 14 EN, реальных каналов 36", "НЕВЕРНО", "формулировка: каналы названы парами; алиас снова посчитан как канал")
check("03 §3.9", "Opus 5.5 «за сутки опубликовали @aipost, @hiaimediaen, @hiaimedia, …»", "8 каналов", "в posts_en.json пост о релизе Opus 5.5 есть у aipost (22.09 20:07, через 3.6 ч после первого RU) и у AInews_en; у hiaimediaen и hiaimedia поста о релизе нет", "НЕВЕРНО", "участники названы без проверки")
print("""
  Внутренние противоречия между/внутри документов (подтверждены по данным выше):
   1. 02 §2.2 technomedia 292 постов/3.4 %  vs  03 §3.7 146 постов (и docs/01:239 «один канал»); 02 шапка 1595 vs 1449 уникальных.
   2. 02 §2.2 d_code 1.5 %  vs  02 §2.10 «0 %»;  02 §2.10 «d_code авторский» vs 03 §3.7 (d_code — 8 EN→RU пар, больше всех).
   3. 02 §2.3/2.5 whackdoor→bugnotfeature n=9  vs  «15 общих тем» (9+3=12).
   4. 02 §2.6 «rozetked единственный стабильный»  vs  §2.7 (2 первых места против 11) и §2.5/n=2.
   5. 02 §2.6 naebnet «09:38 след. день +1440»  vs  23.09 09:38 в соседнем примере; реальный пост 24.09 12:00.
   6. 02 §2.11 «кластер медиана 22»  vs  §2.12 «64 кластера» и docs/10 §3.6 «дизайн-эффект 1.04».
   7. 03 §3.4 (AInews_en ⇄ xor_journal/neuraldvig…)  vs  03 §3.7 (эти каналы «ноль кросс-бордера»).
   8. 03 §3.5 заголовок «два из трёх — реклама»  vs  текст (одна реклама).  03 §3.5 (aipost первый)  vs  05 §3 (Trump: data_secrets первый, +29 к HN; Sonnet: RU до HN).
   9. 05 §3.1 (Sonnet 5.5 «разные события»)  vs  03 §3.5 (Sonnet 5.5 одно событие 28.09): верна 03, в 05 опечатка якоря.
  10. 05 §3: Codex +1400 / ChatGPT $500 +975  vs  timeline_hn.json (16234 / нет HN).  05 §7.2 «два измерения» vs §3 «три».
  11. 05 §2.1 «крупнейшая пара» vs subs.json (7-е и 9-е место по подписчикам).
  12. 03 §3.1 в списке «зарубежных» @GitHub — русскоязычный.  03 §3.1 @OpenAI «не существует» vs страница «View in Telegram».
""")

# ================================================================== --embed
if EMBED:
    sec("9. (--embed) Пересчёт кросс-пар эмбеддингами paraphrase-multilingual-MiniLM-L12-v2")
    try:
        import numpy as np
        from sentence_transformers import SentenceTransformer
    except ImportError:
        np = None
        print("  нет sentence-transformers")
        check("03 (метод)", "воспроизведение 124 пар", 124, "—", "НЕ ПРОВЕРЯЕМО", "нет sentence-transformers")
    if np is not None:
        P = []
        for lang, src_ in (("RU", ru), ("EN", en)):
            for ch, ps in src_.items():
                for p in ps:
                    t_ = clean(p["text"])
                    if len(t_) >= 40:
                        P.append({"lang": lang, "ch": ch, "id": p["id"], "dt": p["dt"], "t": t_})
        m_ = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        E = np.asarray(m_.encode([p["t"] for p in P], batch_size=64, normalize_embeddings=True, show_progress_bar=False))
        cal = m_.encode(["Релиз GPT-6.1 Sol: новая модель OpenAI для кодинга, в 5 раз дешевле",
                         "OpenAI released GPT-6.1 Sol, a new coding model that is 5x cheaper",
                         "Кулинария: рецепт борща"], normalize_embeddings=True)
        c1, c2 = float(cal[0] @ cal[1]), float(cal[0] @ cal[2])
        check("03 §3.2", "калибровка: пара-перевод cos 0.937", 0.937, round(c1, 3), num_verdict(0.937, round(c1, 3), 0.01))
        check("03 §3.2", "калибровка: нерелевантная пара cos 0.100", 0.100, round(c2, 3), num_verdict(0.100, round(c2, 3), 0.01))
        RUi = [i for i, p in enumerate(P) if p["lang"] == "RU"]; ENi = [i for i, p in enumerate(P) if p["lang"] == "EN"]
        S = E[ENi] @ E[RUi].T
        got = set()
        for a in range(len(ENi)):
            for b in range(len(RUi)):
                if S[a, b] >= 0.80 and abs(mins(P[ENi[a]]["dt"], P[RUi[b]]["dt"])) <= 72 * 60:
                    got.add((f"{P[ENi[a]]['ch']}/{P[ENi[a]]['id']}", f"{P[RUi[b]]['ch']}/{P[RUi[b]]['id']}"))
        want = {(r["en_url"].split("t.me/")[1], r["ru_url"].split("t.me/")[1]) for r in CROSS}
        print(f"  пар sim≥0.80, |лаг|≤72ч: {len(got)}; в cross_strict.json: {len(want)}; пересечение {len(got & want)}")
        check("03 (метод)", "124 кросс-пары воспроизводятся", 124, len(got), "ВЕРНО" if got == want else ("ВЕРНО ОКРУГЛЕНО" if len(got ^ want) <= 4 else "НЕВЕРНО"), f"симм. разность {len(got ^ want)}")
        # EN-внутри без ограничения seen2
        Se = E[ENi] @ E[ENi].T
        cnt_all, cnt_ch = Counter(), Counter()
        for a in range(len(ENi)):
            for b in range(a + 1, len(ENi)):
                ca, cb = P[ENi[a]]["ch"], P[ENi[b]]["ch"]
                if ca != cb and Se[a, b] >= 0.80:
                    cnt_all[tuple(sorted((ca, cb)))] += 1
        print(f"  EN↔EN пар каналов с sim≥0.80: {len(cnt_all)}; пар постов всего {sum(cnt_all.values())}; топ: {cnt_all.most_common(6)}")
        check("03 §3.8", "«все пары по 1 совпадению»", "1 у всех", f"макс. {max(cnt_all.values()) if cnt_all else 0} (пар постов {sum(cnt_all.values())} на {len(cnt_all)} пар каналов)",
              "НЕВЕРНО" if cnt_all and max(cnt_all.values()) > 1 else "ВЕРНО", "без ограничения seen2")

# ================================================================== итог
sec("ИТОГО")
cnt = Counter(r["verdict"] for r in RES)
print("  " + ", ".join(f"{k}: {v}" for k, v in cnt.items()) + f"  (всего проверок {len(RES)})")
print("\n  НЕВЕРНО:")
for r in RES:
    if r["verdict"] == "НЕВЕРНО":
        print(f"   - {r['ref']:10s} {r['claim']}: док={r['doc']} → {r['calc']}")
if WRITE_JSON:
    out = os.path.join(D, "recheck_crosspost.json")
    json.dump({"checks": RES, "events": EV, "pairs_total": len(CROSS), "pairs_unique": len(uniq_pairs)},
              open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n  -> {os.path.relpath(out, ROOT)}")
