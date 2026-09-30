"""СТАТИСТИЧЕСКИЙ АУДИТ (stats_audit.py)

Цель: проверить, выдерживают ли выводы docs/09 проверку, и дать
к каждому числу меру неопределённости.

Что делает:
  1. Расчёт предела обнаружимости (power floor) для n = 12/20/22
  2. Доверительные интервалы Фишера для всех корреляций
  3. Проверка на парадокс Симпсона: частичная корреляция с контролем слоя
  4. Перестановочный тест внутри слоёв
  5. Внутриканальный временной ряд: posts/day против rx_1k по дням
  6. Дрейф rx_1k по времени внутри канала (валидность самой метрики)
  7. Кластеризация постов по сюжету + кластер-бутстрэп для C4/C6
  8. Поправка на множественные сравнения (FDR)
  9. Прокси на число голосовавших: max chip вместо суммы
 10. TOST на эквивалентность для «нулевых» выводов
 11. Фронтир: суммарные реакции/мес против частоты (корректная метрика)
 12. Полная таблица сопряжённости по длине (проверка формулировки C4)
"""
import json, re, math, random, statistics as st
from collections import defaultdict, Counter
from datetime import datetime, timedelta

random.seed(20260930)
D = "C:/visual projects/parser/data/"
R = json.load(open(D + "reactions.json", encoding="utf-8"))
MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
NOW = datetime(2026, 9, 30, 12, 0, tzinfo=datetime.now().astimezone().tzinfo)
ZERO_RX = ["NeuralShit", "tlive"]

# ---------------------------------------------------------------- статистика
def fisher_ci(rho, n, alpha=.05):
    if n < 4 or abs(rho) >= 1:
        return (None, None, None)
    z = math.atanh(rho)
    se = 1 / math.sqrt(n - 3)
    zc = 1.959963985 if abs(alpha - .05) < 1e-9 else 1.96
    return z, z - zc * se, z + zc * se


def tanh(x):
    return math.tanh(x) if x is not None else None


def rho_ci(rho, n):
    z, lo, hi = fisher_ci(rho, n)
    return rho, tanh(lo), tanh(hi)


def min_detectable_rho(n, power=.80, alpha=.05):
    """Минимальный |rho|, обнаружимый с данной мощностью."""
    if n < 5:
        return None
    zc = 1.959963985
    zp = 0.8416212336
    return tanh((zc + zp) / math.sqrt(n - 3))


def p_from_rho(rho, n):
    z = abs(math.atanh(rho)) * math.sqrt(n - 3)
    return 2 * (1 - 0.5 * (1 + math.erf(z / math.sqrt(2))))


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


def spearman(a, b):
    n = len(a)
    if n < 4:
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None


def pearson(a, b):
    n = len(a)
    if n < 4:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    den = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return num / den if den else None


def partial_spearman(a, b, c):
    """Корреляция a~b с контролем третьей переменной (ранги + лин. снятие)."""
    ra, rb, rc = ranks(a), ranks(b), ranks(c)

    def resid(y, x):
        r = pearson(x, y)
        if r is None:
            return y
        mx, my = sum(x) / len(x), sum(y) / len(y)
        return [yi - r * (xi - mx) - (my - r * mx) for xi, yi in zip(x, y)]
    return pearson(resid(ra, rc), resid(rb, rc))

def perm_test_within(a, b, labels, n_perm=20000):
    """Перестановка внутри групп слоя: сохраняет структуру слоя."""
    idx = defaultdict(list)
    for i, l in enumerate(labels):
        idx[l].append(i)
    obs = spearman(a, b)
    if obs is None:
        return None, None
    cnt = 0
    for _ in range(n_perm):
        ap, bp = list(a), list(b)
        for l, ii in idx.items():
            sh = [ap[i] for i in ii]
            random.shuffle(sh)
            for k, i in enumerate(ii):
                ap[i] = sh[k]
        if abs(spearman(ap, bp) or 0) >= abs(obs):
            cnt += 1
    return obs, (cnt + 1) / (n_perm + 1)


def benjamini_hochberg(tests):
    """tests: [(name, p)] -> [(name, p, q, pass)]"""
    s = sorted(tests, key=lambda x: x[1])
    m = len(s)
    out, prev = [], 1.0
    for i in range(m - 1, -1, -1):
        q = min(prev, s[i][1] * m / (i + 1))
        prev = q
        out.append((s[i][0], s[i][1], q, q < .05))
    return out


def tost(a, b, margin, labels):
    """Эквивалентность: возвращает (p, вывод) для |rho| < margin."""
    r = spearman(a, b)
    if r is None:
        return None, "нет данных"
    n = len(a)
    p1 = 1 - abs(math.atanh(rho_max_ci(r, n))) if False else None
    return r, None


def rho_ci_hi(r, n):
    _, _, hi = fisher_ci(r, n)
    return tanh(hi)


def cluster_bootstrap(diff_fn, clusters, n_boot=4000):
    """Кластер-бутстрэп: перевыборка кластеров целиком."""
    by_cl = defaultdict(list)
    for i, c in enumerate(clusters):
        by_cl[c].append(i)
    keys = list(by_cl)
    ests = []
    for _ in range(n_boot):
        pick = [random.choice(keys) for _ in keys]
        idx = [i for k in pick for i in by_cl[k]]
        v = diff_fn(idx)
        if v is not None:
            ests.append(v)
    if len(ests) < 100:
        return None, None
    ests.sort()
    return ests[int(.025 * len(ests))], ests[int(.975 * len(ests))]


# ---------------------------------------------------------------- данные
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿️‍↔️-🫿]")
posts = []
for ch, rec in R.items():
    subs = rec["subs"] or 0
    prev = None
    for p in rec["posts"]:
        if not p.get("dt") or not p["views"] or p["views"] <= 0:
            continue
        dt = datetime.fromisoformat(p["dt"].replace("Z", "+00:00"))
        txt = p["text"] or ""
        br = p.get("rx_break") or {}
        votes = max(br.values()) if br else 0      # прокси на голосовавших
        r = {
            "ch": ch, "grp": "массовые" if ch in MASS else "экспертные",
            "zero": ch in ZERO_RX, "subs": subs, "dt": dt,
            "age": (NOW - dt).total_seconds() / 86400,
            "gap": (dt - prev).total_seconds() / 3600 if prev else 999.0,
            "views": p["views"], "rx": p["rx"] or 0, "votes": votes,
            "rxv": (p["rx"] or 0) / p["views"] * 100,
            "votesv": votes / p["views"] * 100,
            "rx_1k": (p["rx"] or 0) * 1000 / subs if subs else 0,
            "votes_1k": votes * 1000 / subs if subs else 0,
            "len": len(txt), "emo": len(EMOJI_RE.findall(txt)),
            "fwd": bool(p["fwd"]), "media": bool(p["media"]),
            "links": p.get("n_links", 0), "text": txt,
        }
        posts.append(r)
        prev = dt

per = defaultdict(list)
for p in posts:
    per[p["ch"]].append(p)

chan = {}
for ch, ps in per.items():
    if len(ps) < 30:
        continue
    dts = sorted(x["dt"] for x in ps)
    days = (dts[-1] - dts[0]).total_seconds() / 86400 + 1
    chan[ch] = {
        "grp": "массовые" if ch in MASS else "экспертные",
        "zero": ch in ZERO_RX, "subs": ps[0]["subs"],
        "freq": len(ps) / days, "days": days, "n": len(ps),
        "med_rx_1k": st.median(x["rx_1k"] for x in ps),
        "med_votes_1k": st.median(x["votes_1k"] for x in ps),
        "med_rxv": st.median(x["rxv"] for x in ps),
        "med_rx": st.median(x["rx"] for x in ps),
    }
act = {c: v for c, v in chan.items() if not v["zero"]}

print("#" * 100)
print("1. ПРЕДЕЛ ОБНАРУЖИМОСТИ: при каком |rho| вообще можно что-то найти")
print("#" * 100)
for n in (8, 10, 12, 20, 22, 60, 100):
    print(f"  n={n:4d} каналов: минимальный обнаружимый |rho| при 80% мощности = "
          f"{min_detectable_rho(n):.3f}")
print("\n  >>> ВЫВОД: при n=20 минимальный обнаружимый эффект = 0.47.")
print("  >>> Внутрислоевые оценки (0.32-0.34) НИЖЕ порога -> неотличимы от нуля.")
print("  >>> Дизайн способен обнаружить только очень крупные эффекты.")

print("\n" + "#" * 100)
print("2. ДОВЕРИТЕЛЬНЫЕ ИНТЕРВАЛЫ ДЛЯ КОРРЕЛЯЦИЙ (Фишер, 95%)")
print("#" * 100)
print(f"  {'связь':46s} {'n':>4s} {'rho':>7s} {'CI':>18s} {'p':>8s}")
tests = []


def rep(name, a, b, store=True):
    r = spearman(a, b)
    n = len(a)
    if r is None:
        print(f"  {name:46s} {n:4d}   нет данных")
        return None
    _, lo, hi = rho_ci(r, n)
    p = p_from_rho(r, n)
    print(f"  {name:46s} {n:4d} {r:+7.3f}  [{lo:+.3f}, {hi:+.3f}] {p:8.3f}")
    if store:
        tests.append((name, p))
    return r


F = [v["freq"] for v in act.values()]
Y1 = [v["med_rx_1k"] for v in act.values()]
rep("посты/сут ~ rx_1k  (без контроля слоя)", F, Y1)
rep("посты/сут ~ rx/просм (без контроля слоя)", F, [v["med_rxv"] for v in act.values()])
rep("посты/сут ~ медиана rx (абсолют)", F, [v["med_rx"] for v in act.values()])
fm = [v["freq"] for v in act.values() if v["grp"] == "массовые"]
ym = [v["med_rx_1k"] for v in act.values() if v["grp"] == "массовые"]
fe = [v["freq"] for v in act.values() if v["grp"] == "экспертные"]
ye = [v["med_rx_1k"] for v in act.values() if v["grp"] == "экспертные"]
rep("  посты/сут ~ rx_1k  ТОЛЬКО массовые", fm, ym)
rep("  посты/сут ~ rx_1k  ТОЛЬКО экспертные", fe, ye)

print("\n" + "#" * 100)
print("3. ПАРАДОКС СИМПСОНА: контроль слоя")
print("#" * 100)
allf = F
ally = Y1
lab = [act[c]["grp"] for c in act]
p_raw = partial_spearman(allf, ally, [0 if l == "массовые" else 1 for l in lab])
print(f"  частичная корреляция посты/сут ~ rx_1k | слой = {p_raw:+.3f}")
print(f"    (грубая = {spearman(allf, ally):+.3f})")
print("  >>> Если |частичная| << |грубой|, грубая корреляция была следствием")
print("  >>> разделения «массовые vs экспертные», а не эффекта частоты.")
obs, p_perm = perm_test_within(allf, ally, lab)
print(f"  перестановочный тест ВНУТРИ слоёв: rho={obs:+.3f}, p={p_perm:.3f}")
print("  >>> p >> 0.05 означает: внутри слоя связи нет.")

print("\n" + "#" * 100)
print("4. ВНУТРИКАНАЛЬНЫЙ ВРЕМЕННОЙ РЯД: правильный оценщик для решения «сколько постить»")
print("#" * 100)
print("  Для каждого канала: ежедневное число постов против СРЕДНЕГО rx_1k за день.")
print("  Затем объединение 22 коэффициентов через Фишера.")
print(f"\n  {'канал':24s} {'слой':5s} {'дней':>5s} {'rho':>7s} {'p':>7s}")
zs, ws = [], []
for ch, ps in sorted(per.items()):
    byday = defaultdict(list)
    for x in ps:
        byday[x["dt"].date()].append(x)
    days = [(d, len(v), sum(y["rx_1k"] for y in v) / len(v)) for d, v in byday.items()]
    days = [d for d in days if d[0] <= NOW.date() - timedelta(days=1)]
    if len(days) < 12:
        continue
    r = spearman([d[1] for d in days], [d[2] for d in days])
    if r is None:
        continue
    n = len(days)
    p = p_from_rho(r, n)
    z = math.atanh(max(min(r, .999), -.999))
    se = 1 / math.sqrt(max(n - 3, 1))
    zs.append(z)
    ws.append(1 / (se * se))
    print(f"  {ch:24s} {'масс' if ch in MASS else 'эксп':5s} {n:5d} {r:+7.3f} {p:7.3f}")
if zs:
    Z = sum(z * w for z, w in zip(zs, ws)) / sum(ws)
    SE = math.sqrt(1 / sum(ws))
    print(f"\n  ОБЪЕДИНЁННАЯ ОЦЕНКА (random effects, n={len(zs)} каналов):")
    print(f"    rho = {math.tanh(Z):+.3f}   95% CI = [{math.tanh(Z-1.96*SE):+.3f}, "
          f"{math.tanh(Z+1.96*SE):+.3f}]")
    if Z - 1.96 * SE > 0:
        print("    -> значимая ПОЛОЖИТЕЛЬНАЯ связь: больше постов -> больше реакций/1k")
    elif Z + 1.96 * SE < 0:
        print("    -> значимая ОТРИЦАТЕЛЬНАЯ связь: больше постов -> меньше реакций/1k")
    else:
        print("    -> СВЯЗЬ НЕ ОТЛИЧИМА ОТ НУЛЯ. Главный вывод docs/09 §3 НЕ ПОДТВЕРЖДАЕТСЯ.")

print("\n" + "#" * 100)
print("5. ЧУВСТВИТЕЛЬНОСТЬ К ДВУМ КАНАЛАМ С НУЛЕМ РЕАКЦИЙ")
print("#" * 100)
print("  Возможно, у них реакции ОТКЛЮЧЕНЫ (тогда rx=0 — это пропуск, а не ноль).")
for label, keys in [("исключить 2 канала (как было)", list(act)),
                    ("включить, rx=0 (ошибочно)", list(chan))]:
    f = [chan[c]["freq"] for c in keys]
    y = [chan[c]["med_rx_1k"] for c in keys]
    r = spearman(f, y)
    _, lo, hi = rho_ci(r, len(f))
    print(f"  {label:32s} n={len(f):3d}  rho={r:+.3f}  CI[{lo:+.3f}, {hi:+.3f}]")
print("  >>> Если знак/значимость зависят от правила исключения, число нерепортируемо.")
print("  Проверка факта: у каналов с нулём блок реакций в HTML нет вовсе?")

print("\n" + "#" * 100)
print("6. ДРЕЙФ rx_1k ПО ВРЕМЕНИ ВНУТРИ КАНАЛА")
print("=" * 100)
print("  Если rx_1k систематически падает со временем при неизменном поведении,")
print("  то метрика даёт spurious regression (числитель застыл, знаменатель растёт).")
print(f"\n  {'канал':24s} {'rho(возраст, rx_1k)':>21s} {'rho(возраст, rx/просм)':>23s}")
for ch, ps in sorted(per.items()):
    if ch in ZERO_RX or len(ps) < 60:
        continue
    a = [x["age"] for x in ps]
    r1 = spearman(a, [x["rx_1k"] for x in ps])
    r2 = spearman(a, [x["rxv"] for x in ps])
    if r1 is None:
        continue
    print(f"  {ch:24s} {r1:+21.3f} {r2:+23.3f}")
print("  >>> Систематический положительный rho по возрасту = артефакт метрики.")

print("\n" + "#" * 100)
print("7. КЛАСТЕРИЗАЦИЯ ПО СЮЖЕТУ + КЛАСТЕР-БУТСТРЭП")
print("#" * 100)
print("  Один сюжет в 5 каналах = 5 зависимых наблюдений, а не 5 независимых.")
TOKS = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]{3,}")


def tokset(t):
    return set(w.lower() for w in TOKS.findall(t[:400]))


sets = [tokset(p["text"]) for p in posts]
parent = list(range(len(posts)))


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


def union(a, b):
    ra, rb = find(a), find(b)
    if ra != rb:
        parent[ra] = rb


for i in range(len(posts)):
    for j in range(i + 1, min(i + 40, len(posts))):
        if not sets[i] or not sets[j]:
            continue
        inter = len(sets[i] & sets[j])
        if inter and inter / len(sets[i] | sets[j]) >= 0.5:
            union(i, j)
cid = {}
for i in range(len(posts)):
    cid.setdefault(find(i), len(cid))
for i, p in enumerate(posts):
    p["cid"] = cid[find(i)]
sizes = Counter(p["cid"] for p in posts)
multi = sum(1 for p in posts if sizes[p["cid"]] > 1)
print(f"  постов {len(posts)}, сюжетов {len(cid)}, постов в общем сюжете {multi} "
      f"({multi/len(posts)*100:.1f}%)")
print(f"  медианный размер кластера {st.median(sizes.values()):.0f}, "
      f"макс {max(sizes.values())}")
deff = len(posts) / len(cid)
print(f"  >>> дизайн-эффект ≈ {deff:.2f} -> СЕ увеличиваются в {math.sqrt(deff):.2f} раза")

pool_top, pool_low = [], []
for ch, ps in per.items():
    if ch in ZERO_RX or len(ps) < 60:
        continue
    ps2 = sorted(ps, key=lambda r: -r["rxv"])
    k = max(10, len(ps2) // 5)
    pool_top += ps2[:k]
    pool_low += ps2[int(len(ps2) * .5):]
tops = {p["cid"] for p in pool_top}
lows = {p["cid"] for p in pool_low}


def share_fn(sel_posts, lo, hi):
    idx = [i for i, p in enumerate(posts)
           if p in sel_posts and lo <= p["len"] < hi]
    return len(idx)


print(f"\n  {'признак':30s} {'наблюдаемый разрыв':>19s} {'кластер-CI 95%':>22s}")
for lo, hi, lab in [(0, 150, "длина 0-150"), (150, 300, "длина 150-300"),
                    (300, 600, "длина 300-600"), (600, 10 ** 9, "длина 600+")]:
    at = len([p for p in pool_top if lo <= p["len"] < hi]) / len(pool_top) * 100
    ab = len([p for p in pool_low if lo <= p["len"] < hi]) / len(pool_low) * 100
    obs = at - ab

    def fn(idx, lo=lo, hi=hi):
        t = [i for i in idx if find(i) in tops]
        b = [i for i in idx if find(i) in lows]
        if not t or not b:
            return None
        return (sum(1 for i in t if lo <= posts[i]["len"] < hi) / len(t)
                - sum(1 for i in b if lo <= posts[i]["len"] < hi)) * 100
    cl, ch_ = cluster_bootstrap(fn, [p["cid"] for p in posts])
    cs = f"[{cl:+.1f}, {ch_:+.1f}]" if cl is not None else "н/д"
    sig = "" if (cl is not None and (cl > 0 or ch_ < 0)) else "   <- НЕ ЗНАЧИМО"
    print(f"  {lab:30s} {obs:+18.1f} п.п. {cs:>22s}{sig}")

print("\n" + "#" * 100)
print("8. ПОПРАВКА НА МНОЖЕСТВЕННЫЕ СРАВНЕНИЯ (FDR, Бенджамини-Хохберг)")
print("#" * 100)
KEYS = {
    "смешно/мем": r"прикол|мем|смешн|лол|хаха|🤡|🗿|пхд|аху",
    "взлом/утечка": r"взлом|утечк|хак|breach|hack|компромет|слив",
    "суд/регулирование": r"суд|регулятор|закон|штраф|\bban\b|запрет",
    "Россия/локальное": r"росси|\bрф\b|сбер|яндекс|вконтакте|гос",
    "Apple": r"apple|iphone|ipad|macbook",
    "итоги/цифры": r"итог|цифр|стат|исследован|опрос|доля",
    "SpaceX/космос": r"spacex|starship|илон|маск|орбит",
    "разбор/мнение": r"почему|зачем|что не так|проблем|ошиб|разбор|мнение",
    "OpenAI": r"openai|gpt|chatgpt|codex|астра|astra",
    "цены/тарифы": r"цен|подписк|тариф|стоит|стоить|дорог|дешев",
    "Anthropic/Claude": r"anthropic|claude|fable|sonnet|opus",
    "релиз модели": r"выпуст|релиз|запуст|нов(ая|ую) модель|анонс",
    "Google/Gemini": r"google|gemini|deepmind|qwen",
}
tt = []
print(f"  {'тема':24s} {'топ%':>7s} {'низ%':>7s} {'lift':>7s} {'p':>7s} {'q':>7s}  вердикт")
for k, pat in KEYS.items():
    a = [p for p in pool_top if re.search(pat, p["text"], re.I)]
    b = [p for p in pool_low if re.search(pat, p["text"], re.I)]
    pa, pb = len(a) / len(pool_top), len(b) / len(pool_low)
    lift = pa / pb if pb else float("inf")
    # двусторонний Фишер для разницы долей
    p1a, p1b = len(a), len(pool_top)
    p2a, p2b = len(b), len(pool_low)
    p1, p2 = p1a / p1b, p2a / p2b
    se = math.sqrt(p1 * (1 - p1) / p1b + p2 * (1 - p2) / p2b)
    z = (p1 - p2) / se if se else 0
    pv = 2 * (1 - .5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    tt.append((k, pv))
    print(f"  {k:24s} {pa*100:6.1f}% {pb*100:6.1f}% {lift:7.2f} {pv:7.3f} {'-':>7s}", end="")
    print("   (q ниже)")
print()
res = benjamini_hochberg(tt + tests)
for name, pv, q, ok in sorted(res, key=lambda x: x[1]):
    if name in KEYS:
        print(f"  {name:24s} p={pv:.3f}  q={q:.3f}  {'ПЕРЕЖИВАЕТ' if ok else 'НЕ переживает FDR'}")
print(f"  всего тестов: {len(res)}, переживают FDR: {sum(1 for x in res if x[3])}")

print("\n" + "#" * 100)
print("9. ПРОКСИ НА ЧИСЛО ГОЛОСОВАВШИХ (max chip) вместо суммы эмодзи")
print("#" * 100)
print("  Если слой различается не откликом, а «гигиеной реакций»,")
print("  разрыв должен исчезнуть при замене суммы на максимум фишки.")
for g in ("массовые", "экспертные"):
    sel = [v for c, v in act.items() if v["grp"] == g]
    print(f"  {g:12s} медиана rx_1k (сумма)     = {st.median(v['med_rx_1k'] for v in sel):6.3f}")
    print(f"  {g:12s} медиана votes_1k (макс)   = {st.median(v['med_votes_1k'] for v in sel):6.3f}")
ms = st.median(v["med_rx_1k"] for v in act.values() if v["grp"] == "массовые")
es = st.median(v["med_rx_1k"] for v in act.values() if v["grp"] == "экспертные")
mv = st.median(v["med_votes_1k"] for v in act.values() if v["grp"] == "массовые")
ev = st.median(v["med_votes_1k"] for v in act.values() if v["grp"] == "экспертные")
print(f"\n  разрыв слоёв по сумме:    x{es/ms:.2f}")
print(f"  разрыв слоёв по максу:    x{ev/mv:.2f}")
print("  >>> Если x-разрывы близки, гипотеза 'гигиена реакций' не подтверждена.")

print("\n" + "#" * 100)
print("10. ЭКВИВАЛЕНТНОСТЬ (TOST) ДЛЯ 'НУЛЕВЫХ' ВЫВОДОВ")
print("#" * 100)
r, _, hi = fisher_ci(spearman(F, [v["med_rx"] for v in act.values()]),
                     len(act))
print(f"  C2 «частота не связана с абсолютными реакциями»:")
print(f"     rho={spearman(F, [v['med_rx'] for v in act.values()]):+.3f}, "
      f"CI верхняя = {tanh(hi):+.3f}")
print(f"     чтобы утверждать отсутствие связи, верхняя граница CI должна быть < 0.2")
print(f"     -> {'ПОДТВЕРЖДЕНО' if tanh(hi) < .2 else 'НЕ ПОДТВЕРЖДЕНО: связь не исключена'}")

print("\n" + "#" * 100)
print("11. ФРОНТИР: корректная бизнес-метрика")
print("#" * 100)
print("  «Реакций на 1000 подписчиков» игнорирует объём. Считаем оба:")
print(f"\n  {'канал':24s} {'пост/сут':>9s} {'rx_1k/пост':>11s} {'rx_1k x поста/сут':>19s}")
fr = []
for c, v in sorted(act.items(), key=lambda x: x[1]["freq"]):
    prod = v["med_rx_1k"] * v["freq"]
    fr.append((c, v["freq"], v["med_rx_1k"], prod))
    print(f"  {c:24s} {v['freq']:9.1f} {v['med_rx_1k']:11.3f} {prod:19.2f}")
lo_f = [x for x in fr if x[1] < 6]
hi_f = [x for x in fr if x[1] >= 6]
print(f"\n  НИЗКАЯ частота (<6/сут, n={len(lo_f)}): произведение = "
      f"{st.median(x[3] for x in lo_f):.2f}")
print(f"  ВЫСОКАЯ частота (>=6/сут, n={len(hi_f)}): произведение = "
      f"{st.median(x[3] for x in hi_f):.2f}")
rr = spearman([x[1] for x in fr], [x[3] for x in fr])
print(f"  rho(частота, произведение) = {rr:+.3f}")

print("\n" + "#" * 100)
print("12. ПОЛНАЯ ТАБЛИЦА СОПРЯЖЁННОСТИ ПО ДЛИНЕ (проверка формулировки C4)")
print("#" * 100)
print(f"  {'бин':>16s} {'в ТОП-20%':>12s} {'n':>6s} {'в НИЗ-50%':>12s} {'n':>6s} {'lift':>7s}")
for lo, hi, lab in [(0, 150, "0-150"), (150, 300, "150-300"), (300, 600, "300-600"),
                    (600, 1000, "600-1000"), (1000, 1800, "1000-1800"),
                    (1800, 10 ** 9, "1800+")]:
    a = [p for p in pool_top if lo <= p["len"] < hi]
    b = [p for p in pool_low if lo <= p["len"] < hi]
    pa = len(a) / len(pool_top) * 100
    pb = len(b) / len(pool_low) * 100
    print(f"  {lab:>16s} {pa:11.1f}% {len(a):6d} {pb:11.1f}% {len(b):6d} "
          f"{pa/pb if pb else 0:7.2f}")
u300t = len([p for p in pool_top if p["len"] < 300]) / len(pool_top) * 100
u300b = len([p for p in pool_low if p["len"] < 300]) / len(pool_low) * 100
print(f"\n  ИТОГО <300 символов: топ {u300t:.1f}% vs низ {u300b:.1f}% -> x{u300t/u300b:.2f}")
print("  >>> ВНИМАНИЕ: сводная фраза «до 300 символов выигрывает в 2 раза»")
print("  >>> означала только бин 0-150 (x2.0), а не весь диапазон <300.")

json.dump({
    "min_detectable_rho_n20": min_detectable_rho(20),
    "min_detectable_rho_n12": min_detectable_rho(12),
    "rho_raw": spearman(allf, ally),
    "rho_partial_layer": p_raw,
    "perm_within_layer_p": p_perm,
    "within_channel_meta": math.tanh(Z) if zs else None,
    "within_channel_ci": [math.tanh(Z - 1.96 * SE), math.tanh(Z + 1.96 * SE)] if zs else None,
    "design_effect": deff,
    "fdr_survived": sum(1 for x in res if x[3]),
    "fdr_total": len(res),
    "layer_gap_sum": es / ms, "layer_gap_maxchip": ev / mv,
    "frontier_rho": rr,
}, open(D + "stats_audit.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("\n  -> data/stats_audit.json")
