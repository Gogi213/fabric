"""Общие функции аудита docs/09 и docs/10 (независимый пересчёт).

Загружает data/reactions.json, чинит известные дефекты парсинга и даёт
статистические помощники. Пути относительные от корня репозитория.
Зависимости: numpy, scipy.

Дефекты, которые здесь исправляются/помечаются (найдены аудитом):
  * фишки с суффиксом K ("😁 1.04K") парсились как 1 (regex NUM ловит только
    цифры до точки); эмодзи-ключ при этом получал хвост " 1.04K".
    rx_fix восстанавливает значение как float*1000 (точность ±0.5 %).
    Кастомные фишки >=1000 восстановить нельзя (ключ "custom" без числа):
    помечаются флагом trunc_custom (кастомная фишка стоит раньше меньшей).
  * ключ "?" — фишка без текстового эмодзи; стоит ПЕРВОЙ при малом числе,
    т.е. нарушает сортировку по убыванию => это не обычная реакция
    (вероятно, платные «звёзды»). rx_nostar = rx_fix без "?".
"""
import json, math, os, re, random
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from scipy import stats

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

MASS = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet",
        "trends", "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic"]
EXPERTS = ["xor_journal", "neuraldvig", "data_secrets", "seeallochnaya",
           "denissexy", "ai_newz", "cgevent", "NeuralShit",
           "ai_machinelearning_big_data", "tproger", "tlive"]
NO_RX = ["NeuralShit", "tlive"]          # блока реакций нет вовсе
# момент сбора: последний пост выборки 2026-09-30 11:30:37 UTC
T_REF = datetime(2026, 9, 30, 11, 35, tzinfo=timezone.utc)

K_KEY = re.compile(r"^(.*?)\s*([\d.,]+)\s*([KM])$")


def fix_break(br):
    """Вернуть (исправленный словарь, число K-фишек, флаг усечения custom)."""
    out, nk = {}, 0
    items = list(br.items())
    for k, v in items:
        m = K_KEY.match(k)
        if m:
            nk += 1
            emo = m.group(1).strip() or "?"
            val = float(m.group(2).replace(",", ".")) * (1e3 if m.group(3) == "K" else 1e6)
            out[emo] = out.get(emo, 0) + val
        else:
            out[k] = out.get(k, 0) + v
    trunc = False
    for i, (k, v) in enumerate(items):
        if k == "custom" and i + 1 < len(items) and v < items[i + 1][1]:
            trunc = True
    return out, nk, trunc


def load(include_norx=False):
    R = json.load(open(os.path.join(DATA, "reactions.json"), encoding="utf-8"))
    rows = []
    for ch, rec in R.items():
        if ch in NO_RX and not include_norx:
            continue
        subs = rec["subs"] or 0
        for p in rec["posts"]:
            if not p.get("dt") or not p["views"] or p["views"] <= 0:
                continue
            dt = datetime.fromisoformat(p["dt"].replace("Z", "+00:00"))
            txt = p["text"] or ""
            br_raw = p.get("rx_break") or {}
            br, nk, trunc = fix_break(br_raw)
            rx_fix = sum(br.values())
            star = br.get("?", 0)
            plain = {k: v for k, v in br.items() if k != "?"}
            rows.append({
                "ch": ch, "layer": "mass" if ch in MASS else "exp", "subs": subs,
                "id": p["id"], "dt": dt,
                "age": (T_REF - dt).total_seconds() / 86400,
                "views": float(p["views"]),
                "rx_raw": float(p["rx"] or 0), "rx": rx_fix,
                "rx_ns": rx_fix - star, "star": star,
                "votes": max(plain.values()) if plain else 0.0,
                "ntypes_raw": len(br_raw), "nk": nk, "trunc_custom": trunc,
                "br": br, "len": len(txt), "text": txt,
                "fwd": bool(p.get("fwd")), "media": bool(p.get("media")),
                "links": p.get("n_links", 0),
            })
    for r in rows:
        r["rxv"] = r["rx"] / r["views"] * 100
        r["rxv_raw"] = r["rx_raw"] / r["views"] * 100
        r["rx_1k"] = r["rx"] * 1000 / r["subs"] if r["subs"] else 0
        r["rx_1k_raw"] = r["rx_raw"] * 1000 / r["subs"] if r["subs"] else 0
        r["votes_1k"] = r["votes"] * 1000 / r["subs"] if r["subs"] else 0
        r["vps"] = r["views"] / r["subs"] if r["subs"] else 0
    return rows


def by_channel(rows):
    d = defaultdict(list)
    for r in rows:
        d[r["ch"]].append(r)
    for ch in d:
        d[ch].sort(key=lambda r: r["dt"])
    return d


def channel_freq(ps):
    dts = [r["dt"] for r in ps]
    span = (max(dts) - min(dts)).total_seconds() / 86400
    return len(ps) / (span + 1), span


# ------------------------------------------------------------------ статистика
def spearman(a, b):
    if len(a) < 4:
        return float("nan")
    r = stats.spearmanr(a, b).statistic
    return float(r)


def fisher_ci(r, n, z=1.959964):
    if n < 5 or abs(r) >= 1 or r != r:
        return (float("nan"), float("nan"))
    se = 1 / math.sqrt(n - 3)
    return math.tanh(math.atanh(r) - z * se), math.tanh(math.atanh(r) + z * se)


def boot_ci(fn, units, n_boot=2000, seed=1, alpha=.05):
    """Бутстрэп по единицам (каналам/сюжетам): fn(list_of_units)->float."""
    rng = random.Random(seed)
    ests = []
    for _ in range(n_boot):
        s = [units[rng.randrange(len(units))] for _ in units]
        v = fn(s)
        if v is not None and v == v:
            ests.append(v)
    ests.sort()
    if len(ests) < 50:
        return float("nan"), float("nan")
    return ests[int(alpha / 2 * len(ests))], ests[int((1 - alpha / 2) * len(ests)) - 1]


def bh(pvals):
    """Бенджамини-Хохберг: вернуть q в исходном порядке."""
    p = np.asarray(pvals, float)
    m = len(p)
    order = np.argsort(p)
    q = np.empty(m)
    prev = 1.0
    for rank in range(m - 1, -1, -1):
        i = order[rank]
        prev = min(prev, p[i] * m / (rank + 1))
        q[i] = prev
    return q


def cmh(tables):
    """Кохран-Мантель-Хензель для набора 2x2 [[a,b],[c,d]] (a: признак&топ).
    Возвращает (OR_MH, CI95, p)."""
    num = den = 0.0
    sa = se = sv = 0.0
    # Robins-Breslow-Greenland var for log OR
    P_R = P_S_Q_R = Q_S = 0.0
    sum_R = sum_S = 0.0
    for (a, b), (c, d) in tables:
        n = a + b + c + d
        if n == 0:
            continue
        R_ = a * d / n
        S_ = b * c / n
        P = (a + d) / n
        Q = (b + c) / n
        sum_R += R_
        sum_S += S_
        P_R += P * R_
        P_S_Q_R += P * S_ + Q * R_
        Q_S += Q * S_
        # CMH chi2
        e = (a + b) * (a + c) / n
        v = (a + b) * (c + d) * (a + c) * (b + d) / (n * n * (n - 1)) if n > 1 else 0
        sa += a
        se += e
        sv += v
    if sum_R == 0 or sum_S == 0:
        return float("nan"), (float("nan"), float("nan")), float("nan")
    orr = sum_R / sum_S
    var = P_R / (2 * sum_R ** 2) + P_S_Q_R / (2 * sum_R * sum_S) + Q_S / (2 * sum_S ** 2)
    lo = math.exp(math.log(orr) - 1.96 * math.sqrt(var))
    hi = math.exp(math.log(orr) + 1.96 * math.sqrt(var))
    chi2 = (abs(sa - se) - .5) ** 2 / sv if sv else float("nan")
    p = float(stats.chi2.sf(chi2, 1))
    return orr, (lo, hi), p


def top_low_pools(per, key="rxv", top_frac=.2, low_frac=.5, min_n=60):
    """Как в behaviour_within/stats_addendum: топ-20 % и низ-50 % по key в канале."""
    top, low = [], []
    for ch, ps in per.items():
        if len(ps) < min_n:
            continue
        s = sorted(ps, key=lambda r: -r[key])
        k = max(10, len(s) // 5)
        top += s[:k]
        low += s[int(len(s) * (1 - low_frac)):]
    return top, low


def fmt_ci(lo, hi, d=3):
    return f"[{lo:+.{d}f}, {hi:+.{d}f}]"
