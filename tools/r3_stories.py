"""R3. Сюжеты, граф перепостов, скорость.

1. Посты (≥50 символов после очистки, без рекламной маркировки) → эмбеддинги
   paraphrase-multilingual-MiniLM-L12-v2 (кэш data/r/emb_*.npy).
2. Пары постов РАЗНЫХ каналов в пределах 72 ч с косинусом ≥ PAIR_SIM → рёбра.
   Для каждой пары — дословность: Жаккар по словесным 3-шинглам.
3. Сюжеты: union-find по рёбрам с косинусом ≥ STORY_SIM и разрывом ≤ 48 ч.
4. Для каждого поста сюжета, кроме первого, «родитель» — более ранний пост с максимальным
   косинусом. Ребро родитель→пост = кандидат в перепост (не доказательство: общий
   первоисточник даёт ту же картину; дословность J ≥ 0.5 — сильный признак копии).
5. Скорость: для сюжетов в ≥3 каналах — кто первый, отставание каждого канала от первого.

Запуск:  python tools/r3_stories.py [--calibrate]
Выход:   data/r/stories.json, data/r/copy_edges.json, data/r/speed.json
"""
import hashlib, json, os, random, re, statistics as st, sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT, clean, is_marked_ad, load  # noqa: E402

D = os.path.join(ROOT, "data", "r")
PAIR_SIM, STORY_SIM = 0.75, 0.80   # калибровка 30.09: 0.80–0.90 — 24/24 та же новость, 0.75–0.80 — ~9/12
WIN_H, STORY_H = 72, 48


def shingles(t, n=3):
    w = re.findall(r"[a-zа-яё0-9]+", t.lower())
    return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}


def jacc(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0


def embed(posts):
    from sentence_transformers import SentenceTransformer
    keys = [f"{p['_ch']}/{p['id']}" for p in posts]
    cache_k = os.path.join(D, "emb_keys.json")
    cache_v = os.path.join(D, "emb_vecs.npy")
    known = {}
    if os.path.exists(cache_k):
        ks = json.load(open(cache_k))
        V = np.load(cache_v)
        known = {k: V[i] for i, k in enumerate(ks)}
    todo = [i for i, k in enumerate(keys) if k not in known]
    if todo:
        m = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        E = m.encode([posts[i]["_clean"][:600] for i in todo], batch_size=128,
                     normalize_embeddings=True, show_progress_bar=False)
        for i, e in zip(todo, E):
            known[keys[i]] = e
        ks = list(known)
        np.save(cache_v, np.stack([known[k] for k in ks]).astype(np.float32))
        json.dump(ks, open(cache_k, "w"))
    return np.stack([known[k] for k in keys]).astype(np.float32)


def main():
    C = load()
    posts = []
    for ch, d in C.items():
        for p in d["posts"]:
            c = clean(p.get("text"), ch)
            if len(c) < 50 or not p["_t"] or is_marked_ad(p):
                continue
            p["_clean"] = c
            posts.append(p)
    posts.sort(key=lambda p: p["_t"])
    print(f"каналов {len(C)}, постов в анализе {len(posts)}", file=sys.stderr)
    E = embed(posts)
    T = np.array([p["_t"].timestamp() for p in posts])
    CH = np.array([p["_ch"] for p in posts])
    SH = [shingles(p["_clean"]) for p in posts]

    # пары в окне 72 ч, блоками
    edges = []
    B = 2000
    for a in range(0, len(posts), B):
        b = min(a + B, len(posts))
        hi = np.searchsorted(T, T[b - 1] + WIN_H * 3600, side="right")
        S = E[a:b] @ E[a:hi].T
        ii, jj = np.where(S >= PAIR_SIM)
        for i, j in zip(ii, jj):
            gi, gj = a + i, a + j
            if gj <= gi or CH[gi] == CH[gj] or T[gj] - T[gi] > WIN_H * 3600:
                continue
            edges.append((gi, gj, float(S[i, j])))
    print(f"пар ≥{PAIR_SIM}: {len(edges)}", file=sys.stderr)

    if "--calibrate" in sys.argv:
        rnd = random.Random(1)
        for lo, hi_ in [(0.75, 0.80), (0.80, 0.85), (0.85, 0.90), (0.90, 1.01)]:
            sel = [e for e in edges if lo <= e[2] < hi_]
            print(f"\n### [{lo}; {hi_}) пар {len(sel)}")
            for i, j, s in rnd.sample(sel, min(12, len(sel))):
                print(f"  [{s:.3f} J={jacc(SH[i], SH[j]):.2f}] @{CH[i]}: {posts[i]['_clean'][:110]}")
                print(f"                @{CH[j]}: {posts[j]['_clean'][:110]}")
        return

    # сюжеты
    par = list(range(len(posts)))

    def f(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for i, j, s in edges:
        if s >= STORY_SIM and T[j] - T[i] <= STORY_H * 3600:
            par[f(i)] = f(j)
    groups = defaultdict(list)
    for i in range(len(posts)):
        groups[f(i)].append(i)
    sim = {(i, j): s for i, j, s in edges}
    stories, copy_edges = [], []
    for g in groups.values():
        chs = {CH[i] for i in g}
        if len(chs) < 2:
            continue
        g.sort(key=lambda i: T[i])
        first = g[0]
        members = []
        for k, j in enumerate(g):
            parent, ps = None, 0.0
            for i in g[:k]:
                s = sim.get((i, j), 0.0)
                if CH[i] != CH[j] and s > ps:
                    parent, ps = i, s
            members.append({"ch": CH[j], "id": posts[j]["id"], "t": posts[j]["dt"],
                            "lag_min": round((T[j] - T[first]) / 60, 1),
                            "fwd": posts[j].get("fwd_name"), "views": posts[j].get("views"),
                            "rx": posts[j].get("rx_total")})
            if parent is not None:
                copy_edges.append({"from": CH[parent], "to": CH[j], "lag_min": round((T[j] - T[parent]) / 60, 1),
                                   "sim": round(ps, 3), "J": round(jacc(SH[parent], SH[j]), 3),
                                   "fwd": bool(posts[j].get("fwd_name"))})
        stories.append({"n_posts": len(g), "n_ch": len(chs), "first_ch": CH[first], "first_t": posts[first]["dt"],
                        "text": posts[first]["_clean"][:300], "members": members})
    stories.sort(key=lambda s: -s["n_ch"])
    print(f"сюжетов в ≥2 каналах: {len(stories)}; в ≥3: {sum(s['n_ch'] >= 3 for s in stories)}", file=sys.stderr)

    # скорость по каналам (сюжеты ≥3 каналов; один пост на канал — самый ранний)
    part, first, lags, ranks = Counter(), Counter(), defaultdict(list), defaultdict(list)
    for s in stories:
        if s["n_ch"] < 3:
            continue
        seen = {}
        for m in s["members"]:
            seen.setdefault(m["ch"], m["lag_min"])
        order = sorted(seen.items(), key=lambda x: x[1])
        for r, (ch, lag) in enumerate(order):
            part[ch] += 1
            lags[ch].append(lag)
            ranks[ch].append(r / (len(order) - 1))
        first[order[0][0]] += 1
    speed = [{"ch": ch, "stories": n, "first": first[ch], "first_share": round(first[ch] / n, 3),
              "median_lag_min": st.median(lags[ch]), "median_rank01": round(st.median(ranks[ch]), 3),
              "subs": (C[ch]["meta"] or {}).get("counters", {}).get("subscribers")}
             for ch, n in part.items()]
    speed.sort(key=lambda r: (-r["stories"]))

    json.dump(stories, open(os.path.join(D, "stories.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(copy_edges, open(os.path.join(D, "copy_edges.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump(speed, open(os.path.join(D, "speed.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("saved stories.json, copy_edges.json, speed.json", file=sys.stderr)


if __name__ == "__main__":
    main()
