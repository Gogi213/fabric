"""R4. Темы для сюжетов, которых нет в типологии (после дособора каналов у сюжета мог смениться первый пост).

Типология (16 тем) построена KMeans по эмбеддингам первых постов сюжетов и названа вручную
(data/r/story_topics_raw.json + story_topic_names.json). Перекластеризация сбила бы названия, поэтому
сюжет без темы получает тему с ближайшим по косинусу центроидом.

Запуск: python tools/r4_topics_assign.py   (после r3_stories.py и r4_origins.py)
"""
import json, os, sys
from collections import Counter

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT  # noqa: E402

D = os.path.join(ROOT, "data", "r")
P = os.path.join(D, "story_topics_raw.json")
T = json.load(open(P, encoding="utf-8"))
keys = json.load(open(os.path.join(D, "emb_keys.json")))
V = np.load(os.path.join(D, "emb_vecs.npy"))
idx = {k: i for i, k in enumerate(keys)}

cent = {}
for lab in set(T["labels"]):
    rows = [idx[a] for a, l in zip(T["anchors"], T["labels"]) if l == lab and a in idx]
    v = V[rows].mean(0)
    cent[lab] = v / np.linalg.norm(v)

have = set(T["anchors"])
new = []
for s in json.load(open(os.path.join(D, "origins.json"), encoding="utf-8")):
    a = f"{s['members'][0]['ch']}/{s['members'][0]['id']}"
    if a not in have and a in idx:
        have.add(a)
        lab = max(cent, key=lambda c: float(V[idx[a]] @ cent[c]))
        T["anchors"].append(a)
        T["labels"].append(lab)
        T["n_media"].append(None)
        new.append(lab)
T["assigned_later"] = T.get("assigned_later", 0) + len(new)
json.dump(T, open(P, "w", encoding="utf-8"), ensure_ascii=False)
print(f"сюжетов отнесено к темам: {len(new)}; по темам: {Counter(new).most_common()}")
