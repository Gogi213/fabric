"""R1. Профиль и тип каждого собранного канала.

Тип канала: центроид эмбеддингов его постов → KMeans → кластеры, которые называются вручную
по заголовкам и примерам (файл data/r/channel_cluster_names.json, ключ — номер кластера).
Плюс признаки: язык, частота, просмотры, ER, доля рекламы, доля скидочных партнёрских ссылок,
доля форвардов, доля видео, медианная длина, оформление (капс, эмодзи).

Запуск:  python tools/r1_channels.py clusters K   → печать кластеров для ручного именования
         python tools/r1_channels.py profile      → data/r/channels.json (с именами кластеров)
"""
import json, os, re, statistics as st, sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT, clean, is_marked_ad, load, post_format  # noqa: E402

D = os.path.join(ROOT, "data", "r")
DEAL = re.compile(r"(ali\.click|aliexpress|market\.yandex|ozon\.ru/t/|wildberries|wb\.ru|%d0%90%d0%9b%d0%98)", re.I)
CAPS = re.compile(r"\b[А-ЯЁA-Z]{4,}\b")
EMO = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def channel_vectors(C):
    keys = json.load(open(os.path.join(D, "emb_keys.json")))
    V = np.load(os.path.join(D, "emb_vecs.npy"))
    idx = {k: i for i, k in enumerate(keys)}
    out = {}
    for ch, d in C.items():
        rows = [idx[f"{ch}/{p['id']}"] for p in d["posts"] if f"{ch}/{p['id']}" in idx]
        if len(rows) >= 3:
            v = V[rows].mean(0)
            out[ch] = v / np.linalg.norm(v)
    return out


def profile(ch, d):
    ps = d["posts"]
    m = (d["meta"] or {})
    subs = m.get("counters", {}).get("subscribers")
    views = [p["views"] for p in ps if p.get("views")]
    txt = " ".join(p.get("text") or "" for p in ps)
    letters = re.findall(r"[A-Za-zА-Яа-яЁё]", txt)
    cyr = sum(1 for c in letters if re.match(r"[А-Яа-яЁё]", c)) / len(letters) if letters else None
    span_days = 14.0
    lens = [len(p.get("text") or "") for p in ps]
    rx = [p["rx_total"] / p["views"] for p in ps if p.get("views") and p.get("has_rx_block")]
    return {
        "handle": ch, "title": m.get("title"), "description": (m.get("description") or "")[:300],
        "subs": subs, "posts_14d": len(ps), "posts_per_day": round(len(ps) / span_days, 2),
        "median_views": st.median(views) if views else None,
        "er_views_subs": round(st.median(views) / subs, 4) if views and subs else None,
        "rx_per_view": round(st.median(rx), 5) if rx else None,
        "cyr_share": round(cyr, 3) if cyr is not None else None,
        "ad_share": round(sum(is_marked_ad(p) for p in ps) / len(ps), 3) if ps else None,
        "deal_share": round(sum(any(DEAL.search(u) for u, _ in p.get("links") or []) for p in ps) / len(ps), 3) if ps else None,
        "fwd_share": round(sum(bool(p.get("fwd_name")) for p in ps) / len(ps), 3) if ps else None,
        "video_share": round(sum(post_format(p) in ("видео", "альбом (с видео)", "кружок") for p in ps) / len(ps), 3) if ps else None,
        "median_len": st.median(lens) if lens else None,
        "caps_per_post": round(sum(len(CAPS.findall(p.get("text") or "")) for p in ps) / len(ps), 2) if ps else None,
        "emoji_per_post": round(sum(len(EMO.findall(p.get("text") or "")) for p in ps) / len(ps), 2) if ps else None,
        "paid_stars_14d": sum(p.get("rx_paid_stars") or 0 for p in ps),
        "no_web_preview": d["crawl"]["stop"] == "no_web_preview",
    }


def main():
    from sklearn.cluster import KMeans
    C = load()
    cv = channel_vectors(C)
    hs = sorted(cv)
    X = np.stack([cv[h] for h in hs])
    mode = sys.argv[1]
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
    lab = dict(zip(hs, km.labels_.tolist()))
    if mode == "clusters":
        for c in range(k):
            mem = [h for h in hs if lab[h] == c]
            mem.sort(key=lambda h: -((C[h]["meta"] or {}).get("counters", {}).get("subscribers") or 0))
            print(f"\n### кластер {c}: {len(mem)} каналов")
            for h in mem[:10]:
                t = (C[h]["meta"] or {}).get("title") or ""
                ex = next((clean(p.get("text"))[:90] for p in C[h]["posts"] if len(clean(p.get("text"))) > 40), "")
                print(f"  @{h:24s} {t[:30]:30s} | {ex}")
        json.dump({"k": k, "labels": lab}, open(os.path.join(D, "channel_clusters.json"), "w"))
        return
    names = json.load(open(os.path.join(D, "channel_cluster_names.json"), encoding="utf-8"))
    cl = json.load(open(os.path.join(D, "channel_clusters.json")))["labels"]
    out = []
    for ch, d in C.items():
        p = profile(ch, d)
        p["cluster"] = cl.get(ch)
        p["kind"] = names.get(str(cl.get(ch)), "не определён (мало постов)")
        out.append(p)
    json.dump(out, open(os.path.join(D, "channels.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(Counter(p["kind"] for p in out).most_common())


if __name__ == "__main__":
    main()
