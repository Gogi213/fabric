"""Аудит «дизайн-эффект 1.04, 3980 сюжетов, 270 постов делят сюжет с другим каналом» (docs/09 §5, docs/10 §3.6).

1) воспроизведение кластеризации stats_audit.py (union-find по окну i..i+40 в порядке файла);
   сколько кластеров реально межканальные;
2) межканальная кластеризация по сюжету: пары постов разных каналов в окне 48 ч,
   общие «редкие» токены (df<=40) >= 3 и Jaccard(редкие) >= 0.3;
3) ICC внутриканального процентиля rx/views внутри сюжета и DEFF = 1 + (m-1)*ICC;
4) сюжетный бутстрэп для эффекта «релиз модели (строго)» и «короче 300».
Запуск: python tools/audit_behaviour_cluster.py
"""
import math, random, re, statistics as st
from collections import Counter, defaultdict
import numpy as np
from audit_behaviour_common import load, by_channel, top_low_pools

rows = load(include_norx=True)          # как stats_audit: 4124 поста
TOKS = re.compile(r"[a-zA-Zа-яА-ЯёЁ0-9]{3,}")

print("=== 1. Воспроизведение кластеризации stats_audit.py ===")
sets = [set(w.lower() for w in TOKS.findall(r["text"][:400])) for r in rows]
parent = list(range(len(rows)))
def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]; x = parent[x]
    return x
cross_pairs = same_pairs = 0
for i in range(len(rows)):
    for j in range(i + 1, min(i + 40, len(rows))):
        if not sets[i] or not sets[j]:
            continue
        inter = len(sets[i] & sets[j])
        if inter and inter / len(sets[i] | sets[j]) >= .5:
            if rows[i]["ch"] == rows[j]["ch"]:
                same_pairs += 1
            else:
                cross_pairs += 1
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj
cl = defaultdict(list)
for i in range(len(rows)):
    cl[find(i)].append(i)
multi = [v for v in cl.values() if len(v) > 1]
multich = [v for v in multi if len({rows[i]["ch"] for i in v}) > 1]
print(f"  кластеров {len(cl)}, многопостовых {len(multi)} ({sum(len(v) for v in multi)} постов), "
      f"из них межканальных {len(multich)}; связей внутри канала {same_pairs}, между каналами {cross_pairs}")
print(f"  доля пар (i,j<i+40) из разных каналов: "
      f"{sum(1 for i in range(len(rows)) for j in range(i+1, min(i+40, len(rows))) if rows[i]['ch']!=rows[j]['ch'])/sum(min(39, len(rows)-i-1) for i in range(len(rows)))*100:.1f}%")
print(f"  «дизайн-эффект» n/кластеров = {len(rows)/len(cl):.3f} — это не DEFF (нужен ICC)")

print("\n=== 2. Межканальная кластеризация по сюжету ===")
rows = load()                           # 20 каналов с реакциями
per = by_channel(rows)
STOP = set("""это как что для или при так уже все его она они был была были будет может
можно нужно чтобы когда если только также теперь сейчас этом этого которые который которая""".split())
tok = []
for r in rows:
    t = re.sub(r"https?://\S+|@\w+", " ", r["text"][:500].lower())
    tok.append({w for w in TOKS.findall(t) if w not in STOP})
df = Counter(w for s in tok for w in s)
rare = [{w for w in s if 2 <= df[w] <= 40} for s in tok]
order = sorted(range(len(rows)), key=lambda i: rows[i]["dt"])
parent = list(range(len(rows)))
links = 0
for a_i, i in enumerate(order):
    for j in order[a_i + 1:]:
        if (rows[j]["dt"] - rows[i]["dt"]).total_seconds() > 48 * 3600:
            break
        if rows[i]["ch"] == rows[j]["ch"]:
            continue
        inter = len(rare[i] & rare[j])
        if inter >= 3 and inter / len(rare[i] | rare[j]) >= .3:
            links += 1
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[ri] = rj
cl = defaultdict(list)
for i in range(len(rows)):
    cl[find(i)].append(i)
for k, v in cl.items():
    for i in v:
        rows[i]["story"] = k
multi = [v for v in cl.values() if len(v) > 1]
sizes = Counter(len(v) for v in cl.values())
print(f"  связей {links}; сюжетов {len(cl)}; межканальных {len(multi)} "
      f"({sum(len(v) for v in multi)} постов = {sum(len(v) for v in multi)/len(rows)*100:.1f}%); "
      f"макс размер {max(len(v) for v in cl.values())}; распределение {sorted(sizes.items())[:10]}")
rng = random.Random(5)
for v in rng.sample([v for v in multi if len(v) >= 3], 4):
    print("   пример:", " | ".join(f"{rows[i]['ch']}: {rows[i]['text'][:60]!r}" for i in v[:4]))

print("\n=== 3. ICC и DEFF ===")
for ch, ps in per.items():
    s = sorted(ps, key=lambda r: r["rxv"])
    for i, r in enumerate(s):
        r["pct"] = (i + .5) / len(s)
y = np.array([r["pct"] for r in rows])
groups = defaultdict(list)
for r in rows:
    groups[r["story"]].append(r["pct"])
# ANOVA ICC(1)
k = len(groups); N = len(rows)
gm = y.mean()
ssb = sum(len(g) * (np.mean(g) - gm) ** 2 for g in groups.values())
ssw = sum(((np.array(g) - np.mean(g)) ** 2).sum() for g in groups.values())
msb = ssb / (k - 1); msw = ssw / (N - k)
n0 = (N - sum(len(g) ** 2 for g in groups.values()) / N) / (k - 1)
icc = (msb - msw) / (msb + (n0 - 1) * msw)
mbar = sum(len(g) ** 2 for g in groups.values()) / N
print(f"  ICC(процентиль rx/views | сюжет) = {icc:.3f}; средний размер кластера (взвеш.) {mbar:.2f}; "
      f"DEFF = 1+(m-1)ICC = {1 + (mbar-1)*icc:.3f}")

print("\n=== 4. Сюжеты у темы «релиз модели (строго)» ===")
MODEL = (r"модел|model|\bllm|gpt-?\s?\d|\bclaude|\bopus|\bsonnet|\bfable|\bgemini|\bgemma|llama|"
         r"\bqwen|deepseek|\bgrok|mistral|\bkimi|minimax|\bglm|\bвеса\b|нейронк|нейросет")
VERB = (r"выпуст|релиз|представил|анонсир|выкатил|выложил|вышл[аи]\b|вышел\b|запустил|"
        r"опубликовал|дропнул|показал")
rel = [r for r in rows if re.search(MODEL, r["text"][:350], re.I) and re.search(VERB, r["text"][:350], re.I)]
st_rel = Counter(r["story"] for r in rel)
print(f"  постов {len(rel)}, сюжетов {len(st_rel)}, в межканальных сюжетах "
      f"{sum(1 for r in rel if len(cl[r['story']])>1)} ({sum(1 for r in rel if len(cl[r['story']])>1)/len(rel)*100:.0f}%)")
print(f"  средний процентиль rx/views: релиз {st.mean(r['pct'] for r in rel):.3f} vs прочие "
      f"{st.mean(r['pct'] for r in rows if r not in rel):.3f}")
# сюжетный бутстрэп разницы средних процентилей
relset = {id(r) for r in rel}
stories = list(cl.values())
bs = []
for _ in range(2000):
    pick = [stories[rng.randrange(len(stories))] for _ in stories]
    a = [rows[i]["pct"] for v in pick for i in v if id(rows[i]) in relset]
    b = [rows[i]["pct"] for v in pick for i in v if id(rows[i]) not in relset]
    bs.append(st.mean(a) - st.mean(b))
bs.sort()
print(f"  разница процентилей {st.mean(r['pct'] for r in rel) - st.mean(r['pct'] for r in rows if id(r) not in relset):+.3f} "
      f"сюжетный бутстрэп [{bs[50]:+.3f}, {bs[1949]:+.3f}]")
# внутри межканальных сюжетов: ранний vs поздний пост сюжета (гипотеза «все уже видели»)
early, late = [], []
for v in multi:
    s = sorted(v, key=lambda i: rows[i]["dt"])
    early.append(rows[s[0]]["pct"])
    late += [rows[i]["pct"] for i in s[1:]]
print(f"  межканальные сюжеты: первый пост процентиль {st.mean(early):.3f} (n={len(early)}), "
      f"последующие {st.mean(late):.3f} (n={len(late)})")
