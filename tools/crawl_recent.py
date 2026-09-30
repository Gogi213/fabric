"""Свежий сбор постов RU-каналов за последние N суток (для сопоставления с фидами).

Отличия от crawl.py / crawl_links.py:
  * пути относительные;
  * сохраняются и посты БЕЗ текста (флаг has_text), чтобы считать полноту;
  * сохраняются медиа-флаг, ссылки, форвард, просмотры;
  * строго последовательно, пауза 2 с (параллелизм ломает вёрстку t.me, docs/06 §2.8).

Запуск:  python tools/crawl_recent.py [DAYS=4]  ->  data/recent_posts.json
"""
import json, os, re, sys, time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "recent_posts.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
RU = ["whackdoor", "bugnotfeature", "technomedia", "exploitex", "naebnet", "trends",
      "technomotel", "hiaimedia", "rozetked", "d_code", "gptpublic", "xor_journal",
      "neuraldvig", "data_secrets", "seeallochnaya", "denissexy", "ai_newz", "cgevent",
      "NeuralShit", "ai_machinelearning_big_data", "tproger", "tlive"]
DAYS = float(sys.argv[1]) if len(sys.argv) > 1 else 4.0
SINCE = datetime.now(timezone.utc) - timedelta(days=DAYS)

S = requests.Session()
S.headers["User-Agent"] = UA


def fetch(ch, max_pages=30):
    posts, before = {}, None
    subs = None
    for _ in range(max_pages):
        url = f"https://t.me/s/{ch}" + (f"?before={before}" if before else "")
        r = S.get(url, timeout=30)
        time.sleep(2.0)
        if r.status_code != 200:
            print(f"  ! {ch} HTTP {r.status_code}", file=sys.stderr)
            break
        soup = BeautifulSoup(r.text, "html.parser")
        if subs is None:
            c = soup.select_one(".tgme_channel_info_counter .counter_value")
            subs = c.get_text(strip=True) if c else None
        wraps = soup.select("div.tgme_widget_message[data-post]")
        if not wraps:
            break
        dts = []
        for w in wraps:
            pid = w["data-post"].split("/")[-1]
            if not pid.isdigit():
                continue
            t = w.select_one("time[datetime]")
            if not t:
                continue
            dt = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00"))
            dts.append(dt)
            body = w.select_one("div.js-message_text")
            txt = body.get_text(" ", strip=True) if body else ""
            links = [a["href"] for a in body.find_all("a", href=True)
                     if a["href"].startswith("http")] if body else []
            fwd = w.select_one("a.tgme_widget_message_forwarded_from_name")
            fwd_div = w.select_one(".tgme_widget_message_forwarded_from")
            v = w.select_one("span.tgme_widget_message_views")
            posts[int(pid)] = {
                "id": int(pid), "dt": dt.isoformat(), "text": txt, "has_text": bool(txt),
                "links": links,
                "fwd_url": fwd.get("href", "") if fwd else "",
                "fwd_name": (fwd.get_text(strip=True) if fwd else
                             (fwd_div.get_text(" ", strip=True).replace("Forwarded from", "").strip()
                              if fwd_div else "")),
                "media": bool(w.select_one(".tgme_widget_message_photo_wrap, video, "
                                           ".tgme_widget_message_video_player, "
                                           ".tgme_widget_message_document")),
                "views": v.get_text(strip=True) if v else "",
            }
        ids = [int(w["data-post"].split("/")[-1]) for w in wraps
               if w["data-post"].split("/")[-1].isdigit()]
        if not ids or (before and min(ids) >= before):
            break
        before = min(ids)
        if dts and min(dts) < SINCE:
            break
    keep = [p for p in posts.values() if datetime.fromisoformat(p["dt"]) >= SINCE]
    return sorted(keep, key=lambda p: p["id"]), subs


if __name__ == "__main__":
    out = {"_meta": {"since": SINCE.isoformat(), "fetched": datetime.now(timezone.utc).isoformat()}}
    for ch in RU:
        ps, subs = fetch(ch)
        ids = [p["id"] for p in ps]
        rng = (max(ids) - min(ids) + 1) if ids else 0
        out[ch] = {"subs": subs, "posts": ps}
        print(f"  {ch:30s} постов {len(ps):4d} (с текстом {sum(p['has_text'] for p in ps):4d}); "
              f"id-диапазон {rng}", file=sys.stderr)
        json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
    print("saved", OUT, file=sys.stderr)
