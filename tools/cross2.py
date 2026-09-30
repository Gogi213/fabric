import json, re, sys
from collections import defaultdict, Counter
from datetime import datetime, timedelta
import numpy as np
from sentence_transformers import SentenceTransformer

D = "C:/visual projects/parser/data/"
ru = json.load(open(D + "posts.json", encoding="utf-8"))
en = json.load(open(D + "posts_en.json", encoding="utf-8"))

def clean(t):
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"@\w+", " ", t)
    return " ".join(t.split())[:900]

posts = []
for lang, src in (("RU", ru), ("EN", en)):
    for ch, ps in src.items():
        for p in ps:
            if len(clean(p["text"])) < 40:
                continue
            posts.append({"lang": lang, "ch": ch, "id": p["id"], "dt": p["dt"],
                          "text": clean(p["text"]), "fwd": p["fwd_name"]})
def dt(s): return datetime.fromisoformat(s)

m = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
E = np.asarray(m.encode([p["text"] for p in posts], batch_size=64,
                       normalize_embeddings=True, show_progress_bar=False))
RU = [i for i, p in enumerate(posts) if p["lang"] == "RU"]
EN = [i for i, p in enumerate(posts) if p["lang"] == "EN"]

# --- 1. same-publisher bilingual pair: hiaimediaen / hiaimedia ---
print("=== A. ОДИН ИЗДАТЕЛЬ, ДВА ЯЗЫКА: @hiaimediaen -> @hiaimedia ===", file=sys.stderr)
A = [i for i in EN if posts[i]["ch"] == "hiaimediaen"]
B = [i for i in RU if posts[i]["ch"] == "hiaimedia"]
same = 0
rufirst = enfirst = 0
lags = []
for a in A:
    best = None
    for b in B:
        v = float(E[a] @ E[b])
        if best is None or v > best[0]:
            best = (v, b)
    if best and best[0] >= 0.80:
        v, b = best
        g = (dt(posts[b]["dt"]) - dt(posts[a]["dt"])).total_seconds() / 60
        same += 1
        lags.append(g)
        if g < 0:
            enfirst += 1
        else:
            rufirst += 1
        print(f"  sim={v:.3f} {'EN первый' if g<0 else 'RU первый'} на {abs(g):6.0f} мин", file=sys.stderr)
        print(f"     EN {posts[a]['dt'][5:16]}  {posts[a]['text'][:95]}", file=sys.stderr)
        print(f"     RU {posts[b]['dt'][5:16]}  {posts[b]['text'][:95]}", file=sys.stderr)
print(f"  ИТОГО пар: {same} из {len(A)} EN-постов | RU первый: {rufirst}, EN первый: {enfirst}",
      file=sys.stderr)

# --- 2. strict cross-border pairs: sim>=0.80, |gap|<=72h ---
print("\n=== B. ЖЁСТКИЙ КРОСС-БОРДЕР (sim>=0.80, |lag|<=72ч) ===", file=sys.stderr)
rows = []
seen = set()
for a in EN:
    for b in RU:
        v = float(E[a] @ E[b])
        if v < 0.80:
            continue
        g = (dt(posts[b]["dt"]) - dt(posts[a]["dt"])).total_seconds() / 60
        if abs(g) > 72 * 60:
            continue
        rows.append((v, g, posts[a], posts[b]))
        seen.add((posts[a]["ch"], posts[b]["ch"]))
rows.sort(key=lambda r: -r[0])
print(f"  найдено пар: {len(rows)}", file=sys.stderr)
cnt = Counter()
for v, g, pe, pr in rows:
    d = "EN->RU" if g > 0 else "RU->EN"
    cnt[(pe["ch"], pr["ch"], d)] += 1
for (e, r, d), n in cnt.most_common(30):
    print(f"  {e:24s} {d}  {r:24s} n={n}", file=sys.stderr)

# --- 3. same-story, who leads, per foreign channel ---
print("\n=== C. КТО ИЗ ЗАРУБЕЖНЫХ ВЕДЁТ РУССКИЕ (sim>=0.80, окно 72ч) ===", file=sys.stderr)
lead = defaultdict(lambda: {"en_first": 0, "ru_first": 0})
for v, g, pe, pr in rows:
    lead[pe["ch"]]["en_first" if g > 0 else "ru_first"] += 1
for c, d in sorted(lead.items(), key=lambda kv: -(kv[1]["en_first"] + kv[1]["ru_first"])):
    tot = d["en_first"] + d["ru_first"]
    print(f"  {c:26s} пар={tot:3d}  EN-первый={d['en_first']:3d} ({d['en_first']/tot*100:3.0f}%)  "
          f"RU-первый={d['ru_first']:3d}", file=sys.stderr)

# --- 4. RU channels that are downstream of ANY foreign channel ---
print("\n=== D. РУССКИЕ КАНАЛЫ-ПОЛУЧАТЕЛИ (хотя бы одна EN->RU пара) ===", file=sys.stderr)
down = Counter()
for v, g, pe, pr in rows:
    if g > 0:
        down[pr["ch"]] += 1
allru = Counter(p["ch"] for p in posts if p["lang"] == "RU")
for r, n in down.most_common():
    print(f"  {r:26s} {n:3d} пар из {allru[r]:3d} постов", file=sys.stderr)
print("  --- не получают НИ ОДНОЙ пары sim>=0.80: ---", file=sys.stderr)
for r, n in allru.most_common():
    if r not in down:
        print(f"  {r:26s} ({n} постов)", file=sys.stderr)

# --- 5. English-internal republication ---
print("\n=== E. ВНУТРИ АНГЛИЙСКОГО (sim>=0.80) ===", file=sys.stderr)
seen2 = set()
enpair = Counter(); enwin = Counter()
for a in range(len(EN)):
    for b in range(a+1, len(EN)):
        if posts[EN[a]]["ch"] == posts[EN[b]]["ch"]:
            continue
        v = float(E[EN[a]] @ E[EN[b]])
        if v >= 0.80:
            k = tuple(sorted((posts[EN[a]]["ch"], posts[EN[b]]["ch"])))
            if k in seen2:
                continue
            seen2.add(k)
            enpair[k] += 1
            enwin[posts[EN[a]]["ch"] if dt(posts[EN[a]]["dt"]) < dt(posts[EN[b]]["dt"])
                  else posts[EN[b]]["ch"]] += 1
for (a, b), n in enpair.most_common(12):
    print(f"  {a:24s} <-> {b:24s} {n}", file=sys.stderr)
print("  чаще всех был первым:", enwin.most_common(8), file=sys.stderr)

json.dump([{"sim": v, "gap_min": g, "en_ch": pe["ch"], "en_dt": pe["dt"],
            "en_text": pe["text"], "en_url": f"https://t.me/{pe['ch']}/{pe['id']}",
            "ru_ch": pr["ch"], "ru_dt": pr["dt"], "ru_text": pr["text"],
            "ru_url": f"https://t.me/{pr['ch']}/{pr['id']}", "ru_fwd": pr["fwd"]}
           for v, g, pe, pr in rows],
          open(D + "cross_strict.json", "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\nwrote cross_strict.json", file=sys.stderr)
