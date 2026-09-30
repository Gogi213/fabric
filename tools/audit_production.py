"""Аудит docs/08 (производственные метрики) и строк README «Что измерено».

Всё пересчитывается из сырых data/*.json; цифры документов не используются как вход.
Запуск (из корня репозитория):  python tools/audit_production.py
Сеть не нужна. Существующие файлы не меняет.

Принципы:
  * утверждение про слой -> бутстрэп по КАНАЛАМ (B=10000, seed 20260930),
    CI перцентильный; рядом — непараметрический CI медианы по порядковым статистикам;
  * алиас tehnochat (= technomedia) исключён везде;
  * слои проверяются в 4 определениях: метка автора, размер (>=1 млн подписчиков),
    метка с исправлением hiaimedia/gptpublic, медиана частоты (кроме самой частоты).
"""
import json, math, os, re, statistics as st, sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "data")
J = lambda n: json.load(open(os.path.join(D, n), encoding="utf-8"))

links = J("links.json")
posts = J("posts.json")
subs0 = {k: v for k, v in J("subs.json").items() if not k.startswith("_")}
recent = J("recent_posts.json")
react = J("reactions.json")

MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
EXP = ["xor_journal", "neuraldvig", "data_secrets", "seeallochnaya", "denissexy",
       "ai_newz", "cgevent", "NeuralShit", "ai_machinelearning_big_data", "tproger", "tlive"]
RU = MASS + EXP
SINCE = datetime(2026, 9, 15, tzinfo=timezone.utc)          # tools/crawl_links.py
RNG = np.random.default_rng(20260930)
B = 10000


def dt(s):
    return datetime.fromisoformat(s)


def vnum(s):
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip().upper().replace(" ", "").replace(" ", "")
    m = re.match(r"^([\d.,]+)([KM])?$", s)
    if not m:
        return None
    return float(m.group(1).replace(",", ".")) * {"K": 1e3, "M": 1e6}.get(m.group(2), 1)


def hr(t):
    print("\n" + "=" * 100 + "\n" + t + "\n" + "=" * 100)


# ---------------------------------------------------------------- статистика
def q(a, p):
    return float(np.quantile(np.asarray(a, float), p))


def med_ci_os(vals, conf=.95):
    """CI медианы по порядковым статистикам (без распределительных допущений)."""
    x = np.sort(np.asarray(vals, float))
    n = len(x)
    best = None
    for k in range(0, n // 2):
        cov = stats.binom.cdf(n - k - 1, n, .5) - stats.binom.cdf(k, n, .5) + stats.binom.pmf(k, n, .5) * 0
        cov = 1 - 2 * stats.binom.cdf(k, n, .5)
        if cov >= conf:
            best = (x[k], x[n - k - 1], cov)
    return best  # (lo, hi, фактическое покрытие)


def boot_med(vals, b=B):
    x = np.asarray(vals, float)
    idx = RNG.integers(0, len(x), (b, len(x)))
    m = np.median(x[idx], axis=1)
    return q(m, .025), float(np.median(x)), q(m, .975)


def boot_ratio(a, b_, fn=np.median, b=B):
    """CI отношения статистик двух независимых групп каналов."""
    a, b_ = np.asarray(a, float), np.asarray(b_, float)
    ia = RNG.integers(0, len(a), (b, len(a)))
    ib = RNG.integers(0, len(b_), (b, len(b_)))
    r = fn(a[ia], axis=1) / fn(b_[ib], axis=1)
    return q(r, .025), float(fn(a) / fn(b_)), q(r, .975)


def boot_diff(a, b_, fn=np.median, b=B):
    a, b_ = np.asarray(a, float), np.asarray(b_, float)
    ia = RNG.integers(0, len(a), (b, len(a)))
    ib = RNG.integers(0, len(b_), (b, len(b_)))
    r = fn(a[ia], axis=1) - fn(b_[ib], axis=1)
    return q(r, .025), float(fn(a) - fn(b_)), q(r, .975)


def mw(a, b_):
    return stats.mannwhitneyu(a, b_, alternative="two-sided").pvalue


def spear_ci(x, y, b=B):
    x, y = np.asarray(x, float), np.asarray(y, float)
    r = stats.spearmanr(x, y).statistic
    idx = RNG.integers(0, len(x), (b, len(x)))
    rs = []
    for i in idx:
        if len(set(x[i])) > 2 and len(set(y[i])) > 2:
            rs.append(stats.spearmanr(x[i], y[i]).statistic)
    return q(rs, .025), float(r), q(rs, .975), stats.spearmanr(x, y).pvalue


def fmt3(t, f="{:.2f}"):
    lo, m, hi = t[:3]
    return f"{f.format(m)} [{f.format(lo)}; {f.format(hi)}]"


def cluster_median(per_ch, b=B):
    """медиана пула постов при бутстрэпе каналов (как tools/uncertainty.py)."""
    keys = list(per_ch)
    arrs = [np.asarray(per_ch[k], float) for k in keys]
    pooled = np.concatenate(arrs)
    out = []
    for _ in range(b // 5):
        pick = RNG.integers(0, len(keys), len(keys))
        out.append(np.median(np.concatenate([arrs[i] for i in pick])))
    return q(out, .025), float(np.median(pooled)), q(out, .975)


subs_live = {ch: vnum(recent[ch]["subs"]) for ch in RU if ch in recent}
BIG = [c for c in RU if subs0[c] >= 1e6]
SMALL = [c for c in RU if subs0[c] < 1e6]
MASS_FIX = [c for c in MASS if c not in ("hiaimedia", "gptpublic")]
EXP_FIX = EXP + ["hiaimedia", "gptpublic"]
LAYERS = {
    "метка автора (11/11)": (MASS, EXP),
    "метка, hiaimedia+gptpublic -> эксп. (9/13)": (MASS_FIX, EXP_FIX),
    f"размер >=1 млн ({len(BIG)}/{len(SMALL)})": (BIG, SMALL),
}


def layer_report(name, val, unit="", f="{:.2f}", skip_size=False, extra_freq_split=None):
    """val: {канал: число}. Печатает медианы слоёв с CI, отношение, MW p."""
    print(f"  {name}:")
    defs = dict(LAYERS)
    if extra_freq_split:
        defs.update(extra_freq_split)
    res = {}
    for dn, (A, Bb) in defs.items():
        a = [val[c] for c in A if c in val and val[c] is not None]
        b_ = [val[c] for c in Bb if c in val and val[c] is not None]
        if len(a) < 3 or len(b_) < 3:
            continue
        ca, cb = boot_med(a), boot_med(b_)
        oa, ob = med_ci_os(a), med_ci_os(b_)
        rr = boot_ratio(a, b_) if min(b_) > 0 else (None, None, None)
        p = mw(a, b_)
        rtxt = fmt3(rr) if rr[0] is not None else "н/д"
        print(f"    {dn:44s} A={f.format(ca[1])}{unit} [{f.format(ca[0])}; {f.format(ca[2])}] "
              f"(OS {f.format(oa[0])}–{f.format(oa[1])}, {oa[2]*100:.0f}%) n={len(a)} | "
              f"B={f.format(cb[1])}{unit} [{f.format(cb[0])}; {f.format(cb[2])}] "
              f"(OS {f.format(ob[0])}–{f.format(ob[1])}) n={len(b_)} | A/B={rtxt} | MW p={p:.3g}")
        res[dn] = (ca, cb, rr, p)
    return res


# =================================================================== 0. данные
hr("0. ДАННЫЕ И ОКНО")
n_ru = sum(len(links[c]) for c in RU)
n_all = sum(len(v) for v in links.values())
T_END = max(dt(p["dt"]) for v in links.values() for p in v)
W = (T_END - SINCE).total_seconds() / 86400
print(f"  links.json: всего {n_all} постов в {len(links)} ключах; 22 RU без алиаса: {n_ru}; "
      f"алиас tehnochat: {len(links['tehnochat'])}")
print(f"  SINCE (crawl_links.py) = {SINCE:%Y-%m-%d %H:%M}; самый поздний пост в файле = {T_END:%Y-%m-%d %H:%M} UTC; "
      f"окно W = {W:.2f} сут")
tz = Counter(p["dt"][-6:] for c in RU for p in links[c])
secs = sum(1 for c in RU for p in links[c] if dt(p["dt"]).second != 0) / n_ru
print(f"  смещения часового пояса в dt: {dict(tz)}; доля dt с ненулевыми секундами {secs*100:.1f} %")
print(f"  posts.json: {sum(len(v) for v in posts.values())} постов, без алиаса "
      f"{sum(len(posts[c]) for c in RU if c in posts)}")

# =================================================================== 1. частота
hr("1. ЧАСТОТА ПУБЛИКАЦИЙ (docs/08 §2)")
freq_proj, freq_w, span = {}, {}, {}
for c in RU:
    d = sorted(dt(p["dt"]) for p in links[c])
    s = (d[-1] - d[0]).total_seconds() / 86400
    span[c] = s
    freq_proj[c] = len(d) / (s + 1)                     # формула tools/production.py
    freq_w[c] = len(d) / W                               # общий знаменатель = окно
print("  канал                         n   span+1  /сут(проект)  n/W(окно)   док «всего за 15.6 сут» = n")
for c in sorted(RU, key=lambda c: -freq_proj[c]):
    print(f"  {c:28s}{len(links[c]):4d}  {span[c]+1:6.2f}   {freq_proj[c]:6.2f}      {freq_w[c]:6.2f}")
print(f"  медиана span+1 = {st.median(span[c]+1 for c in RU):.2f} сут (в доке «15.6 сут окна» — такой общей величины нет)")

# второе независимое окно: recent_posts.json (26.09 21:42 – 30.09 21:42), все сообщения
meta = recent["_meta"]
t0, t1 = dt(meta["since"]), dt(meta["fetched"])
Wr = (t1 - t0).total_seconds() / 86400
freq_rec_all, freq_rec_txt, notext = {}, {}, {}
for c in RU:
    ps = [p for p in recent[c]["posts"] if dt(p["dt"]) >= t0]
    freq_rec_all[c] = len(ps) / Wr
    freq_rec_txt[c] = sum(p["has_text"] for p in ps) / Wr
    notext[c] = 1 - sum(p["has_text"] for p in ps) / max(len(ps), 1)
print(f"\n  Повтор на другом окне (recent_posts.json, {t0:%d.%m %H:%M}–{t1:%d.%m %H:%M}, {Wr:.2f} сут):")
print(f"  доля сообщений без текста: медиана {st.median(notext.values())*100:.1f} %, "
      f"макс {max(notext.values())*100:.1f} % ({max(notext, key=notext.get)}); "
      f"всего {sum(1 for c in RU for p in recent[c]['posts'] if dt(p['dt'])>=t0 and not p['has_text'])} из "
      f"{sum(1 for c in RU for p in recent[c]['posts'] if dt(p['dt'])>=t0)}")
# длинное окно: reactions.json (глубина 7–168 сут)
freq_rx = {}
for c in RU:
    d = sorted(dt(p["dt"]) for p in react[c]["posts"])
    freq_rx[c] = len(d) / ((d[-1] - d[0]).total_seconds() / 86400)
print("  канал                        проект  n/W   recent(все)  recent(текст)  reactions.json(глубина)")
for c in sorted(RU, key=lambda c: -freq_w[c]):
    print(f"  {c:28s}{freq_proj[c]:6.1f} {freq_w[c]:6.1f}   {freq_rec_all[c]:6.1f}      {freq_rec_txt[c]:6.1f}"
          f"        {freq_rx[c]:6.1f}")
r = stats.spearmanr([freq_w[c] for c in RU], [freq_rec_all[c] for c in RU]).statistic
print(f"  Spearman(окно 15–29.09, окно 27–30.09) по каналам = {r:.3f}")

freq_split = None
F = {}
for nm, v in [("проект n/(span+1)", freq_proj), ("n/W, W=окно", freq_w),
              ("recent, все сообщения", freq_rec_all), ("reactions.json, длинное окно", freq_rx)]:
    F[nm] = layer_report(f"частота [{nm}], постов/сут", v, f="{:.1f}")
tot = sum(freq_w.values())
print(f"\n  Сумма 22 каналов: {sum(freq_proj.values()):.0f}/сут (проект), {tot:.0f}/сут (n/W) = {tot*30:.0f}/мес")
print(f"  «13 постов/сутки = ~4.3 поста в час»: 13/24 = {13/24:.2f}/ч; 13/14 (рабочие 06–20 UTC) = {13/14:.2f}/ч")
x = np.array([math.log10(subs0[c]) for c in RU])
print("  Spearman(частота n/W, log подписчиков) по 22 каналам:",
      fmt3(spear_ci(x, [freq_w[c] for c in RU])), f"p={spear_ci(x, [freq_w[c] for c in RU], b=200)[3]:.3g}")
vals = sorted(freq_w.values())
print("  распределение частот (n/W), по возрастанию:", ", ".join(f"{v:.1f}" for v in vals))
gaps = np.diff(vals)
print(f"  наибольший разрыв между соседними значениями: {gaps.max():.2f} (между {vals[gaps.argmax()]:.1f} и "
      f"{vals[gaps.argmax()+1]:.1f}); медианный разрыв {np.median(gaps):.2f}")

# дневная нагрузка (полные сутки 15..28.09)
print("\n  Суточная нагрузка по полным суткам 15–28.09 (для планирования смен):")
wk = {}
for c in RU:
    cnt = Counter(dt(p["dt"]).date() for p in links[c])
    days = [SINCE.date() + timedelta(d) for d in range(14)]
    arr = np.array([cnt.get(d, 0) for d in days])
    we = np.array([d.weekday() >= 5 for d in days])
    wk[c] = (arr, we)
for g, names in (("массовый", MASS), ("экспертный", EXP)):
    p90 = [q(wk[c][0], .9) for c in names]
    mx = [wk[c][0].max() for c in names]
    rat = [wk[c][0][wk[c][1]].mean() / max(wk[c][0][~wk[c][1]].mean(), 1e-9) for c in names]
    print(f"    {g}: медиана по каналам p90 суток = {st.median(p90):.0f}, макс суток = {st.median(mx):.0f}; "
          f"выходные/будни = {st.median(rat):.2f} (медиана по каналам)")

# =================================================================== 2. расписание
hr("2. РАСПИСАНИЕ (docs/08 §3, docs/05 §2.2)")
H = {c: np.bincount([dt(p["dt"]).hour for p in links[c]], minlength=24) for c in RU}
pool = sum(H.values())
print("  Пул 22 каналов (как в доке), доля постов по часу UTC, топ-8:")
for h in np.argsort(-pool)[:8]:
    print(f"    {h:02d}:00  {pool[h]/pool.sum()*100:5.1f} %")
share = {c: H[c] / H[c].sum() for c in RU}
eq = np.mean([share[c] for c in RU], axis=0)
idx = RNG.integers(0, len(RU), (B, len(RU)))
S = np.array([share[c] for c in RU])
bs = S[idx].mean(axis=1)                                   # B x 24
print("  Равный вес каналов (средняя доля по каналам), 95 % CI бутстрэп по каналам:")
for h in np.argsort(-eq)[:8]:
    print(f"    {h:02d}:00  {eq[h]*100:5.1f} % [{q(bs[:, h], .025)*100:.1f}; {q(bs[:, h], .975)*100:.1f}]")
peak_boot = Counter(int(np.argmax(r)) for r in bs)
print(f"  Час-максимум в бутстрэпе: {dict(peak_boot.most_common(6))} (доля реплик)")
top3 = sorted(RU, key=lambda c: -len(links[c]))[:3]
k = sum(H[c][13:18].sum() for c in top3)
print(f"  Вклад 3 самых частых каналов {top3}: {sum(H[c].sum() for c in top3)/pool.sum()*100:.1f} % всех постов, "
      f"{k/pool[13:18].sum()*100:.1f} % постов 13–17 UTC")
loo = Counter()
for c in RU:
    loo[int(np.argmax(pool - H[c]))] += 1
print(f"  Пиковый час пула при исключении по одному каналу: {dict(loo)}")
for g, names in (("массовый", MASS), ("экспертный", EXP)):
    ph = sum(H[c] for c in names)
    night = ph[list(range(0, 6)) + [21, 22, 23]].sum()
    act = ph[6:21].sum() / ph.sum()
    eqg = np.mean([share[c] for c in names], axis=0)
    print(f"  {g}: пул-пик {int(np.argmax(ph)):02d}:00 ({ph.max()/ph.sum()*100:.1f} %); равновзв. пик "
          f"{int(np.argmax(eqg)):02d}:00 ({eqg.max()*100:.1f} %); постов 00–05 и 21–23 UTC: {night} "
          f"({night/ph.sum()*100:.1f} %: 00–05 {ph[0:6].sum()}, 21–23 {ph[21:24].sum()}); доля 06–20 UTC {act*100:.1f} %")
    print("     профиль по часам 00..23 (пул, %): " + " ".join(f"{x/ph.sum()*100:.0f}" for x in ph))
    zero = [c for c in names if H[c][list(range(0, 6)) + [21, 22, 23]].sum() == 0]
    print(f"     каналов без единого поста 00–05/21–23 UTC: {len(zero)} из {len(names)} {zero}")
# окно 13:00–17:59
w13 = {c: H[c][13:18].sum() / H[c].sum() * 100 for c in RU if H[c].sum() >= 20}
print("  Доля постов 13:00–17:59 UTC по каналам (каналы с >=20 постами); равномерный ориентир 5/15 часов "
      "06–20 = 33.3 %, 5/24 = 20.8 %:")
for g, names in (("массовый", MASS), ("экспертный", EXP)):
    v = [w13[c] for c in names if c in w13]
    bm = boot_med(v)
    mean_b = RNG.choice(v, (B, len(v))).mean(axis=1)
    print(f"    {g}: медиана {bm[1]:.1f} % [{bm[0]:.1f}; {bm[2]:.1f}] (бутстрэп медианы), "
          f"среднее {np.mean(v):.1f} % [{q(mean_b,.025):.1f}; {q(mean_b,.975):.1f}], n={len(v)}")
for lab, hs in (("13–16 (4 ч)", range(13, 17)), ("13–15 (3 ч)", range(13, 16)), ("08–11", range(8, 12)),
                ("18–20", range(18, 21)), ("06–20", range(6, 21))):
    print(f"    пул {lab}: {pool[list(hs)].sum()/pool.sum()*100:.1f} %  | равновзв.: {eq[list(hs)].sum()*100:.1f} %")
for lab, hs in (("09–18", range(9, 19)), ("06–20", range(6, 21))):
    for g, names in (("масс", MASS), ("эксп", EXP)):
        v = [H[c][list(hs)].sum() / H[c].sum() * 100 for c in names]
        bm = RNG.choice(v, (B, len(v))).mean(axis=1)
        print(f"    доля в {lab} UTC, {g}: среднее по каналам {np.mean(v):.1f} % [{q(bm,.025):.1f}; {q(bm,.975):.1f}]")
act = pool[6:21] / pool[6:21].sum()
print(f"  Неравномерность внутри 06–20 UTC: max/min часа = {act.max()/act.min():.2f}; "
      f"энтропия/макс = {-(act*np.log(act)).sum()/math.log(15):.3f} (1 = равномерно)")

# просмотры по часу публикации (внутри канала, посты старше 3 сут)
print("\n  Просмотры по часу публикации, внутри канала (log-просмотры минус медиана канала), посты возрастом >=3 сут:")
BLK = [("00–05", range(0, 6)), ("06–09", range(6, 10)), ("10–12", range(10, 13)), ("13–17", range(13, 18)),
       ("18–20", range(18, 21)), ("21–23", range(21, 24))]
rel = defaultdict(dict)
for c in RU:
    ps = [(dt(p["dt"]), vnum(p["views"])) for p in links[c]]
    ps = [(t, v) for t, v in ps if v and (T_END - t).days >= 3]
    if len(ps) < 10:
        continue
    lv = np.log([v for _, v in ps])
    m = np.median(lv)
    for bn, hs in BLK:
        x_ = [l - m for (t, _), l in zip(ps, lv) if t.hour in hs]
        if len(x_) >= 3:
            rel[bn][c] = float(np.mean(x_))
for bn, _ in BLK:
    v = list(rel[bn].values())
    if len(v) < 3:
        print(f"    {bn}: каналов с >=3 постами: {len(v)} — не оценивается")
        continue
    mb = RNG.choice(v, (B, len(v))).mean(axis=1)
    print(f"    {bn}: {(math.exp(np.mean(v))-1)*100:+5.1f} % [{(math.exp(q(mb,.025))-1)*100:+.1f}; "
          f"{(math.exp(q(mb,.975))-1)*100:+.1f}] к медиане канала, каналов {len(v)}")

# механизм: чем дольше пост остаётся последним в канале, тем больше просмотров?
rows_g = defaultdict(list)
for c in RU:
    ps = sorted((dt(p["dt"]), vnum(p["views"])) for p in links[c] if vnum(p["views"]))
    for (t, v), (t2, _) in zip(ps, ps[1:]):
        age = (T_END - t).total_seconds() / 86400
        gap = (t2 - t).total_seconds() / 3600
        if age >= 3 and gap > 0:
            rows_g[c].append((math.log(gap), math.log(v), math.log(age), t.hour))


def fe_gap(keys):
    xs, ys = [], []
    for k in keys:
        a = np.array(rows_g[k][:])
        if len(a) < 8:
            continue
        a = a[:, :3] - a[:, :3].mean(axis=0)
        xs.append(a[:, [0, 2]]); ys.append(a[:, 1])
    return np.linalg.lstsq(np.vstack(xs), np.concatenate(ys), rcond=None)[0][0]


kk = [c for c in RU if len(rows_g[c]) >= 8]
g0 = fe_gap(kk)
gb = [fe_gap([kk[i] for i in RNG.integers(0, len(kk), len(kk))]) for _ in range(2000)]
print(f"  Механизм: log-просмотры ~ log(часов до следующего поста канала) + log(возраст), FE канала, посты >=3 сут: "
      f"удвоение паузы -> {((2**g0)-1)*100:+.1f} % [{((2**q(gb,.025))-1)*100:+.1f}; {((2**q(gb,.975))-1)*100:+.1f}] "
      f"просмотров, каналов {len(kk)}")
ng = [math.exp(r[0]) for c in RU for r in rows_g[c] if r[3] >= 21 or r[3] < 6]
dg = [math.exp(r[0]) for c in RU for r in rows_g[c] if 6 <= r[3] < 21]
print(f"  медианная пауза до следующего поста: после ночного поста {st.median(ng):.1f} ч, после дневного {st.median(dg):.1f} ч")

# docs/05 §2.2: «в пик копии расходятся за минуты, вне пика окно спокойнее» — лаг 1-й -> 2-й канал по кластерам
CL = J("clusters.json")["clusters"]
lagp, lago = [], []
for cl in CL:
    ms = sorted(cl["members"], key=lambda m: m["dt"])
    t1 = dt(ms[0]["dt"])
    nxt = next((m for m in ms[1:] if m["ch"] != ms[0]["ch"]), None)
    if not nxt:
        continue
    lag = (dt(nxt["dt"]) - t1).total_seconds() / 60
    (lagp if 13 <= t1.hour <= 17 else lago).append(lag)
print(f"  docs/05 §2.2: лаг до 2-го канала в кластерах, первый пост в 13–17 UTC: медиана {st.median(lagp):.0f} мин "
      f"(n={len(lagp)}); вне 13–17: {st.median(lago):.0f} мин (n={len(lago)}); MW p={mw(lagp, lago):.2f}")
print(f"  «13:00–17:00 = 29 % постов» (docs/05): пул 13:00–16:59 = {pool[13:17].sum()/pool.sum()*100:.1f} %, "
      f"13:00–17:59 = {pool[13:18].sum()/pool.sum()*100:.1f} %")

# =================================================================== 3. реклама
hr("3. РЕКЛАМНАЯ НАГРУЗКА (docs/08 §4)")
ERID_P = re.compile(r"\b2[A-Za-z0-9]{15,25}\b")
ADTAG_P = re.compile(r"(#реклама\b|#ad\b|\bреклама\b|\bрекламное сообщение\b|\bsponsored\b|\bpartnership\b)", re.I)
FWD_OK = re.compile(r"(\bновост\b|\bпресс-релиз\b|\bрелиз\b|\bзапуск\b|\bобъявл)", re.I)


def proj_ad(p):
    blob = p["text"] + " " + " ".join(p.get("links") or [])
    if ERID_P.search(blob) or ADTAG_P.search(p["text"]):
        return True
    return bool(p.get("fwd_name") and not FWD_OK.search(p["text"]))


ERID_TXT = re.compile(r"\b(erid|ерид)\b\s*[:=]?\s*[A-Za-z0-9]{6,}", re.I)
ERID_URL = re.compile(r"[?&](?:amp;)?erid=([A-Za-z0-9]+)", re.I)
MARK = re.compile(r"(#реклама\b|#ad\b|#промо\b|#партн[её]р|на правах рекламы|рекламное сообщение|"
                  r"[Рр]еклама\.\s+(?:[А-ЯA-Z«\"]|ООО|АО|ИП))")


def own(u, c):
    return re.search(rf"(?:t\.me|telegram\.me)/{re.escape(c)}\b", u, re.I) is not None


def explicit_ad(p, c, self_erid=False):
    if ERID_TXT.search(p["text"]) or MARK.search(p["text"]):
        return True
    for u in p.get("links") or []:
        if ERID_URL.search(u) and (self_erid or not own(u, c)):
            return True
    return False


erid_hits = [(c, m) for c in RU for p in links[c]
             for m in ERID_P.findall(p["text"] + " " + " ".join(p["links"]))]
real = Counter(len(m) for c in RU for p in links[c] for u in p["links"] for m in ERID_URL.findall(u))
print(f"  Проектная регулярка ERID: {len(erid_hits)} совпадений в "
      f"{sum(1 for c in RU for p in links[c] if ERID_P.search(p['text']+' '+' '.join(p['links'])))} постах; "
      f"чисто цифровых: {sum(1 for _, m in erid_hits if m.isdigit())}; из ссылок x.com/twitter: "
      f"{sum(1 for c in RU for p in links[c] for u in p['links'] if ERID_P.search(u) and re.search('x.com|twitter.com', u))}")
print(f"  Настоящие erid в ссылках: {sum(real.values())} шт., длины: {dict(sorted(real.items()))}")
own_only = sum(1 for c in RU for p in links[c]
               if any(ERID_URL.search(u) for u in p["links"]) and all(own(u, c) for u in p["links"] if ERID_URL.search(u))
               and not ERID_TXT.search(p["text"]) and not MARK.search(p["text"]))
print(f"  Постов, где erid только в ссылке на СВОЙ канал (подпись): {own_only} "
      f"(whackdoor: t.me/whackdoor?erid=2VtzquZvQkb на обычных редакционных постах)")
ad = {}
for nm, fn in (("проект (docs/08)", proj_ad),
               ("явная маркировка, без erid в подписи", lambda p, c=None: None),
               ("явная маркировка, вкл. erid в подписи", None)):
    pass
defs = {
    "проект (docs/08)": lambda p, c: proj_ad(p),
    "проект без форвардов": lambda p, c: bool(ERID_P.search(p["text"] + " " + " ".join(p["links"])) or ADTAG_P.search(p["text"])),
    "явная маркировка": lambda p, c: explicit_ad(p, c),
    "явная + erid в подписи": lambda p, c: explicit_ad(p, c, True),
}
for nm, fn in defs.items():
    ad[nm] = {c: sum(fn(p, c) for p in links[c]) / len(links[c]) * 100 for c in RU}
print("  канал                         проект  без_форв  явная  явная+подп  n   форвардов")
for c in sorted(RU, key=lambda c: -ad["проект (docs/08)"][c]):
    f_ = sum(1 for p in links[c] if p["fwd_name"] or p["fwd_url"])
    print(f"  {c:28s}{ad['проект (docs/08)'][c]:6.1f} {ad['проект без форвардов'][c]:8.1f} "
          f"{ad['явная маркировка'][c]:6.1f} {ad['явная + erid в подписи'][c]:8.1f}  {len(links[c]):4d} {f_:4d}")
for nm in defs:
    layer_report(f"ad% [{nm}]", ad[nm], "%", f="{:.1f}",
                 extra_freq_split={"частота n/W >= медианы (11/11)":
                                   (sorted(RU, key=lambda c: -freq_w[c])[:11], sorted(RU, key=lambda c: -freq_w[c])[11:])})
ge20 = [c for c in EXP if len(links[c]) >= 20]
print(f"  Сверка 18.9 vs 19.6: медиана проектного ad% экспертов по 11 = {st.median(ad['проект (docs/08)'][c] for c in EXP):.1f}; "
      f"по {len(ge20)} с >=20 постами (фильтр uncertainty.py, выпадает ai_newz) = "
      f"{st.median(ad['проект (docs/08)'][c] for c in ge20):.1f}")
# усечение: теряется ли маркировка в links.json (1200 симв.) — сверка с полным текстом posts.json
lost = 0
tot_m = 0
for c in RU:
    full = {p["id"]: p["text"] for p in posts.get(c, [])}
    for p in links[c]:
        if p["id"] in full:
            a1 = bool(ERID_TXT.search(full[p["id"]]) or MARK.search(full[p["id"]]))
            a2 = bool(ERID_TXT.search(p["text"]) or MARK.search(p["text"]))
            tot_m += a1
            lost += a1 and not a2
print(f"  Маркировка в тексте, потерянная из-за обрезки 1200 симв. (сверка с posts.json): {lost} из {tot_m}")
# сигналы возможной НЕмаркированной рекламы (эвристика, верхняя граница, не классификатор)
AD_DOM = re.compile(r"(alfa\.me|alfabank|sberbank|sber\.ru|mts\.ru|beeline|tbank|t-bank|setka\.ru|avito|ozon|"
                    r"wildberries|mws\.ru|selectel|timeweb|beget|netology|skillbox|yandex\.cloud|cloud\.ru)", re.I)
SHORT = re.compile(r"//(u\.to|clck\.ru|bit\.ly|vk\.cc|cutt\.ly|tinyurl\.com|clc\.to|is\.gd)/", re.I)
PROMO = re.compile(r"(промокод|скидк[аиу] по ссылке|utm_content=|utm_campaign=)", re.I)


def signal(p, c):
    if explicit_ad(p, c, True):
        return False
    blob = p["text"] + " " + " ".join(p["links"])
    return bool(AD_DOM.search(" ".join(p["links"])) or SHORT.search(" ".join(p["links"])) or PROMO.search(blob))


sig = {c: sum(signal(p, c) for p in links[c]) / len(links[c]) * 100 for c in RU}
layer_report("посты БЕЗ явной маркировки, но с рекламным сигналом (рекл. домен / сокращатель / промокод / utm_campaign)",
             sig, "%", f="{:.1f}")
print("     по каналам: " + ", ".join(f"{c}:{sig[c]:.0f}" for c in sorted(RU, key=lambda c: -sig[c])))
# форварды
fw = {c: sum(1 for p in links[c] if p["fwd_name"] or p["fwd_url"]) for c in RU}
print(f"  Форварды: {sum(fw.values())} из {n_ru} постов = {sum(fw.values())/n_ru*100:.1f} %; медиана доли: "
      f"масс {st.median(fw[c]/len(links[c])*100 for c in MASS):.1f} %, эксп {st.median(fw[c]/len(links[c])*100 for c in EXP):.1f} %")
fwp = {}
for c in RU:
    f_ = [p for p in links[c] if p.get("fwd_name")]
    fwp[c] = sum(1 for p in f_ if not FWD_OK.search(p["text"])) / max(len(f_), 1) * 100
print(f"  Воспроизведение «форвард%» docs/08 (fw/max(f,1)): масс {st.median(fwp[c] for c in MASS):.1f} %, "
      f"эксп {st.median(fwp[c] for c in EXP):.1f} % — это доля «нередакционных» среди форвардов, не доля постов")

# =================================================================== 4. длина
hr("4. ДЛИНА ПОСТА (docs/08 §5)")
Lc = {c: [len(p["text"]) for p in posts[c]] for c in RU if c in posts}
allL = [x for c in RU for x in Lc[c]]
allL_alias = [len(p["text"]) for v in posts.values() for p in v]
print(f"  Все посты posts.json: медиана {st.median(allL_alias):.0f} (n={len(allL_alias)}, с алиасом); "
      f"без алиаса {st.median(allL):.0f} (n={len(allL)}); p25 {q(allL,.25):.0f}, p75 {q(allL,.75):.0f}, "
      f"p95 {q(allL,.95):.0f}, max {max(allL)}")
print(f"  CI общей медианы, бутстрэп по каналам: {fmt3(cluster_median(Lc), '{:.0f}')}")
for g, names in (("массовый", MASS), ("экспертный", EXP)):
    cm = cluster_median({c: Lc[c] for c in names})
    mm = boot_med([st.median(Lc[c]) for c in names])
    print(f"  {g}: медиана пула {fmt3(cm, '{:.0f}')} ; медиана медиан каналов {fmt3(mm, '{:.0f}')}")
medL = {c: st.median(Lc[c]) for c in RU}
layer_report("медиана длины канала, симв.", medL, f="{:.0f}",
             extra_freq_split={"частота n/W >= медианы (11/11)":
                               (sorted(RU, key=lambda c: -freq_w[c])[:11], sorted(RU, key=lambda c: -freq_w[c])[11:])})
print("  Медианы длины по каналам, по возрастанию:",
      ", ".join(f"{c}:{medL[c]:.0f}{'м' if c in MASS else 'э'}" for c in sorted(RU, key=medL.get)))
print("  Spearman(частота n/W, медиана длины):", fmt3(spear_ci([freq_w[c] for c in RU], [medL[c] for c in RU])),
      f"p={stats.spearmanr([freq_w[c] for c in RU], [medL[c] for c in RU]).pvalue:.3g}")
for lo_, hi_ in ((200, 420), (800, 1300)):
    print(f"    каналов с медианой в [{lo_}; {hi_}]: масс {sum(lo_<=medL[c]<=hi_ for c in MASS)}/11, "
          f"эксп {sum(lo_<=medL[c]<=hi_ for c in EXP)}/11")
# усечение
cut_all = sum(1 for v in links.values() for p in v if len(p["text"]) >= 1199)
cut_ru = sum(1 for c in RU for p in links[c] if len(p["text"]) >= 1199)
print(f"  Обрезка 1200: все ключи {cut_all}/{n_all} = {cut_all/n_all*100:.1f} %; 22 RU {cut_ru}/{n_ru} = "
      f"{cut_ru/n_ru*100:.1f} %; масс {sum(1 for c in MASS for p in links[c] if len(p['text'])>=1199)/sum(len(links[c]) for c in MASS)*100:.1f} %, "
      f"эксп {sum(1 for c in EXP for p in links[c] if len(p['text'])>=1199)/sum(len(links[c]) for c in EXP)*100:.1f} %")
Ll = [len(p["text"]) for v in links.values() for p in v]
print(f"  «376 vs 381»: медиана links.json (37 ключей, 2 нед., обрезано) = {st.median(Ll):.0f}; "
      f"posts.json (23 ключа, 1 нед., полное) = {st.median(allL_alias):.0f} — разные выборки")
same, n_same = 0, 0
for c in RU:
    full = {p["id"]: len(p["text"]) for p in posts.get(c, [])}
    for p in links[c]:
        if p["id"] in full:
            n_same += 1
            same += (min(full[p["id"]], 1200) == len(p["text"]))
print(f"  Одни и те же посты в двух файлах: {n_same}; длина совпадает с min(полная,1200) у {same} ({same/n_same*100:.1f} %)")
EMO_P = re.compile("[\U0001F300-\U0001FAFF☀-➿️⬀-⯿]")
EMO_C = re.compile("[\U0001F300-\U0001FAFF☀-➿⬀-⯿]")
for nm, R in (("проектная (с U+FE0F)", EMO_P), ("без U+FE0F", EMO_C)):
    em = {c: st.median(len(R.findall(p["text"])) for p in posts[c]) for c in RU}
    print(f"  эмодзи/пост, медиана [{nm}]: масс " + ", ".join(f"{em[c]:.0f}" for c in MASS) +
          " | эксп " + ", ".join(f"{em[c]:.0f}" for c in EXP) +
          f" | эксп с ненулевой медианой: {sum(em[c] > 0 for c in EXP)}/11")

# =================================================================== 5. ER
hr("5. ER = медиана просмотров / подписчики (docs/08 §6)")
V = {c: [(dt(p["dt"]), vnum(p["views"])) for p in links[c] if vnum(p["views"])] for c in RU}
er = {c: st.median(v for _, v in V[c]) / subs0[c] * 100 for c in RU}
er3 = {c: st.median(v for t, v in V[c] if (T_END - t).total_seconds() >= 3 * 86400) / subs0[c] * 100 for c in RU}
er_live = {c: st.median(v for _, v in V[c]) / subs_live[c] * 100 for c in RU}
mv = {c: st.median(v for _, v in V[c]) for c in RU}
print("  Подписчики: subs.json (30.09 04:05) vs recent_posts.json (30.09 ~21:40):",
      f"медиана |Δ| {st.median(abs(subs_live[c]/subs0[c]-1)*100 for c in RU):.2f} %, "
      f"макс {max(abs(subs_live[c]/subs0[c]-1)*100 for c in RU):.2f} %")
print("  каналы с |Δ|>1 %: " + ", ".join(f"{c} {subs0[c]:,.0f}->{subs_live[c]:,.0f} ({(subs_live[c]/subs0[c]-1)*100:+.1f} %)"
                                     for c in RU if abs(subs_live[c]/subs0[c]-1) > .01))
print("  Подписчики reactions.json vs subs.json: различий",
      sum(1 for c in RU if abs(react[c]["subs"] - subs0[c]) > 1))
# рост просмотров с возрастом: одни и те же посты в links.json (crawl ~29.09) и reactions.json (~30.09)
g = defaultdict(list)
for c in RU:
    rv = {str(p["id"]): p["views"] for p in react[c]["posts"] if p.get("views")}
    for t, v in V[c]:
        pass
    for p in links[c]:
        v1 = vnum(p["views"])
        if p["id"] in rv and v1:
            age = (T_END - dt(p["dt"])).total_seconds() / 86400
            b_ = "<1" if age < 1 else "1–2" if age < 2 else "2–3" if age < 3 else "3–7" if age < 7 else ">=7"
            g[b_].append(rv[p["id"]] / v1 - 1)
print("  Прирост просмотров того же поста между сбором links.json и reactions.json, по возрасту в links.json (сут):")
for b_ in ("<1", "1–2", "2–3", "3–7", ">=7"):
    if g[b_]:
        print(f"    {b_:4s}: медиана {st.median(g[b_])*100:+.1f} %, n={len(g[b_])}")
print("  канал                        слой  подписч.   мед.просм   ER%    ER%(>=3сут)  ER%(subs 30.09 вечер)")
for c in sorted(RU, key=lambda c: -er[c]):
    print(f"  {c:28s} {'м' if c in MASS else 'э'} {subs0[c]:10,.0f} {mv[c]:10,.0f} {er[c]:6.2f}  {er3[c]:6.2f}      {er_live[c]:6.2f}")
for nm, v in (("ER, как в доке", er), ("ER, только посты >=3 сут", er3)):
    layer_report(nm, v, "%", f="{:.2f}",
                 extra_freq_split={"частота n/W >= медианы (11/11)":
                                   (sorted(RU, key=lambda c: -freq_w[c])[:11], sorted(RU, key=lambda c: -freq_w[c])[11:])})
layer_report("медиана просмотров на пост (абсолютно)", mv, f="{:,.0f}")
ls = np.log10([subs0[c] for c in RU])
le = np.log10([er[c] for c in RU])
print("  Spearman(log подписчиков, ER), 22 канала:", fmt3(spear_ci(ls, le)))
for g_, names in (("внутри массового", MASS), ("внутри экспертного", EXP)):
    print(f"    {g_}: rho = {stats.spearmanr([subs0[c] for c in names], [er[c] for c in names]).statistic:.2f}")
# регрессия log ER ~ log subs + слой
X = np.column_stack([np.ones(22), ls, [1.0 if c in EXP else 0.0 for c in RU]])
beta = np.linalg.lstsq(X, le, rcond=None)[0]
bb = []
for _ in range(B):
    i = RNG.integers(0, 22, 22)
    if len(set(X[i, 2])) < 2:
        continue
    bb.append(np.linalg.lstsq(X[i], le[i], rcond=None)[0])
bb = np.array(bb)
print(f"  log10 ER = a + b*log10 subs + c*[эксп]: b = {beta[1]:.2f} [{q(bb[:,1],.025):.2f}; {q(bb[:,1],.975):.2f}], "
      f"c = {beta[2]:.2f} [{q(bb[:,2],.025):.2f}; {q(bb[:,2],.975):.2f}] (x{10**beta[2]:.2f} "
      f"[{10**q(bb[:,2],.025):.2f}; {10**q(bb[:,2],.975):.2f}])")
X0 = np.column_stack([np.ones(22), ls])
b0 = np.linalg.lstsq(X0, le, rcond=None)[0]
res = le - X0 @ b0
print(f"  ER по размеру: log10 ER = {b0[0]:.2f} {b0[1]:+.2f}*log10 subs; остатки (x раз к ожидаемому по размеру): " +
      ", ".join(f"{c}:{10**r:.2f}" for c, r in sorted(zip(RU, res), key=lambda x: x[1])))
print(f"  прогноз этой подгонки для 30K (вне диапазона данных!): ER {10**(b0[0]+b0[1]*math.log10(3e4)):.0f} %")
print(f"  валовые просмотры/сутки на подписчика при равном размере (по цифрам docs/08): масс 3.86 %*13.0 = {3.86*13.0/100:.2f}, "
      f"эксп 13.30 %*2.7 = {13.30*2.7/100:.2f}")
X1 = np.column_stack([np.ones(22), [1.0 if c in EXP else 0.0 for c in RU]])
b1 = np.linalg.lstsq(X1, le, rcond=None)[0]
print(f"  без контроля размера: c = x{10**b1[1]:.2f}")
print(f"  Минимум подписчиков в выборке: {min(subs0.values()):,.0f} (экстраполяция ER на канал 30K — вне диапазона)")
low = [c for c in RU if er[c] < 2.5]
print(f"  ER < 2.5 %: {[(c, round(er[c],2), subs0[c]) for c in low]}")
print("  «Охват/сутки» = медиана просмотров × постов/сут — сумма просмотров, не уникальный охват.")

# =================================================================== 6. длина ↔ просмотры
hr("6. ДЛИНА ↔ ПРОСМОТРЫ (docs/08 §7)")
print("  Воспроизведение таблицы (links.json; <400 vs >1000 симв.; >=3 в каждой группе) с размерами групп:")
for c in RU:
    ps = [(len(p["text"]), vnum(p["views"])) for p in links[c] if vnum(p["views"])]
    if len(ps) < 12:
        continue
    sh = [v for l, v in ps if l < 400]
    lo_ = [v for l, v in ps if l > 1000]
    if len(sh) < 3 or len(lo_) < 3:
        continue
    print(f"    {c:28s} n<400={len(sh):3d} n>1000={len(lo_):3d}  разница медиан {(st.median(lo_)/st.median(sh)-1)*100:+6.1f} %")
# внутриканальная регрессия log(views) ~ log2(len) + log(age) с фикс. эффектами канала; посты >=3 сут
rows = []
for c in RU:
    for p in links[c]:
        v = vnum(p["views"])
        age = (T_END - dt(p["dt"])).total_seconds() / 86400
        if v and age >= 3 and len(p["text"]) > 0:
            rows.append((c, math.log2(min(len(p["text"]), 1200)), math.log(v), math.log(age)))
chs = sorted({r[0] for r in rows})


def fe_slope(sub):
    y, x1, x2 = [], [], []
    for c in set(r[0] for r in sub):
        rr = [r for r in sub if r[0] == c]
        if len(rr) < 5:
            continue
        a = np.array([[r[1], r[2], r[3]] for r in rr])
        a -= a.mean(axis=0)
        x1 += list(a[:, 0]); y += list(a[:, 1]); x2 += list(a[:, 2])
    Xm = np.column_stack([x1, x2])
    return np.linalg.lstsq(Xm, np.array(y), rcond=None)[0][0]


byc = defaultdict(list)
for r in rows:
    byc[r[0]].append(r)
s0 = fe_slope(rows)
bs_ = []
for _ in range(2000):
    pick = RNG.integers(0, len(chs), len(chs))
    sub = []
    for j, i in enumerate(pick):
        sub += [(f"{chs[i]}#{j}",) + r[1:] for r in byc[chs[i]]]
    bs_.append(fe_slope(sub))
lo_, hi_ = q(bs_, .025), q(bs_, .975)
pct = lambda b_: (2 ** 0 * math.exp(b_) - 1) * 100
print(f"  FE-регрессия (посты >=3 сут, n={len(rows)}, каналов {len(chs)}): удвоение длины -> просмотры "
      f"{pct(s0):+.1f} % [{pct(lo_):+.1f}; {pct(hi_):+.1f}] (бутстрэп по каналам)")
l90, h90 = q(bs_, .05), q(bs_, .95)
marg = max(abs(pct(l90)), abs(pct(h90)))
print(f"  TOST (через 90 % CI {pct(l90):+.1f}; {pct(h90):+.1f}): эквивалентность нулю доказана для любой границы "
      f">= ±{marg:.1f} % просмотров на удвоение длины (например ±5 %: да)")
rho_c = []
for c in chs:
    rr = byc[c]
    if len(rr) >= 10:
        rho_c.append(stats.spearmanr([r[1] for r in rr], [r[2] for r in rr]).statistic)
print(f"  Внутриканальные Spearman(длина, просмотры): медиана {st.median(rho_c):+.2f}, "
      f"положительных {sum(r > 0 for r in rho_c)}/{len(rho_c)}")
print("\nГотово.")
