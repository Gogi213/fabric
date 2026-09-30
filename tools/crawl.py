import json, re, time, sys
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

CHANNELS = [
    "whackdoor", "bugnotfeature", "technomedia", "tehnochat", "exploitex",
    "naebnet", "trends", "tlive", "technomotel", "hiaimedia",
    "xor_journal", "ai_newz", "data_secrets", "seeallochnaya", "denissexy",
    "neuraldvig", "gptpublic", "rozetked", "d_code", "cgevent",
    "NeuralShit", "tproger", "ai_machinelearning_big_data",
]

# --- foreign / English-language set ---
EN_CHANNELS = [
    "anthropic",                   # "Discover - Tech News", 1.44M
    "aipost",                      # AI Post, 696K
    "hiaimediaen",                 # Hi, AI - Tech News, 565K  (sister of RU @hiaimedia)
    "TheHackerNews",              # 164K
    "GitHub",                      # 156K
    "news_crypto",                 # 100K
    "TechDaily",                   # 19.4K
    "bleepingcomputer",            # 11.7K
    "perplexity_ai",               # 3.73K
    "machinelearningresearchnews", # 3.44K
    "levelsio",                    # 2.96K
    "tldrtech",                    # TLDR;TECH
    "AInews_en",
    "ml_news",
]

import os
if os.environ.get("EN_ONLY"):
    CHANNELS = [c for c in EN_CHANNELS if c != "AIAgent_s"]


SINCE = datetime(2026, 9, 22, 0, 0, tzinfo=timezone.utc)
S = requests.Session()
S.headers.update({"User-Agent": UA})


def norm(t):
    t = t.lower()
    t = re.sub(r"<br\s*/?>", " ", t)
    t = re.sub(r"https?://\S+", " ", t)
    t = re.sub(r"[^0-9a-zа-яё]+", " ", t, flags=re.I)
    return " ".join(t.split())


def shingles(text, n=3):
    w = text.split()
    return {" ".join(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def fetch(username, before=None, max_pages=25):
    posts = []
    for _ in range(max_pages):
        url = f"https://t.me/s/{username}" + (f"?before={before}" if before else "")
        try:
            r = S.get(url, timeout=30)
        except Exception as e:
            print(f"  ! {username} {before}: {e}", file=sys.stderr)
            break
        if r.status_code != 200:
            break
        soup = BeautifulSoup(r.text, "html.parser")
        wraps = soup.select("div.tgme_widget_message[data-post]")
        if not wraps:
            break
        page = []
        page_dts = []
        for w in wraps:
            post_id = w.get("data-post", "").split("/")[-1]
            if not post_id.isdigit():
                continue
            t = w.select_one("time[datetime]")
            if not t:
                continue
            dt = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00"))
            page_dts.append(dt)
            if dt < SINCE:
                continue
            txt_el = w.select_one("div.js-message_text")
            txt = txt_el.get_text(" ", strip=True) if txt_el else ""
            if not txt:
                continue
            fwd = w.select_one("a.tgme_widget_message_forwarded_from_name")
            fwd_name = fwd.get_text(strip=True) if fwd else ""
            fwd_link = w.select_one("a.tgme_widget_message_forwarded_from")
            fwd_url = fwd_link.get("href", "") if fwd_link else ""
            views = w.select_one("span.tgme_widget_message_views")
            page.append({
                "id": post_id, "dt": dt.isoformat(),
                "text": txt, "fwd_name": fwd_name, "fwd_url": fwd_url,
                "views": views.get_text(strip=True) if views else "",
            })
            posts.append(page[-1])
        ids = [int(p["id"]) for p in page] or [
            int(w.get("data-post").split("/")[-1]) for w in wraps
            if w.get("data-post", "").split("/")[-1].isdigit()]
        if not ids:
            break
        oldest = min(ids)
        page_mindt = min(page_dts) if page_dts else None
        reached_start = page_mindt is not None and page_mindt < SINCE
        if before and oldest >= int(before):
            break
        before = oldest
        if reached_start:
            break
        time.sleep(0.5)
    return posts, False


if __name__ == "__main__":
    out = {}
    for u in CHANNELS:
        print(f"crawling @{u} ...", file=sys.stderr)
        posts, done = fetch(u)
        out[u] = posts
        print(f"  {len(posts)} posts, oldest={posts[-1]['dt'][:10] if posts else '-'}",
              file=sys.stderr)
    outfile = ("C:/visual projects/parser/data/posts_en.json"
               if os.environ.get("EN_ONLY") else
               "C:/visual projects/parser/data/posts.json")
    with open(outfile, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("total", sum(len(v) for v in out.values()), "->", outfile, file=sys.stderr)
