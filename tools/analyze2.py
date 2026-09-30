import json, re, sys
from collections import defaultdict, Counter
from datetime import datetime
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

P = "C:/visual projects/parser/data/posts.json"
data = json.load(open(P, encoding="utf-8"))

# ---------- normalize ----------
def norm(t):
    t = t.lower()
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[^0-9a-zа-яё]+", " ", t)
    return " ".join(t.split())

posts = []
for ch, ps in data.items():
    for p in ps:
        n = norm(p["text"])
        if len(n) < 20:
            continue
        posts.append({"ch": ch, "id": p["id"], "dt": p["dt"], "text": p["text"],
                      "n": n, "fwd": p["fwd_name"]})
print(f"posts with text: {len(posts)}", file=sys.stderr)

def dt(p): return datetime.fromisoformat(p["dt"])
def canon(ch):
    return "technomedia/tehnochat" if ch in ("technomedia", "tehnochat") else ch
for p in posts:
    p["c"] = canon(p["ch"])
chs = sorted({p["c"] for p in posts})

# ---------- similarity: tfidf cosine (catches rewrites) ----------
vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=1,
                      sublinear_tf=True, max_features=200000)
X = vec.fit_transform([p["n"] for p in posts])
from sklearn.preprocessing import normalize
X = normalize(X)

best = {}
S = (X @ X.T).toarray()
np.fill_diagonal(S, 0.0)
for i in range(len(posts)):
    for j in range(i+1, len(posts)):
        if posts[i]["c"] == posts[j]["c"]:
            S[i, j] = S[j, i] = 0.0
        else:
            v = S[i, j]
            if v > best.get((i, j), 0):
                best[(i, j)] = v

# ---------- exact/verbatim layer ----------
def sh(t, n=3):
    w = t.split()
    return set(" ".join(w[i:i+n]) for i in range(max(0, len(w)-n+1)))
for p in posts:
    p["S"] = sh(p["n"])
inv = defaultdict(list)
for i, p in enumerate(posts):
    for s in p["S"]:
        inv[s].append(i)
def jac(a, b):
    return len(a & b) / (len(a) + len(b) - len(a & b)) if a and b else 0.0
verbatim = set()
for s, idxs in inv.items():
    if len(idxs) > 40:
        continue
    for a in range(len(idxs)):
        for b in range(a+1, len(idxs)):
            i, j = idxs[a], idxs[b]
            if posts[i]["c"] == posts[j]["c"]:
                continue
            if jac(posts[i]["S"], posts[j]["S"]) >= 0.55:
                verbatim.add((min(i, j), max(i, j)))

# ---------- clusters from topic edges (sim >= 0.42) ----------
par = list(range(len(posts)))
def find(x):
    while par[x] != x:
        par[x] = par[par[x]]; x = par[x]
    return x
def uni(a, b):
    ra, rb = find(a), find(b)
    if ra != rb: par[rb] = ra

topic_edges = {}
for (i, j), v in best.items():
    if v >= 0.42:
        topic_edges[(i, j)] = v
        uni(i, j)
clusters = defaultdict(list)
for i in range(len(posts)):
    clusters[find(i)].append(i)
clusters = {k: v for k, v in clusters.items() if len(v) >= 2}
print(f"clusters: {len(clusters)}  topic edges: {len(topic_edges)}  verbatim pairs: {len(verbatim)}",
      file=sys.stderr)

def cluster_info(idxs):
    ps = sorted([posts[i] for i in idxs], key=dt)
    first = ps[0]
    span = (dt(ps[-1]) - dt(first)).total_seconds()/60
    vb = any((min(a,b),max(a,b)) in verbatim for a in idxs for b in idxs if a!=b)
    return first, span, {p["c"] for p in ps}, vb, ps

rows = []
for idxs in clusters.values():
    first, span, cs, vb, ps = cluster_info(idxs)
    rows.append({"first": first, "span": span, "ch": cs, "vb": vb, "ps": ps})
rows.sort(key=lambda r: dt(r["first"]), reverse=True)

# ---------- per-channel overlap ----------
dup = Counter(); tot = Counter()
for p in posts:
    tot[p["c"]] += 1
for r in rows:
    for c in r["ch"]:
        dup[c] += 1

print("\n=== ДОЛЯ ПОСТОВ, ПЕРЕПИСАННЫХ/СОВПАДАЮЩИХ С ДРУГИМ КАНАЛОМ ===", file=sys.stderr)
for c in sorted(chs, key=lambda c: -(dup[c]/max(tot[c],1))):
    t = tot[c]
    if t:
        print(f"  {c:26s} {dup[c]:4d}/{t:4d} = {dup[c]/t*100:5.1f}%", file=sys.stderr)

# ---------- pairwise ----------
pc = Counter()
for r in rows:
    ks = sorted(r["ch"])
    for a in range(len(ks)):
        for b in range(a+1, len(ks)):
            pc[(ks[a], ks[b])] += 1
print("\n=== ПАРНЫЕ СОВПАДЕНИЯ (сколько общих тем за неделю) ===", file=sys.stderr)
for (a, b), c in pc.most_common(40):
    print(f"  {a:26s} <-> {b:26s} {c}", file=sys.stderr)

# ---------- forward map ----------
print("\n=== АТРИБУЦИЯ TELEGRAM ('Переслано от') ===", file=sys.stderr)
fb = defaultdict(Counter)
for p in posts:
    if p["fwd"]:
        fb[p["c"]][p["fwd"]] += 1
for c in sorted(fb, key=lambda c: -sum(fb[c].values())):
    print(f"  {c}:", file=sys.stderr)
    for s, k in fb[c].most_common():
        print(f"      <- {s:34s} {k}", file=sys.stderr)

# ---------- who-first table ----------
print("\n=== КТО ПЕРВЫЙ В КЛАСТЕРЕ (первые 60) ===", file=sys.stderr)
firstcount = Counter()
for r in rows:
    firstcount[r["first"]["c"]] += 1
for c, k in firstcount.most_common():
    print(f"  {c:26s} {k}", file=sys.stderr)

json.dump({
    "n_posts": len(posts), "channels": dict(tot),
    "dup": dict(dup),
    "pairwise": [{"a": a, "b": b, "n": n} for (a, b), n in pc.most_common()],
    "forwards": {c: dict(v) for c, v in fb.items()},
    "clusters": [{
        "first": {"ch": r["first"]["c"], "dt": r["first"]["dt"],
                  "text": r["first"]["text"][:300],
                  "fwd": r["first"]["fwd"],
                  "url": f"https://t.me/{r['first']['ch']}/{r['first']['id']}"},
        "span_min": round(r["span"], 1), "n_ch": len(r["ch"]), "verbatim": r["vb"],
        "members": [{"ch": p["c"], "dt": p["dt"], "fwd": p["fwd"],
                     "text": p["text"][:180],
                     "url": f"https://t.me/{p['ch']}/{p['id']}"} for p in r["ps"]],
    } for r in rows],
}, open("C:/visual projects/parser/data/clusters.json", "w",
        encoding="utf-8"), ensure_ascii=False, indent=1)
print("\nwrote clusters.json", file=sys.stderr)
