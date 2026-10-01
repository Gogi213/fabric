"""R1–R2. Сводка по корпусу и типам каналов (таблица «Типы каналов» в research/R1-R2).

Вход: data/r/channels.json (tools/r1_channels.py profile), корпус.
Выход: печать + data/r/r1_summary.json.
"""
import json, os, statistics as st, sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from r_lib import ROOT, load, post_format  # noqa: E402

D = os.path.join(ROOT, "data", "r")
MEDIA = {"Медиа: AI и тех-новости", "Медиа: массовые тех-развлекательные", "Медиа: гаджеты и железо",
         "Apple и смартфоны (медиа и магазины)", "Медиа: кибербез и мошенничество"}
CH = json.load(open(os.path.join(D, "channels.json"), encoding="utf-8"))
C = load()

n_posts = sum(len(d["posts"]) for d in C.values())
fmt = Counter(post_format(p) for d in C.values() for p in d["posts"])
print(f"каналов {len(CH)}, постов {n_posts}, без веб-превью {sum(c['no_web_preview'] for c in CH)}")
print("форматы:", ", ".join(f"{k} {100 * v / n_posts:.0f} %" for k, v in fmt.most_common(8)))

by = defaultdict(list)
for c in CH:
    by[c["kind"]].append(c)
rows = []
print(f"\n{'тип':45s} {'n':>4s} {'подп':>6s} {'п/сут':>6s} {'просм/подп':>10s} {'видео':>6s} {'длина':>6s}")
for k, cs in sorted(by.items(), key=lambda x: -len(x[1])):
    med = lambda f: st.median([c[f] for c in cs if c.get(f) is not None] or [float("nan")])
    r = {"kind": k, "n": len(cs), "subs": med("subs"), "ppd": med("posts_per_day"), "er": med("er_views_subs"),
         "video": med("video_share"), "len": med("median_len")}
    rows.append(r)
    print(f"{k[:45]:45s} {r['n']:4d} {r['subs'] / 1e3:5.0f}K {r['ppd']:6.1f} {100 * r['er']:9.1f}% "
          f"{100 * r['video']:5.0f}% {r['len']:6.0f}")

# все каналы медиа-типов, как в таблице R1–R2; в R3 дополнительно исключены скидочные (deal_share ≥ 0.3)
media = [c for c in CH if c["kind"] in MEDIA]
n_media_r3 = sum((c.get("deal_share") or 0) < 0.3 for c in media)
stars = [c for c in media if c["paid_stars_14d"]]
print(f"\nканалов медиа-типов {len(media)} (без скидочных {n_media_r3}), подписок {sum(c['subs'] or 0 for c in media) / 1e6:.1f} млн; "
      f"со звёздами {len(stars)}, звёзд {sum(c['paid_stars_14d'] for c in media)}")
json.dump({"n_channels": len(CH), "n_posts": n_posts, "formats": dict(fmt), "kinds": rows,
           "n_media": len(media), "n_media_r3": n_media_r3, "media_subs": sum(c["subs"] or 0 for c in media),
           "media_with_stars": len(stars), "media_stars": sum(c["paid_stars_14d"] for c in media)},
          open(os.path.join(D, "r1_summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
