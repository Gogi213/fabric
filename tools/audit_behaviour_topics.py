"""Аудит тематических выводов docs/09 §6 и README («релиз модели x0.54 q<0.001»,
«Google/Gemini x0.43», «локальное РФ x1.45», «регулирование x1.42», FDR 8 из 18).

1) воспроизведение (пулы топ-20 %/низ-50 %, z-тест, BH на 18 тестов);
2) CMH по каналам и бутстрэп по каналам для lift;
3) FE-регрессия (процентиль rx/views внутри канала) с контролем длины/медиа/возраста;
4) строгие классификаторы (после ручной проверки точности; см. --sample);
5) пересечения тем; чувствительность FDR к размеру семейства.
Запуск: python tools/audit_behaviour_topics.py [--sample KEY]
"""
import math, random, re, sys, statistics as st
import numpy as np
from scipy import stats
from audit_behaviour_common import load, by_channel, top_low_pools, cmh, bh

rows = load()
per = by_channel(rows)
CH = sorted(per)
DOC = {  # ровно как в tools/stats_audit.py
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
MODEL = (r"модел|model|\bllm|gpt-?\s?\d|\bclaude|\bopus|\bsonnet|\bfable|\bgemini|\bgemma|llama|"
         r"\bqwen|deepseek|\bgrok|mistral|\bkimi|minimax|\bglm|\bвеса\b|нейронк|нейросет")
VERB = (r"выпуст|релиз|представил|анонсир|выкатил|выложил|вышл[аи]\b|вышел\b|запустил|"
        r"опубликовал|дропнул|показал")
STRICT = {
    "релиз модели (строго)": lambda t: bool(re.search(MODEL, t[:350], re.I) and re.search(VERB, t[:350], re.I)),
    "Google (строго)": lambda t: bool(re.search(r"google|gemini|deepmind|\bгугл|gemma", t[:350], re.I)),
    "Россия (строго)": lambda t: bool(re.search(
        r"\bросси|\bрф\b|\bсбер|яндекс|вконтакте|минцифр|госдум|госуслуг|роскомнадзор|\bркн\b|"
        r"\bмтс\b|т-банк|тинькофф|москв|росфин|\bфсб\b|мессенджер\w* max|госмессенджер", t, re.I)),
    "суд/регулир. (строго)": lambda t: bool(re.search(
        r"\bсуд(а|е|ом|ы|ов|у)?\b|судебн|\bсуди(тся|лись|лся|ть)|\bиск(а|ом|и)?\b|регулятор|"
        r"законопроект|\bзакон(а|ы|ом|у|ов)?\b|законодател|штраф|\bban\b|\bзапрет|блокиров|"
        r"роскомнадзор|\bркн\b|госдум|\bминцифр|\bантимонопол|\bFTC\b|\bEU AI Act|еврокомисс", t, re.I)),
}
for r in rows:
    for k, p in DOC.items():
        r["T:" + k] = 1.0 if re.search(p, r["text"], re.I) else 0.0
    for k, f in STRICT.items():
        r["T:" + k] = 1.0 if f(r["text"]) else 0.0
    r["short"] = 1.0 if r["len"] < 300 else 0.0
    r["lage"] = math.log(max(r["age"], .05))
    r["llen"] = math.log(r["len"] + 20)
for ch, ps in per.items():
    s = sorted(ps, key=lambda r: r["rxv"])
    for i, r in enumerate(s):
        r["pct"] = (i + .5) / len(s)
    s = sorted(ps, key=lambda r: r["rxv_raw"])
    for i, r in enumerate(s):
        r["pct_raw"] = (i + .5) / len(s)

if len(sys.argv) > 2 and sys.argv[1] == "--sample":
    key = sys.argv[2]
    m = [r for r in rows if r["T:" + key]]
    rng = random.Random(99)
    for i, r in enumerate(rng.sample(m, min(20, len(m)))):
        print(f"{i:02d} [{r['ch']}] {re.sub(chr(10), ' ', r['text'])[:220]}")
    sys.exit()


def z_two_prop(a, n1, b, n2):
    p1, p2 = a / n1, b / n2
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    z = (p1 - p2) / se if se else 0
    return 2 * stats.norm.sf(abs(z))


def fe_coef(rows_, y, xs):
    byc = {}
    for r in rows_:
        byc.setdefault(r["ch"], []).append(r)
    Y, X = [], []
    for c, ps in byc.items():
        my = st.mean(r[y] for r in ps)
        mx = [st.mean(r[x] for r in ps) for x in xs]
        for r in ps:
            Y.append(r[y] - my)
            X.append([r[x] - m for x, m in zip(xs, mx)])
    return np.linalg.lstsq(np.array(X), np.array(Y), rcond=None)[0]


def fe_boot(xs, y="pct", n=600, seed=4):
    rng = random.Random(seed)
    est = fe_coef(rows, y, xs)
    bs = []
    for _ in range(n):
        rr = []
        for j, c in enumerate(rng.choice(CH) for _ in CH):
            for r in per[c]:
                q = dict(r)
                q["ch"] = f"{c}#{j}"
                rr.append(q)
        bs.append(fe_coef(rr, y, xs)[0])
    lo, hi = np.percentile(bs, [2.5, 97.5])
    p = 2 * min(np.mean(np.array(bs) <= 0), np.mean(np.array(bs) >= 0))
    return est[0], lo, hi, max(p, 1 / n)


print("=== 1. Воспроизведение таблицы docs/09 §6 (raw rx, как в stats_audit) ===")
top, low = top_low_pools(per, key="rxv_raw")
res = []
for k in DOC:
    a = sum(r["T:" + k] for r in top)
    b = sum(r["T:" + k] for r in low)
    res.append((k, a / len(top) * 100, b / len(low) * 100, z_two_prop(a, len(top), b, len(low))))
DOC_CORR_P = [0.001, 0.357, 0.872, 0.294, 0.422]   # 5 корреляций из stats_audit (p как в выводе)
q18 = bh([x[3] for x in res] + DOC_CORR_P)
for (k, pa, pb, p), q in zip(res, q18):
    print(f"  {k:20s} топ {pa:5.1f}% низ {pb:5.1f}% lift {pa/pb:5.2f} p={p:.4f} q18={q:.4f}")
print(f"  переживают при m=18: {sum(1 for q in q18 if q < .05)}")
for m_extra in (40, 80):
    ps = [x[3] for x in res] + DOC_CORR_P + [1.0] * (m_extra - 18)
    qs = bh(ps)[:13]
    print(f"  если семейство {m_extra} тестов (прочие p=1, оптимистично): "
          + ", ".join(f"{k.split('/')[0]} q={q:.3f}" for (k, *_), q in zip(res, qs) if k in
                      ("релиз модели", "Google/Gemini", "Россия/локальное", "суд/регулирование", "OpenAI")))

print("\n=== 2. CMH по каналам (стратифицированный OR топ vs низ) и lift с бутстрэпом по каналам ===")
KEYS = ["релиз модели", "Google/Gemini", "Россия/локальное", "суд/регулирование",
        "смешно/мем", "взлом/утечка", "цены/тарифы", "OpenAI", "Anthropic/Claude"] + list(STRICT)
top, low = top_low_pools(per, key="rxv")
topset = {id(r) for r in top}
lowset = {id(r) for r in low}


def lift_of(chs, k):
    t = l = nt = nl = 0
    for c in chs:
        s = sorted(per[c], key=lambda r: -r["rxv"])
        kk = max(10, len(s) // 5)
        tt, ll = s[:kk], s[int(len(s) * .5):]
        t += sum(r["T:" + k] for r in tt); nt += len(tt)
        l += sum(r["T:" + k] for r in ll); nl += len(ll)
    return (t / nt) / (l / nl) if l else float("nan")


cmh_p = {}
for k in KEYS:
    tabs = []
    for c in CH:
        tt = [r for r in per[c] if id(r) in topset]
        ll = [r for r in per[c] if id(r) in lowset]
        a = sum(r["T:" + k] for r in tt); b = len(tt) - a
        cc = sum(r["T:" + k] for r in ll); d = len(ll) - cc
        tabs.append(((a, b), (cc, d)))
    orr, (lo, hi), p = cmh(tabs)
    cmh_p[k] = p
    rng = random.Random(8)
    bs = sorted(lift_of([rng.choice(CH) for _ in CH], k) for _ in range(1000))
    bs = [x for x in bs if x == x]
    n_k = sum(r["T:" + k] for r in rows)
    print(f"  {k:24s} n={n_k:4.0f} lift {lift_of(CH, k):.2f} CI-каналы [{bs[25]:.2f}, {bs[-26]:.2f}]  "
          f"OR_MH {orr:.2f} [{lo:.2f}, {hi:.2f}] p={p:.4f}")

print("\n=== 3. FE-регрессия: процентиль rx/views в канале ~ тема + log длины + медиа + log возраста ===")
print("    (коэффициент = сдвиг внутриканального процентиля; CI бутстрэп по каналам, 600)")
fe_p = {}
for k in KEYS:
    est, lo, hi, p = fe_boot(["T:" + k, "llen", "media", "lage"])
    fe_p[k] = p
    print(f"  {k:24s} {est:+.4f} [{lo:+.4f}, {hi:+.4f}] p_boot~{p:.3f}")

print("\n=== 4. Сколько каналов показывают тот же знак (lift<1 для анти-, >1 для про-) ===")
for k in ["релиз модели", "Google/Gemini", "Россия/локальное", "суд/регулирование"] + list(STRICT):
    signs = []
    for c in CH:
        L = lift_of([c], k)
        if L == L and not math.isinf(L):
            signs.append(L)
    print(f"  {k:24s} каналов с оценкой {len(signs)}; lift<1: {sum(1 for x in signs if x<1)}, "
          f">1: {sum(1 for x in signs if x>1)}; медиана {st.median(signs):.2f}")

print("\n=== 5. Пересечения тем (доля постов темы A, попавших и в B) ===")
KK = ["релиз модели", "Google/Gemini", "Россия/локальное", "суд/регулирование", "цены/тарифы",
      "OpenAI", "Anthropic/Claude"]
for a in KK:
    na = sum(r["T:" + a] for r in rows)
    print(f"  {a:20s} n={na:4.0f}  " + "  ".join(
        f"{b.split('/')[0][:8]}:{sum(1 for r in rows if r['T:'+a] and r['T:'+b])/na*100:3.0f}%"
        for b in KK if b != a))
n_state = sum(1 for r in rows if re.search(r"государств", r["text"], re.I))
print(f"  'государств*' ловится ОБЕИМИ темами (РФ через 'гос', суд через 'суд'): {n_state} постов")
print(f"  длина: медиана у 'релиз модели' {st.median(r['len'] for r in rows if r['T:релиз модели']):.0f} "
      f"vs прочие {st.median(r['len'] for r in rows if not r['T:релиз модели']):.0f}")
