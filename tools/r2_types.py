"""R2. Вид (формат) и тип поста.

Вид — по содержимому (tools/r_lib.post_format): текст, фото, альбом, видео, форвард, опрос…
Тип — смысловая роль поста; кодбук:
  NEWS    — сообщение о событии: релиз, анонс, сделка, закон, инцидент, утечка, исследование;
  TOOL    — находка/подборка сервиса, приложения, репозитория, промпта, лайфхака («нашли», «полезное»);
  EXPLAIN — авторский разбор, гайд, объяснение, мнение, аналитика, обзор устройства;
  MEME    — юмор, мем, вирусное видео или курьёз без новостной ценности;
  DIGEST  — подборка нескольких новостей в одном посте;
  PROMO   — реклама (маркированная или явная), продвижение чужого канала/продукта;
  SELF    — свой контент/мероприятие/розыгрыш/опрос/служебное объявление канала.

Режимы:
  python tools/r2_types.py sample N   → data/r/label_sample.jsonl (стратифицировано по каналам) для ручной разметки
  python tools/r2_types.py train      → обучение на data/r/labels.jsonl, кросс-валидация, разметка корпуса
  python tools/r2_types.py formats    → распределение видов постов
"""
import json, os, random, sys
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT, clean, is_marked_ad, load, post_format  # noqa: E402

D = os.path.join(ROOT, "data", "r")
TYPES = ["NEWS", "TOOL", "EXPLAIN", "MEME", "DIGEST", "PROMO", "SELF"]


def cmd_sample(n):
    C = load()
    rnd = random.Random(42)
    chans = list(C)
    rnd.shuffle(chans)
    out, per = [], max(1, n // max(1, len(chans)))
    pool = []
    for ch in chans:
        ps = [p for p in C[ch]["posts"] if (p.get("text") or "").strip()]
        rnd.shuffle(ps)
        pool.extend(ps[:max(per, 1)])
    rnd.shuffle(pool)
    for p in pool[:n]:
        out.append({"key": f"{p['_ch']}/{p['id']}", "fmt": post_format(p), "ad": is_marked_ad(p),
                    "text": (p.get("text") or "")[:500]})
    with open(os.path.join(D, "label_sample.jsonl"), "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"sample {len(out)} из {len(C)} каналов", file=sys.stderr)


def cmd_formats():
    C = load()
    cnt, per = Counter(), defaultdict(Counter)
    for ch, d in C.items():
        for p in d["posts"]:
            f = post_format(p)
            cnt[f] += 1
            per[ch][f] += 1
    tot = sum(cnt.values())
    print(f"постов {tot}, каналов {len(C)}")
    for f, n in cnt.most_common():
        shares = [per[ch][f] / sum(per[ch].values()) for ch in per if sum(per[ch].values()) >= 10]
        print(f"  {f:22s}{n:7d} {100 * n / tot:5.1f} %   медиана доли по каналам {100 * np.median(shares):5.1f} %")


def features(posts):
    from sentence_transformers import SentenceTransformer
    m = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    E = m.encode([clean(p.get("text"), p["_ch"])[:600] or "-" for p in posts], batch_size=128,
                 normalize_embeddings=True, show_progress_bar=False)
    fmts = ["текст", "фото", "альбом", "видео", "форвард", "опрос", "текст + превью ссылки"]
    X2 = np.array([[post_format(p) == f for f in fmts] + [is_marked_ad(p), len(p.get("text") or "") / 1000,
                    len(p.get("links") or []) / 5] for p in posts], dtype=np.float32)
    return np.hstack([E, X2])


def cmd_train():
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import classification_report
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    C = load()
    idx = {f"{p['_ch']}/{p['id']}": p for d in C.values() for p in d["posts"]}
    lab = [json.loads(l) for l in open(os.path.join(D, "labels.jsonl"), encoding="utf-8")]
    lab = [r for r in lab if r["key"] in idx and r["type"] in TYPES]
    P = [idx[r["key"]] for r in lab]
    y = np.array([r["type"] for r in lab])
    X = features(P)
    clf = LogisticRegression(max_iter=3000, C=2.0, class_weight="balanced")
    pred = cross_val_predict(clf, X, y, cv=StratifiedKFold(5, shuffle=True, random_state=0))
    rep = classification_report(y, pred, digits=2, zero_division=0)
    print(rep)
    clf.fit(X, y)
    allp = [p for d in C.values() for p in d["posts"] if (p.get("text") or "").strip() or p.get("media")]
    Xa = features(allp)
    pa = clf.predict(Xa)
    prob = clf.predict_proba(Xa).max(1)
    out = {f"{p['_ch']}/{p['id']}": [t, round(float(q), 3)] for p, t, q in zip(allp, pa, prob)}
    json.dump(out, open(os.path.join(D, "post_types.json"), "w", encoding="utf-8"), ensure_ascii=False)
    json.dump({"report": rep, "n_labels": len(lab), "labels_by_type": Counter(y.tolist())},
              open(os.path.join(D, "post_types_eval.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("saved post_types.json", Counter(pa.tolist()), file=sys.stderr)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[0] == "sample":
        cmd_sample(int(a[1]))
    elif a[0] == "train":
        cmd_train()
    elif a[0] == "formats":
        cmd_formats()
